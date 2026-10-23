"""Semiconductor flow: re-entrant route, queue time, rework, bottleneck."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from resilimes.agents.planner import naive_alternative, reject_alternative
from resilimes.config import HORIZON
from resilimes.domain.critique import critique_schedule
from resilimes.domain.gantt import build_gantt
from resilimes.domain.kpis import qtime_report
from resilimes.domain.plant import load_sample
from resilimes.domain.scenarios import plants_for_scenario
from resilimes.domain.schedule import (
    POLICY_FROZEN,
    POLICY_RECOVER,
    _bottleneck_area,
    _expand,
    schedule_plant,
)


def _plant():
    return load_sample(Path("data/sample"), HORIZON)


def test_route_is_reentrant_and_today_stops_at_cmp() -> None:
    plant = _plant()
    route = plant.product_map()["PROD-A28"].route
    assert [step.step for step in route] == [
        "DEP",
        "LITHO",
        "MEAS",
        "ETCH",
        "CLEAN",
        "CMP",
        "DEP-L2",
        "LITHO-L2",
        "MEAS-L2",
        "ETCH-L2",
        "CLEAN-L2",
        "CMP-L2",
    ]
    assert route[0].capability == "cvd_oxide"
    assert route[1].layer == "L1"
    assert route[7].layer == "L2"
    assert route[1].area == "Lithography"
    assert route[7].area == "Lithography"
    assert any(tool.equipment_id == "DEP-01" for tool in plant.equipment)
    assert any("overlay_cd" in tool.capability for tool in plant.equipment)
    assert any("wet_clean" in tool.capability for tool in plant.equipment)
    assert plant.product_map()["PROD-A28"].route_id == "ROUTE-A28"
    steps = _expand(plant)["LOT-1001"]
    assert [step.step for step in steps] == ["LITHO", "MEAS", "ETCH", "CLEAN", "CMP"]
    assert any(rule.from_step == "CLEAN" and rule.to_step == "DEP-L2" for rule in plant.qtime_rules)


def test_qtime_is_respected_on_the_litho_book() -> None:
    plant = _plant()
    pair = plants_for_scenario(plant, "litho_down")
    schedule = schedule_plant(pair.after, POLICY_RECOVER)
    critique = critique_schedule(pair.after, schedule)
    assert critique.verdict == "accept"
    assert not any(item.constraint == "qtime" for item in critique.violations)
    report = qtime_report(pair.after, schedule)
    assert report["violations"] == 0
    assert report["held"] == 0
    frozen = schedule_plant(pair.before, POLICY_FROZEN)
    waiting = qtime_report(pair.before, frozen)
    assert waiting["violations"] == 0
    assert waiting["held"] == 0
    assert int(str(waiting["at_risk"])) == 0
    assert int(str(report["at_risk"])) == 0


def test_tight_qtime_holds_the_lot_and_rejects_the_naive_start() -> None:
    plant = _plant()
    pair = plants_for_scenario(plant, "qtime")
    schedule = schedule_plant(pair.after, POLICY_RECOVER)
    held = [item for item in schedule.unscheduled if item.job_id == "LOT-1003"]
    assert held and held[0].reason.startswith("Q-time")
    assert not any(op.job_id == "LOT-1003" and op.step == "CMP" for op in schedule.operations)
    committed = critique_schedule(pair.after, schedule)
    assert not any(item.constraint == "qtime" for item in committed.violations)
    rejected = reject_alternative(pair.after, naive_alternative(pair.after, "qtime"))
    assert rejected.verdict == "reject"
    assert rejected.violations[0].constraint == "qtime"
    report = qtime_report(pair.after, schedule)
    assert report["held"] >= 1
    assert float(str(report["compliance_pct"])) < 100.0


def test_critic_rejects_a_placed_qtime_violation() -> None:
    plant = _plant()
    pair = plants_for_scenario(plant, "litho_down")
    schedule = schedule_plant(pair.after, POLICY_RECOVER)
    operations = [op.model_copy() for op in schedule.operations]
    moved = False
    for op in operations:
        if op.job_id == "LOT-1003" and op.step == "DEP-2":
            op.start_min += 2000
            op.end_min = op.start_min + op.process_min
            moved = True
    assert moved
    broken = schedule.model_copy(update={"operations": operations})
    critique = critique_schedule(pair.after, broken)
    assert critique.verdict == "reject"
    assert any(item.constraint == "qtime" for item in critique.violations)


def test_rework_is_inserted_once_and_limited() -> None:
    plant = _plant()
    pair = plants_for_scenario(plant, "rework")
    before = schedule_plant(pair.before, POLICY_RECOVER)
    after = schedule_plant(pair.after, POLICY_RECOVER)
    before_steps = [op.step for op in before.operations if op.job_id == "LOT-1004"]
    after_steps = [op.step for op in after.operations if op.job_id == "LOT-1004"]
    assert "LITHO-RW" not in before_steps
    assert "MEAS-RW" not in before_steps
    meas = after_steps.index("MEAS")
    assert after_steps[meas : meas + 4] == ["MEAS", "STRIP", "LITHO-RW", "MEAS-RW"]
    rework_ops = [op for op in after.operations if op.rework]
    assert rework_ops and all(op.step == "MEAS-RW" for op in rework_ops)
    assert any(op.step == "STRIP" and op.equipment_id == "WET-01" for op in after.operations)
    litho_before = sum(op.process_min for op in before.operations if op.step == "LITHO")
    litho_after = sum(op.process_min for op in after.operations if op.step in {"LITHO", "LITHO-RW"})
    assert litho_after > litho_before
    job = next(item for item in pair.after.jobs if item.job_id == "LOT-1004")
    job.rework_count = job.rework_limit
    limited = schedule_plant(pair.after, POLICY_RECOVER)
    assert not any(op.step in {"LITHO-RW", "MEAS-RW", "STRIP"} for op in limited.operations)
    gantt = build_gantt(pair.after, after)
    bars = [bar for row in gantt["rows"] for bar in row["bars"]]  # type: ignore[index, union-attr]
    assert any(bar["rework"] for bar in bars)  # type: ignore[index]


def test_bottleneck_is_detected_and_marked() -> None:
    plant = _plant()
    pair = plants_for_scenario(plant, "litho_down")
    schedule = schedule_plant(pair.after, POLICY_RECOVER)
    assert schedule.bottleneck_area == _bottleneck_area(pair.after, _expand(pair.after))
    assert schedule.bottleneck_area
    assert any("bottleneck" in action.reason for action in schedule.actions)
    gantt = build_gantt(pair.after, schedule)
    marked = [
        row
        for row in gantt["rows"]  # type: ignore[index, union-attr]
        if row["bottleneck"]  # type: ignore[index]
    ]
    assert marked
    assert {row["area"] for row in marked} == {schedule.bottleneck_area}  # type: ignore[index]


def test_clean_to_next_film_holds_when_polish_sits_inside_a_tight_window() -> None:
    plant = _plant()
    for job in plant.jobs:
        if job.job_id != "LOT-1004":
            continue
        job.released_through = "DEP-L2"
        job.current_step = "CLEAN"
        job.status = "RUNNING"
        job.started_at = plant.horizon - timedelta(minutes=40)
        job.process_time_min = 16
        job.assigned_equipment = "WET-01"
    for rule in plant.qtime_rules:
        if rule.rule_id == "QT-A28-CLEAN-DEP":
            rule.max_min = 15
    schedule = schedule_plant(plant, POLICY_RECOVER)
    held = [item for item in schedule.unscheduled if item.job_id == "LOT-1004"]
    assert held and held[0].step == "DEP-L2"
    assert held[0].reason.startswith("Q-time")
    assert any(op.job_id == "LOT-1004" and op.step == "CMP" for op in schedule.operations)
    assert not any(op.job_id == "LOT-1004" and op.step == "DEP-L2" for op in schedule.operations)
