"""Trace invariants. A started step runs on a tool of that step's family."""

from __future__ import annotations

from typing import Any

import pytest

from resilimes.smt.fab import Fab, Family, Route, load_fab, lot_number, measured
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
            for lot, step in zip(event[3], event[4], strict=True):
                rows.append((fab.lot_id[lot], step, fab.tool_name[event[2]]))
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
    forged = [("start", 150.0, 0, (0,), (1,), 1150.0, "", (0,))]
    first_b = next(
        i for i, e in enumerate(result.events) if e[0] == "start" and e[4] == (1,) and 0 in e[3]
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


@pytest.mark.parametrize("pct", [10.0, 33.0, 37.0, 52.0, 59.0, 100.0])
def test_sampling_rule_measures_exactly_pct_of_every_hundred_lots(pct: float) -> None:
    route = _two_family_fab().routes[0]
    route.sample_pct = [100.0, pct]
    route.step_no = [1, 2]
    for start in (0, 7, 250):
        hits = [measured(route, 1, number) for number in range(start, start + 100)]
        assert sum(hits) == int(pct)
    assert lot_number("Init_Lot_3_17", 0) == 17
    assert lot_number("odd", 5) == 5


def test_unsampled_q_time_target_is_skipped_and_closes_the_window() -> None:
    fab = _two_family_fab(cqt_limit=1.0)
    route = fab.routes[0]
    route.sample_pct = [100.0, 0.0]
    route.step_no = [1, 2]
    result = run_policy(
        fab, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    # L_AB skips B (0 % sampled) right after A: no Q-time check, route done.
    assert result.skipped == 1
    assert result.qtime_skipped == 1
    assert result.qtime_violations == 0
    assert any(event[0] == "skip" and event[3] == 1 for event in result.events)
    report = check_trace(fab, result, downs=[[], []], pm=[[], []])
    assert report["total"] == 0, report["examples"]
    # Forging a skip of a measured step is caught.
    route.sample_pct = [100.0, 100.0]
    assert check_trace(fab, result, downs=[[], []], pm=[[], []])["counts"]["sampling"] == 1


def test_full_fab_skips_sampled_steps_at_the_dataset_rate() -> None:
    fab = load_fab()
    sampled = sum(1 for route in fab.routes for pct in route.sample_pct if pct < 100.0)
    assert sampled > 0
    horizon = 4 * 3600.0
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=horizon,
        downs=sample_downs(fab, 1, horizon),
        pm=pm_windows(fab, horizon),
    )
    assert result.skipped > 0


def _qtime_fab(*, cqt_limit: float, second: str, second_due: float = 100_000.0) -> Fab:
    """Labeled unit fixture, not SMT2020 data.

    ``Etch_A-1`` runs ``L_Q`` (normal) at step A for 100 s. If ``cqt_limit`` is
    set, that opens a Q-time window to step B. ``Clean_B-1`` (500 s per lot)
    has ``L_V1`` (VIP) and ``L_2`` (class ``second``) waiting at B from 0 s.
    At 500 s ``L_Q`` has ``cqt_limit - 400`` s left before B must start.
    ``L_V1`` and ``L_2`` follow route ``B`` (B only), so they are not inside a
    Q-time span at t=0 and carry no inherited window.
    """
    fab = _two_family_fab(cqt_limit=cqt_limit)
    route = fab.routes[0]
    route.cycle[:] = [100.0, 500.0]
    route.remain[:] = [600.0, 500.0]
    only_b = Route(
        route_id="B",
        family=[1],
        cycle=[500.0],
        recipe=[0],
        batch_min=[0],
        batch_max=[0],
        cqt_limit=[0.0],
        cqt_target=[-1],
        remain=[500.0],
        step_index={2: 0},
        dedicate_root=[-1],
    )
    fab.routes.append(only_b)
    fab.route_index["B"] = 1
    fab.lot_id[:] = ["L_Q", "L_V1", "L_2"]
    fab.lot_product[:] = ["p", "p", "p"]
    fab.lot_route[:] = [0, 1, 1]
    fab.lot_step[:] = [0, 0, 0]
    fab.lot_due[:] = [100_000.0, 100_000.0, second_due]
    fab.lot_value[:] = [1.0, 1.0, 1.0]
    fab.lot_class[:] = ["normal", "VIP", second]
    fab.lot_priority[:] = [10, 30, 30 if second == "VIP" else 20]
    return fab


def _b_order(fab: Fab, policy: str) -> tuple[list[str], Any]:
    result = run_policy(
        fab, policy=policy, seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    order = [fab.lot_id[e[3][0]] for e in result.events if e[0] == "start" and e[2] == 1]
    return order, result


def test_qtime_urgent_normal_lot_jumps_a_waiting_vip() -> None:
    fab = _qtime_fab(cqt_limit=700.0, second="VIP")
    order, result = _b_order(fab, "resilimes")
    assert order == ["L_V1", "L_Q", "L_2"]
    assert result.qtime_overrides == 1
    assert result.qtime_override_displaced == {"VIP": 1}
    assert result.qtime_violations == 0
    overrides = [e for e in result.events if e[0] == "override"]
    assert len(overrides) == 1 and fab.lot_id[overrides[0][3]] == "L_Q"
    assert check_trace(fab, result, downs=[[], []], pm=[[], []])["total"] == 0
    # EDD has no override: the VIP goes first and L_Q misses its window.
    order, result = _b_order(fab, "edd")
    assert order == ["L_V1", "L_2", "L_Q"]
    assert result.qtime_overrides == 0
    assert result.qtime_violations == 1


def test_qtime_override_needs_the_window_to_be_close() -> None:
    # 4600 s left at 500 s: far beyond need + 900 s, so the VIP keeps its turn.
    order, result = _b_order(_qtime_fab(cqt_limit=5000.0, second="VIP"), "resilimes")
    assert order == ["L_V1", "L_2", "L_Q"]
    assert result.qtime_overrides == 0


def test_no_override_on_a_step_without_dataset_cqt() -> None:
    fab = _qtime_fab(cqt_limit=0.0, second="VIP")
    order, result = _b_order(fab, "resilimes")
    assert order == ["L_V1", "L_2", "L_Q"]
    assert result.qtime_overrides == 0
    assert not [e for e in result.events if e[0] == "override"]


def test_late_hot_lot_stays_ahead_of_a_qtime_urgent_lot() -> None:
    fab = _qtime_fab(cqt_limit=700.0, second="hot", second_due=0.0)
    order, result = _b_order(fab, "resilimes")
    # The late hot lot leads at 0 s (band 0), the urgent normal lot then jumps
    # the on-time VIP at 500 s.
    assert order == ["L_2", "L_Q", "L_V1"]
    assert result.qtime_overrides == 1
    assert check_trace(fab, result, downs=[[], []], pm=[[], []])["total"] == 0


def test_override_check_flags_an_override_outside_a_cqt_window() -> None:
    fab = _qtime_fab(cqt_limit=0.0, second="VIP")
    _order, result = _b_order(fab, "resilimes")
    start = next(i for i, e in enumerate(result.events) if e[0] == "start" and e[2] == 1)
    lead = result.events[start][3][0]
    forged = ("override", result.events[start][1], 1, lead, 1, 2, 100.0, 0.0, "VIP")
    result.events.insert(start, forged)
    report = check_trace(fab, result, downs=[[], []], pm=[[], []])
    assert report["counts"]["qtime_override"] == 1


def test_full_fab_overrides_only_on_dataset_cqt_windows() -> None:
    fab = load_fab()
    horizon = 12 * 3600.0
    downs = sample_downs(fab, 1, horizon)
    pm = pm_windows(fab, horizon)
    spans = set()
    for route_i, route in enumerate(fab.routes):
        for origin, limit in enumerate(route.cqt_limit):
            if limit > 0 and route.cqt_target[origin] >= 0:
                for index in range(origin + 1, route.cqt_target[origin] + 1):
                    spans.add((route_i, index))
    result = run_policy(
        fab, policy="resilimes", seed=1, horizon=horizon, downs=downs, pm=pm, record=True
    )
    rows = [e for e in result.events if e[0] == "override"]
    assert rows and len(rows) == result.qtime_overrides
    assert all((fab.lot_route[e[3]], e[4]) in spans for e in rows)
    assert check_trace(fab, result, downs=downs, pm=pm)["counts"]["qtime_override"] == 0
    edd = run_policy(fab, policy="edd", seed=1, horizon=horizon, downs=downs, pm=pm)
    assert edd.qtime_overrides == 0


def test_transport_delays_the_next_start_by_the_bay_move() -> None:
    # Etch_A and Clean_B are different STNGRP bays: 3 min from A to B.
    fab = _qtime_fab(cqt_limit=0.0, second="VIP")
    fab.lot_route[:] = [0, 0, 0]
    fab.lot_step[:] = [0, 0, 0]
    result = run_policy(
        fab, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    ends = {e[2]: e[1] for e in result.events if e[0] == "end" and e[3] == 0}
    first_b = {}
    for e in result.events:
        if e[0] == "start" and e[2] == 1:
            for lot in e[3]:
                first_b.setdefault(lot, e[1])
    assert first_b and all(first_b[lot] >= ends[lot] + 180.0 - 1e-6 for lot in first_b)
    assert min(first_b[lot] - ends[lot] for lot in first_b) == pytest.approx(180.0)
    assert check_trace(fab, result, downs=[[], []], pm=[[], []])["counts"]["transport"] == 0
    # Same bay: 1 min.
    fab.families[1].group = "Etch"
    result = run_policy(
        fab, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    ends = {e[2]: e[1] for e in result.events if e[0] == "end" and e[3] == 0}
    first = next(e for e in result.events if e[0] == "start" and e[2] == 1)
    assert first[1] == pytest.approx(ends[first[3][0]] + 60.0)


def test_transport_check_flags_a_start_before_the_move_is_over() -> None:
    fab = _qtime_fab(cqt_limit=0.0, second="VIP")
    fab.lot_route[:] = [0, 0, 0]
    fab.lot_step[:] = [0, 0, 0]
    result = run_policy(
        fab, policy="edd", seed=1, horizon=5000, downs=[[], []], pm=[[], []], record=True
    )
    at = next(i for i, e in enumerate(result.events) if e[0] == "start" and e[2] == 1)
    row = list(result.events[at])
    lot = row[3][0]
    end = next(e[1] for e in result.events if e[0] == "end" and e[2] == lot and e[3] == 0)
    row[1] = end + 30.0
    result.events[at] = tuple(row)
    report = check_trace(fab, result, downs=[[], []], pm=[[], []])
    assert report["counts"]["transport"] >= 1


def test_no_transport_ablation_is_a_separate_flag() -> None:
    fab = _qtime_fab(cqt_limit=0.0, second="VIP")
    fab.lot_route[:] = [0, 0, 0]
    fab.lot_step[:] = [0, 0, 0]
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=5000,
        downs=[[], []],
        pm=[[], []],
        record=True,
        transport=False,
    )
    ends = {e[2]: e[1] for e in result.events if e[0] == "end" and e[3] == 0}
    first = next(e for e in result.events if e[0] == "start" and e[2] == 1)
    assert first[1] == pytest.approx(ends[first[3][0]])
    assert result.transport is False
    assert check_trace(fab, result, downs=[[], []], pm=[[], []])["total"] == 0
