"""Dataset releases: order.txt lots enter the fab at their release, step 0."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.test_smt_invariants import _two_family_fab

from resilimes.smt.fab import load_fab, release_at
from resilimes.smt.invariants import check_trace
from resilimes.smt.planning import dataset_releases, with_releases
from resilimes.smt.qtime_study import balance_kpis
from resilimes.smt.simulate import run_policy

NO_DOWNS: list[list[tuple[float, float]]] = [[], []]


def _run(fab, horizon: float = 8000.0):
    return run_policy(
        fab,
        policy="fifo",
        seed=1,
        horizon=horizon,
        downs=NO_DOWNS,
        pm=NO_DOWNS,
        record=True,
    )


def test_releases_are_off_by_default() -> None:
    fab = _two_family_fab()
    assert fab.lot_release == []
    assert release_at(fab, 1) == 0.0


def test_with_releases_appends_order_lots_at_step_zero() -> None:
    fab = load_fab()
    until = 7 * 86400.0
    plant = with_releases(fab, until=until)
    n = len(fab.lot_id)
    found = dataset_releases(fab, until=until)
    assert len(plant.lot_id) == n + len(found) > 0
    assert plant.lot_id[:n] == fab.lot_id and plant.lot_release[:n] == [0.0] * n
    products: dict[int, set[str]] = {}
    for lot in range(n):
        products.setdefault(fab.lot_route[lot], set()).add(fab.lot_product[lot])
    for lot in range(n, len(plant.lot_id)):
        route = plant.lot_route[lot]
        assert plant.lot_step[lot] == 0
        assert 0.0 <= plant.lot_release[lot] < until
        assert plant.lot_product[lot] in products[route]
        assert plant.lot_due[lot] > plant.lot_release[lot]
    assert plant.lot_due[n:] == [item.due_sec for item in found if item.release_sec >= 0.0]
    assert plant.lot_release[n:] == sorted(plant.lot_release[n:])


def test_released_lot_waits_for_its_release_and_counts_from_it() -> None:
    fab = replace(_two_family_fab(), lot_step=[0, 0], lot_release=[0.0, 3000.0])
    result = _run(fab)
    first = min(e[1] for e in result.events if e[0] == "start" and 1 in e[3])
    assert first >= 3000.0
    assert check_trace(fab, result, downs=NO_DOWNS, pm=NO_DOWNS)["total"] == 0
    kpi = balance_kpis(fab, result.events, 8000.0, NO_DOWNS, NO_DOWNS)
    assert kpi["completed_kpi"] == result.completed_routes == 2
    # X-factor runs from the release: both lots see the same route with no
    # contention once lot 0 has cleared, so lot 1's X is not inflated by 3000 s.
    assert result.mean_x_factor is not None and result.mean_x_factor < 2.0


def test_check_trace_flags_a_start_before_release() -> None:
    fab = replace(_two_family_fab(), lot_step=[0, 0])
    result = _run(fab)
    late = replace(fab, lot_release=[0.0, 3000.0])
    counts = check_trace(late, result, downs=NO_DOWNS, pm=NO_DOWNS)["counts"]
    assert counts["release"] > 0


def test_study_plan_holds_every_released_lot(monkeypatch: pytest.MonkeyPatch) -> None:
    from resilimes.smt import qtime_study as study

    monkeypatch.setenv("RESILIMES_STUDY_HORIZON_H", "48")
    fab = load_fab()
    plant, _ = study._setup(fab, "published", 1, "resilimes", releases=True)
    plan = study.book_plan(fab, "published", releases=True)
    assert len(plant.lot_id) > len(fab.lot_id)
    assert all(plan.find(lot_id) is not None for lot_id in plant.lot_id)
    released = plant.lot_id[len(fab.lot_id) :]
    assert all(plan.lot(lot_id).released for lot_id in released)
    assert study.book_plan(fab, "published", releases=False) is not plan
