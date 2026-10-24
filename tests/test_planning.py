"""Planning layer: backward step dues, forward litho capacity check, baseline priority."""

from __future__ import annotations

import json
import time
from functools import cache
from itertools import pairwise

import pytest

from resilimes.smt.fab import (
    Fab,
    Family,
    Route,
    load_fab,
    lot_number,
    measured,
    transport_seconds,
)
from resilimes.smt.planning import (
    BANDS,
    DAY_SEC,
    PlanningOutput,
    backward,
    band_of,
    build_plan,
    dataset_releases,
    family_pm,
    lead_time,
    litho_availability,
    plan_input,
    plan_scenario,
    raw_path_seconds,
    scenario_input,
    standard_band,
    standard_lead_times,
    visit_path,
)

# ------------------------------------------------------------------ fixtures


def _litho_fab(*, pm_first: float = 1e9, pm_duration: float = 0.0) -> Fab:
    """Labeled unit fixture, not SMT2020 data.

    ``Etch_A`` (1 tool, group Etch) and ``Litho_X`` (2 scanners, group Litho,
    MTTF 9000 s / MTTR 1000 s, so availability 0.9). Route ``ALA``: A 100 s,
    L 900 s, A 100 s. Lots ``L_1``..``L_3`` start at A at t=0 with dues 30000,
    20000 and 10000 s, so ``L_3`` is the most urgent.
    """
    families = [
        Family(name="Etch_A", group="Etch", tools=1, tool0=0, litho=False, scanner=False),
        Family(name="Litho_X", group="Litho", tools=2, tool0=1, litho=True, scanner=True),
    ]
    route = Route(
        route_id="ALA",
        family=[0, 1, 0],
        cycle=[100.0, 900.0, 100.0],
        recipe=[0, 0, 0],
        batch_min=[0, 0, 0],
        batch_max=[0, 0, 0],
        cqt_limit=[0.0, 0.0, 0.0],
        cqt_target=[-1, -1, -1],
        remain=[1100.0, 1000.0, 100.0],
        step_index={1: 0, 2: 1, 3: 2},
        dedicate_root=[-1, -1, -1],
    )
    pm = [(1, pm_first, 1e9, pm_duration, "PM_X")] if pm_duration > 0 else []
    return Fab(
        families=families,
        family_index={"Etch_A": 0, "Litho_X": 1},
        tool_family=[0, 1, 1],
        tool_name=["Etch_A-1", "Litho_X-1", "Litho_X-2"],
        routes=[route],
        route_index={"ALA": 0},
        lot_id=["L_1", "L_2", "L_3"],
        lot_product=["p", "p", "p"],
        lot_route=[0, 0, 0],
        lot_step=[0, 0, 0],
        lot_due=[30000.0, 20000.0, 10000.0],
        lot_value=[1.0, 1.0, 1.0],
        lot_class=["normal", "normal", "normal"],
        lot_priority=[10, 10, 10],
        recipe_name=[""],
        setup={},
        down_mttf={"Litho": 9000.0},
        down_mttr={"Litho": 1000.0},
        pm=pm,
        focus_family=1,
        focus_tool=1,
        hot_lot=0,
        pm_calendar="",
        group_names=["Etch", "Litho"],
    )


def _toy_plan(fab: Fab, **kwargs: object) -> PlanningOutput:
    return build_plan(fab, plan_input(fab, releases=False, **kwargs))  # type: ignore[arg-type]


@cache
def _fab() -> Fab:
    return load_fab()


@cache
def _published() -> PlanningOutput:
    return plan_scenario(_fab())


# ------------------------------------------------------- backward pass (toy)


def test_backward_pass_step_dues_chain_raw_time_and_transport() -> None:
    fab = _litho_fab()
    route = fab.routes[0]
    finish, start = backward(fab, route, [0, 1, 2], 10000.0)
    assert finish[2] == 10000.0
    assert start[2] == 9900.0
    # Litho -> Etch is across groups: 3 min.
    assert finish[1] == 9900.0 - 180.0
    assert start[1] == finish[1] - 900.0
    assert finish[0] == start[1] - 180.0
    assert start[0] == finish[0] - 100.0


def test_backward_pass_scales_process_and_transport_by_the_flow_factor() -> None:
    fab = _litho_fab()
    route = fab.routes[0]
    raw_finish, _ = backward(fab, route, [0, 1, 2], 10000.0)
    finish, start = backward(fab, route, [0, 1, 2], 10000.0, 2.0)
    assert finish[2] == 10000.0
    assert start[2] == 10000.0 - 2 * 100.0
    for pos in range(3):
        assert 10000.0 - finish[pos] == pytest.approx(2 * (10000.0 - raw_finish[pos]))
    assert finish[2] - start[0] == pytest.approx(2 * raw_path_seconds(fab, route, [0, 1, 2]))


def test_transport_is_one_minute_same_group_three_across() -> None:
    fab = _fab()
    litho = [fam for fam, item in enumerate(fab.families) if item.group == "Litho"]
    assert transport_seconds(fab, litho[0], litho[1]) == 60.0
    other = next(fam for fam, item in enumerate(fab.families) if item.group != "Litho")
    assert transport_seconds(fab, litho[0], other) == 180.0


def test_visit_path_skips_steps_the_lot_number_is_not_measured_at() -> None:
    fab = _fab()
    lot = 0
    route = fab.routes[fab.lot_route[lot]]
    number = lot_number(fab.lot_id[lot], lot)
    path = visit_path(route, fab.lot_step[lot], number)
    assert path[0] == fab.lot_step[lot]
    skipped = [
        index
        for index in range(fab.lot_step[lot] + 1, len(route.family))
        if not measured(route, index, number)
    ]
    assert skipped, "SMT2020 routes have sampled metrology"
    assert not set(skipped) & set(path)
    assert path == sorted(path)


@pytest.mark.parametrize(
    ("raw_slack", "score", "band"),
    [
        (-1.0, 5.0, "critical"),
        (0.0, -0.01, "behind"),
        (10.0, 0.0, "on_plan"),
        (10.0, 0.99, "on_plan"),
        (10.0, 1.0, "ahead"),
    ],
)
def test_band_thresholds(raw_slack: float, score: float, band: str) -> None:
    assert band_of(raw_slack, score) == band


# ------------------------------------------------------ forward pass (toy)


def test_forward_pass_respects_scanner_count_and_queue_order() -> None:
    plan = _toy_plan(_litho_fab())
    proc = 900.0 / 0.9
    arrive = 100.0 + 180.0
    l1, l2, l3 = (plan.lot(name) for name in ("L_1", "L_2", "L_3"))
    # Two scanners: the two most urgent lots (L_3, L_2) start on arrival.
    assert l3.plan_start[1] == pytest.approx(arrive)
    assert l2.plan_start[1] == pytest.approx(arrive)
    assert l1.plan_start[1] == pytest.approx(arrive + proc)
    assert l1.litho_wait_sec == pytest.approx(proc)
    assert l3.plan_finish_sec == pytest.approx(arrive + proc + 180.0 + 100.0)
    assert l3.raw_finish_sec == pytest.approx(100.0 + 180.0 + 900.0 + 180.0 + 100.0)
    assert [lot.rank for lot in (l3, l2, l1)] == [1, 2, 3]


def test_forward_pass_does_not_start_litho_into_a_pm_window() -> None:
    proc = 900.0 / 0.9
    arrive = 280.0
    fab = _litho_fab(pm_first=arrive + proc + 10.0, pm_duration=2000.0)
    plan = _toy_plan(fab)
    l1 = plan.lot("L_1")
    # L_1 could start when a scanner frees at arrive + proc, but it would run
    # into the PM, so it waits for the PM to end.
    assert l1.plan_start[1] == pytest.approx(arrive + proc + 10.0 + 2000.0)
    assert family_pm(fab, 1e6) == {1: [(arrive + proc + 10.0, arrive + proc + 2010.0)]}


def test_forced_down_scanner_is_unavailable_until_it_returns() -> None:
    fab = _litho_fab()
    plan = _toy_plan(fab, down_until={1: 5000.0})
    starts = sorted(plan.lot(name).plan_start[1] for name in ("L_1", "L_2", "L_3"))
    proc = 900.0 / 0.9
    assert starts == pytest.approx([280.0, 280.0 + proc, 280.0 + 2 * proc])
    day0 = next(row for row in plan.litho if row.day == 0)
    up = DAY_SEC + (DAY_SEC - 5000.0)
    assert day0.capacity_h == pytest.approx(up * 0.9 / 3600.0, abs=0.01)


def test_availability_comes_from_the_down_calendar() -> None:
    assert litho_availability(_litho_fab()) == {1: pytest.approx(0.9)}
    avail = litho_availability(_fab())
    names = {_fab().families[fam].name: val for fam, val in avail.items()}
    assert len(names) == 9
    assert names["Litho_FE_92"] == pytest.approx(10080.0 / (10080.0 + 705.59), abs=1e-4)


def test_plan_input_drops_finished_lots_and_keeps_sim_state() -> None:
    fab = _litho_fab()
    inp = plan_input(
        fab,
        now=50.0,
        lot_step=[1, 0, 0],
        lot_ready=[400.0, 0.0, 0.0],
        finished=[False, False, True],
        releases=False,
    )
    assert inp.lot_id == ["L_1", "L_2"]
    assert inp.lot_step == [1, 0]
    assert inp.lot_ready == [400.0, 50.0]
    plan = build_plan(fab, inp)
    assert plan.lot("L_1").plan_start[0] == pytest.approx(400.0)


# --------------------------------------------------------- dataset releases


def test_dataset_releases_follow_order_txt() -> None:
    fab = _fab()
    rel = dataset_releases(fab, until=7 * DAY_SEC)
    by_class: dict[str, int] = {}
    for item in rel:
        by_class[item.order_class] = by_class.get(item.order_class, 0) + 1
    # 10 normal products every 258.46 min, 10 hot products weekly, one VIP.
    assert by_class["normal"] == pytest.approx(10 * 7 * 1440 / 258.46, abs=10)
    assert 1 <= by_class["hot"] <= 20
    assert len({item.lot_id for item in rel}) == len(rel)
    assert all(item.due_sec > item.release_sec for item in rel)
    assert all(0.0 <= item.release_sec < 7 * DAY_SEC for item in rel)
    later = dataset_releases(fab, until=7 * DAY_SEC, after=DAY_SEC)
    assert all(item.release_sec >= DAY_SEC for item in later)


# ---------------------------------------------------- full fab (published)


def test_full_fab_plan_covers_every_wip_lot_and_is_fast() -> None:
    fab = _fab()
    began = time.perf_counter()
    plan = _published()
    assert time.perf_counter() - began < 30.0
    wip = [lot for lot in plan.lots if not lot.released]
    assert len(wip) == len(fab.lot_id) == 2156
    assert any(lot.released for lot in plan.lots)
    assert sorted(lot.rank for lot in plan.lots) == list(range(1, len(plan.lots) + 1))
    assert sum(plan.band_counts().values()) == 2156
    assert set(plan.band_counts()) == set(BANDS)


def test_full_fab_step_dues_end_at_the_lot_due_and_increase() -> None:
    for lot in _published().lots[:300]:
        assert lot.step_due[-1] == lot.due_sec
        assert all(a < b for a, b in pairwise(lot.step_due))
        assert all(s <= d for s, d in zip(lot.latest_start, lot.step_due, strict=True))
        assert lot.due_of(lot.steps[-1]) == lot.due_sec
        assert lot.plan_finish_sec >= lot.raw_finish_sec - 1e-6


def test_full_fab_litho_never_exceeds_scanner_count_or_hits_pm() -> None:
    fab = _fab()
    plan = _published()
    pm = family_pm(fab, 400 * DAY_SEC)
    spans: dict[int, list[tuple[float, float]]] = {fam: [] for fam in pm}
    for lot in plan.lots:
        route = fab.routes[fab.route_index[lot.route_id]]
        for pos, index in enumerate(lot.steps):
            fam = route.family[index]
            if fam in spans:
                spans[fam].append((lot.plan_start[pos], lot.plan_end[pos]))
    for fam, items in spans.items():
        marks = sorted([(s, 1) for s, _e in items] + [(e, -1) for _s, e in items])
        busy = peak = 0
        for _t, step in marks:
            busy += step
            peak = max(peak, busy)
        assert peak <= fab.families[fam].tools
        for start, end in items:
            for lo, hi in pm[fam]:
                assert end <= lo + 1e-6 or start >= hi - 1e-6


def test_full_fab_ranks_follow_class_tier() -> None:
    plan = _published()
    by_tier: dict[int, list[int]] = {}
    for lot in plan.lots:
        by_tier.setdefault(lot.tier, []).append(lot.rank)
    tiers = sorted(by_tier)
    for low, high in pairwise(tiers):
        assert max(by_tier[low]) < min(by_tier[high])
    first = min(plan.lots, key=lambda lot: lot.rank)
    assert first.order_class == "VIP"
    last = max(plan.lots, key=lambda lot: lot.rank)
    assert plan.priority_key(first.lot_id) < plan.priority_key(last.lot_id)


def test_full_fab_output_object_is_serialisable() -> None:
    plan = _published()
    summary = plan.summary()
    assert summary["wip_lots"] == 2156
    assert set(summary["availability"]) == {item.name for item in _fab().families if item.litho}
    payload = json.dumps(plan.to_dict(limit=5))
    assert "litho" in payload
    days = {row.family for row in plan.litho}
    assert len(days) == 9
    assert all(row.overload == (row.demand_h > row.capacity_h) for row in plan.litho)


# ---------------------------------------------------------------- scenarios


def test_hot_lot_scenario_makes_the_hot_lot_vip_and_first() -> None:
    fab = _fab()
    inp = scenario_input(fab, "hot_lot", releases=False)
    name = fab.lot_id[fab.hot_lot]
    plan = build_plan(fab, inp)
    lot = plan.lot(name)
    assert lot.order_class == "VIP"
    assert lot.due_sec == 12 * 3600.0
    assert lot.band == "critical"
    assert lot.rank == 1


def test_litho_down_scenario_removes_focus_scanner_capacity() -> None:
    fab = _fab()
    base = build_plan(fab, scenario_input(fab, "published", releases=False))
    down = build_plan(fab, scenario_input(fab, "litho_down", releases=False))
    focus = fab.families[fab.focus_family].name

    def day0(plan: PlanningOutput) -> float:
        return next(r.capacity_h for r in plan.litho if r.family == focus and r.day == 0)

    lost = day0(base) - day0(down)
    assert lost == pytest.approx(705.59 / 60.0 * plan_availability(down, focus), abs=0.05)


def plan_availability(plan: PlanningOutput, family: str) -> float:
    return plan.availability[family]


def test_pm_scenario_shifts_the_litho_pm_calendar() -> None:
    fab = _fab()
    inp = scenario_input(fab, "pm_avoid", releases=False)
    assert inp.pm_shift_sec != 0.0
    shifted = family_pm(fab, 30 * DAY_SEC, shift_sec=inp.pm_shift_sec)
    base = family_pm(fab, 30 * DAY_SEC)
    assert shifted != base


def test_unknown_scenario_raises() -> None:
    with pytest.raises(KeyError):
        scenario_input(_fab(), "no_such_scenario")


# ------------------------------------------------- standard lead time targets


def test_standard_lead_times_are_order_txt_due_minus_start() -> None:
    fab = _fab()
    table = standard_lead_times(fab)
    assert len(table) == 21
    days = {key: value / DAY_SEC for key, value in table.items()}
    normal = [value for (_r, kind), value in days.items() if kind == "normal"]
    hot = [value for (_r, kind), value in days.items() if kind == "hot"]
    assert min(normal) == pytest.approx(23.78, abs=0.01)
    assert max(normal) == pytest.approx(56.35, abs=0.01)
    assert min(hot) == pytest.approx(16.87, abs=0.01)
    assert max(hot) == pytest.approx(38.3, abs=0.01)
    r3 = fab.route_index["r_3"]
    assert days[(r3, "VIP")] == pytest.approx(38.3, abs=0.01)
    # A VIP on a part with no SuperHot order takes the part's tightest class.
    r5 = fab.route_index["r_5"]
    assert lead_time(fab, r5, "VIP") == table[(r5, "hot")]


def test_released_lot_targets_are_release_plus_standard_cumulative_time() -> None:
    fab = _fab()
    plan = build_plan(fab, plan_input(fab, release_until=DAY_SEC))
    released = [lot for lot in plan.lots if lot.released]
    assert released
    for lot in released:
        route = fab.routes[fab.route_index[lot.route_id]]
        lead = lead_time(fab, fab.route_index[lot.route_id], lot.order_class)
        assert lot.due_sec - lot.ready_sec == pytest.approx(lead)
        # Standard start of step 1 is the release: on the standard curve.
        assert lot.latest_start[0] == pytest.approx(lot.ready_sec, abs=1e-3)
        assert lot.progress_sec == pytest.approx(0.0, abs=1e-3)
        cum = 0.0
        for pos, index in enumerate(lot.steps):
            if pos > 0:
                prev = route.family[lot.steps[pos - 1]]
                cum += transport_seconds(fab, prev, route.family[index])
            cum += route.cycle[index]
            assert lot.step_due[pos] == pytest.approx(
                lot.ready_sec + lot.flow_factor * cum, abs=1e-3
            )


def test_wip_targets_anchor_at_the_due_and_progress_is_standard_slack() -> None:
    plan = _published()
    fab = _fab()
    for lot in [item for item in plan.lots if not item.released][:300]:
        assert lot.flow_factor > 1.0
        assert lot.step_due[-1] == lot.due_sec
        route = fab.routes[fab.route_index[lot.route_id]]
        raw = raw_path_seconds(fab, route, lot.steps)
        assert lot.standard_remaining_sec == pytest.approx(lot.flow_factor * raw)
        assert lot.remaining_raw_sec == pytest.approx(raw)
        assert lot.progress_sec == pytest.approx(
            lot.due_sec - lot.ready_sec - lot.standard_remaining_sec
        )
        assert lot.band == standard_band(lot.raw_slack_sec, lot.progress_sec, lot.plan_slack_sec)
    summary = plan.summary()
    wip = [item for item in plan.lots if not item.released]
    assert summary["targets"] == "standard"
    assert summary["due_tighter_than_standard"] == sum(1 for i in wip if i.progress_sec < 0)
    assert summary["due_tighter_than_standard"] >= summary["due_tighter_than_raw"]


@pytest.mark.parametrize(
    ("raw_slack", "progress", "plan_slack", "band"),
    [
        (-1.0, 5.0, 5.0, "critical"),
        (1.0, -1.0, 5.0, "behind"),
        (1.0, 0.0, -1.0, "on_plan"),
        (1.0, 0.0, 0.0, "ahead"),
    ],
)
def test_standard_bands(raw_slack: float, progress: float, plan_slack: float, band: str) -> None:
    assert standard_band(raw_slack, progress, plan_slack) == band


def test_raw_targets_keep_the_no_queueing_backward_pass() -> None:
    fab = _fab()
    plan = build_plan(fab, scenario_input(fab, "published", releases=False, targets="raw"))
    assert plan.targets == "raw"
    for lot in plan.lots[:200]:
        assert lot.flow_factor == 1.0
        route = fab.routes[fab.route_index[lot.route_id]]
        finish, start = backward(fab, route, lot.steps, lot.due_sec)
        assert list(lot.step_due) == finish
        assert list(lot.latest_start) == start


def test_standard_ranks_follow_tier_band_then_progress() -> None:
    plan = _published()
    ranked = sorted(plan.lots, key=lambda item: item.rank)
    keys = [(i.tier, BANDS.index(i.band), i.progress_sec) for i in ranked]
    for a, b in pairwise(keys):
        assert a <= b
