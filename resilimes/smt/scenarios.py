"""Headline scenarios on the full SMT2020 fab.

The six-lot sample bay stays in ``resilimes.domain.scenarios`` for unit tests.
It is not what this module returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from resilimes.config import Settings
from resilimes.engines.scout.engine import default_scout
from resilimes.smt.fab import DATA_SOURCE, LITHO_MTTR_MIN, READ_QUERY, Fab, initial_queues, load_fab
from resilimes.smt.simulate import (
    RunResult,
    macro_aps_ms,
    pm_shift_to_open,
    pm_windows,
    run_policy,
    sample_downs,
)

logger = logging.getLogger(__name__)

# One shift on a click. The multi-shift study uses 48h and five seeds.
INTERACTIVE_HORIZON_SEC = 12 * 3600.0
STUDY_HORIZON_SEC = 48 * 3600.0
HOT_DUE_SEC = 12 * 3600.0
PM_OPEN_SEC = 2 * 3600.0
SEEDS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class SmtScenario:
    id: str
    title: str
    summary: str
    incident: str
    before_policy: str
    after_policy: str
    kind: str


SCENARIOS: dict[str, SmtScenario] = {
    "litho_down": SmtScenario(
        id="litho_down",
        title="Lithography breakdown",
        summary=(
            "Litho_FE_92-1, an expose scanner in the largest Litho_* family, "
            "is down for the published lithography MTTR."
        ),
        incident=(
            "Machine Litho_FE_92-1 down. Breakdown on expose family Litho_FE_92. "
            "Repair uses the published lithography MTTR of 705.59 minutes."
        ),
        before_policy="edd",
        after_policy="resilimes",
        kind="litho",
    ),
    "hot_lot": SmtScenario(
        id="hot_lot",
        title="Hot lot",
        summary=(
            "A normal lot four steps before an expose scanner is raised to VIP "
            "with a due 12 hours from the snapshot."
        ),
        incident="Hot lot: promote one normal WIP lot to VIP, due in 12 hours.",
        before_policy="fifo",
        after_policy="resilimes",
        kind="hot",
    ),
    "pm_avoid": SmtScenario(
        id="pm_avoid",
        title="PM avoidance",
        summary=(
            "The published weekly PM on Litho_FE_92 is shifted so it opens two "
            "hours into the window. Duration and interval stay as published."
        ),
        incident=(
            "Preventive maintenance on Litho_FE_92. Lots that would run across "
            "the PM window stay off the tool."
        ),
        before_policy="edd",
        after_policy="resilimes",
        kind="pm",
    ),
    "wip_threshold": SmtScenario(
        id="wip_threshold",
        title="WIP threshold",
        summary=(
            "When a station family holds more than two lots per tool, ResiliMES "
            "replans that family only and shortens the look-ahead."
        ),
        incident="WIP over the station-family threshold. Replan that family only.",
        before_policy="fifo",
        after_policy="resilimes",
        kind="wip",
    ),
    "qtime": SmtScenario(
        id="qtime",
        title="Queue time",
        summary=("Published CQT limits. ResiliMES adds PED risk. FIFO does not."),
        incident="Q-time: published CQT limits are active across the fab.",
        before_policy="fifo",
        after_policy="resilimes",
        kind="qtime",
    ),
}


def list_smt_scenarios() -> list[SmtScenario]:
    return list(SCENARIOS.values())


def scenario_payload(fab: Fab | None = None) -> dict[str, Any]:
    plant = fab or load_fab()
    queues = initial_queues(plant)
    grouped: dict[str, dict[str, Any]] = {}
    for family in plant.families:
        row = grouped.setdefault(
            family.group,
            {
                "id": family.group,
                "kind": "group",
                "status": "IDLE",
                "tools": 0,
                "families": 0,
                "queue": queues.get(family.group, 0),
                "litho": family.group == "Litho",
            },
        )
        row["tools"] += family.tools
        row["families"] += 1
    return {
        "fab": DATA_SOURCE,
        "scenarios": [item.__dict__ for item in SCENARIOS.values()],
        "bay": list(grouped.values()),
        "counts": _counts(plant),
        "query": READ_QUERY,
        "data_source": DATA_SOURCE,
    }


def run_smt(
    settings: Settings,
    scenario_id: str,
    *,
    actor_role: str = "planner",
    actor_id: str = "planner.ops",
    seed: int = 1,
    horizon_sec: float | None = None,
    on_event: Any = None,
) -> dict[str, Any]:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise KeyError(scenario_id)
    fab = load_fab()
    horizon = INTERACTIVE_HORIZON_SEC if horizon_sec is None else horizon_sec
    scout = default_scout(
        signing_secret=settings.scout_signing_secret,
        provider_mode="mock",
        ttl_seconds=settings.scout_ttl_seconds,
    )
    decision = scout.decide(
        {
            "prompt": scenario.incident,
            "surface": "mes_console",
            "user": {"id": actor_id, "role": actor_role},
        }
    )
    _emit(
        on_event,
        "scout",
        "scout",
        "Scout Intent",
        f"Intent {decision.intent.get('primary')}.",
        {"intent": decision.intent.get("primary"), "confidence": decision.intent.get("confidence")},
    )
    if decision.risk.get("level") == "block" or decision.execution_contract is None:
        logger.info(
            "data source: smt2020",
            extra={"fields": {"query": READ_QUERY, "scenario": scenario_id, "blocked": "true"}},
        )
        return {
            "fab": DATA_SOURCE,
            "blocked": True,
            "scenario_id": scenario_id,
            "incident": scenario.incident,
            "narrative": decision.risk.get("reason") or "Scout refused the request.",
            "scout": _scout_public(decision),
            "verdict": {"verdict": "reject"},
            "mode": {"label": "SMT2020", "data": DATA_SOURCE},
            "data_source": DATA_SOURCE,
            "query": READ_QUERY,
        }
    _emit(on_event, "sim", "dispatcher", "Full fab", _count_line(fab), {"lots": len(fab.lot_id)})
    report = simulate_pair(fab, scenario, seed=seed, horizon=horizon)
    report["scout"] = _scout_public(decision)
    report["blocked"] = False
    report["verdict"] = {"verdict": "accept"}
    report["mode"] = {"label": "SMT2020", "data": DATA_SOURCE, "llm": "mock"}
    logger.info(
        "data source: smt2020",
        extra={
            "fields": {
                "query": READ_QUERY,
                "scenario": scenario_id,
                "seed": str(seed),
                "horizon_h": str(horizon / 3600.0),
            }
        },
    )
    return report


def simulate_pair(
    fab: Fab,
    scenario: SmtScenario,
    *,
    seed: int,
    horizon: float,
) -> dict[str, Any]:
    forced_tool = fab.focus_tool if scenario.kind == "litho" else None
    forced_until = LITHO_MTTR_MIN * 60.0 if scenario.kind == "litho" else 0.0
    shift = pm_shift_to_open(fab, fab.pm_calendar, PM_OPEN_SEC) if scenario.kind == "pm" else 0.0
    downs = sample_downs(
        fab,
        seed,
        horizon,
        forced_tool=forced_tool,
        forced_until=forced_until,
    )
    pm = pm_windows(fab, horizon, shift_sec=shift)
    hot = fab.hot_lot if scenario.kind == "hot" else None
    # The before book keeps the lot at its published priority.
    before = run_policy(
        fab,
        policy=scenario.before_policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        hot_lot=hot,
        trace=True,
        focus_down_until=forced_until,
    )
    after = run_policy(
        fab,
        policy=scenario.after_policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        hot_lot=hot,
        hot_due=HOT_DUE_SEC if hot is not None else None,
        promote_hot=hot is not None,
        trace=True,
        focus_down_until=forced_until,
    )
    aps_ms, scanner_steps = macro_aps_ms(fab)
    return _report(fab, scenario, before, after, seed, horizon, aps_ms, scanner_steps, shift)


def _report(
    fab: Fab,
    scenario: SmtScenario,
    before: RunResult,
    after: RunResult,
    seed: int,
    horizon: float,
    aps_ms: float,
    scanner_steps: int,
    shift: float,
) -> dict[str, Any]:
    family = fab.families[fab.focus_family]
    return {
        "fab": DATA_SOURCE,
        "data_source": DATA_SOURCE,
        "query": READ_QUERY,
        "scenario_id": scenario.id,
        "incident": scenario.incident,
        "horizon": "2018-01-01T00:00:00Z",
        "horizon_h": horizon / 3600.0,
        "seed": seed,
        "counts": _counts(fab),
        "policies": {"before": before.policy, "after": after.policy},
        "focus": {
            "family": family.name,
            "group": family.group,
            "tool": fab.tool_name[fab.focus_tool],
            "tools_in_family": family.tools,
            "down_min": round(LITHO_MTTR_MIN, 2) if scenario.kind == "litho" else 0,
            "sibling_starts_before": before.sibling_starts,
            "sibling_starts_after": after.sibling_starts,
            "queue_max_before": before.focus_queue_max,
            "queue_max_after": after.focus_queue_max,
            "downstream_queue_max_before": before.downstream_queue_max,
            "downstream_queue_max_after": after.downstream_queue_max,
        },
        "hot_lot": {
            "lot_id": fab.lot_id[fab.hot_lot],
            "product": fab.lot_product[fab.hot_lot],
            "rule": "priority 10, four steps before an expose scanner, lowest lot id",
            "steps_before": before.hot_steps,
            "steps_after": after.hot_steps,
            "scanner_start_min_before": before.hot_scanner_start_min,
            "scanner_start_min_after": after.hot_scanner_start_min,
        },
        "pm": {
            "calendar": fab.pm_calendar,
            "shift_h": round(shift / 3600.0, 2),
            "note": (
                "FOA is one published constant per family, so every tool in the "
                "family shares the window. The PM scenario subtracts the same "
                "offset from every day-based calendar."
            ),
        },
        "kpis": {"before": _kpi(before), "after": _kpi(after), "delta": _delta(before, after)},
        "timing": {
            "dispatch_p50_ms": after.dispatch_p50_ms,
            "dispatch_p95_ms": after.dispatch_p95_ms,
            "dispatch_decisions": after.dispatch_decisions,
            "aps_ms": round(aps_ms, 1),
            "scanner_steps": scanner_steps,
            "sim_before_s": before.sim_s,
            "sim_after_s": after.sim_s,
        },
        "board": _board(fab, after),
        "gantt": {
            "bin_min": 15,
            "before": _bars(fab, before),
            "after": _bars(fab, after),
            "focus_bars": after.focus_bars,
        },
        "definitions": {
            "on_time_pct": (
                "Lots whose due is at or before the horizon. On time only if the "
                "route finishes at or before the due. Lots already due at the "
                "snapshot stay in the denominator."
            ),
            "weighted_tardiness_min": (
                "Lot value times minutes late. An open lot is censored at the horizon."
            ),
            "cycle_time_h": "Mean completion time of lots that finish the route inside the horizon.",
            "litho_util_pct": "Busy time on the 102 Litho_* tools divided by tools times horizon.",
            "qtime_violations": "CQT target started after the limit, or the limit expired inside the horizon.",
            "pm_avoided": "ResiliMES decisions that refused at least one lot because it would cross a PM.",
            "pm_overlaps": "Baseline starts whose process overlaps a PM window.",
        },
    }


def _counts(fab: Fab) -> dict[str, int]:
    return {
        "groups": len(fab.families),
        "tools": len(fab.tool_name),
        "litho_tools": fab.litho_tools,
        "scanner_tools": fab.scanner_tools,
        "products": fab.products,
        "lots": len(fab.lot_id),
        "station_groups": len(fab.group_names),
    }


def _kpi(result: RunResult) -> dict[str, Any]:
    return {
        "policy": result.policy,
        "on_time_pct": result.on_time_pct,
        "weighted_tardiness_min": result.weighted_tardiness_min,
        "due_in_horizon": result.due_in_horizon,
        "already_late": result.already_late,
        "completed_routes": result.completed_routes,
        "cycle_time_h": result.cycle_time_h,
        "mean_step_cycle_min": result.mean_step_cycle_min,
        "litho_util_pct": result.litho_util_pct,
        "scanner_util_pct": result.scanner_util_pct,
        "qtime_violations": result.qtime_violations,
        "pm_avoided": result.pm_avoided,
        "pm_overlaps": result.pm_overlaps,
        "wip_replans": result.wip_replans,
    }


def _delta(before: RunResult, after: RunResult) -> dict[str, Any]:
    def sub(left: float | None, right: float | None) -> float | None:
        if left is None or right is None:
            return None
        return round(right - left, 2)

    return {
        "on_time_pct": round(after.on_time_pct - before.on_time_pct, 2),
        "weighted_tardiness_min": round(
            after.weighted_tardiness_min - before.weighted_tardiness_min, 1
        ),
        "qtime_violations": after.qtime_violations - before.qtime_violations,
        "litho_util_pct": round(after.litho_util_pct - before.litho_util_pct, 2),
        "cycle_time_h": sub(before.cycle_time_h, after.cycle_time_h),
        "pm_avoided": after.pm_avoided - before.pm_avoided,
    }


def _board(fab: Fab, result: RunResult) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for family in fab.families:
        row = rows.setdefault(
            family.group,
            {
                "id": family.group,
                "kind": "group",
                "tools": 0,
                "families": 0,
                "queue": result.queue_end.get(family.group, 0),
                "down": result.down_tools.get(family.group, 0),
                "status": "IDLE",
            },
        )
        row["tools"] += family.tools
        row["families"] += 1
    for row in rows.values():
        if row["down"]:
            row["status"] = "DOWN"
    return list(rows.values())


def _bars(fab: Fab, result: RunResult) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    if not result.occupancy:
        return bars
    for fam, row in enumerate(result.occupancy):
        family = fab.families[fam]
        segments: list[dict[str, float]] = []
        start: int | None = None
        peak = 0.0
        for index, value in enumerate(row):
            if value > 0:
                peak = max(peak, value)
                if start is None:
                    start = index
            elif start is not None:
                segments.append(
                    {
                        "s": start * 15,
                        "e": index * 15,
                        "n": round(peak / _bin_seconds(), 2),
                    }
                )
                start = None
                peak = 0.0
        if start is not None:
            segments.append(
                {"s": start * 15, "e": len(row) * 15, "n": round(peak / _bin_seconds(), 2)}
            )
        if not segments:
            continue
        bars.append(
            {
                "id": family.name,
                "group": family.group,
                "scanner": family.scanner,
                "litho": family.litho,
                "bars": segments,
            }
        )
    return bars


def _bin_seconds() -> float:
    return 900.0


def _scout_public(decision: Any) -> dict[str, Any]:
    contract = decision.execution_contract or {}
    return {
        "engine": "scout-intent",
        "intent": decision.intent.get("primary"),
        "confidence": decision.intent.get("confidence"),
        "risk": decision.risk.get("level"),
        "contract": bool(contract),
        "test": "tests/test_scout_engine.py",
    }


def _count_line(fab: Fab) -> str:
    return (
        f"{len(fab.families)} families, {len(fab.tool_name)} tools, "
        f"{fab.litho_tools} litho, {len(fab.lot_id)} lots."
    )


def _emit(
    on_event: Any,
    phase: str,
    agent: str,
    title: str,
    summary: str,
    slots: dict[str, Any],
) -> None:
    if on_event is None:
        return
    on_event(
        {
            "type": "step",
            "phase": phase,
            "agent": agent,
            "title": title,
            "summary": summary,
            "evidence": [READ_QUERY] if phase == "sim" else [],
            "slots": slots,
            "elapsed_ms": 0,
        }
    )
