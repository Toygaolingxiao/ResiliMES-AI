"""PM plan: staggered per-tool PM calendar (planning layer)."""

from __future__ import annotations

from collections import defaultdict
from functools import cache
from itertools import pairwise

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
    FamilyPm,
    PmPlan,
    build_pm_plan,
    published_occurrences,
    published_windows,
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
