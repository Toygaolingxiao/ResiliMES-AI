"""Scheduler properties on the sample fab and on tiny synthetic plants."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from resilimes.config import HORIZON
from resilimes.domain.critique import critique_schedule
from resilimes.domain.kpis import completion_of, evaluate, first_op
from resilimes.domain.models import Equipment, Job, Plant, Product, RouteStep
from resilimes.domain.plant import load_sample
from resilimes.domain.scenarios import plants_for_scenario
from resilimes.domain.schedule import POLICY_FROZEN, POLICY_RECOVER, schedule_plant


def test_litho_recovery_saves_the_priority_lot() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    pair = plants_for_scenario(plant, "litho_down")
    before = schedule_plant(pair.before, POLICY_FROZEN)
    after = schedule_plant(pair.after, POLICY_RECOVER)
    before_first = first_op(before, "LOT-1001")
    after_first = first_op(after, "LOT-1001")
    assert before_first is not None and after_first is not None
    assert before_first.equipment_id == "LITHO-02"
    assert after_first.equipment_id == "LITHO-01"
    assert completion_of(after, "LOT-1001") == 253
    before_kpi = evaluate(pair.before, before)
    after_kpi = evaluate(pair.after, after)
    assert after_kpi.weighted_tardiness_min < before_kpi.weighted_tardiness_min
    assert after_kpi.on_time_delivery_pct > before_kpi.on_time_delivery_pct
    assert critique_schedule(pair.after, after).verdict == "accept"
    assert critique_schedule(pair.before, before).verdict == "accept"


def test_every_mask_type_has_two_copies_and_litho_names_one() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    counts: dict[tuple[str, str], int] = {}
    for item in plant.reticles:
        key = (item.product_id, item.step)
        counts[key] = counts.get(key, 0) + 1
    assert counts
    assert min(counts.values()) >= 2
    pair = plants_for_scenario(plant, "litho_down")
    after = schedule_plant(pair.after, POLICY_RECOVER)
    litho = [op for op in after.operations if op.step.startswith("LITHO")]
    assert litho
    assert all(op.reticle_id for op in litho)
    rush = plants_for_scenario(plant, "rush_order")
    booked = schedule_plant(rush.after, POLICY_RECOVER)
    exposures = [op for op in booked.operations if op.step == "LITHO"]
    overlapped = False
    for index, left in enumerate(exposures):
        for right in exposures[index + 1 :]:
            if left.equipment_id == right.equipment_id:
                continue
            if left.start_min < right.end_min and right.start_min < left.end_min:
                assert left.reticle_id != right.reticle_id
                overlapped = True
    assert overlapped
    assert completion_of(booked, "LOT-2001") == 216


def test_schedule_is_deterministic() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    pair = plants_for_scenario(plant, "litho_down")
    first = schedule_plant(pair.after, POLICY_RECOVER).model_dump()
    second = schedule_plant(pair.after, POLICY_RECOVER).model_dump()
    assert first == second


def test_no_overlap_and_no_down_window_starts() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    pair = plants_for_scenario(plant, "litho_down")
    schedule = schedule_plant(pair.after, POLICY_RECOVER)
    equipment = pair.after.equipment_map()
    by_tool: dict[str, list[tuple[int, int]]] = {}
    for op in schedule.operations:
        assert op.start_min >= equipment[op.equipment_id].available_at_min
        by_tool.setdefault(op.equipment_id, []).append((op.start_min, op.end_min))
    for spans in by_tool.values():
        spans.sort()
        for index in range(1, len(spans)):
            assert spans[index][0] >= spans[index - 1][1]


def test_running_lot_is_not_preempted() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    pair = plants_for_scenario(plant, "litho_down")
    schedule = schedule_plant(pair.after, POLICY_RECOVER)
    first = first_op(schedule, "LOT-1002")
    assert first is not None
    assert first.pinned is True
    assert first.equipment_id == "LITHO-01"


def test_material_shortage_holds_new_litho_and_keeps_running_lot() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    pair = plants_for_scenario(plant, "material_shortage")
    after = schedule_plant(pair.after, POLICY_RECOVER)
    held = {item.job_id for item in after.unscheduled}
    assert "LOT-1001" in held
    assert "LOT-1004" in held
    assert first_op(after, "LOT-1002") is not None
    critique = critique_schedule(pair.after, after)
    assert critique.verdict == "conditional"
    assert not any(item.severity == "high" for item in critique.violations)


def test_capability_blocks_unqualified_tool() -> None:
    plant = _tiny(capability="etch_dielectric", step_capability="etch_metal")
    schedule = schedule_plant(plant, POLICY_RECOVER)
    assert schedule.operations == []
    assert schedule.unscheduled[0].job_id == "LOT-1"


def test_operator_pool_serializes_parallel_tools() -> None:
    horizon = HORIZON
    plant = Plant(
        plant_id="TINY",
        horizon=horizon,
        operator_pool=1,
        equipment=[
            _tool("T-01"),
            _tool("T-02"),
        ],
        jobs=[
            _job("LOT-1", 0),
            _job("LOT-2", 1),
        ],
        products=[_product()],
        source="test",
    )
    schedule = schedule_plant(plant, POLICY_RECOVER)
    spans = sorted((op.start_min, op.end_min) for op in schedule.operations)
    assert len(spans) == 2
    assert spans[1][0] >= spans[0][1]


def test_single_tool_does_not_overlap() -> None:
    plant = _tiny()
    plant.jobs.append(_job("LOT-2", 1))
    schedule = schedule_plant(plant, POLICY_RECOVER)
    ops = sorted(schedule.operations, key=lambda op: op.start_min)
    assert ops[1].start_min >= ops[0].end_min
    assert critique_schedule(plant, schedule).verdict == "accept"


def _tool(equipment_id: str = "T-01") -> Equipment:
    return Equipment(
        equipment_id=equipment_id,
        name=equipment_id,
        area="Test",
        status="IDLE",
        capability=["etch_dielectric"],
        setup_time_min=0,
        operators_required=1,
        max_wip=4,
    )


def _job(job_id: str, offset: int) -> Job:
    return Job(
        job_id=job_id,
        product_id="P",
        priority=1,
        qty=1,
        current_step="QUEUED",
        status="QUEUED",
        due_at=HORIZON + timedelta(hours=8 + offset),
        process_time_min=30,
    )


def _product(step_capability: str = "etch_dielectric") -> Product:
    return Product(
        product_id="P",
        name="P",
        route=[
            RouteStep(
                step="ETCH",
                capability=step_capability,
                process_time_min=30,
                setup_family="E",
            )
        ],
    )


def _tiny(capability: str = "etch_dielectric", step_capability: str = "etch_dielectric") -> Plant:
    tool = _tool()
    tool.capability = [capability]
    return Plant(
        plant_id="TINY",
        horizon=HORIZON,
        operator_pool=4,
        equipment=[tool],
        jobs=[_job("LOT-1", 0)],
        products=[_product(step_capability)],
        source="test",
    )
