"""Current-shift snapshot for the landing.

The recommended story is the lithography fault. Its frozen book is the plan
on screen, and each small scenario reports the on-time and tardiness change
the recovery will show. The 1,000-lot fab is not solved on page load.
"""

from __future__ import annotations

from typing import Any

from resilimes.domain.floor import ReplanTrigger, TriggerKind, tool_queues, wip_steps
from resilimes.domain.gantt import build_gantt, shared_window
from resilimes.domain.kpis import evaluate
from resilimes.domain.models import Plant
from resilimes.domain.scenarios import list_scenarios, plants_for_scenario
from resilimes.domain.schedule import POLICY_FROZEN, POLICY_RECOVER, schedule_plant

_DOWN = {"DOWN", "MAINTENANCE"}


def build_overview(plant: Plant) -> dict[str, Any]:
    impacts: dict[str, dict[str, float | int] | None] = {}
    for scenario in list_scenarios():
        if scenario.kind == "scale":
            impacts[scenario.id] = None
            continue
        try:
            impacts[scenario.id] = _impact(plant, scenario.id, scenario.kind)
        except (KeyError, ValueError):
            impacts[scenario.id] = None
    try:
        shift = _litho_shift(plant)
    except (KeyError, ValueError):
        shift = _plain_shift(plant)
    shift["impacts"] = impacts
    shift["recommended"] = "litho_down"
    return shift


def _impact(plant: Plant, scenario_id: str, kind: str) -> dict[str, float | int]:
    pair = plants_for_scenario(plant, scenario_id)
    before_policy = POLICY_FROZEN if kind == "frozen_vs_recover" else POLICY_RECOVER
    before = schedule_plant(pair.before, before_policy)
    after = schedule_plant(pair.after, POLICY_RECOVER)
    left = evaluate(pair.before, before)
    right = evaluate(pair.after, after)
    return {
        "otd_before": left.on_time_delivery_pct,
        "otd_after": right.on_time_delivery_pct,
        "tardy_before": left.weighted_tardiness_min,
        "tardy_after": right.weighted_tardiness_min,
        "risk_before": left.lots_at_risk,
        "risk_after": right.lots_at_risk,
    }


def _litho_shift(plant: Plant) -> dict[str, Any]:
    pair = plants_for_scenario(plant, "litho_down")
    return _shift(pair.before, POLICY_FROZEN, trigger_kind="breakdown", scenario_id="litho_down")


def _plain_shift(plant: Plant) -> dict[str, Any]:
    return _shift(plant, POLICY_FROZEN)


def _shift(
    plant: Plant,
    policy: str,
    *,
    trigger_kind: TriggerKind | None = None,
    scenario_id: str = "",
) -> dict[str, Any]:
    book = schedule_plant(plant, policy)
    chart = build_gantt(plant, book)
    window = shared_window(chart, chart)
    kpi = evaluate(plant, book)
    rows = chart["rows"]
    assert isinstance(rows, list)
    tools = [_tool(row) for row in rows if isinstance(row, dict)]
    return {
        "kpis": {
            "on_time_delivery_pct": kpi.on_time_delivery_pct,
            "lots_at_risk": kpi.lots_at_risk,
            "wip": len(plant.jobs),
            "utilization_pct": kpi.utilization_pct,
        },
        "down_tools": [item["id"] for item in tools if item["status"] in _DOWN],
        "gantt": chart,
        "window": window,
        "tools": tools,
        "queues": [item.model_dump() for item in tool_queues(plant, book)],
        "wip_steps": [item.model_dump() for item in wip_steps(plant)],
        "trigger": ReplanTrigger(kind=trigger_kind, scenario_id=scenario_id).model_dump(),
        "materials": [
            {
                "id": stock.material_id,
                "name": stock.name,
                "on_hand": stock.on_hand,
                "unit": stock.unit,
                "status": "short" if stock.on_hand <= 0 else "ok",
            }
            for stock in plant.materials
        ],
    }


def _tool(row: dict[str, Any]) -> dict[str, Any]:
    bars = [bar for bar in row.get("bars") or [] if isinstance(bar, dict) and not bar.get("held")]
    now = next((bar for bar in bars if int(bar["start_min"]) <= 0 < int(bar["end_min"])), None)
    nxt = min(bars, key=lambda bar: int(bar["start_min"])) if now is None and bars else None
    status = str(row.get("status") or "")
    available = int(row.get("available_at_min") or 0)
    return {
        "id": str(row.get("equipment_id") or ""),
        "area": str(row.get("area") or ""),
        "status": status,
        "lot": str(now["job_id"]) if now else "",
        "step": str(now["step"]) if now else "",
        "eta_min": int(now["end_min"]) if now else None,
        "next_lot": str(nxt["job_id"]) if nxt else "",
        "next_min": int(nxt["start_min"]) if nxt else None,
        "down_until_min": available if status in _DOWN else None,
        "state": str(row.get("state") or "idle"),
    }
