"""Trace invariants. A started step runs on a tool of that step's family."""

from __future__ import annotations

import pytest

from resilimes.smt.fab import Fab, Family, Route, load_fab
from resilimes.smt.invariants import check_trace
from resilimes.smt.simulate import pm_windows, run_policy, sample_downs

POLICIES = ("resilimes", "edd", "fifo", "cr", "smt_rule")


def _two_family_fab(*, cqt_limit: float = 0.0) -> Fab:
    """Labeled unit fixture, not SMT2020 data.

    Family ``Etch_A`` (tool ``Etch_A-1``) and family ``Clean_B`` (tool
    ``Clean_B-1``). Route ``AB`` is A then B. Lot ``L_AB`` starts at A.
    Lot ``L_B`` starts at B and holds ``Clean_B-1`` for 1000 s, so ``L_AB``
    finishes A at 100 s and then waits for B while ``Etch_A-1`` is idle.
    A stale queue entry would let ``Etch_A-1`` start the B step.
    """
    families = [
        Family(name="Etch_A", group="Etch", tools=1, tool0=0, litho=False, scanner=False),
        Family(name="Clean_B", group="Clean", tools=1, tool0=1, litho=False, scanner=False),
    ]
    route = Route(
        route_id="AB",
        family=[0, 1],
        cycle=[100.0, 1000.0],
        recipe=[0, 0],
        batch_min=[0, 0],
        batch_max=[0, 0],
        cqt_limit=[cqt_limit, 0.0],
        cqt_target=[1 if cqt_limit > 0 else -1, -1],
        remain=[1100.0, 1000.0],
        step_index={1: 0, 2: 1},
        dedicate_root=[-1, -1],
    )
    return Fab(
        families=families,
        family_index={"Etch_A": 0, "Clean_B": 1},
        tool_family=[0, 1],
        tool_name=["Etch_A-1", "Clean_B-1"],
        routes=[route],
        route_index={"AB": 0},
        lot_id=["L_AB", "L_B"],
        lot_product=["p", "p"],
        lot_route=[0, 0],
        lot_step=[0, 1],
        lot_due=[100_000.0, 100_000.0],
        lot_value=[1.0, 1.0],
        lot_class=["normal", "normal"],
        lot_priority=[10, 10],
        recipe_name=[""],
        setup={},
        down_mttf={},
        down_mttr={},
        pm=[],
        focus_family=0,
        focus_tool=0,
        hot_lot=0,
        pm_calendar="",
        group_names=["Etch", "Clean"],
    )


def _starts(fab: Fab, policy: str) -> list[tuple[str, int, str]]:
    result = run_policy(
        fab,
        policy=policy,
        seed=1,
        horizon=5000,
        downs=[[], []],
        pm=[[], []],
        record=True,
    )
    rows = []
    for event in result.events:
        if event[0] == "start":
            for lot in event[3]:
                rows.append((fab.lot_id[lot], event[4], fab.tool_name[event[2]]))
    return rows


@pytest.mark.parametrize("policy", POLICIES)
def test_advanced_lot_leaves_its_old_family_queue(policy: str) -> None:
    fab = _two_family_fab()
    rows = _starts(fab, policy)
    for lot_id, step, tool in rows:
        route = fab.routes[fab.lot_route[fab.lot_id.index(lot_id)]]
        assert tool.startswith(fab.families[route.family[step]].name + "-"), (lot_id, step, tool)
    # L_AB runs B only after L_B frees Clean_B-1, never on Etch_A-1.
    assert ("L_AB", 1, "Clean_B-1") in rows
    assert ("L_AB", 1, "Etch_A-1") not in rows


@pytest.mark.parametrize("policy", POLICIES)
def test_full_fab_starts_pass_every_invariant(policy: str) -> None:
    fab = load_fab()
    horizon = 4 * 3600.0
    downs = sample_downs(fab, 1, horizon)
    pm = pm_windows(fab, horizon)
    result = run_policy(
        fab, policy=policy, seed=1, horizon=horizon, downs=downs, pm=pm, record=True
    )
    report = check_trace(fab, result, downs=downs, pm=pm)
    assert report["starts"] > 1000
    assert report["total"] == 0, report["examples"]
    assert report["qtime_recount"] == result.qtime_violations


def test_checker_flags_a_wrong_family_start() -> None:
    fab = _two_family_fab()
    result = run_policy(
        fab, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    assert check_trace(fab, result, downs=[[], []], pm=[[], []])["total"] == 0
    # Start lot L_AB's step 1 (Clean_B) on Etch_A-1, before the real start.
    forged = [("start", 150.0, 0, (0,), 1, 1150.0)]
    first_b = next(
        i for i, e in enumerate(result.events) if e[0] == "start" and e[4] == 1 and 0 in e[3]
    )
    result.events[first_b:first_b] = forged
    report = check_trace(fab, result, downs=[[], []], pm=[[], []])
    assert report["counts"]["family"] == 1
    assert report["counts"]["route_order"] >= 1


def test_checker_flags_pm_and_down_overlap() -> None:
    fab = _two_family_fab()
    result = run_policy(
        fab, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    # The A start at 0 runs to 100. A PM at 50 and a down window over 0 both catch it.
    report = check_trace(fab, result, downs=[[(0.0, 10.0)], []], pm=[[(50.0, 60.0)], []])
    assert report["counts"]["pm_overlap"] == 1
    assert report["counts"]["down_start"] == 1


def test_qtime_recount_uses_a_strict_greater_than() -> None:
    # A ends at 100. The window closes at 100 + 900 = 1000, exactly when
    # Clean_B-1 frees up. Starting at the deadline is not a violation.
    fab = _two_family_fab(cqt_limit=900.0)
    result = run_policy(
        fab, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    report = check_trace(fab, result, downs=[[], []], pm=[[], []])
    assert result.qtime_violations == 0
    assert report["qtime_recount"] == 0
    assert report["total"] == 0
    late = _two_family_fab(cqt_limit=899.0)
    result = run_policy(
        late, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    report = check_trace(late, result, downs=[[], []], pm=[[], []])
    assert result.qtime_violations == 1
    assert report["qtime_recount"] == 1
    assert report["total"] == 0
