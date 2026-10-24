"""PM plan: staggered per-tool PM calendar (planning layer)."""

from __future__ import annotations

import random
from collections import defaultdict
from functools import cache
from itertools import pairwise

import pytest

from resilimes.smt.fab import Fab, Family, Route, load_fab
from resilimes.smt.planning import (
    LithoDay,
    PlanningOutput,
    build_plan,
    family_pm,
    plan_horizon,
    plan_input,
    plan_scenario,
    scenario_input,
)
from resilimes.smt.pm_plan import (
    PM_WINDOW_SEC,
    FamilyPm,
    PmPlan,
    PmState,
    build_pm_plan,
    flexible_windows,
    pm_decision,
    published_occurrences,
    published_windows,
    queue_work_sec,
)
from resilimes.smt.simulate import pm_windows

DAY = 86400.0
WINDOW = 56 * DAY

# ------------------------------------------------------------------ fixtures


def _toy_fab(tools: int, calendars: list[tuple[float, float, float]]) -> Fab:
    """Labeled unit fixture, not SMT2020 data.

    One litho family ``Litho_X`` with ``tools`` scanners and the given PM
    calendars ``(first, interval, duration)`` in seconds; one lot ``L_1`` with
    a single 900 s litho step due at 100000 s.
    """
    families = [
        Family(name="Litho_X", group="Litho", tools=tools, tool0=0, litho=True, scanner=True)
    ]
    route = Route(
        route_id="L",
        family=[0],
        cycle=[900.0],
        recipe=[0],
        batch_min=[0],
        batch_max=[0],
        cqt_limit=[0.0],
        cqt_target=[-1],
        remain=[900.0],
        step_index={1: 0},
        dedicate_root=[-1],
    )
    return Fab(
        families=families,
        family_index={"Litho_X": 0},
        tool_family=[0] * tools,
        tool_name=[f"Litho_X-{i + 1}" for i in range(tools)],
        routes=[route],
        route_index={"L": 0},
        lot_id=["L_1"],
        lot_product=["p"],
        lot_route=[0],
        lot_step=[0],
        lot_due=[100000.0],
        lot_value=[1.0],
        lot_class=["normal"],
        lot_priority=[10],
        recipe_name=[""],
        setup={},
        down_mttf={},
        down_mttr={},
        pm=[(0, f, i, d, f"PM_{k}") for k, (f, i, d) in enumerate(calendars)],
        focus_family=0,
        focus_tool=0,
        hot_lot=0,
        pm_calendar="",
        group_names=["Litho"],
    )


@cache
def _fab() -> Fab:
    return load_fab()


@cache
def _plan() -> PmPlan:
    return build_pm_plan(_fab(), WINDOW)


def _by_name(plan: PmPlan) -> dict[str, FamilyPm]:
    return {item.family: item for item in plan.families.values()}


def _peak(spans: list[tuple[float, float]]) -> int:
    marks = sorted([(lo, 1) for lo, _hi in spans] + [(hi, -1) for _lo, hi in spans])
    level = peak = 0
    for _t, step in marks:
        level += step
        peak = max(peak, level)
    return peak


# ------------------------------------------------------------- toy mapping


def test_even_stagger_by_tool_index_last_tool_keeps_published_time() -> None:
    fab = _toy_fab(3, [(300.0, 300.0, 50.0)])
    plan = build_pm_plan(fab, 1000.0)
    assert plan.per_tool() == [
        [(100.0, 150.0), (400.0, 450.0), (700.0, 750.0)],
        [(200.0, 250.0), (500.0, 550.0), (800.0, 850.0)],
        [(300.0, 350.0), (600.0, 650.0), (900.0, 950.0)],
    ]
    stats = plan.families[0]
    assert (stats.count_before, stats.count_after) == (9, 9)
    assert (stats.max_in_pm_before, stats.max_in_pm_after) == (3, 1)
    assert (stats.min_available_before, stats.min_available_after) == (0, 2)
    assert stats.lanes == 1 and not stats.overlap_required


def test_single_tool_family_keeps_the_published_calendar() -> None:
    fab = _toy_fab(1, [(300.0, 300.0, 50.0), (500.0, 1000.0, 80.0)])
    plan = build_pm_plan(fab, 2000.0)
    assert plan.per_tool() == published_windows(fab, 2000.0)
    assert plan.families[0].max_delay_h == 0.0


def test_overfull_family_keeps_minimum_overlap_and_is_flagged() -> None:
    # 3 tools x 50 s per 100 s: load 1.5, so two tools must overlap sometimes.
    fab = _toy_fab(3, [(100.0, 100.0, 50.0)])
    plan = build_pm_plan(fab, 1000.0)
    stats = plan.families[0]
    assert stats.load == 1.5 and stats.lanes == 2
    assert stats.overlap_required and stats.overfull_calendars == ("PM_0",)
    assert stats.max_in_pm_after == 2
    assert plan.flagged() == ["Litho_X"]
    assert stats.count_after == stats.count_before == 27


def test_nominal_start_never_before_published_minus_one_interval() -> None:
    fab = _toy_fab(4, [(1000.0, 1000.0, 10.0)])
    plan = build_pm_plan(fab, 5000.0)
    for window in plan.windows:
        assert window.nominal_sec > window.published_sec - 1000.0
        assert window.start_sec >= window.nominal_sec


# --------------------------------------------------------------- full fab


def test_before_matches_simulate_pm_windows() -> None:
    fab = _fab()
    for shift in (0.0, 120.0 * 3600.0):
        ours = published_windows(fab, WINDOW, shift_sec=shift)
        assert ours == [sorted(spans) for spans in pm_windows(fab, WINDOW, shift_sec=shift)]


def test_pm_count_and_durations_are_the_datasets() -> None:
    plan = _plan()
    fab = _fab()
    published = pm_windows(fab, WINDOW)
    assert len(plan.windows) == sum(len(spans) for spans in published)
    for stats in plan.families.values():
        assert stats.count_after == stats.count_before
    by_name = {name: duration for _f, _s, _i, duration, name in fab.pm}
    for window in plan.windows:
        assert abs((window.end_sec - window.start_sec) - by_name[window.calendar]) < 1e-6
        assert window.nominal_sec > window.published_sec - _interval(fab, window.calendar)
        assert window.start_sec >= window.nominal_sec - 1e-9


def _interval(fab: Fab, name: str) -> float:
    return next(interval for _f, _s, interval, _d, cal in fab.pm if cal == name)


def test_occurrences_per_tool_match_the_published_occurrences() -> None:
    plan = _plan()
    fab = _fab()
    seen: dict[tuple[int, str], list[int]] = defaultdict(list)
    for window in plan.windows:
        seen[(window.tool, window.calendar)].append(window.occurrence)
    for fam, first, interval, duration, name in fab.pm:
        wanted = [k for k, _s in published_occurrences(first, interval, duration, WINDOW)]
        item = fab.families[fam]
        for tool in range(item.tool0, item.tool0 + item.tools):
            assert sorted(seen[(tool, name)]) == wanted


def test_no_tool_overlaps_itself_and_family_stays_within_lanes() -> None:
    plan = _plan()
    fab = _fab()
    for fam, stats in plan.families.items():
        item = fab.families[fam]
        spans: list[tuple[float, float]] = []
        for tool in range(item.tool0, item.tool0 + item.tools):
            own = plan.tool_windows(tool)
            assert all(a[1] <= b[0] + 1e-6 for a, b in pairwise(own))
            spans += own
        assert _peak(spans) <= stats.lanes
        assert stats.max_in_pm_after <= stats.lanes
        assert stats.lanes == max(1, -int(-stats.load // 1))
        if stats.load <= 1.0:
            assert stats.max_in_pm_after == 1 and not stats.overlap_required


def test_furnaces_and_litho_are_staggered() -> None:
    stats = _by_name(_plan())
    for name in ("Diffusion_FE_94", "Diffusion_BE_123", "Litho_BE_93"):
        row = stats[name]
        assert row.max_in_pm_before == row.tools
        assert row.max_in_pm_after == 1
    for name in ("Litho_FE_92", "Litho_BE_110", "Litho_FE_111"):
        row = stats[name]
        assert row.overlap_required and row.max_in_pm_after == 2
    # 26 scanners x 6.65 h > 168 h: the weekly calendar alone cannot be staggered.
    fe92 = stats["Litho_FE_92"].overfull_calendars
    assert len(fe92) == 1 and fe92[0].endswith("WK")
    assert not stats["Litho_BE_110"].overfull_calendars


def test_plan_is_deterministic_and_per_tool_has_simulate_shape() -> None:
    fab = _fab()
    first = build_pm_plan(fab, WINDOW).per_tool()
    again = build_pm_plan(fab, WINDOW).per_tool()
    assert first == again
    assert len(first) == len(fab.tool_family)
    assert all(spans == sorted(spans) for spans in first)


# --------------------------------------------------------------- planning hook


def _days(out: PlanningOutput, family: str) -> list[LithoDay]:
    return [day for day in out.litho if day.family == family]


def test_hook_with_family_calendar_per_tool_reproduces_default() -> None:
    fab = _fab()
    inp = scenario_input(fab, "published")
    pm = family_pm(fab, plan_horizon(inp))
    explicit = scenario_input(fab, "published")
    explicit.tool_pm = {
        tool: spans
        for fam, spans in pm.items()
        for tool in range(
            fab.families[fam].tool0, fab.families[fam].tool0 + fab.families[fam].tools
        )
    }
    base = build_plan(fab, inp)
    same = build_plan(fab, explicit)
    assert [(x.lot_id, x.rank, x.band) for x in base.lots] == [
        (x.lot_id, x.rank, x.band) for x in same.lots
    ]
    assert base.litho == same.litho


def test_toy_staggered_pm_lets_the_other_scanner_run() -> None:
    fab = _toy_fab(2, [(0.0, 1e6, 5000.0)])
    family = build_plan(fab, plan_input(fab, releases=False))
    # Published calendar: both scanners in PM over [0, 5000), the lot waits.
    assert family.lots[0].litho_wait_sec == 5000.0
    staggered = plan_input(fab, releases=False, tool_pm={0: [], 1: [(0.0, 5000.0)]})
    assert build_plan(fab, staggered).lots[0].litho_wait_sec == 0.0


def test_staggered_plan_raises_pm_day_capacity_and_removes_overloads() -> None:
    fab = _fab()
    base = plan_scenario(fab)
    stag = plan_scenario(fab, staggered_pm=True)
    for name in ("Litho_BE_110", "Litho_FE_92"):
        before = _days(base, name)
        after = _days(stag, name)
        # Same PM hours inside the window, spread instead of all at once.
        total_before = sum(day.capacity_h for day in before)
        total_after = sum(day.capacity_h for day in after)
        assert abs(total_after - total_before) <= 0.005 * total_before
        assert min(day.capacity_h for day in after) > min(day.capacity_h for day in before)
        assert sum(day.overload for day in after) < sum(day.overload for day in before)


# ------------------------------------------------------------ flexible PM

HOUR = 3600.0
WEEK = 7 * DAY


def _flex(tools: int, calendars: list[tuple[float, float, float]]) -> PmState:
    fab = _toy_fab(tools, calendars)
    return PmState.build(fab, build_pm_plan(fab, 60 * DAY))


def test_window_is_one_day_and_capped_by_next_pm() -> None:
    assert PM_WINDOW_SEC == 24 * HOUR
    # One weekly calendar: +-24 h around the planned start.
    state = _flex(3, [(10 * DAY, WEEK, 6 * HOUR)])
    pm = state.pms[2][1]
    assert abs(pm.planned_sec - pm.earliest_sec - 24 * HOUR) < 1e-6
    assert abs(pm.latest_sec - pm.planned_sec - 24 * HOUR) < 1e-6
    # WK at 10 d (6 h) and MN 10 h later on the same single tool: the WK latest
    # stops at the MN start minus the WK duration, the MN earliest at the WK end.
    state = _flex(1, [(10 * DAY, WEEK, 6 * HOUR), (10 * DAY + 10 * HOUR, 30 * DAY, 4 * HOUR)])
    wk, mn = state.pms[0][0], state.pms[0][1]
    assert wk.window.calendar == "PM_0" and mn.window.calendar == "PM_1"
    assert wk.latest_sec == mn.planned_sec - wk.duration_sec
    assert mn.earliest_sec == wk.window.end_sec
    # Dataset plan: every window holds its planned start and no two windows of
    # one tool can make two PMs overlap.
    for items in flexible_windows(_plan()).values():
        for pm in items:
            assert pm.earliest_sec <= pm.planned_sec <= pm.latest_sec
            assert pm.latest_sec - pm.planned_sec <= PM_WINDOW_SEC + 1e-6
            assert pm.planned_sec - pm.earliest_sec <= PM_WINDOW_SEC + 1e-6
        for a, b in pairwise(items):
            assert a.latest_sec + a.duration_sec <= b.planned_sec + 1e-6
            assert b.earliest_sec >= a.window.end_sec - 1e-6


def test_opportunistic_start_when_idle_and_no_queue() -> None:
    state = _flex(3, [(10 * DAY, WEEK, 6 * HOUR)])
    pm = state.pms[0][0]
    now = pm.earliest_sec
    state.set_queue(0, 0.0, now)
    out = pm_decision(0, now, state)
    assert out.action == "start_now" and out.reason == "no_queue,early"
    assert out.start_sec == now < pm.planned_sec
    assert state.committed[0][0].start_sec == now
    assert state.head(0) is state.pms[0][1]
    # Before the window: nothing decided, nothing logged.
    other = state.pms[1][0]
    assert pm_decision(1, other.earliest_sec - 600.0, state).reason == "before_window"
    assert len(state.log) == 1


def test_defer_under_heavy_queue_and_start_when_absorbed() -> None:
    state = _flex(3, [(10 * DAY, WEEK, 6 * HOUR)])
    pm = state.pms[0][0]
    now = pm.planned_sec
    dur = pm.duration_sec
    # Two other idle scanners absorb 2 * D; 3 * D grows the queue.
    state.set_queue(0, 3 * dur, now)
    out = pm_decision(0, now, state)
    assert out.action == "defer" and out.reason.startswith("queue_heavy")
    assert out.absorb_sec == 2 * dur and 0 not in state.committed
    # A running tool absorbs only what is left after its lot.
    state.set_queue(0, 1.5 * dur, now)
    state.set_tool(1, busy_until=now + 0.75 * dur)
    assert pm_decision(0, now, state).action == "defer"
    state.set_tool(1, busy_until=now)
    out = pm_decision(0, now + 300.0, state)
    assert out.action == "start_now" and out.reason == "queue_absorbed,late"
    assert state.log[-1] is out and len(state.log) == 3


def test_force_at_latest_and_never_on_a_running_tool() -> None:
    state = _flex(3, [(10 * DAY, WEEK, 6 * HOUR)])
    pm = state.pms[0][0]
    state.set_queue(0, 100 * pm.duration_sec, pm.latest_sec)
    out = pm_decision(0, pm.latest_sec, state)
    assert out.action == "force" and out.start_sec == pm.latest_sec
    assert out.reason.startswith("latest_start,queue_heavy")
    # Running tool inside the window: it waits for the lot.
    pm1 = state.pms[1][0]
    state.set_queue(0, 0.0, pm1.planned_sec)
    state.set_tool(1, busy_until=pm1.planned_sec + 1200.0)
    assert pm_decision(1, pm1.planned_sec, state).reason == "tool_busy"
    # At the latest start the PM is forced after the current lot ...
    state.set_tool(1, busy_until=pm1.latest_sec + 1200.0)
    out = pm_decision(1, pm1.latest_sec - 100.0, state)
    assert out.action == "force" and out.start_sec == pm1.latest_sec + 1200.0
    assert "after" not in out.reason and "tool_busy" in out.reason
    # ... and no lot may start on the tool until the committed PM is over.
    end = pm1.latest_sec + 1200.0 + pm1.duration_sec
    assert not state.may_start_lot(1, pm1.latest_sec + 1200.0, 60.0)
    assert state.may_start_lot(1, end, 60.0)


def test_dispatch_guard_refuses_a_lot_past_the_latest_start() -> None:
    state = _flex(3, [(10 * DAY, WEEK, 6 * HOUR)])
    pm = state.pms[2][0]
    now = pm.latest_sec - 3600.0
    assert state.may_start_lot(2, now, 3600.0)
    assert not state.may_start_lot(2, now, 3601.0)


def test_concurrency_cap_respected() -> None:
    state = _flex(10, [(10 * DAY, WEEK, 6 * HOUR)])
    assert state.lanes[0] == 1
    a, b = state.pms[0][0], state.pms[1][0]
    now = a.planned_sec + 10 * HOUR
    assert a.earliest_sec <= now <= a.latest_sec and b.earliest_sec <= now <= b.latest_sec
    state.set_queue(0, 0.0, now)
    assert pm_decision(0, now, state).action == "start_now"
    out = pm_decision(1, now, state)
    assert out.action == "defer" and out.reason == "concurrency_cap(1/1)"
    assert state.in_pm(0, now) == 1
    later = now + a.duration_sec
    assert pm_decision(1, later, state).action == "start_now"


def test_queue_work_uses_master_data_time_and_full_batch_share() -> None:
    fab = _toy_fab(1, [(DAY, WEEK, HOUR)])
    assert queue_work_sec(fab, [(0, 0), (0, 0)]) == 1800.0
    fab.routes[0].batch_max[0] = 4
    assert queue_work_sec(fab, [(0, 0)]) == 225.0


def _replay(
    days: float, families: list[str], seed: int, heavy_share: float
) -> tuple[PmState, list[int]]:
    """Tick replay on dataset PM plans with a random queue and random lots.

    Unit harness, not a simulation: lots are random 10-90 min jobs and the
    family queue is light or heavy by day.
    """
    fab = _fab()
    plan = build_pm_plan(fab, days * DAY)
    state = PmState.build(fab, plan)
    rng = random.Random(seed)
    fams = [fab.family_index[name] for name in families]
    tools = [t for fam in fams for t in state.family_tools[fam]]
    busy = dict.fromkeys(tools, 0.0)
    # Heavy-queue days per family (queues persist over a day, not per tick).
    regime = {fam: [rng.random() < heavy_share for _ in range(int(days) + 1)] for fam in fams}
    now = 0.0
    while now < days * DAY:
        for fam in fams:
            n = len(state.family_tools[fam])
            heavy = regime[fam][int(now // DAY)]
            work = rng.uniform(1.5, 3.0) if heavy else rng.uniform(0.0, 0.2)
            state.set_queue(fam, work * n * 6 * HOUR, now)
        for tool in tools:
            proc = rng.uniform(600.0, 5400.0)
            if busy[tool] <= now and rng.random() < 0.5 and state.may_start_lot(tool, now, proc):
                busy[tool] = now + proc
            state.set_tool(tool, busy_until=busy[tool])
            pm_decision(tool, now, state)
        now += state.tick_sec
    return state, tools


@pytest.mark.parametrize("heavy_share", [0.3, 0.95])
def test_replay_commits_every_pm_once_inside_its_window(heavy_share: float) -> None:
    days = 21.0
    families = ["Litho_FE_92", "Litho_BE_110", "Diffusion_FE_120"]
    state, tools = _replay(days, families, 7, heavy_share)
    for tool in tools:
        planned = state.pms.get(tool, [])
        done = state.committed.get(tool, [])
        due = [p for p in planned if p.latest_sec < days * DAY - state.tick_sec]
        # Nothing dropped: every PM due by the end is committed, once, in order.
        assert [c.pm for c in done][: len(due)] == due
        assert len({id(c.pm) for c in done}) == len(done)
        # Nothing merged: each keeps its duration and they never overlap.
        for c in done:
            assert abs(c.end_sec - c.start_sec - c.pm.duration_sec) < 1e-6
            assert c.pm.earliest_sec - 1e-6 <= c.start_sec <= c.pm.latest_sec + 1e-6
        for x, y in pairwise(done):
            assert x.end_sec <= y.start_sec + 1e-6
    k = state.kpis()
    assert k["pm_committed"] + k["pm_pending"] == k["pm_planned"]
    assert k["forced"] == sum(1 for d in state.log if d.action == "force")
    assert k["deferral_max_h"] <= 24 + 1e-6 and k["advance_max_h"] <= 24 + 1e-6
    if heavy_share < 0.5:
        # Light days: idle tools take PMs early; less PM time on heavy days.
        assert k["advanced"] > 0 and k["deferred"] > 0
        assert k["pm_h_high_queue_actual"] < k["pm_h_high_queue_planned"]
    else:
        # Almost always heavy: every PM is held to its latest start, then forced.
        assert k["advanced"] == 0 and k["forced"] == k["pm_committed"] > 0
    assert all(d.reason for d in state.log)
