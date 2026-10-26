"""Unit tests for the P1 cheap-evidence pieces: the max_plans plumbing,
the K-curve aggregation, and the zero-call comparison."""

from __future__ import annotations

from typing import Any

from resilimes.agents.sim_select import MAX_PLANS, PLAN_SYSTEM, plan_system
from resilimes.smt import search_curve_study as curve
from resilimes.smt import zero_call_study


def test_plan_system_default_is_byte_identical() -> None:
    assert plan_system() == PLAN_SYSTEM
    assert f"up to {MAX_PLANS} alternative plans" in PLAN_SYSTEM
    assert "up to 15 alternative plans" in plan_system(15)


def test_curve_aggregate_math() -> None:
    rows: list[dict[str, Any]] = [
        {"k": 3, "qtime_avoidable": 2, "hot_late": 1, "sim_calls": 40},
        {"k": 3, "qtime_avoidable": 4, "hot_late": 0, "sim_calls": 60},
        {"k": 50, "qtime_avoidable": 1, "hot_late": 0, "sim_calls": 400},
    ]
    by_k = curve.aggregate(rows)
    assert by_k["3"]["runs"] == 2
    assert by_k["3"]["qtime_avoidable"] == {"mean": 3.0, "min": 2.0, "max": 4.0}
    assert by_k["3"]["sim_calls"]["mean"] == 50.0
    assert by_k["50"]["runs"] == 1


def test_zero_call_compare_identical_and_different() -> None:
    base = {
        "weighted_tardiness_min": 100.0,
        "on_time_pct": 7.14,
        "qtime_violations": 3,
        "qtime_avoidable": 0,
        "hot_late": 0,
        "hot_due": 0,
        "completed_routes": 5,
        "shift_lead": {"escalated": 0, "llm_calls": 0},
        "decisions": [{}, {}],
    }
    same = zero_call_study.compare_rules_vs_mock_wiring(base, dict(base))
    assert same["identical"] is True
    assert same["llm_calls"] == 0
    assert same["exceptions"] == 2

    changed = dict(base)
    changed["qtime_avoidable"] = 1
    diff = zero_call_study.compare_rules_vs_mock_wiring(base, changed)
    assert diff["identical"] is False
    assert diff["fields"]["qtime_avoidable"]["same"] is False
    assert diff["fields"]["hot_late"]["same"] is True
