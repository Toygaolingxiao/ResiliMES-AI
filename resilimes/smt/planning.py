"""Layer 1, long-term planning, for the full SMT2020 fab.

The output is a baseline priority for every lot and a target time (step due)
for every step it still has to run. The scheduling layer (about every 5 min of
sim time) and the real-time dispatcher read it; nothing here dispatches.

Method, all from dataset times and capacities, no tuned weights:

1. Path. A lot visits its current step and then every later route step that
   its lot number samples (``fab.measured``), the same rule the simulator uses.
2. Step targets from the standard lead time (``targets="standard"``, the
   default). The standard lead time of a product (part = route by number) and
   priority class is the dataset's own: ``order.txt`` DUE - START (normal lots
   23.8-56.4 d, hot 16.9-38.3 d, SuperHot part_3 38.3 d). It is spread over
   the steps the lot visits (sampling skipped as the simulator does) in
   proportion to raw process plus transport time (1 min inside a STNGRP group,
   3 min across, ``fab.transport_seconds``): one flow factor per product,
   ``F = LT / raw`` over the full visited route, so every step gets a standard
   time ``F * (process + transport in)``. The step target (step due) of a
   visited step is the lot due minus the standard time still to run after it,
   ``due - F * raw after the step``. That anchors WIP whose release is unknown
   at its due; for a released lot it equals release + the standard cumulative
   time to the step, since its due is release + LT. The standard start of a
   step is its target minus its standard process time. A (product, class)
   with no order row (a scenario promotes a lot to VIP on another part) takes
   the product's tightest listed lead time; a product with no order row at
   all (a test fab) keeps raw time, F = 1. A later refinement could use one
   flow factor per tool family instead of per product (more standard time at
   the bottleneck), from the same order data; not done here.

   ``targets="raw"`` keeps the earlier backward pass: F = 1, so the step due is
   the latest finish at raw time with no queueing anywhere.
3. Forward capacity check. Every ``Litho_*`` family (7 expose families and the
   2 REG families) is a finite pool of its published tools. Everything else is
   infinite capacity at raw process time. A litho start may not overlap a PM
   window (published calendars, copied onto every tool of the family, as the
   simulator does) or a scenario's forced down. Random breakdowns are taken as
   the expected availability of the STNGRP down calendar,
   ``MTTF / (MTTF + MTTR)``: a litho step is planned at raw time divided by it.
   The litho queue is served the way the dataset rule names it, HotLotFIRST
   (class tier), then the step's latest start. That gives a capacity-feasible
   finish for every lot.
4. Baseline priority.

   Standard targets: progress = standard start of the lot's current step minus
   the time the lot is ready there (positive: ahead of its standard curve,
   negative: behind), in seconds of standard time; score = progress over the
   standard time still to run. A lot with progress < 0 has a due tighter than
   its standard remaining time (``summary()["due_tighter_than_standard"]``).
   Bands:

   - ``critical``: the due is missed even with zero waiting
     (due < ready + remaining raw time).
   - ``behind``: behind its standard curve (progress < 0).
   - ``on_plan``: on or ahead of the standard curve, but the capacity plan
     (step 3) finishes after the due.
   - ``ahead``: on or ahead of the standard curve and the capacity plan
     finishes by the due.

   The rank orders lots by class tier (VIP, hot, normal, the same strict tier
   the dispatcher uses), then band, then progress. Lower rank is more urgent.

   Raw targets (the earlier version): plan slack = due minus capacity-feasible
   finish, score = plan slack over the raw time still needed; ``critical`` as
   above, ``behind`` score < 0, ``ahead`` score >= 1, else ``on_plan``; rank by
   tier, band, score.

Q-time is only the dataset CQT windows: a window is at risk in the plan when
the planned start of its target step is later than the end of its origin step
plus the CQT limit. Windows a lot is already inside at the snapshot open at
``now`` (``fab.inherited_windows``). Raw materials are always available.
Releases follow ``order.txt``: each order row releases a lot of its part every
REPEAT minutes from START, due DUE - START after its release.

Not modelled here (left to scheduling): setups, batch forming, scanner
dedication (SVESTN/FORSTEP pins), rework, and capacity outside litho.
"""

from __future__ import annotations

import heapq
import math
import time
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from resilimes.config import ROOT
from resilimes.data.smt2020_kernel import SNAPSHOT, _rows, _stamp, _to_sec
from resilimes.kernel.score import class_tier, lot_value, order_class_from_priority
from resilimes.smt.fab import Fab, Route, lot_number, measured, transport_seconds

DAY_SEC = 86400.0
BANDS = ("critical", "behind", "on_plan", "ahead")
SCENARIO_PUBLISHED = "published"

_ARRIVE = 0
_FREE = 1


@dataclass(frozen=True)
class Release:
    """One future lot from ``order.txt``."""

    lot_id: str
    route: int
    release_sec: float
    due_sec: float
    order_class: str
    number: int
    part: str = ""
    priority: int = 0


@dataclass
class PlanInput:
    """What one planning run sees. Lot lists are parallel; WIP lots come first,
    in ``fab`` order, then the dataset releases."""

    scenario_id: str
    now: float
    lot_id: list[str]
    lot_route: list[int]
    lot_step: list[int]
    lot_ready: list[float]
    lot_due: list[float]
    lot_class: list[str]
    lot_number: list[int]
    released: list[bool]
    release_until: float
    # Litho tool index -> forced down until (sim seconds), e.g. a scenario down.
    down_until: dict[int, float] = field(default_factory=dict)
    # Seconds subtracted from every PM calendar, as ``simulate.pm_windows`` does.
    pm_shift_sec: float = 0.0
    # Optional per-tool PM windows (``pm_plan.PmPlan.tool_spans``). None keeps
    # the published family calendar on every tool, as ``simulate.pm_windows``.
    tool_pm: dict[int, list[tuple[float, float]]] | None = None
    # Step targets: "standard" (order.txt lead time) or "raw" (no queueing).
    targets: str = "standard"


@dataclass(frozen=True)
class LotPlan:
    index: int
    lot_id: str
    route_id: str
    order_class: str
    tier: int
    released: bool
    ready_sec: float
    due_sec: float
    step: int
    remaining_raw_sec: float
    raw_finish_sec: float
    plan_finish_sec: float
    raw_slack_sec: float
    plan_slack_sec: float
    litho_wait_sec: float
    score: float
    band: str
    rank: int
    qtime_windows: int
    qtime_at_risk: int
    # Route step indices still to visit, and per visited step: step due (latest
    # finish), latest start, capacity-plan start and finish. Sim seconds.
    steps: tuple[int, ...]
    step_due: tuple[float, ...]
    latest_start: tuple[float, ...]
    plan_start: tuple[float, ...]
    plan_end: tuple[float, ...]
    # Standard lead time (step 2): flow factor, standard time still to run from
    # the current step, and progress against the standard curve (ahead > 0).
    flow_factor: float = 1.0
    standard_remaining_sec: float = 0.0
    progress_sec: float = 0.0

    def due_of(self, route_step: int) -> float | None:
        """Step due of one route step index, or None when the lot will not visit it."""
        pos = bisect_right(self.steps, route_step) - 1
        if pos < 0 or self.steps[pos] != route_step:
            return None
        return self.step_due[pos]

    def public(self) -> dict[str, Any]:
        return {
            "lot_id": self.lot_id,
            "route": self.route_id,
            "class": self.order_class,
            "released": self.released,
            "step": self.step,
            "due_h": round(self.due_sec / 3600.0, 2),
            "remaining_raw_h": round(self.remaining_raw_sec / 3600.0, 2),
            "raw_finish_h": round(self.raw_finish_sec / 3600.0, 2),
            "plan_finish_h": round(self.plan_finish_sec / 3600.0, 2),
            "plan_slack_h": round(self.plan_slack_sec / 3600.0, 2),
            "litho_wait_h": round(self.litho_wait_sec / 3600.0, 2),
            "score": round(self.score, 4),
            "flow_factor": round(self.flow_factor, 3),
            "standard_remaining_h": round(self.standard_remaining_sec / 3600.0, 2),
            "progress_h": round(self.progress_sec / 3600.0, 2),
            "band": self.band,
            "rank": self.rank,
            "qtime_windows": self.qtime_windows,
            "qtime_at_risk": self.qtime_at_risk,
            "next_step_due_h": round(self.step_due[0] / 3600.0, 2) if self.step_due else None,
        }


@dataclass(frozen=True)
class LithoDay:
    """One litho family on one plan day. Hours are raw process hours."""

    family: str
    day: int
    capacity_h: float
    # Raw hours whose latest start falls on this day (before ``now`` counts on day 0).
    demand_h: float
    # Raw hours the capacity plan starts on this day.
    planned_h: float
    overload: bool
    # Demand through this day exceeds capacity through this day.
    cum_overload: bool


@dataclass
class PlanningOutput:
    """One planning run for one scenario. Read by the scheduling layer."""

    scenario_id: str
    now: float
    lots: list[LotPlan]
    litho: list[LithoDay]
    availability: dict[str, float]
    release_until: float
    runtime_ms: float
    targets: str = "standard"
    _by_id: dict[str, LotPlan] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {item.lot_id: item for item in self.lots}

    def lot(self, lot_id: str) -> LotPlan:
        return self._by_id[lot_id]

    def find(self, lot_id: str) -> LotPlan | None:
        """The lot's plan, or None when the plan does not know the lot."""
        return self._by_id.get(lot_id)

    def priority_key(self, lot_id: str) -> tuple[float, ...]:
        """Sort key for the scheduler: smaller is more urgent."""
        item = self._by_id[lot_id]
        return (float(item.rank),)

    def step_due(self, lot_id: str, route_step: int) -> float | None:
        return self._by_id[lot_id].due_of(route_step)

    def band_counts(self, *, wip_only: bool = True) -> dict[str, int]:
        counts = dict.fromkeys(BANDS, 0)
        for item in self.lots:
            if wip_only and item.released:
                continue
            counts[item.band] += 1
        return counts

    def overloads(self) -> list[LithoDay]:
        return [item for item in self.litho if item.overload]

    def summary(self) -> dict[str, Any]:
        wip = [item for item in self.lots if not item.released]
        over: dict[str, list[int]] = {}
        cum: dict[str, int] = {}
        for item in self.litho:
            if item.overload:
                over.setdefault(item.family, []).append(item.day)
            if item.cum_overload:
                cum[item.family] = cum.get(item.family, 0) + 1
        return {
            "scenario_id": self.scenario_id,
            "now_h": self.now / 3600.0,
            "wip_lots": len(wip),
            "release_lots": len(self.lots) - len(wip),
            "release_until_h": round(self.release_until / 3600.0, 1),
            "targets": self.targets,
            "due_tighter_than_standard": sum(1 for item in wip if item.progress_sec < 0.0),
            "due_tighter_than_raw": sum(1 for item in wip if item.raw_slack_sec < 0.0),
            "bands": self.band_counts(),
            "bands_by_class": _bands_by_class(wip),
            "qtime_windows": sum(item.qtime_windows for item in wip),
            "qtime_at_risk": sum(item.qtime_at_risk for item in wip),
            "litho_overload_days": over,
            "litho_cum_overload_days": cum,
            "availability": {key: round(val, 4) for key, val in self.availability.items()},
            "runtime_ms": round(self.runtime_ms, 1),
        }

    def to_dict(self, *, limit: int | None = None) -> dict[str, Any]:
        ranked = sorted(self.lots, key=lambda item: item.rank)
        if limit is not None:
            ranked = ranked[:limit]
        return {
            **self.summary(),
            "lots": [item.public() for item in ranked],
            "litho": [item.__dict__ for item in self.litho],
        }


def _bands_by_class(lots: Sequence[LotPlan]) -> dict[str, dict[str, int]]:
    found: dict[str, dict[str, int]] = {}
    for item in lots:
        row = found.setdefault(item.order_class, dict.fromkeys(BANDS, 0))
        row[item.band] += 1
    return found


# --------------------------------------------------------------------- inputs


_LEAD: dict[tuple[str, ...], dict[tuple[int, str], float]] = {}


def standard_lead_times(fab: Fab) -> dict[tuple[int, str], float]:
    """(route index, order class) -> ``order.txt`` DUE - START, seconds."""
    key = tuple(route.route_id for route in fab.routes)
    if key not in _LEAD:
        path = ROOT / "data" / "smt2020"
        part_route = {row["PART"].strip(): row["ROUTE"].strip() for row in _rows(path / "part.txt")}
        found: dict[tuple[int, str], float] = {}
        for row in _rows(path / "order.txt"):
            route = part_route[row["PART"].strip()]
            if route not in fab.route_index:
                continue
            kind = order_class_from_priority(int(float(row["PRIOR"])))
            span = (_stamp(row["DUE"]) - _stamp(row["START"])).total_seconds()
            slot = (fab.route_index[route], kind)
            found[slot] = min(span, found.get(slot, span))
        _LEAD[key] = found
    return _LEAD[key]


def lead_time(fab: Fab, route: int, order_class: str) -> float | None:
    """Standard lead time of one product and class; the product's tightest
    listed class when the pair has no order row; None when the product has
    no order row at all (a test fab), which keeps raw time (F = 1)."""
    table = standard_lead_times(fab)
    found = table.get((route, order_class))
    if found is not None:
        return found
    listed = [span for (item, _kind), span in table.items() if item == route]
    return min(listed) if listed else None


def raw_path_seconds(fab: Fab, route: Route, path: Sequence[int]) -> float:
    """Raw process plus transport over a visited path."""
    total = 0.0
    for pos, index in enumerate(path):
        total += route.cycle[index]
        if pos > 0:
            total += transport_seconds(fab, route.family[path[pos - 1]], route.family[index])
    return total


def dataset_releases(fab: Fab, *, until: float, after: float = 0.0) -> list[Release]:
    """Lots ``order.txt`` releases in ``[after, until)`` (sim seconds)."""
    path = ROOT / "data" / "smt2020"
    part_route = {row["PART"].strip(): row["ROUTE"].strip() for row in _rows(path / "part.txt")}
    found: list[Release] = []
    for row in _rows(path / "order.txt"):
        start = (_stamp(row["START"]) - SNAPSHOT).total_seconds()
        due_after = (_stamp(row["DUE"]) - SNAPSHOT).total_seconds() - start
        every = _to_sec(float(row["REPEAT"]), row["RUNITS"] or "min")
        count = int(float(row["RPT#"]))
        per = max(1, int(float(row["LOTSPERRPT"] or 1)))
        route = fab.route_index[part_route[row["PART"].strip()]]
        prior = int(float(row["PRIOR"]))
        kind = order_class_from_priority(prior)
        name = row["LOT"].strip()
        for k in range(count):
            moment = start + k * every
            if moment >= until:
                break
            if moment < after:
                continue
            for j in range(per):
                number = k * per + j + 1
                found.append(
                    Release(
                        lot_id=f"{name}_{number}",
                        route=route,
                        release_sec=moment,
                        due_sec=moment + due_after,
                        order_class=kind,
                        number=number,
                        part=row["PART"].strip(),
                        priority=prior,
                    )
                )
    found.sort(key=lambda item: (item.release_sec, item.lot_id))
    return found


def with_releases(fab: Fab, *, until: float) -> Fab:
    """``fab`` plus every ``order.txt`` lot released in ``[0, until)``.

    Released lots are appended after the WIP (WIP indices do not move) at
    step index 0, with the dataset's product, class, priority and due; raw
    material is always available, so a lot enters the fab at its release.
    """
    found = [item for item in dataset_releases(fab, until=until) if item.release_sec >= 0.0]
    base = list(fab.lot_release) or [0.0] * len(fab.lot_id)
    return replace(
        fab,
        lot_id=[*fab.lot_id, *(item.lot_id for item in found)],
        lot_product=[*fab.lot_product, *(item.part for item in found)],
        lot_route=[*fab.lot_route, *(item.route for item in found)],
        lot_step=[*fab.lot_step, *(0 for _ in found)],
        lot_due=[*fab.lot_due, *(item.due_sec for item in found)],
        lot_value=[*fab.lot_value, *(lot_value(item.order_class) for item in found)],
        lot_class=[*fab.lot_class, *(item.order_class for item in found)],
        lot_priority=[*fab.lot_priority, *(item.priority for item in found)],
        lot_release=[*base, *(item.release_sec for item in found)],
    )


def plan_input(
    fab: Fab,
    *,
    scenario_id: str = SCENARIO_PUBLISHED,
    now: float = 0.0,
    lot_step: Sequence[int] | None = None,
    lot_ready: Sequence[float] | None = None,
    lot_due: Sequence[float] | None = None,
    lot_class: Sequence[str] | None = None,
    finished: Sequence[bool] | None = None,
    releases: bool = True,
    release_until: float | None = None,
    down_until: dict[int, float] | None = None,
    pm_shift_sec: float = 0.0,
    tool_pm: dict[int, list[tuple[float, float]]] | None = None,
    targets: str = "standard",
) -> PlanInput:
    """Build the input from the fab and, inside a sim, the current lot state.

    ``release_until`` defaults to the latest WIP due: every release that can
    compete for litho with the WIP before the WIP is due is in the plan.
    """
    steps = list(lot_step) if lot_step is not None else list(fab.lot_step)
    ready = list(lot_ready) if lot_ready is not None else [now] * len(fab.lot_id)
    dues = list(lot_due) if lot_due is not None else list(fab.lot_due)
    kinds = list(lot_class) if lot_class is not None else list(fab.lot_class)
    done = list(finished) if finished is not None else [False] * len(fab.lot_id)
    until = release_until if release_until is not None else max(dues, default=now)
    inp = PlanInput(
        scenario_id=scenario_id,
        now=now,
        lot_id=[],
        lot_route=[],
        lot_step=[],
        lot_ready=[],
        lot_due=[],
        lot_class=[],
        lot_number=[],
        released=[],
        release_until=until,
        down_until=dict(down_until or {}),
        pm_shift_sec=pm_shift_sec,
        tool_pm=tool_pm,
        targets=targets,
    )
    for lot, name in enumerate(fab.lot_id):
        if done[lot]:
            continue
        inp.lot_id.append(name)
        inp.lot_route.append(fab.lot_route[lot])
        inp.lot_step.append(steps[lot])
        inp.lot_ready.append(max(now, ready[lot]))
        inp.lot_due.append(dues[lot])
        inp.lot_class.append(kinds[lot])
        inp.lot_number.append(lot_number(name, lot))
        inp.released.append(False)
    if releases:
        for item in dataset_releases(fab, until=until, after=now):
            inp.lot_id.append(item.lot_id)
            inp.lot_route.append(item.route)
            inp.lot_step.append(0)
            inp.lot_ready.append(item.release_sec)
            inp.lot_due.append(item.due_sec)
            inp.lot_class.append(item.order_class)
            inp.lot_number.append(item.number)
            inp.released.append(True)
    return inp


def plan_horizon(inp: PlanInput) -> float:
    """Calendar horizon of one planning run (PM windows are built up to it)."""
    return max([inp.release_until, *inp.lot_due, inp.now]) + 365 * DAY_SEC


def with_pm_plan(fab: Fab, inp: PlanInput) -> PlanInput:
    """Hook: the same input with the staggered per-tool PM plan (``pm_plan``).

    The plan covers the planning window ``[0, release_until)``, so the PM
    count inside the window equals the dataset's (the stagger only moves PMs
    earlier, never across the window end). Occurrences the dataset starts
    after the window keep the published family calendar.
    """
    from resilimes.smt.pm_plan import build_pm_plan, published_windows

    window = inp.release_until
    plan = build_pm_plan(fab, window, shift_sec=inp.pm_shift_sec)
    later = published_windows(fab, plan_horizon(inp), shift_sec=inp.pm_shift_sec)
    tool_pm: dict[int, list[tuple[float, float]]] = {}
    for item in fab.families:
        if not item.litho:
            continue
        for tool in range(item.tool0, item.tool0 + item.tools):
            tail = [span for span in later[tool] if span[0] >= window]
            tool_pm[tool] = _merge([*plan.tool_windows(tool), *tail])
    inp.tool_pm = tool_pm
    return inp


def scenario_input(
    fab: Fab,
    scenario_id: str,
    *,
    releases: bool = True,
    targets: str = "standard",
    release_until: float | None = None,
    staggered_pm: bool = False,
) -> PlanInput:
    """Planning input for one headline scenario (``resilimes.smt.scenarios``).

    ``published`` is the published book with no incident. Each scenario changes
    only what the simulator changes: dues and classes (tight, xfactor, hot), a
    forced litho down (litho, xfactor) and the PM shift (pm). The tight book's
    Dielectric down is outside litho, so it does not change litho capacity.
    ``release_until`` (default: the latest WIP due) bounds the planned releases.
    """
    until = release_until if release_until is not None else max(fab.lot_due, default=0.0)
    if scenario_id == SCENARIO_PUBLISHED:
        inp = plan_input(fab, releases=releases, release_until=until, targets=targets)
        return with_pm_plan(fab, inp) if staggered_pm else inp
    from resilimes.smt.fab import LITHO_MTTR_MIN
    from resilimes.smt.scenarios import HOT_DUE_SEC, PM_OPEN_SEC, SCENARIOS
    from resilimes.smt.simulate import pm_shift_to_open
    from resilimes.smt.tight import TIGHT_HORIZON_SEC, apply_tight, apply_xfactor

    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise KeyError(scenario_id)
    dues = list(fab.lot_due)
    kinds = list(fab.lot_class)
    down: dict[int, float] = {}
    shift = 0.0
    if scenario.kind == "tight":
        book = apply_tight(fab, horizon=TIGHT_HORIZON_SEC)
        dues = list(book.fab.lot_due)
        kinds = list(book.fab.lot_class)
    elif scenario.kind == "xfactor":
        dues = list(apply_xfactor(fab).lot_due)
        down[fab.focus_tool] = 600.0 * 60.0
    elif scenario.kind == "litho":
        down[fab.focus_tool] = LITHO_MTTR_MIN * 60.0
    elif scenario.kind == "hot":
        dues[fab.hot_lot] = HOT_DUE_SEC
        kinds[fab.hot_lot] = "VIP"
    elif scenario.kind == "pm":
        shift = pm_shift_to_open(fab, fab.pm_calendar, PM_OPEN_SEC)
    inp = plan_input(
        fab,
        scenario_id=scenario_id,
        lot_due=dues,
        lot_class=kinds,
        releases=releases,
        release_until=until,
        down_until=down,
        pm_shift_sec=shift,
        targets=targets,
    )
    return with_pm_plan(fab, inp) if staggered_pm else inp


# ----------------------------------------------------------------- the plan


def litho_availability(fab: Fab) -> dict[int, float]:
    """Expected up fraction of each litho family from its STNGRP down calendar."""
    found: dict[int, float] = {}
    for fam, item in enumerate(fab.families):
        if not item.litho:
            continue
        mttf = fab.down_mttf.get(item.group, 0.0)
        mttr = fab.down_mttr.get(item.group, 0.0)
        found[fam] = mttf / (mttf + mttr) if mttf > 0 and mttr > 0 else 1.0
    return found


def family_pm(
    fab: Fab, until: float, *, shift_sec: float = 0.0
) -> dict[int, list[tuple[float, float]]]:
    """PM windows per litho family, the same calendar rule as ``simulate.pm_windows``."""
    found: dict[int, list[tuple[float, float]]] = {
        fam: [] for fam, item in enumerate(fab.families) if item.litho
    }
    for fam, first, interval, duration, _name in fab.pm:
        if fam not in found or interval <= 0 or duration <= 0:
            continue
        start = first - shift_sec
        guard = 0
        while start < until and guard < 10000:
            end = start + duration
            if end > 0:
                found[fam].append((max(0.0, start), end))
            start += interval
            guard += 1
    for fam, spans in found.items():
        found[fam] = _merge(spans)
    return found


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def visit_path(route: Route, step: int, number: int) -> list[int]:
    """The current step, then every later step this lot number is measured at."""
    return [step] + [
        index for index in range(step + 1, len(route.family)) if measured(route, index, number)
    ]


def backward(
    fab: Fab, route: Route, path: Sequence[int], due: float, factor: float = 1.0
) -> tuple[list[float], list[float]]:
    """(step due, start) per visited step: every process and transport time
    times ``factor`` (1: raw, no queueing; the flow factor: standard time)."""
    count = len(path)
    finish = [0.0] * count
    start = [0.0] * count
    cursor = due
    for pos in range(count - 1, -1, -1):
        index = path[pos]
        finish[pos] = cursor
        start[pos] = cursor - factor * route.cycle[index]
        if pos > 0:
            cursor = start[pos] - factor * transport_seconds(
                fab, route.family[path[pos - 1]], route.family[index]
            )
    return finish, start


def build_plan(fab: Fab, inp: PlanInput) -> PlanningOutput:
    """Step targets, forward litho capacity check, bands and ranks."""
    if inp.targets not in ("standard", "raw"):
        raise ValueError(inp.targets)
    began = time.perf_counter()
    now = inp.now
    n = len(inp.lot_id)
    avail = litho_availability(fab)
    litho = [item.litho for item in fab.families]
    pm = family_pm(fab, plan_horizon(inp), shift_sec=inp.pm_shift_sec)
    tool_pm = _tool_pm(fab, inp, pm)
    tool_ends = {tool: [end for _start, end in spans] for tool, spans in tool_pm.items()}

    paths: list[list[int]] = []
    sdue: list[list[float]] = []
    lstart: list[list[float]] = []
    tiers: list[int] = []
    factors: list[float] = []
    raw_need: list[float] = []
    path_cache: dict[tuple[int, int, int], list[int]] = {}
    full_raw: dict[tuple[int, int], float] = {}
    standard = inp.targets == "standard"
    for lot in range(n):
        route = fab.routes[inp.lot_route[lot]]
        key = (inp.lot_route[lot], inp.lot_step[lot], inp.lot_number[lot])
        path = path_cache.get(key)
        if path is None:
            path = visit_path(route, inp.lot_step[lot], inp.lot_number[lot])
            path_cache[key] = path
        paths.append(path)
        factor = 1.0
        if standard:
            whole = (inp.lot_route[lot], inp.lot_number[lot])
            if whole not in full_raw:
                full_raw[whole] = raw_path_seconds(
                    fab, route, visit_path(route, 0, inp.lot_number[lot])
                )
            lead = lead_time(fab, inp.lot_route[lot], inp.lot_class[lot])
            if lead is not None and full_raw[whole] > 0.0:
                factor = lead / full_raw[whole]
        factors.append(factor)
        raw_need.append(raw_path_seconds(fab, route, path))
        finish, start = backward(fab, route, path, inp.lot_due[lot], factor)
        sdue.append(finish)
        lstart.append(start)
        tiers.append(class_tier(inp.lot_class[lot]))

    # Forward pass: event list over litho families only.
    p_start: list[list[float]] = [[0.0] * len(path) for path in paths]
    p_end: list[list[float]] = [[0.0] * len(path) for path in paths]
    litho_wait = [0.0] * n
    done_at = [0.0] * n
    events: list[tuple[float, int, int, int, int]] = []
    seq = 0
    queues: dict[int, list[tuple[int, float, int, int]]] = {fam: [] for fam in pm}
    idle: dict[int, list[int]] = {fam: [] for fam in pm}
    for fam in pm:
        item = fab.families[fam]
        for tool in range(item.tool0, item.tool0 + item.tools):
            until = inp.down_until.get(tool, 0.0)
            if until > now:
                events.append((until, _FREE, fam, tool, seq))
                seq += 1
            else:
                idle[fam].append(tool)
    arrive_at: list[float] = [0.0] * n

    def flow(lot: int, pos: int, moment: float) -> None:
        """Run non-litho steps at raw time from ``pos``; stop at the next litho step."""
        nonlocal seq
        route = fab.routes[inp.lot_route[lot]]
        path = paths[lot]
        starts = p_start[lot]
        ends = p_end[lot]
        last = len(path)
        while pos < last:
            index = path[pos]
            fam = route.family[index]
            if litho[fam]:
                arrive_at[lot] = moment
                heapq.heappush(events, (moment, _ARRIVE, lot, pos, seq))
                seq += 1
                return
            starts[pos] = moment
            end = moment + route.cycle[index]
            ends[pos] = end
            pos += 1
            if pos < last:
                nxt = route.family[path[pos]]
                moment = end + transport_seconds(fab, fam, nxt)
            else:
                moment = end
        done_at[lot] = moment

    def dispatch(fam: int, moment: float) -> None:
        nonlocal seq
        queue = queues[fam]
        tools = idle[fam]
        rate = avail[fam]
        while queue and tools:
            _tier, _ls, lot, pos = queue[0]
            route = fab.routes[inp.lot_route[lot]]
            index = paths[lot][pos]
            proc = route.cycle[index] / rate
            tool = -1
            while tools:
                cand = tools.pop()
                spans = tool_pm[cand]
                hit = bisect_right(tool_ends[cand], moment)
                if hit < len(spans) and spans[hit][0] < moment + proc:
                    # Starting now would run into this tool's next PM: the tool
                    # waits for the PM to end (with the published calendar
                    # every tool of the family does).
                    heapq.heappush(events, (spans[hit][1], _FREE, fam, cand, seq))
                    seq += 1
                    continue
                tool = cand
                break
            if tool < 0:
                return
            heapq.heappop(queue)
            end = moment + proc
            p_start[lot][pos] = moment
            p_end[lot][pos] = end
            litho_wait[lot] += moment - arrive_at[lot]
            heapq.heappush(events, (end, _FREE, fam, tool, seq))
            seq += 1
            nxt = pos + 1
            if nxt < len(paths[lot]):
                nfam = route.family[paths[lot][nxt]]
                move = transport_seconds(fab, route.family[index], nfam)
                flow(lot, nxt, end + move)
            else:
                done_at[lot] = end

    heapq.heapify(events)
    for lot in range(n):
        flow(lot, 0, inp.lot_ready[lot])
    while events:
        # Apply every event at this instant before dispatching, so lots that
        # arrive together are started in priority order, not arrival order.
        moment = events[0][0]
        touched: set[int] = set()
        while events and events[0][0] == moment:
            _moment, kind, a, b, _seq = heapq.heappop(events)
            if kind == _ARRIVE:
                fam = fab.routes[inp.lot_route[a]].family[paths[a][b]]
                heapq.heappush(queues[fam], (tiers[a], lstart[a][b], a, b))
            else:
                fam = a
                idle[fam].append(b)
            touched.add(fam)
        for fam in sorted(touched):
            dispatch(fam, moment)

    lots = _lot_plans(
        fab, inp, paths, sdue, lstart, p_start, p_end, done_at, litho_wait, tiers, factors, raw_need
    )
    days = _litho_days(fab, inp, paths, lstart, p_start, pm, tool_pm, avail)
    return PlanningOutput(
        scenario_id=inp.scenario_id,
        now=now,
        lots=lots,
        litho=days,
        availability={fab.families[fam].name: val for fam, val in avail.items()},
        release_until=inp.release_until,
        runtime_ms=(time.perf_counter() - began) * 1000.0,
        targets=inp.targets,
    )


def _tool_pm(
    fab: Fab, inp: PlanInput, pm: dict[int, list[tuple[float, float]]]
) -> dict[int, list[tuple[float, float]]]:
    """PM windows per litho tool: the PM plan if given, else the family calendar."""
    found: dict[int, list[tuple[float, float]]] = {}
    for fam, spans in pm.items():
        item = fab.families[fam]
        for tool in range(item.tool0, item.tool0 + item.tools):
            if inp.tool_pm is None:
                found[tool] = spans
            else:
                found[tool] = _merge(list(inp.tool_pm.get(tool, [])))
    return found


def standard_band(raw_slack: float, progress: float, plan_slack: float) -> str:
    """Band against the standard curve (module docstring, step 4)."""
    if raw_slack < 0.0:
        return "critical"
    if progress < 0.0:
        return "behind"
    if plan_slack < 0.0:
        return "on_plan"
    return "ahead"


def band_of(raw_slack: float, score: float) -> str:
    if raw_slack < 0.0:
        return "critical"
    if score < 0.0:
        return "behind"
    if score >= 1.0:
        return "ahead"
    return "on_plan"


def _qtime(
    route: Route,
    path: Sequence[int],
    starts: Sequence[float],
    ends: Sequence[float],
    now: float,
    released: bool,
) -> tuple[int, int]:
    """(dataset CQT windows in the plan, windows whose target starts too late)."""
    where = {index: pos for pos, index in enumerate(path)}
    windows = 0
    risk = 0
    if not released and path:
        step = path[0]
        for origin in range(step - 1, -1, -1):
            target = route.cqt_target[origin]
            if route.cqt_limit[origin] > 0 and target >= step:
                pos = where.get(target)
                if pos is not None:
                    windows += 1
                    if starts[pos] > now + route.cqt_limit[origin]:
                        risk += 1
                break
    for pos, index in enumerate(path):
        limit = route.cqt_limit[index]
        if limit <= 0:
            continue
        aim = where.get(route.cqt_target[index])
        if aim is None or aim <= pos:
            continue
        windows += 1
        if starts[aim] > ends[pos] + limit:
            risk += 1
    return windows, risk


def _lot_plans(
    fab: Fab,
    inp: PlanInput,
    paths: list[list[int]],
    sdue: list[list[float]],
    lstart: list[list[float]],
    p_start: list[list[float]],
    p_end: list[list[float]],
    done_at: list[float],
    litho_wait: list[float],
    tiers: list[int],
    factors: list[float],
    raw_need: list[float],
) -> list[LotPlan]:
    standard = inp.targets == "standard"
    rows: list[tuple[tuple[float, ...], int]] = []
    pre: list[tuple[float, float, float, float, float, str, float, float, float]] = []
    for lot in range(len(inp.lot_id)):
        ready = inp.lot_ready[lot]
        due = inp.lot_due[lot]
        std_need = due - lstart[lot][0]
        # Raw targets: the raw need is the backward pass's own (bit-identical).
        need = raw_need[lot] if standard else std_need
        raw_finish = ready + need
        plan_finish = done_at[lot]
        raw_slack = due - raw_finish
        plan_slack = due - plan_finish
        progress = lstart[lot][0] - ready
        if standard:
            score = progress / std_need if std_need > 0 else progress
            band = standard_band(raw_slack, progress, plan_slack)
            key = progress
        else:
            score = plan_slack / need if need > 0 else plan_slack
            band = band_of(raw_slack, score)
            key = score
        pre.append(
            (need, raw_finish, plan_finish, raw_slack, plan_slack, band, score, std_need, progress)
        )
        rows.append(((float(tiers[lot]), float(BANDS.index(band)), key, due), lot))
    rows.sort()
    rank = [0] * len(rows)
    for place, (_key, lot) in enumerate(rows, start=1):
        rank[lot] = place
    plans: list[LotPlan] = []
    for lot in range(len(inp.lot_id)):
        route = fab.routes[inp.lot_route[lot]]
        need, raw_finish, plan_finish, raw_slack, plan_slack, band, score, std_need, progress = pre[
            lot
        ]
        windows, risk = _qtime(
            route, paths[lot], p_start[lot], p_end[lot], inp.now, inp.released[lot]
        )
        plans.append(
            LotPlan(
                index=lot,
                lot_id=inp.lot_id[lot],
                route_id=route.route_id,
                order_class=inp.lot_class[lot],
                tier=tiers[lot],
                released=inp.released[lot],
                ready_sec=inp.lot_ready[lot],
                due_sec=inp.lot_due[lot],
                step=paths[lot][0],
                remaining_raw_sec=need,
                raw_finish_sec=raw_finish,
                plan_finish_sec=plan_finish,
                raw_slack_sec=raw_slack,
                plan_slack_sec=plan_slack,
                litho_wait_sec=litho_wait[lot],
                score=score,
                band=band,
                rank=rank[lot],
                qtime_windows=windows,
                qtime_at_risk=risk,
                steps=tuple(paths[lot]),
                step_due=tuple(sdue[lot]),
                latest_start=tuple(lstart[lot]),
                plan_start=tuple(p_start[lot]),
                plan_end=tuple(p_end[lot]),
                flow_factor=factors[lot],
                standard_remaining_sec=std_need,
                progress_sec=progress,
            )
        )
    return plans


def _up_seconds(spans: Sequence[tuple[float, float]], start: float, end: float) -> float:
    """Seconds of ``[start, end)`` outside ``spans``."""
    lost = 0.0
    for lo, hi in spans:
        if hi <= start:
            continue
        if lo >= end:
            break
        lost += min(hi, end) - max(lo, start)
    return max(0.0, end - start - lost)


def _litho_days(
    fab: Fab,
    inp: PlanInput,
    paths: list[list[int]],
    lstart: list[list[float]],
    p_start: list[list[float]],
    pm: dict[int, list[tuple[float, float]]],
    tool_pm: dict[int, list[tuple[float, float]]],
    avail: dict[int, float],
) -> list[LithoDay]:
    now = inp.now
    days = max(1, math.ceil((inp.release_until - now) / DAY_SEC))
    demand = {fam: [0.0] * days for fam in pm}
    planned = {fam: [0.0] * days for fam in pm}
    for lot, path in enumerate(paths):
        route = fab.routes[inp.lot_route[lot]]
        for pos, index in enumerate(path):
            fam = route.family[index]
            if fam not in demand:
                continue
            hours = route.cycle[index] / 3600.0
            day = max(0, int((lstart[lot][pos] - now) // DAY_SEC))
            if day < days:
                demand[fam][day] += hours
            day = int((p_start[lot][pos] - now) // DAY_SEC)
            if 0 <= day < days:
                planned[fam][day] += hours
    out: list[LithoDay] = []
    for fam in sorted(pm, key=lambda item: fab.families[item].name):
        item = fab.families[fam]
        cum_need = 0.0
        cum_cap = 0.0
        for day in range(days):
            lo = now + day * DAY_SEC
            hi = lo + DAY_SEC
            up = 0.0
            for tool in range(item.tool0, item.tool0 + item.tools):
                down = inp.down_until.get(tool, 0.0)
                own = tool_pm[tool]
                spans = _merge([*own, (now, down)]) if down > now else own
                up += _up_seconds(spans, lo, hi)
            cap = up * avail[fam] / 3600.0
            cum_need += demand[fam][day]
            cum_cap += cap
            out.append(
                LithoDay(
                    family=item.name,
                    day=day,
                    capacity_h=round(cap, 2),
                    demand_h=round(demand[fam][day], 2),
                    planned_h=round(planned[fam][day], 2),
                    overload=demand[fam][day] > cap + 1e-9,
                    cum_overload=cum_need > cum_cap + 1e-9,
                )
            )
    return out


def plan_scenario(
    fab: Fab, scenario_id: str = SCENARIO_PUBLISHED, *, staggered_pm: bool = False
) -> PlanningOutput:
    """One planning run for a headline scenario (or ``published``).

    ``staggered_pm`` swaps the published family PM calendar for the per-tool
    plan of ``pm_plan.build_pm_plan`` (capacity check and litho dispatch).
    """
    return build_plan(fab, scenario_input(fab, scenario_id, staggered_pm=staggered_pm))
