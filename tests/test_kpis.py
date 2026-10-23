"""Before/after comparison figures computed from the scheduler, not from constants."""

from __future__ import annotations

from pathlib import Path

from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.config import HORIZON, Settings
from resilimes.domain.kpis import compare_load, evaluate, flow_metrics, lots_moved, step_waits
from resilimes.domain.models import Equipment, Plant, Schedule, ScheduledOp
from resilimes.domain.plant import load_sample
from resilimes.domain.scenarios import plants_for_scenario
from resilimes.domain.schedule import POLICY_FROZEN, POLICY_RECOVER, schedule_plant

AREAS = {"CMP", "Deposition", "Etch", "Lithography"}


def _span(tool: str, start: int, end: int) -> ScheduledOp:
    return ScheduledOp(
        job_id=f"{tool}-{start}",
        product_id="P",
        step="ETCH",
        step_index=0,
        equipment_id=tool,
        start_min=start,
        end_min=end,
        setup_min=0,
        process_min=end - start,
        setup_family="E",
        priority=1,
    )


def _two_tool_plant() -> Plant:
    up = Equipment(
        equipment_id="UP",
        name="Up",
        area="Etch",
        status="IDLE",
        capability=["etch_dielectric"],
        available_at_min=0,
    )
    down = Equipment(
        equipment_id="DOWN",
        name="Down",
        area="Etch",
        status="DOWN",
        capability=["etch_dielectric"],
        available_at_min=100,
    )
    return Plant(
        plant_id="TINY",
        horizon=HORIZON,
        equipment=[up, down],
        jobs=[],
        products=[],
        source="test",
    )


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


def test_shared_horizon_keeps_a_down_tool_from_inflating_utilization() -> None:
    before_plant, before, after_plant, after = _books("litho_down")
    load = compare_load(before_plant, before, after_plant, after)
    before_span = evaluate(before_plant, before).makespan_min
    after_span = evaluate(after_plant, after).makespan_min
    assert load["horizon_min"] == max(before_span, after_span)
    assert int(load["horizon_min"]) > after_span
    before_side = load["before"]
    after_side = load["after"]
    assert isinstance(before_side, dict) and isinstance(after_side, dict)
    assert before_side["available_min"] == after_side["available_min"]
    assert int(before_side["available_min"]) > 0
    assert before_side["busy_min"] == after_side["busy_min"]
    assert before_side["utilization_pct"] == after_side["utilization_pct"]
    # The old per-book makespan dropped LITHO-02 out of the short book.
    assert evaluate(after_plant, after).utilization_pct > float(after_side["utilization_pct"]) + 5
    down = after_side["down"]
    assert isinstance(down, list)
    litho = next(row for row in down if row["equipment_id"] == "LITHO-02")
    assert litho["down_min"] == 600
    for side in (before_side, after_side):
        areas = side["areas"]
        assert isinstance(areas, list)
        assert {str(row["area"]) for row in areas} == AREAS
        busy = sum(int(row["busy_min"]) for row in areas)
        available = sum(int(row["available_min"]) for row in areas)
        assert side["utilization_pct"] == round(100.0 * busy / available, 1)
        for row in areas:
            assert 0.0 <= float(row["utilization_pct"]) <= 100.0


def test_shorter_book_on_a_fixed_window_does_not_change_the_denominator() -> None:
    plant = _two_tool_plant()
    short = Schedule(policy="recover", operations=[_span("UP", 0, 40)])
    long = Schedule(policy="recover", operations=[_span("UP", 160, 200)])
    load = compare_load(plant, short, plant, long)
    assert load["horizon_min"] == 200
    before_side = load["before"]
    after_side = load["after"]
    assert isinstance(before_side, dict) and isinstance(after_side, dict)
    assert before_side["available_min"] == 300
    assert after_side["available_min"] == 300
    assert before_side["utilization_pct"] == after_side["utilization_pct"]
    assert float(before_side["utilization_pct"]) < 20
    down = before_side["down"]
    assert isinstance(down, list) and down[0]["equipment_id"] == "DOWN"
    assert down[0]["down_min"] == 100


def test_flow_metrics_and_step_waits_come_from_the_book() -> None:
    _before_plant, before, _after_plant, after = _books("litho_down")
    flowed = flow_metrics(after)
    assert flowed["mean_lead_min"] > 0
    assert flowed["mean_wait_min"] >= 0
    assert flowed["mean_x_factor"] >= 1
    ranks = step_waits(after)
    assert ranks
    assert ranks[0]["avg_min"] >= ranks[-1]["avg_min"]
    assert flow_metrics(before)["mean_lead_min"] > flowed["mean_lead_min"]


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
    assert report.kpis["horizon_min"] == max(
        report.kpis["before"]["makespan_min"], report.kpis["after"]["makespan_min"]
    )
    assert report.kpis["before"]["utilization_pct"] == report.kpis["after"]["utilization_pct"]
    assert report.kpis["delta"]["utilization_pct"] == 0
    assert any(row["equipment_id"] == "LITHO-02" for row in report.kpis["down"]["after"])
    assert report.kpis["after"]["mean_x_factor"] >= 1
    assert report.kpis["waits"]["after"]
    for side in ("before", "after"):
        for row in report.kpis["areas"][side]:
            assert 0.0 <= float(row["utilization_pct"]) <= 100.0
