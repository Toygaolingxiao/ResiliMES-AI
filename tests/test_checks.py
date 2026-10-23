"""Constraint registry: same verdicts, plus the lean semiconductor checks."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.agents.planner import naive_alternative, reject_alternative
from resilimes.config import HORIZON, Settings
from resilimes.domain.checks import REGISTRY, validate
from resilimes.domain.critique import constraint_checks, critique_schedule
from resilimes.domain.models import (
    Equipment,
    Inhibit,
    Job,
    Plant,
    Product,
    Reticle,
    RouteStep,
    Schedule,
    ScheduledOp,
    Unscheduled,
)
from resilimes.domain.plant import load_sample
from resilimes.domain.scenarios import plants_for_scenario
from resilimes.domain.schedule import POLICY_RECOVER, schedule_plant

EXPECTED = (
    "equipment_status",
    "capability",
    "overlap",
    "wip",
    "operators",
    "material",
    "precedence",
    "preemption",
    "qtime",
    "rework_limit",
    "reticle",
    "inhibit",
    "release_time",
    "hold_release",
)


def test_registry_lists_every_check() -> None:
    assert tuple(item.id for item in REGISTRY) == EXPECTED
    for item in REGISTRY:
        assert set(item.name) == {"en", "zh", "ja"}
        assert item.description["en"]
        assert item.category in {"equipment", "lot", "process", "material", "time"}
        assert item.fields


def test_litho_book_passes_and_keeps_the_down_tool_refusal() -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    pair = plants_for_scenario(plant, "litho_down")
    after = schedule_plant(pair.after, POLICY_RECOVER)
    report = validate(pair.after, after)
    assert report["overall"] == "passed"
    assert report["failed"] == 0
    by_id = {row["id"]: row for row in report["details"]}  # type: ignore[misc]
    assert by_id["equipment_status"]["status"] == "passed"
    assert by_id["reticle"]["status"] == "passed"
    assert by_id["inhibit"]["status"] == "passed"
    assert by_id["release_time"]["status"] == "passed"
    assert by_id["rework_limit"]["status"] == "passed"
    assert by_id["qtime"]["status"] == "passed"
    committed = critique_schedule(pair.after, after)
    rejected = reject_alternative(pair.after, naive_alternative(pair.after, "frozen"))
    assert rejected.violations[0].constraint == "equipment_status"
    assert any(item.constraint == "reticle" for item in rejected.violations)
    rows = constraint_checks(committed, rejected)
    refused = next(row for row in rows if row["constraint"] == "equipment_status")
    assert refused["result"] == "rejected"
    assert "LITHO-02" in refused["reason"]


def test_recovery_validation_matches_the_registry() -> None:
    report = run_recovery(
        Settings(mode="mock", horizon=HORIZON, scout_signing_secret="check-secret"),
        RecoverInput(scenario="litho_down"),
    )
    assert report.validation is not None
    assert report.validation["overall"] == "passed"
    assert [row["id"] for row in report.validation["details"]] == list(EXPECTED)


def test_reticle_blocks_two_tools_at_once() -> None:
    plant = _bay()
    plant.reticles = [Reticle(reticle_id="RET-1", product_id="P", layer="L1", step="LITHO")]
    schedule = Schedule(
        policy="recover",
        operations=[
            _op("LOT-1", "T-01", 0, 30),
            _op("LOT-2", "T-02", 0, 30),
        ],
    )
    critique = critique_schedule(plant, schedule)
    assert critique.verdict == "reject"
    assert any(item.constraint == "reticle" for item in critique.violations)
    legal = schedule_plant(plant, POLICY_RECOVER)
    assert critique_schedule(plant, legal).verdict == "accept"
    uses = [
        (op.equipment_id, op.start_min, op.end_min) for op in legal.operations if op.step == "LITHO"
    ]
    for index, left in enumerate(uses):
        for right in uses[index + 1 :]:
            if left[0] == right[0]:
                continue
            assert left[2] <= right[1] or right[2] <= left[1]


def test_inhibit_rejects_a_dedicated_tool() -> None:
    plant = _bay()
    plant.inhibits = [Inhibit(inhibit_id="INH-1", product_id="P", recipe="", equipment_id="T-01")]
    placed = schedule_plant(plant, POLICY_RECOVER)
    assert placed.operations
    assert all(op.equipment_id != "T-01" for op in placed.operations)
    illegal = Schedule(policy="recover", operations=[_op("LOT-1", "T-01", 0, 30)])
    critique = critique_schedule(plant, illegal)
    assert any(item.constraint == "inhibit" for item in critique.violations)


def test_release_time_blocks_an_early_start() -> None:
    plant = _bay()
    plant.jobs[0].release_min = 40
    placed = schedule_plant(plant, POLICY_RECOVER)
    first = next(op for op in placed.operations if op.job_id == "LOT-1")
    assert first.start_min >= 40
    assert critique_schedule(plant, placed).verdict == "accept"
    early = Schedule(policy="recover", operations=[_op("LOT-1", "T-02", 0, 30)])
    critique = critique_schedule(plant, early)
    assert any(item.constraint == "release_time" for item in critique.violations)


def test_rework_limit_rejects_a_second_loop() -> None:
    plant = _bay()
    plant.jobs[0].rework_of = "LITHO"
    plant.jobs[0].rework_limit = 1
    schedule = Schedule(
        policy="recover",
        operations=[
            _op("LOT-1", "T-02", 0, 30, step="LITHO-RW", rework=True, step_index=1),
            _op("LOT-1", "T-02", 30, 60, step="LITHO-RW", rework=True, step_index=2),
        ],
    )
    critique = critique_schedule(plant, schedule)
    assert any(item.constraint == "rework_limit" for item in critique.violations)
    wrong = Schedule(
        policy="recover",
        operations=[_op("LOT-1", "T-02", 0, 30, step="ETCH", rework=True)],
    )
    again = critique_schedule(plant, wrong)
    assert any("return step" in item.detail for item in again.violations)


def test_a_hold_stays_conditional() -> None:
    plant = _bay()
    schedule = Schedule(
        policy="recover",
        unscheduled=[Unscheduled(job_id="LOT-1", step="LITHO", reason="Held for the demo.")],
    )
    critique = critique_schedule(plant, schedule)
    assert critique.verdict == "conditional"
    assert not critique.violations
    report = validate(plant, schedule)
    assert report["overall"] == "passed"
    hold = next(row for row in report["details"] if row["id"] == "hold_release")  # type: ignore[union-attr]
    assert hold["status"] == "passed"
    assert len(hold["violations"]) == 1


def _bay() -> Plant:
    return Plant(
        plant_id="TINY",
        horizon=HORIZON,
        operator_pool=4,
        equipment=[_tool("T-01"), _tool("T-02")],
        jobs=[_job("LOT-1"), _job("LOT-2")],
        products=[
            Product(
                product_id="P",
                name="P",
                route=[
                    RouteStep(
                        step="LITHO",
                        capability="litho_193nm",
                        process_time_min=30,
                        setup_family="L",
                        recipe="LITHO_L1",
                        area="Lithography",
                    )
                ],
            )
        ],
        source="test",
    )


def _tool(equipment_id: str) -> Equipment:
    return Equipment(
        equipment_id=equipment_id,
        name=equipment_id,
        area="Lithography",
        status="IDLE",
        capability=["litho_193nm"],
        max_wip=1,
    )


def _job(job_id: str) -> Job:
    return Job(
        job_id=job_id,
        product_id="P",
        priority=1,
        qty=1,
        current_step="LITHO",
        status="QUEUED",
        due_at=HORIZON + timedelta(hours=8),
        process_time_min=30,
    )


def _op(
    job_id: str,
    tool: str,
    start: int,
    end: int,
    *,
    step: str = "LITHO",
    rework: bool = False,
    step_index: int = 0,
) -> ScheduledOp:
    return ScheduledOp(
        job_id=job_id,
        product_id="P",
        step=step,
        step_index=step_index,
        equipment_id=tool,
        start_min=start,
        end_min=end,
        setup_min=0,
        process_min=end - start,
        setup_family="L",
        priority=1,
        rework=rework,
    )
