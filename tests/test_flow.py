"""Semiconductor flow: re-entrant route, queue time, rework, bottleneck."""

from __future__ import annotations

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
        "LITHO",
        "ETCH",
        "CMP",
        "LITHO-L2",
        "ETCH-L2",
        "CMP-L2",
    ]
    assert route[0].layer == "L1"
    assert route[3].layer == "L2"
    assert route[0].area == "Lithography"
    assert route[3].area == "Lithography"
    assert plant.product_map()["PROD-A28"].route_id == "ROUTE-A28"
    steps = _expand(plant)["LOT-1001"]
    assert [step.step for step in steps] == ["LITHO", "ETCH", "CMP"]
    assert any(rule.from_step == "ETCH" and rule.to_step == "CMP" for rule in plant.qtime_rules)


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
    assert int(str(waiting["at_risk"])) >= 1
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
        if op.job_id == "LOT-1004" and op.step == "CMP":
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
    assert after_steps[:3] == ["LITHO", "STRIP", "LITHO-RW"]
    rework_ops = [op for op in after.operations if op.rework]
    assert rework_ops and all(op.step == "LITHO-RW" for op in rework_ops)
    litho_before = sum(op.process_min for op in before.operations if op.step == "LITHO")
    litho_after = sum(op.process_min for op in after.operations if op.step in {"LITHO", "LITHO-RW"})
    assert litho_after > litho_before
    job = next(item for item in pair.after.jobs if item.job_id == "LOT-1004")
    job.rework_count = job.rework_limit
    limited = schedule_plant(pair.after, POLICY_RECOVER)
    assert not any(op.step == "LITHO-RW" for op in limited.operations)
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
