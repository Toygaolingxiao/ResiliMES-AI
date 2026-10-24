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
