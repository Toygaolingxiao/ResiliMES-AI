"""CP-SAT reference against the list scheduler. The solve is skipped without OR-Tools."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from resilimes.config import HORIZON
from resilimes.domain.checks import validate
from resilimes.domain.cpsat import optimality_reference, ortools_available
from resilimes.domain.critique import critique_schedule
from resilimes.domain.kpis import evaluate
from resilimes.domain.models import Schedule, ScheduledOp, Unscheduled
from resilimes.domain.plant import load_sample
from resilimes.domain.scale_fab import build_scale_plant
from resilimes.domain.scenarios import plants_for_scenario
from resilimes.domain.schedule import POLICY_RECOVER, schedule_plant

HEROES = ("litho_down", "rush_order", "material_shortage", "rework", "qtime")
SCALE_HORIZON = datetime(2026, 10, 22, 6, 30, tzinfo=UTC)

requires_ortools = pytest.mark.skipif(not ortools_available(), reason="ortools is optional")


def _book(payload: dict) -> Schedule:
    reference = payload["reference"]
    return Schedule(
        policy="cpsat",
        operations=[ScheduledOp.model_validate(row) for row in reference["operations"]],
        unscheduled=[Unscheduled.model_validate(row) for row in reference["unscheduled"]],
    )


@requires_ortools
@pytest.mark.parametrize("scenario", HEROES)
def test_hero_reference_passes_the_critic_and_matches_tardiness(scenario: str) -> None:
    plant = load_sample(Path("data/sample"), HORIZON)
    after = plants_for_scenario(plant, scenario).after
    heuristic = schedule_plant(after, POLICY_RECOVER)
    snapshot = heuristic.model_dump()
    report = optimality_reference(after, heuristic, mode="exact", limit_s=5)
    assert heuristic.model_dump() == snapshot
    assert report["available"] is True
    assert report["status"] == "OPTIMAL"
    assert report["proved"] is True
    heuristic_kpi = evaluate(after, heuristic)
    assert report["best_tardiness_min"] <= heuristic_kpi.weighted_tardiness_min
    reference = _book(report)
    assert validate(after, heuristic)["failed"] == 0
    assert validate(after, reference)["failed"] == 0
    assert critique_schedule(after, heuristic).verdict != "reject"
    assert critique_schedule(after, reference).verdict != "reject"
    assert evaluate(after, reference).weighted_tardiness_min == report["best_tardiness_min"]
    litho = [op for op in reference.operations if op.step.startswith("LITHO")]
    assert litho
    assert all(op.reticle_id for op in litho)
    if scenario == "rework":
        assert report["best_tardiness_min"] == 0
        assert heuristic_kpi.makespan_min == 402
        assert report["best_makespan_min"] == 326
        assert report["improved"] is True
    elif scenario == "rush_order":
        assert report["best_tardiness_min"] == heuristic_kpi.weighted_tardiness_min
        assert heuristic_kpi.makespan_min == 342
        assert report["best_makespan_min"] == 293
        assert report["improved"] is True
    elif scenario == "qtime":
        assert report["best_tardiness_min"] == heuristic_kpi.weighted_tardiness_min
        assert heuristic_kpi.makespan_min == 285
        assert report["best_makespan_min"] == 256
        assert report["improved"] is True
    else:
        assert report["best_tardiness_min"] == heuristic_kpi.weighted_tardiness_min
        assert report["best_makespan_min"] == heuristic_kpi.makespan_min
        assert report["improved"] is False


def test_missing_solver_hides_the_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("resilimes.domain.cpsat.ortools_available", lambda: False)
    plant = load_sample(Path("data/sample"), HORIZON)
    after = plants_for_scenario(plant, "litho_down").after
    heuristic = schedule_plant(after, POLICY_RECOVER)
    report = optimality_reference(after, heuristic, mode="exact", limit_s=5)
    assert report["available"] is False
    assert report["status"] == "UNAVAILABLE"
    assert report["reference"] is None
    assert report["heuristic_tardiness_min"] == evaluate(after, heuristic).weighted_tardiness_min


@requires_ortools
def test_scale_neighborhood_keeps_the_heuristic_available() -> None:
    plant = build_scale_plant(SCALE_HORIZON)
    heuristic = schedule_plant(plant, POLICY_RECOVER)
    snapshot = heuristic.model_dump()
    report = optimality_reference(plant, heuristic, mode="lns", limit_s=2, include_book=True)
    assert heuristic.model_dump() == snapshot
    assert report["available"] is True
    assert report["runtime_ms"] < 8000
    heuristic_kpi = evaluate(plant, heuristic)
    assert report["best_tardiness_min"] <= heuristic_kpi.weighted_tardiness_min
    assert validate(plant, heuristic)["failed"] == 0
    assert report["status"] == "KEPT"
    assert report["improved"] is False
    assert report["best_tardiness_min"] == 0
    assert heuristic_kpi.makespan_min == 5116
    assert report["best_makespan_min"] == 5116
    assert report["makespan_delta_min"] == 0
    assert report["reference"] is None
