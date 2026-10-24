"""Q-time r2: window buckets, deadline event, batching, shortlist, urgency, reservation."""

from __future__ import annotations

from tests.test_smt_invariants import _two_family_fab

from resilimes.smt.fab import Fab, Family, Route, inherited_windows, load_fab
from resilimes.smt.invariants import check_trace
from resilimes.smt.qtime_kpi import bucket_counts, qtime_buckets
from resilimes.smt.simulate import run_policy

NO_DOWNS: list[list[tuple[float, float]]] = [[], []]


def _run(fab, policy="edd", horizon=5000.0, **kwargs):
    return run_policy(
        fab,
        policy=policy,
        seed=1,
        horizon=horizon,
        downs=NO_DOWNS,
        pm=NO_DOWNS,
        record=True,
        **kwargs,
    )


# Fix 6: reporting -----------------------------------------------------------


def test_inherited_window_is_counted_apart_from_dispatcher_windows() -> None:
    # L_B sits at B (inside the A->B span) at t=0: an inherited window with the
    # full 899 s limit, met at 0 s. L_AB opens a dispatcher window at 100 s and
    # cannot start B by 999 s (Q-time hold at the deadline).
    fab = _two_family_fab(cqt_limit=899.0)
    assert inherited_windows(fab) == [(1, 0, 1, 899.0)]
    result = _run(fab)
    assert result.qtime_inherited["met"] == 1
    assert result.qtime_inherited_windows == 1
    assert result.qtime_windows["held"] == 1
    assert result.qtime_violations == 1
    assert result.qtime_rate_pct == 0.0
    assert check_trace(fab, result, downs=NO_DOWNS, pm=NO_DOWNS)["total"] == 0


def test_true_rate_counts_every_missed_bucket() -> None:
    # 2692 met of 3108 scored windows (the PR #18 total; the split of the 416
    # misses here is illustrative). met / (met + late) overstates the rate.
    body = bucket_counts({"met": 2692, "late": 190, "recleaned": 36, "expired": 190})
    assert body["scored"] == 3108
    assert body["rate_pct"] == 86.6
    assert round(100 * 2692 / (2692 + 190), 1) == 93.4
    held = bucket_counts({"met": 1, "late": 1, "held": 2})
    assert held["started_late"] == 3 and held["rate_pct"] == 25.0


def test_api_block_reports_four_buckets_and_inherited() -> None:
    result = _run(_two_family_fab(cqt_limit=899.0))
    body = qtime_buckets(result)
    for key in ("met", "started_late", "recleaned", "open_expired", "rate_pct"):
        assert key in body
    assert body["inherited"]["met"] == 1


def test_full_fab_has_433_inherited_windows() -> None:
    assert len(inherited_windows(load_fab())) == 433


# Fix 5: timed deadline event ------------------------------------------------


def _b_starts(fab, result, lot: int) -> list[float]:
    return [e[1] for e in result.events if e[0] == "start" and lot in e[3] and e[2] == 1]


def test_deadline_event_holds_an_unstarted_lot_and_requeues_it() -> None:
    # L_AB ends A at 100 s; B must start by 999 s but L_B holds Clean_B-1 to
    # 1000 s. The origin is not a wet step, so at 999 s the lot goes to Q-time
    # hold for 30 min, then requeues.
    fab = _two_family_fab(cqt_limit=899.0)
    result = _run(fab)
    holds = [e for e in result.events if e[0] == "qhold"]
    assert len(holds) == 1 and holds[0][2] == 0 and holds[0][1] > 999.0
    assert result.qtime_windows["held"] == 1 and result.qtime_holds == 1
    assert result.qtime_windows["late"] == 0
    assert result.qtime_violations == 1
    assert result.qtime_hold_lot_min == 30.0
    assert _b_starts(fab, result, 0)[0] >= holds[0][1] + 1800.0
    assert check_trace(fab, result, downs=NO_DOWNS, pm=NO_DOWNS)["total"] == 0


def test_deadline_event_recleans_a_wet_origin_lot() -> None:
    fab = _two_family_fab(cqt_limit=899.0)
    fab.families[0].group = "Wet_Etch"
    fab.group_names[0] = "Wet_Etch"
    result = _run(fab)
    cleans = [e for e in result.events if e[0] == "reclean"]
    assert len(cleans) == 1 and cleans[0][3] == 1 and cleans[0][4] == 0
    assert result.recleans == 1
    # The second pass through A opens a new window that is met.
    assert result.qtime_windows["recleaned"] == 1
    assert result.qtime_windows["met"] == 1
    assert check_trace(fab, result, downs=NO_DOWNS, pm=NO_DOWNS)["total"] == 0


def test_hold_check_flags_a_start_inside_the_hold() -> None:
    fab = _two_family_fab(cqt_limit=899.0)
    result = _run(fab)
    at = next(i for i, e in enumerate(result.events) if e[0] == "start" and 0 in e[3] and e[2] == 1)
    row = list(result.events[at])
    row[1] = 1500.0
    result.events[at] = tuple(row)
    assert check_trace(fab, result, downs=NO_DOWNS, pm=NO_DOWNS)["counts"]["qtime_hold"] == 1


def test_without_the_deadline_event_the_lot_just_starts_late() -> None:
    result = _run(_two_family_fab(cqt_limit=899.0), deadline_event=False)
    assert result.qtime_windows["late"] == 1 and result.qtime_holds == 0


# Fix 4: full-queue batching -------------------------------------------------


def _furnace_fab() -> Fab:
    """Labeled unit fixture, not SMT2020 data.

    One furnace (``Furnace-1``, Diffusion), BATCHMN = BATCHMX = 150 wafers
    (6 lots). Lots 0-2 and 24-26 share recipe ``R``; lots 3-23 each run a
    recipe of their own. FIFO keeps the first 24 lots as candidates, so only
    3 of the 6 ``R`` lots are on the shortlist.
    """
    families = [
        Family(name="Furnace", group="Diffusion", tools=1, tool0=0, litho=False, scanner=False)
    ]
    routes = []
    for recipe in range(22):
        routes.append(
            Route(
                route_id=f"F{recipe}",
                family=[0],
                cycle=[3600.0],
                recipe=[recipe + 1],
                batch_min=[150],
                batch_max=[150],
                cqt_limit=[0.0],
                cqt_target=[-1],
                remain=[3600.0],
                step_index={1: 0},
                dedicate_root=[-1],
            )
        )
    lot_route = [0, 0, 0, *range(1, 22), 0, 0, 0]
    n = len(lot_route)
    return Fab(
        families=families,
        family_index={"Furnace": 0},
        tool_family=[0],
        tool_name=["Furnace-1"],
        routes=routes,
        route_index={route.route_id: i for i, route in enumerate(routes)},
        lot_id=[f"L_{i}" for i in range(n)],
        lot_product=["p"] * n,
        lot_route=lot_route,
        lot_step=[0] * n,
        lot_due=[100_000.0] * n,
        lot_value=[1.0] * n,
        lot_class=["normal"] * n,
        lot_priority=[10] * n,
        recipe_name=["", *[f"r{i}" for i in range(22)]],
        setup={},
        down_mttf={},
        down_mttr={},
        pm=[],
        focus_family=0,
        focus_tool=0,
        hot_lot=0,
        pm_calendar="",
        group_names=["Diffusion"],
    )


def test_batch_fills_from_lots_beyond_the_shortlist() -> None:
    fab = _furnace_fab()
    result = run_policy(fab, policy="fifo", seed=1, horizon=5000, downs=[[]], pm=[[]], record=True)
    first = next(e for e in result.events if e[0] == "start")
    assert sorted(first[3]) == [0, 1, 2, 24, 25, 26]
    assert first[6] == "min_met"
    # Later batches are one-lot recipes under no_arrivals; the first is full.
    assert result.batch_cap_lots >= 6
    assert result.batch_short_full == 0
    assert check_trace(fab, result, downs=[[]], pm=[[]])["total"] == 0


# Fix 1: Q-time shortlist admission -----------------------------------------


def _crowded_b_fab(*, cqt_limit: float = 30_000.0, others: int = 20) -> Fab:
    """Labeled unit fixture, not SMT2020 data.

    ``Clean_B-1`` (1000 s per lot) has ``others`` normal lots on route ``B``
    (no Q-time) due soon, and ``L_Q`` at B on route ``AB``: an inherited
    window with ``cqt_limit`` s and a far due date. The queue is over the
    ResiliMES WIP threshold (8), so the shortlist is capped at 8 by slack and
    ``L_Q`` is cut from it unless the Q-time admission rule adds it back.
    """
    fab = _two_family_fab(cqt_limit=cqt_limit)
    fab.routes.append(
        Route(
            route_id="B",
            family=[1],
            cycle=[1000.0],
            recipe=[0],
            batch_min=[0],
            batch_max=[0],
            cqt_limit=[0.0],
            cqt_target=[-1],
            remain=[1000.0],
            step_index={2: 0},
            dedicate_root=[-1],
        )
    )
    fab.route_index["B"] = 1
    n = others + 1
    fab.lot_id[:] = ["L_Q", *[f"L_{i}" for i in range(others)]]
    fab.lot_product[:] = ["p"] * n
    fab.lot_route[:] = [0] + [1] * others
    fab.lot_step[:] = [1] + [0] * others
    fab.lot_due[:] = [1_000_000.0] + [30_000.0 + 100.0 * i for i in range(others)]
    fab.lot_value[:] = [1.0] * n
    fab.lot_class[:] = ["normal"] * n
    fab.lot_priority[:] = [10] * n
    return fab


def _b_position(result, lot: int = 0) -> int:
    order = [e[3][0] for e in result.events if e[0] == "start" and e[2] == 1]
    return order.index(lot)


def test_open_window_lot_is_admitted_to_a_capped_shortlist() -> None:
    fab = _crowded_b_fab()
    after = _run(fab, policy="resilimes", horizon=25_000.0)
    before = _run(fab, policy="resilimes", horizon=25_000.0, r2_policy=False)
    # Without the rule L_Q (largest slack) stays off the 8-lot shortlist until
    # the queue falls to the threshold (12 starts); with it, its Q-time risk
    # ranks it near the front.
    assert _b_position(before) >= 12
    assert _b_position(after) <= 1
    assert after.qtime_shortlist_added > 0
    assert before.qtime_shortlist_added == 0
    assert check_trace(fab, after, downs=NO_DOWNS, pm=NO_DOWNS)["total"] == 0


def test_shortlist_admission_is_resilimes_only() -> None:
    result = _run(_crowded_b_fab(), policy="edd", horizon=25_000.0)
    assert result.qtime_shortlist_added == 0


# Fix 2: graded urgency -------------------------------------------------------


def _sim(fab, policy="resilimes", r2_policy=True):
    from resilimes.smt.simulate import _Sim

    return _Sim(
        fab,
        policy=policy,
        seed=1,
        horizon=10_000.0,
        downs=[[] for _ in fab.tool_name],
        pm=[[] for _ in fab.tool_name],
        hot_lot=None,
        hot_due=None,
        promote_hot=False,
        trace=False,
        focus_down_until=0.0,
        r2_policy=r2_policy,
    )


def _three_step_fab() -> Fab:
    """Route A, B, B with a 1000 s window from the A step to the second B step.

    ``L_AB`` sits at the first B step (an upstream step of the span) and
    ``L_B`` at the target. B takes 300 s; B to B is a same-bay move (60 s).
    """
    fab = _two_family_fab(cqt_limit=1000.0)
    route = fab.routes[0]
    route.family[:] = [0, 1, 1]
    route.cycle[:] = [100.0, 300.0, 300.0]
    route.recipe[:] = [0, 0, 0]
    route.batch_min[:] = [0, 0, 0]
    route.batch_max[:] = [0, 0, 0]
    route.cqt_limit[:] = [1000.0, 0.0, 0.0]
    route.cqt_target[:] = [2, -1, -1]
    route.remain[:] = [700.0, 600.0, 300.0]
    route.step_index.clear()
    route.step_index.update({1: 0, 2: 1, 3: 2})
    route.dedicate_root[:] = [-1, -1, -1]
    fab.lot_step[:] = [1, 2]
    return fab


def test_graded_urgency_is_monotonic_and_peaks_at_the_latest_start() -> None:
    sim = _sim(_three_step_fab())
    for lot in (0, 1):
        sim.open_window(lot, 0, 2, 1000.0, 0.0, inherited=True)
    # Target lot: need 0, latest start 1000 s.
    grades = [sim.qtime_grade(1, t) for t in (0.0, 250.0, 500.0, 999.0, 1000.0, 1500.0)]
    assert grades == sorted(grades)
    assert grades[0] == 0.0 and grades[2] == 0.5
    assert grades[4] == 1.0 and grades[5] == 1.0
    # Upstream lot: still needs 300 s at B plus the 60 s move, so its latest
    # start here is 640 s and it is graded ahead of the target lot.
    assert sim.qtime_need(0) == 360.0
    assert sim.qtime_grade(0, 640.0) == 1.0
    assert sim.qtime_grade(0, 320.0) > sim.qtime_grade(1, 320.0)
    # Same value through the PED slot of the tiered key; 0 outside a window.
    assert sim.ped(1, 500.0) == 0.5
    sim.close_window(1, "met")
    assert sim.ped(1, 500.0) == 0.0


def test_graded_urgency_is_resilimes_only() -> None:
    sim = _sim(_three_step_fab(), r2_policy=False)
    sim.open_window(1, 0, 2, 1000.0, 0.0, inherited=True)
    # The PR #18 PED curve (exp) is kept for the ablation: not linear.
    assert sim.ped(1, 500.0) != 0.5
