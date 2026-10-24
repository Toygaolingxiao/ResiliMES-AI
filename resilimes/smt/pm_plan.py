"""PM plan: a staggered per-tool PM calendar (planning layer).

SMT2020 publishes one PM calendar per tool family (``pmcal.txt`` linked through
``attach.txt``; WK / MN / QT rows): a first start (FOA), an interval (MTBPM)
and a duration (MTTR). ``simulate.pm_windows`` copies the family calendar onto
every tool, so a whole family goes down at once (e.g. all 23 Litho_BE_110
scanners for 6.65 h every week). This module turns that into an explicit
per-tool calendar in which a family loses as few tools at a time as its PM
load allows. The scheduling layer reads it as PM windows; dispatch must never
start a lot that would run into one.

Mapping to the published calendar (no tuned constant anywhere)
---------------------------------------------------------------
For a family with ``n`` tools (tool index order ``0..n-1``) and each of its
calendars ``c`` (first start ``F``, interval ``I``, duration ``D``, all as
published, after the same optional ``shift_sec`` as ``simulate.pm_windows``):

1. **Same occurrences.** The dataset calendar has occurrences
   ``F + k*I`` for ``k = 0, 1, ...`` (kept while they start before the
   horizon and end after 0, exactly as ``simulate.pm_windows``). Every tool
   keeps exactly those occurrence indices ``k``: the total PM count per tool,
   per family and for the fab is the dataset's, and every PM keeps its
   published duration.
2. **Even stagger, by tool index.** Tool ``i``'s nominal start for occurrence
   ``k`` is ``F + k*I - (n-1-i) * I/n``: the last tool keeps the published
   time, the others are spread ``I/n`` apart before it. Every nominal start is
   therefore later than ``F + k*I - I`` (never earlier than the published
   time minus one interval), and the nominal interval of each tool is the
   published ``I``. A nominal start before 0 is moved to 0.
3. **Lanes.** The family PM load is ``L = n * sum_c(D_c / I_c)`` (average
   tools in PM). The allowed number of tools in PM at once is
   ``lanes = max(1, ceil(L))``: 1 whenever full staggering is possible, else
   the minimum overlap, which is flagged (``overlap_required``). A single-tool
   family keeps its published calendar unchanged.
4. **Placement.** All of a family's occurrences are placed in order of
   (nominal start, calendar order in the dataset, tool index). Each starts at
   the earliest time at or after its nominal start at which its tool is not
   already in PM and fewer than ``lanes`` tools of the family are in PM for
   its whole duration. Calendars with different intervals (WK 168 h, MN
   720 h, QT 2184 h) drift against each other, so a few occurrences start
   later than nominal; ``max_delay_h`` reports by how much.

Flexible execution (``pm_decision``)
------------------------------------
The plan above gives every PM a *planned* start. PMs are not mandatory at that
exact time: each planned PM gets an allowed window and the scheduling layer
calls ``pm_decision(tool, now, state)`` at every scheduling tick.

* **Window (fab rule ``PM_WINDOW_SEC``).** SMT2020 has no PM tolerance field;
  the window is the fab owner's rule, one parameter, default 24 h: a PM may
  move up to one day either side of its planned start,
  ``earliest = planned - 24 h`` and ``latest = planned + 24 h``. ``latest`` never
  passes the same tool's next planned PM (any calendar) minus this PM's
  duration, and ``earliest`` is never before the end of the tool's previous
  planned PM, nor before 0. Not tuned.
* **force** when waiting one more tick would pass ``latest`` (the PM then
  starts as soon as the tool's current lot or batch is done).
* **start_now** (opportunistic, also before the planned time) when the tool
  is inside its window, up and idle, fewer than ``lanes`` tools of the family
  hold a PM, and the family's eligible queue (standard work seconds from the
  master-data step times) fits on the other tools during the PM duration.
* **defer** otherwise: the queue exceeds what the other up tools can process
  during the PM (taking this tool down now would grow the queue), the tool is
  running, down, or the family is at its PM cap.

A started or forced PM is *committed*: ``PmState.may_start_lot`` refuses a lot
that would run into it or past the latest start of the tool's next PM. Every
planned PM is committed exactly once (deferral moves it, never drops or merges
it). Every in-window decision is logged with its reason.
"""

from __future__ import annotations

import math
from bisect import bisect_left, insort
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from resilimes.smt.fab import Fab

_EPS = 1e-6


@dataclass(frozen=True)
class PmWindow:
    """One planned PM on one tool."""

    tool: int
    family: int
    calendar: str
    occurrence: int
    published_sec: float  # dataset start of this occurrence (whole family)
    nominal_sec: float  # evenly staggered start
    start_sec: float  # planned start (>= nominal)
    end_sec: float
    interval_sec: float = 0.0  # published MTBPM of this calendar

    @property
    def delay_sec(self) -> float:
        return self.start_sec - self.nominal_sec


@dataclass(frozen=True)
class FamilyPm:
    """Before/after figures for one family with a PM calendar."""

    family: str
    group: str
    tools: int
    calendars: tuple[tuple[str, float, float, float], ...]  # (name, first_h, interval_h, dur_h)
    load: float  # average tools in PM: tools * sum(D / I)
    lanes: int
    overlap_required: bool
    overfull_calendars: tuple[str, ...]  # calendars where tools * D > I on their own
    count_before: int
    count_after: int
    max_in_pm_before: int
    max_in_pm_after: int
    min_available_before: int
    min_available_after: int
    max_delay_h: float
    mean_delay_h: float

    def row(self) -> dict[str, Any]:
        cal = {
            name.rsplit("_", 1)[-1]: (interval, dur) for name, _f, interval, dur in self.calendars
        }
        return {
            "family": self.family,
            "group": self.group,
            "tools": self.tools,
            "interval_h/duration_h": {k: f"{i:g}/{d:.2f}" for k, (i, d) in cal.items()},
            "load": round(self.load, 3),
            "lanes": self.lanes,
            "overlap_required": self.overlap_required,
            "overfull_calendars": list(self.overfull_calendars),
            "pm_count": (self.count_before, self.count_after),
            "max_in_pm": (self.max_in_pm_before, self.max_in_pm_after),
            "min_available": (self.min_available_before, self.min_available_after),
            "min_available_pct": (
                round(100.0 * self.min_available_before / self.tools, 1),
                round(100.0 * self.min_available_after / self.tools, 1),
            ),
            "max_delay_h": round(self.max_delay_h, 2),
            "mean_delay_h": round(self.mean_delay_h, 2),
        }


@dataclass
class PmPlan:
    """Per-tool PM calendar over ``[0, horizon)``."""

    horizon: float
    shift_sec: float
    tool_count: int
    windows: list[PmWindow]
    families: dict[int, FamilyPm]
    _by_tool: dict[int, list[tuple[float, float]]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        by_tool: dict[int, list[tuple[float, float]]] = {}
        for item in self.windows:
            by_tool.setdefault(item.tool, []).append((item.start_sec, item.end_sec))
        self._by_tool = {tool: sorted(spans) for tool, spans in by_tool.items()}

    def tool_windows(self, tool: int) -> list[tuple[float, float]]:
        """Planned PM windows of one tool, sorted, unmerged."""
        return list(self._by_tool.get(tool, []))

    def per_tool(self) -> list[list[tuple[float, float]]]:
        """Same shape as ``simulate.pm_windows``: one list per tool index."""
        return [self.tool_windows(tool) for tool in range(self.tool_count)]

    def tool_spans(self, tools: Sequence[int]) -> dict[int, list[tuple[float, float]]]:
        """Merged windows per tool, for capacity checks."""
        return {tool: _merge(self.tool_windows(tool)) for tool in tools}

    def family_rows(self, families: Sequence[str] | None = None) -> list[dict[str, Any]]:
        rows = sorted(self.families.values(), key=lambda item: item.family)
        if families is not None:
            wanted = set(families)
            rows = [item for item in rows if item.family in wanted]
        return [item.row() for item in rows]

    def flagged(self) -> list[str]:
        """Families where full staggering is impossible (minimum overlap kept)."""
        return sorted(item.family for item in self.families.values() if item.overlap_required)

    def summary(self) -> dict[str, Any]:
        return {
            "horizon_h": round(self.horizon / 3600.0, 1),
            "shift_h": round(self.shift_sec / 3600.0, 2),
            "families": len(self.families),
            "pm_count_before": sum(item.count_before for item in self.families.values()),
            "pm_count_after": sum(item.count_after for item in self.families.values()),
            "overlap_required": self.flagged(),
        }


# ----------------------------------------------------------------- dataset


def published_occurrences(
    first: float, interval: float, duration: float, horizon: float, shift_sec: float = 0.0
) -> list[tuple[int, float]]:
    """(k, start) of the dataset calendar, the rule of ``simulate.pm_windows``."""
    found: list[tuple[int, float]] = []
    if interval <= 0 or duration <= 0:
        return found
    start = first - shift_sec
    k = 0
    while start < horizon and k < 10000:
        if start + duration > 0:
            found.append((k, start))
        start += interval
        k += 1
    return found


def published_windows(
    fab: Fab, horizon: float, *, shift_sec: float = 0.0
) -> list[list[tuple[float, float]]]:
    """The dataset calendar per tool (every tool gets its family's windows)."""
    per_family: list[list[tuple[float, float]]] = [[] for _ in fab.families]
    for fam, first, interval, duration, _name in fab.pm:
        for _k, start in published_occurrences(first, interval, duration, horizon, shift_sec):
            per_family[fam].append((max(0.0, start), start + duration))
    return [sorted(per_family[fam]) for fam in fab.tool_family]


# ----------------------------------------------------------------- the plan


def build_pm_plan(fab: Fab, horizon: float, *, shift_sec: float = 0.0) -> PmPlan:
    """Staggered per-tool PM calendar for every family with a PM calendar."""
    calendars: dict[int, list[tuple[str, float, float, float]]] = {}
    for fam, first, interval, duration, name in fab.pm:
        if interval > 0 and duration > 0:
            calendars.setdefault(fam, []).append((name, first, interval, duration))
    windows: list[PmWindow] = []
    stats: dict[int, FamilyPm] = {}
    for fam in sorted(calendars):
        item = fab.families[fam]
        cals = calendars[fam]
        tools = list(range(item.tool0, item.tool0 + item.tools))
        n = len(tools)
        load = n * sum(duration / interval for _name, _f, interval, duration in cals)
        lanes = max(1, math.ceil(load - 1e-9))
        jobs: list[tuple[float, int, int, int, float, float, str]] = []
        for order, (name, first, interval, duration) in enumerate(cals):
            for k, start in published_occurrences(first, interval, duration, horizon, shift_sec):
                for pos in range(n):
                    stagger = (n - 1 - pos) * interval / n
                    nominal = start if n == 1 else max(0.0, start - stagger)
                    jobs.append((nominal, order, pos, k, start, duration, name))
        jobs.sort(key=lambda job: (job[0], job[1], job[2]))
        placed: list[tuple[float, float, int]] = []  # (start, end, tool), sorted by start
        busy: dict[int, list[tuple[float, float]]] = {tool: [] for tool in tools}
        fam_windows: list[PmWindow] = []
        interval_of = {name: interval for name, _f, interval, _d in cals}
        for nominal, _order, pos, k, published, duration, name in jobs:
            tool = tools[pos]
            if n == 1:
                begin = max(0.0, published)
            else:
                begin = _earliest(placed, busy[tool], nominal, duration, lanes)
            end = published + duration if n == 1 else begin + duration
            insort(placed, (begin, end, tool))
            insort(busy[tool], (begin, end))
            fam_windows.append(
                PmWindow(
                    tool=tool,
                    family=fam,
                    calendar=name,
                    occurrence=k,
                    published_sec=published,
                    nominal_sec=nominal,
                    start_sec=begin,
                    end_sec=end,
                    interval_sec=interval_of[name],
                )
            )
        windows.extend(fam_windows)
        before_spans = _merge(
            [
                (max(0.0, start), start + duration)
                for _name, first, interval, duration in cals
                for _k, start in published_occurrences(
                    first, interval, duration, horizon, shift_sec
                )
            ]
        )
        max_before = n if before_spans else 0
        max_after = _peak_tools([(w.start_sec, w.end_sec, w.tool) for w in fam_windows])
        delays = [w.delay_sec for w in fam_windows]
        stats[fam] = FamilyPm(
            family=item.name,
            group=item.group,
            tools=n,
            calendars=tuple(
                (name, first / 3600.0, interval / 3600.0, duration / 3600.0)
                for name, first, interval, duration in cals
            ),
            load=load,
            lanes=lanes,
            overlap_required=lanes > 1,
            overfull_calendars=tuple(
                name for name, _f, interval, duration in cals if n * duration > interval
            ),
            count_before=n
            * sum(
                len(published_occurrences(first, interval, duration, horizon, shift_sec))
                for _name, first, interval, duration in cals
            ),
            count_after=len(fam_windows),
            max_in_pm_before=max_before,
            max_in_pm_after=max_after,
            min_available_before=n - max_before,
            min_available_after=n - max_after,
            max_delay_h=max(delays, default=0.0) / 3600.0,
            mean_delay_h=(sum(delays) / len(delays) / 3600.0) if delays else 0.0,
        )
    return PmPlan(
        horizon=horizon,
        shift_sec=shift_sec,
        tool_count=len(fab.tool_family),
        windows=sorted(windows, key=lambda w: (w.tool, w.start_sec)),
        families=stats,
    )


def _earliest(
    placed: list[tuple[float, float, int]],
    own: list[tuple[float, float]],
    nominal: float,
    duration: float,
    lanes: int,
) -> float:
    """Earliest start >= nominal: tool free and < ``lanes`` tools in PM throughout."""
    begin = nominal
    while True:
        end = begin + duration
        clash = [hi for lo, hi in own if lo < end - _EPS and hi > begin + _EPS]
        if not clash:
            # Placed windows overlapping [begin, end): any start before end.
            upto = bisect_left(placed, (end - _EPS, -math.inf, -1))
            over = [(lo, hi) for lo, hi, _tool in placed[:upto] if hi > begin + _EPS]
            if _peak_overlap(over, begin, end) < lanes:
                return begin
            clash = [hi for _lo, hi in over]
        begin = min(hi for hi in clash if hi > begin + _EPS)


def _peak_overlap(spans: list[tuple[float, float]], begin: float, end: float) -> int:
    """Most of ``spans`` active at once inside ``[begin, end)``."""
    marks: list[tuple[float, int]] = []
    for lo, hi in spans:
        marks.append((max(lo, begin), 1))
        marks.append((min(hi, end), -1))
    marks.sort(key=lambda mark: (mark[0], mark[1]))
    level = peak = 0
    for _t, step in marks:
        level += step
        peak = max(peak, level)
    return peak


def _peak_tools(spans: list[tuple[float, float, int]]) -> int:
    """Most distinct tools in PM at once (a tool's own windows merged first)."""
    by_tool: dict[int, list[tuple[float, float]]] = {}
    for lo, hi, tool in spans:
        by_tool.setdefault(tool, []).append((lo, hi))
    merged = [span for items in by_tool.values() for span in _merge(items)]
    marks = sorted([(lo, 1) for lo, _hi in merged] + [(hi, -1) for _lo, hi in merged])
    level = peak = 0
    for _t, step in marks:
        level += step
        peak = max(peak, level)
    return peak


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


# ----------------------------------------------------------------- flexible

# Fab rule from the fab owner, not a dataset field (SMT2020 publishes no PM
# tolerance): a PM may move up to one day either side of its planned start.
PM_WINDOW_SEC = 24 * 3600.0
# Scheduling tick of the dispatch layer (s); a PM is forced on the last tick
# that still starts it by its latest start.
PM_TICK_SEC = 300.0

PmAction = Literal["start_now", "defer", "force"]


@dataclass(frozen=True)
class FlexPm:
    """One planned PM with its allowed start window."""

    window: PmWindow
    earliest_sec: float
    latest_sec: float

    @property
    def tool(self) -> int:
        return self.window.tool

    @property
    def planned_sec(self) -> float:
        return self.window.start_sec

    @property
    def duration_sec(self) -> float:
        return self.window.end_sec - self.window.start_sec


def flexible_windows(plan: PmPlan, window_sec: float = PM_WINDOW_SEC) -> dict[int, list[FlexPm]]:
    """Allowed window per planned PM, per tool in planned order (module docstring)."""
    found: dict[int, list[FlexPm]] = {}
    by_tool: dict[int, list[PmWindow]] = {}
    for item in plan.windows:
        by_tool.setdefault(item.tool, []).append(item)
    for tool, items in sorted(by_tool.items()):
        items.sort(key=lambda w: (w.start_sec, w.end_sec))
        out: list[FlexPm] = []
        for pos, item in enumerate(items):
            slack = window_sec
            planned = item.start_sec
            earliest = max(0.0, planned - slack)
            if pos > 0:
                earliest = max(earliest, items[pos - 1].end_sec)
            latest = planned + slack
            if pos + 1 < len(items):
                latest = min(latest, items[pos + 1].start_sec - (item.end_sec - planned))
            out.append(
                FlexPm(
                    window=item,
                    earliest_sec=min(earliest, planned),
                    latest_sec=max(latest, planned),
                )
            )
        found[tool] = out
    return found


def queue_work_sec(fab: Fab, steps: Iterable[tuple[int, int]]) -> float:
    """Standard work seconds of queued lots ``(route index, step index)``.

    Master-data step time per lot; a batch step counts its process time over
    the full batch size (``batch_max``), i.e. one lot's share of a full batch.
    """
    total = 0.0
    for route_i, step in steps:
        route = fab.routes[route_i]
        size = route.batch_max[step]
        total += route.cycle[step] / size if size > 1 else route.cycle[step]
    return total


@dataclass
class ToolStatus:
    """What the scheduling layer knows about one tool at a tick."""

    busy_until: float = 0.0  # end of the running lot / batch (<= now: idle)
    down_until: float = 0.0  # unscheduled down (<= now: up)


@dataclass(frozen=True)
class CommittedPm:
    pm: FlexPm
    start_sec: float
    end_sec: float
    action: PmAction
    reason: str
    over_cap: bool = False

    @property
    def shift_sec(self) -> float:
        return self.start_sec - self.pm.planned_sec


@dataclass(frozen=True)
class PmDecision:
    tool: int
    family: int
    now: float
    action: PmAction
    reason: str
    pm: FlexPm | None = None
    start_sec: float | None = None  # set for start_now / force
    queue_sec: float = 0.0
    absorb_sec: float = 0.0
    in_pm: int = 0
    lanes: int = 1


@dataclass
class PmState:
    """Runtime PM state the scheduling layer keeps and updates every tick."""

    pms: dict[int, list[FlexPm]]
    tool_family: dict[int, int]
    family_tools: dict[int, list[int]]
    lanes: dict[int, int]
    window_sec: float = PM_WINDOW_SEC
    tick_sec: float = PM_TICK_SEC
    status: dict[int, ToolStatus] = field(default_factory=dict)
    queue_sec: dict[int, float] = field(default_factory=dict)
    committed: dict[int, list[CommittedPm]] = field(default_factory=dict)
    log: list[PmDecision] = field(default_factory=list)
    samples: dict[int, list[tuple[float, bool]]] = field(default_factory=dict)
    _head: dict[int, int] = field(default_factory=dict, repr=False)
    _ref: dict[int, float] = field(default_factory=dict, repr=False)

    @classmethod
    def build(
        cls,
        fab: Fab,
        plan: PmPlan,
        *,
        window_sec: float = PM_WINDOW_SEC,
        tick_sec: float = PM_TICK_SEC,
    ) -> PmState:
        pms = flexible_windows(plan, window_sec)
        family_tools: dict[int, list[int]] = {}
        tool_family: dict[int, int] = {}
        for fam in plan.families:
            item = fab.families[fam]
            family_tools[fam] = list(range(item.tool0, item.tool0 + item.tools))
            for tool in family_tools[fam]:
                tool_family[tool] = fam
        return cls(
            pms=pms,
            tool_family=tool_family,
            family_tools=family_tools,
            lanes={fam: item.lanes for fam, item in plan.families.items()},
            window_sec=window_sec,
            tick_sec=tick_sec,
        )

    # --- inputs from the scheduling layer
    def set_tool(self, tool: int, *, busy_until: float = 0.0, down_until: float = 0.0) -> None:
        self.status[tool] = ToolStatus(busy_until=busy_until, down_until=down_until)

    def set_queue(self, family: int, work_sec: float, now: float) -> None:
        """Family eligible queue (standard work s); also sampled for the KPIs.

        A sample is a high-queue period when the queue exceeds what all but one
        of the family's tools can process during its shortest PM: the defer
        test with every tool up and idle.
        """
        self.queue_sec[family] = work_sec
        tools = self.family_tools.get(family, [])
        if family not in self._ref:
            durations = [p.duration_sec for t in tools for p in self.pms.get(t, [])]
            self._ref[family] = min(durations, default=0.0)
        limit = (max(1, len(tools)) - 1) * self._ref[family]
        self.samples.setdefault(family, []).append((now, work_sec > limit + _EPS))

    # --- queries
    def head(self, tool: int) -> FlexPm | None:
        """The tool's next PM not yet committed (planned order)."""
        items = self.pms.get(tool, [])
        pos = self._head.get(tool, 0)
        return items[pos] if pos < len(items) else None

    def last_committed(self, tool: int) -> CommittedPm | None:
        items = self.committed.get(tool)
        return items[-1] if items else None

    def free_at(self, tool: int, now: float) -> float:
        """When the tool is free of its lot, a down and its last committed PM."""
        st = self.status.get(tool, ToolStatus())
        last = self.last_committed(tool)
        return max(now, st.busy_until, st.down_until, last.end_sec if last else 0.0)

    def in_pm(self, family: int, now: float, *, exclude: int = -1) -> int:
        """Tools of the family holding a committed PM that has not ended."""
        count = 0
        for tool in self.family_tools.get(family, []):
            last = self.last_committed(tool)
            if tool != exclude and last is not None and last.end_sec > now + _EPS:
                count += 1
        return count

    def absorb_sec(self, family: int, tool: int, now: float, duration: float) -> float:
        """Work the family's other tools can do in ``[now, now + duration)``."""
        total = 0.0
        for other in self.family_tools.get(family, []):
            if other != tool:
                total += max(0.0, now + duration - self.free_at(other, now))
        return total

    def may_start_lot(self, tool: int, now: float, proc_sec: float) -> bool:
        """Dispatch guard: no lot into a committed PM or past the next latest start."""
        last = self.last_committed(tool)
        if last is not None and last.end_sec > now + _EPS:
            return False
        nxt = self.head(tool)
        return nxt is None or now + proc_sec <= nxt.latest_sec + _EPS

    def pending(self) -> list[FlexPm]:
        return [p for tool, items in self.pms.items() for p in items[self._head.get(tool, 0) :]]

    def _commit(self, pm: FlexPm, start: float, action: PmAction, reason: str, cap: bool) -> None:
        self.committed.setdefault(pm.tool, []).append(
            CommittedPm(pm, start, start + pm.duration_sec, action, reason, cap)
        )
        self._head[pm.tool] = self._head.get(pm.tool, 0) + 1

    # --- KPIs
    def kpis(self) -> dict[str, Any]:
        done = [c for items in self.committed.values() for c in items]
        late = [c.shift_sec / 3600.0 for c in done if c.shift_sec > _EPS]
        early = [-c.shift_sec / 3600.0 for c in done if c.shift_sec < -_EPS]
        high = self._high_spans()
        planned_h = actual_h = 0.0
        for c in done:
            spans = high.get(self.tool_family[c.pm.tool], [])
            planned_h += _overlap(spans, c.pm.planned_sec, c.pm.window.end_sec)
            actual_h += _overlap(spans, c.start_sec, c.end_sec)
        return {
            "pm_planned": sum(len(items) for items in self.pms.values()),
            "pm_committed": len(done),
            "pm_pending": len(self.pending()),
            "deferred": len(late),
            "deferral_mean_h": sum(late) / len(late) if late else 0.0,
            "deferral_max_h": max(late, default=0.0),
            "advanced": len(early),
            "advance_mean_h": sum(early) / len(early) if early else 0.0,
            "advance_max_h": max(early, default=0.0),
            "forced": sum(1 for c in done if c.action == "force"),
            "forced_over_cap": sum(1 for c in done if c.over_cap),
            "pm_h_high_queue_planned": planned_h / 3600.0,
            "pm_h_high_queue_actual": actual_h / 3600.0,
        }

    def _high_spans(self) -> dict[int, list[tuple[float, float]]]:
        found: dict[int, list[tuple[float, float]]] = {}
        for fam, items in self.samples.items():
            spans: list[tuple[float, float]] = []
            for pos, (t, high) in enumerate(items):
                end = items[pos + 1][0] if pos + 1 < len(items) else t + self.tick_sec
                if high and end > t:
                    spans.append((t, end))
            found[fam] = _merge(spans)
        return found


def pm_decision(tool: int, now: float, state: PmState) -> PmDecision:
    """start_now / defer / force for the tool's next PM at this tick (logged).

    start_now and force commit the PM (``state.committed``). Decisions outside
    the PM's window (before ``earliest``, no PM left, previous PM still on) are
    returned as defer but not logged: they are not decisions about a PM.
    """
    fam = state.tool_family.get(tool, -1)
    lanes = state.lanes.get(fam, 1)
    pm = state.head(tool)
    if pm is None:
        return PmDecision(tool, fam, now, "defer", "no_pending_pm", lanes=lanes)
    last = state.last_committed(tool)
    if last is not None and last.end_sec > now + _EPS:
        return PmDecision(tool, fam, now, "defer", "previous_pm_on", pm, lanes=lanes)
    if now < pm.earliest_sec - _EPS:
        return PmDecision(tool, fam, now, "defer", "before_window", pm, lanes=lanes)
    st = state.status.get(tool, ToolStatus())
    queue = state.queue_sec.get(fam, 0.0)
    absorb = state.absorb_sec(fam, tool, now, pm.duration_sec)
    others = state.in_pm(fam, now, exclude=tool)

    def done(action: PmAction, reason: str, start: float | None = None) -> PmDecision:
        out = PmDecision(tool, fam, now, action, reason, pm, start, queue, absorb, others, lanes)
        state.log.append(out)
        return out

    at_latest = now + state.tick_sec > pm.latest_sec + _EPS or now >= pm.latest_sec - _EPS
    if st.down_until > now + _EPS:
        hold = "tool_down"
    elif st.busy_until > now + _EPS:
        hold = "tool_busy"
    elif others >= lanes:
        hold = f"concurrency_cap({others}/{lanes})"
    elif queue > absorb + _EPS:
        hold = f"queue_heavy({queue / 3600:.2f}h>{absorb / 3600:.2f}h)"
    else:
        when = "early" if now < pm.planned_sec - _EPS else "on_time"
        if now > pm.planned_sec + _EPS:
            when = "late"
        why = ("no_queue" if queue <= _EPS else "queue_absorbed") + "," + when
        state._commit(pm, now, "start_now", why, False)
        return done("start_now", why, now)
    if not at_latest:
        return done("defer", hold)
    start = state.free_at(tool, now)
    cap = state.in_pm(fam, start, exclude=tool) >= lanes
    why = f"latest_start,{hold}"
    state._commit(pm, start, "force", why, cap)
    return done("force", why, start)


def _overlap(spans: list[tuple[float, float]], begin: float, end: float) -> float:
    return sum(max(0.0, min(hi, end) - max(lo, begin)) for lo, hi in spans)


def markdown_table(plan: PmPlan) -> str:
    """Per-family before/after table (dataset calendar vs this plan)."""
    head = (
        "| family | tools | calendars I/D h | load | lanes | flag "
        "| max in PM before→after | min available before→after | PMs | max/mean delay h |"
    )
    lines = [head, "|" + "---|" * 10]
    for item in sorted(plan.families.values(), key=lambda row: (row.group, row.family)):
        cals = ", ".join(
            f"{name.rsplit('_', 1)[-1]} {interval:g}/{dur:.2f}"
            for name, _f, interval, dur in item.calendars
        )
        flag = "overlap" if item.overlap_required else ""
        if item.overfull_calendars:
            flag += (
                " (" + ",".join(c.rsplit("_", 1)[-1] for c in item.overfull_calendars) + " n·D>I)"
            )
        lines.append(
            f"| {item.family} | {item.tools} | {cals} | {item.load:.2f} | {item.lanes} | {flag} "
            f"| {item.max_in_pm_before}→{item.max_in_pm_after} "
            f"| {item.min_available_before} (0%)→{item.min_available_after} "
            f"({100.0 * item.min_available_after / item.tools:.0f}%) "
            f"| {item.count_before}→{item.count_after} "
            f"| {item.max_delay_h:.2f}/{item.mean_delay_h:.2f} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    from resilimes.smt.fab import load_fab

    print(markdown_table(build_pm_plan(load_fab(), 56 * 86400.0)))
