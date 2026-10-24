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
"""

from __future__ import annotations

import math
from bisect import bisect_left, insort
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

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
