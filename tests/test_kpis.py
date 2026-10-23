"""Before/after comparison figures computed from the scheduler, not from constants."""

from __future__ import annotations

from pathlib import Path

from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.config import HORIZON, Settings
from resilimes.domain.kpis import area_utilization, evaluate, lots_moved
from resilimes.domain.models import Plant, Schedule
from resilimes.domain.plant import load_sample
from resilimes.domain.scenarios import plants_for_scenario
from resilimes.domain.schedule import POLICY_FROZEN, POLICY_RECOVER, schedule_plant

AREAS = {"CMP", "Deposition", "Etch", "Lithography"}


def _books(scenario_id: str) -> tuple[Plant, Schedule, Plant, Schedule]:
    plant = load_sample(Path("data/sample"), HORIZON)
    pair = plants_for_scenario(plant, scenario_id)
    policy = POLICY_FROZEN if scenario_id == "litho_down" else POLICY_RECOVER
    return (
        pair.before,
        schedule_plant(pair.before, policy),
        pair.after,
        schedule_plant(pair.after, POLICY_RECOVER),
    )


def test_area_rows_cover_every_tool_group_and_reconcile() -> None:
    before_plant, before, after_plant, after = _books("litho_down")
    for plant, schedule in ((before_plant, before), (after_plant, after)):
        rows = area_utilization(plant, schedule)
        assert {str(row["area"]) for row in rows} == AREAS
        assert sum(int(row["tools"]) for row in rows) == len(plant.equipment)
        busy = sum(int(row["busy_min"]) for row in rows)
        available = sum(int(row["available_min"]) for row in rows)
        for row in rows:
            pct = float(row["utilization_pct"])
            assert 0.0 <= pct <= 100.0
            if int(row["available_min"]) == 0:
                assert pct == 0.0
            else:
                assert pct == round(100.0 * int(row["busy_min"]) / int(row["available_min"]), 1)
        plant_pct = evaluate(plant, schedule).utilization_pct
        assert plant_pct == (round(100.0 * busy / available, 1) if available else 0.0)


def test_litho_lots_moved_is_the_scanner_change() -> None:
    _before_plant, before, _after_plant, after = _books("litho_down")
    moved = lots_moved(before, after)
    assert "LOT-1001" in moved
    assert "LOT-1002" not in moved


def test_rush_insert_and_stockout_holds_are_not_tool_moves() -> None:
    _bp, before, _ap, after = _books("rush_order")
    assert "LOT-2001" not in lots_moved(before, after)
    _bp, before, _ap, after = _books("material_shortage")
    moved = lots_moved(before, after)
    assert "LOT-1001" not in moved
    assert "LOT-1004" not in moved


def test_setup_changes_count_paid_setups() -> None:
    before_plant, before, after_plant, after = _books("litho_down")
    before_kpi = evaluate(before_plant, before)
    after_kpi = evaluate(after_plant, after)
    assert before_kpi.setup_changes == sum(1 for op in before.operations if op.setup_min > 0)
    assert after_kpi.setup_changes == sum(1 for op in after.operations if op.setup_min > 0)


def test_recovery_report_carries_areas_and_lots_moved() -> None:
    report = run_recovery(
        Settings(mode="mock", horizon=HORIZON, scout_signing_secret="kpi-secret"),
        RecoverInput(scenario="litho_down"),
    )
    assert report.kpis is not None
    assert {row["area"] for row in report.kpis["areas"]["after"]} == AREAS
    assert {row["area"] for row in report.kpis["areas"]["before"]} == AREAS
    assert "LOT-1001" in report.kpis["lots_moved"]
    assert report.kpis["delta"]["setup_changes"] == (
        report.kpis["after"]["setup_changes"] - report.kpis["before"]["setup_changes"]
    )
    for side in ("before", "after"):
        for row in report.kpis["areas"][side]:
            assert 0.0 <= float(row["utilization_pct"]) <= 100.0
