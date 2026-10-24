"""Study KPIs: rebuilt from events, they must agree with the simulator."""

from __future__ import annotations

from tests.test_smt_invariants import _two_family_fab

from resilimes.smt.qtime_study import _complement, _merge_spans, _overlap, _spread, balance_kpis
from resilimes.smt.simulate import run_policy

NO_DOWNS: list[list[tuple[float, float]]] = [[], []]


def test_span_helpers() -> None:
    merged = _merge_spans([(5.0, 7.0), (0.0, 2.0), (1.0, 3.0)])
    assert merged == [(0.0, 3.0), (5.0, 7.0)]
    assert _complement(merged, 10.0) == [(3.0, 5.0), (7.0, 10.0)]
    assert _overlap(merged, [(2.0, 6.0)]) == 2.0
    assert _spread([1.0, 3.0]) == {"max_min": 2.0, "cv": 0.5}
    assert _spread([]) == {"max_min": None, "cv": None}


def test_kpis_match_the_simulator_on_a_toy_fab() -> None:
    fab = _two_family_fab()
    horizon = 5000.0
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=horizon,
        downs=NO_DOWNS,
        pm=NO_DOWNS,
        record=True,
    )
    kpi = balance_kpis(fab, result.events, horizon, NO_DOWNS, NO_DOWNS)
    assert kpi["completed_kpi"] == result.completed_routes
    assert sum(row["completed"] for row in kpi["route"].values()) == result.completed_routes
    starts = [e for e in result.events if e[0] == "start"]
    busy = {0: 0.0, 1: 0.0}
    for event in starts:
        busy[event[2]] += min(float(event[5]), horizon) - float(event[1])
    assert kpi["util_spread"]["max_min"] == round(abs(busy[1] - busy[0]) / horizon, 4)
    ends = sum(1 for e in result.events if e[0] == "end")
    assert kpi["steps_per_day"] == round(ends / (horizon / 86400.0), 1)
    assert sum(kpi["wip_quintile_end_lots"]) == len(fab.lot_id) - result.completed_routes
