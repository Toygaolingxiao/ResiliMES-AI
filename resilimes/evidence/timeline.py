"""Lot visits and tool states rebuilt from one recorded run.

Needs ``run_policy(..., record=True, lot_log=True)``. A *visit* is one queue
entry of one lot at one step: ready -> start -> leave. The rows come straight
from the simulator (``lot_log["ready"]``, ``events``), so nothing here is
estimated; the only reconstruction is the ordering of the two streams, which
uses the ``n_events`` index each lot-log row carries.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from resilimes.smt.fab import Fab
from resilimes.smt.simulate import RunResult

DOWN, PM, BUSY, RESERVED, IDLE = "down", "pm", "busy", "reserved", "idle"


@dataclass
class Visit:
    lot: int
    step: int
    family: int
    ready: float
    start: float | None = None
    tool: int = -1
    leave: float | None = None
    outcome: str = "open"  # done, rework, qhold, reclean, superseded, open
    setup_sec: float = 0.0
    batch_lots: int = 0
    reason: str = ""
    redo: bool = False  # a step repeated after a Q-time re-clean


@dataclass
class Gap:
    """Time a lot spends between two visits (or before the first one)."""

    lot: int
    start: float
    end: float
    kind: str  # transport, rework_hold, qtime_hold, release_hold


@dataclass
class Displacement:
    """A lot passed over by an explicit decision (rule override or AI)."""

    lot: int
    tool: int
    at: float
    until: float
    source: str  # qtime_override or ai_decision


@dataclass
class Timeline:
    fab: Fab
    horizon: float
    downs: list[list[tuple[float, float]]]
    pm: list[list[tuple[float, float]]]
    visits: dict[int, list[Visit]] = field(default_factory=dict)
    gaps: dict[int, list[Gap]] = field(default_factory=dict)
    busy: list[list[tuple[float, float]]] = field(default_factory=list)
    reserved: list[list[tuple[float, float]]] = field(default_factory=list)
    displaced: dict[int, list[Displacement]] = field(default_factory=dict)
    ai_events: list[dict[str, Any]] = field(default_factory=list)
    completed: dict[int, float] = field(default_factory=dict)
    by_family: dict[int, list[Visit]] = field(default_factory=dict)
    setups: list[tuple[float, int, float]] = field(default_factory=list)  # (t, tool, sec)
    starts: list[tuple[float, int, int]] = field(default_factory=list)  # (t, tool, lots)
    _ready_index: dict[int, list[float]] = field(default_factory=dict)
    _segments: dict[int, tuple[list[float], list[str]]] = field(default_factory=dict)

    # ---- tool state ---------------------------------------------------------------------
    def _segs(self, tool: int) -> tuple[list[float], list[str]]:
        """Disjoint state pieces of one tool: ``edges[i]..edges[i+1]`` is ``states[i]``.

        Down > PM > busy > reserved > idle where they overlap. Covers [0, inf).
        """
        cached = self._segments.get(tool)
        if cached is not None:
            return cached
        layers = (
            (DOWN, _merge(self.downs[tool])),
            (PM, _merge(self.pm[tool])),
            (BUSY, _merge(self.busy[tool])),
            (RESERVED, _merge(self.reserved[tool])),
        )
        cuts = {0.0}
        for _state, spans in layers:
            for left, right in spans:
                cuts.add(max(0.0, left))
                cuts.add(max(0.0, right))
        edges = sorted(cuts)
        states: list[str] = []
        for index, left in enumerate(edges):
            right = edges[index + 1] if index + 1 < len(edges) else left + 1.0
            mid = (left + right) / 2.0
            found = IDLE
            for state, spans in layers:
                if _covers_sorted(spans, mid):
                    found = state
                    break
            states.append(found)
        self._segments[tool] = (edges, states)
        return edges, states

    def tool_state(self, tool: int, moment: float) -> str:
        edges, states = self._segs(tool)
        index = bisect.bisect_right(edges, moment) - 1
        return states[max(0, index)]

    def tool_edges(self, tool: int, start: float, end: float) -> list[float]:
        edges, _states = self._segs(tool)
        return edges[bisect.bisect_right(edges, start) : bisect.bisect_left(edges, end)]

    def state_seconds(self, tool: int, start: float, end: float) -> dict[str, float]:
        """Seconds in each state on [start, end). Down > PM > busy > reserved > idle."""
        out = {DOWN: 0.0, PM: 0.0, BUSY: 0.0, RESERVED: 0.0, IDLE: 0.0}
        if end <= start:
            return out
        edges, states = self._segs(tool)
        index = max(0, bisect.bisect_right(edges, start) - 1)
        cursor = start
        while cursor < end:
            right = edges[index + 1] if index + 1 < len(edges) else end
            right = min(right, end)
            out[states[index]] += right - cursor
            cursor = right
            index += 1
        return out

    def family_tools(self, family: int) -> range:
        fam = self.fab.families[family]
        return range(fam.tool0, fam.tool0 + fam.tools)

    # ---- queue ----------------------------------------------------------------------------
    def waiting_at(self, family: int, moment: float) -> int:
        """Lots in the family queue (ready, not started) at ``moment``."""
        rows = self.by_family.get(family, [])
        readies = self._ready_index.get(family, [])
        upto = bisect.bisect_right(readies, moment)
        count = 0
        for visit in rows[:upto]:
            began = visit.start if visit.start is not None else visit.leave
            if began is None or began > moment:
                count += 1
        return count

    def in_process_at(self, family: int, moment: float) -> int:
        rows = self.by_family.get(family, [])
        readies = self._ready_index.get(family, [])
        upto = bisect.bisect_right(readies, moment)
        count = 0
        for visit in rows[:upto]:
            if visit.start is None or visit.start > moment:
                continue
            end = visit.leave if visit.leave is not None else self.horizon
            if moment < end:
                count += 1
        return count


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sorted, disjoint union of the spans."""
    merged: list[tuple[float, float]] = []
    for left, right in sorted(spans):
        if right <= left:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged


def _covers_sorted(spans: list[tuple[float, float]], moment: float) -> bool:
    """``spans`` sorted and disjoint (see ``_merge``)."""
    index = bisect.bisect_right(spans, (moment, float("inf"))) - 1
    return index >= 0 and spans[index][0] <= moment < spans[index][1]


def build_timeline(
    fab: Fab,
    result: RunResult,
    *,
    downs: list[list[tuple[float, float]]],
    pm: list[list[tuple[float, float]]],
    hold_until: dict[int, float] | None = None,
) -> Timeline:
    if "ready" not in result.lot_log:
        raise ValueError("build_timeline needs run_policy(record=True, lot_log=True)")
    horizon = result.horizon_sec
    events = result.events
    stream: dict[int, list[tuple[tuple[int, int], tuple[Any, ...]]]] = defaultdict(list)
    for row in result.lot_log["ready"]:
        stream[row[1]].append(((row[3], -1), ("ready", *row)))
    setup_at: dict[int, float] = {row[3]: row[2] for row in result.lot_log.get("setup", [])}
    busy: list[list[tuple[float, float]]] = [[] for _ in fab.tool_name]
    reserved: list[list[tuple[float, float]]] = [[] for _ in fab.tool_name]
    open_busy: dict[int, tuple[float, int]] = {}
    open_res: dict[int, float] = {}
    overrides: list[tuple[float, int, int]] = []
    starts: list[tuple[float, int, int]] = []
    ai_events: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        kind = event[0]
        if kind == "start":
            _, moment, tool, lots, _steps, finish, _reason, _chosen = event
            open_busy[tool] = (moment, index)
            busy[tool].append((moment, finish))
            starts.append((moment, tool, len(lots)))
            for lot in lots:
                stream[lot].append(((index, 0), event))
        elif kind in ("end", "reclean", "qhold"):
            stream[event[2]].append(((index, 0), event))
        elif kind == "rework":
            stream[event[3]].append(((index, 0), event))
        elif kind == "interrupt":
            _, moment, tool, _lots = event
            if busy[tool] and busy[tool][-1][1] > moment:
                left = busy[tool][-1][0]
                busy[tool][-1] = (left, moment)
        elif kind == "reserve":
            open_res[event[2]] = event[1]
        elif kind == "release":
            began = open_res.pop(event[2], None)
            if began is not None and event[1] > began:
                reserved[event[2]].append((began, event[1]))
        elif kind == "override":
            # ("override", t, tool, lead, step, plain, remaining, need, displaced)
            overrides.append((event[1], event[2], event[5]))
        elif kind == "ai_decision":
            payload = event[2] if len(event) > 2 and isinstance(event[2], dict) else {}
            ai_events.append({"t": event[1], **payload})
    for tool, began in open_res.items():
        reserved[tool].append((began, horizon))
    for spans in busy:
        spans.sort()
    for spans in reserved:
        spans.sort()
    timeline = Timeline(fab=fab, horizon=horizon, downs=downs, pm=pm, busy=busy, reserved=reserved)
    timeline.ai_events = ai_events
    timeline.starts = starts
    timeline.setups = [(row[0], row[1], row[2]) for row in result.lot_log.get("setup", [])]
    held = hold_until or {}
    for lot in range(len(fab.lot_id)):
        rows = sorted(stream.get(lot, []), key=lambda item: item[0])
        visits, gaps, done_at = _lot_visits(fab, lot, rows, setup_at, held.get(lot))
        timeline.visits[lot] = visits
        timeline.gaps[lot] = gaps
        if done_at is not None:
            timeline.completed[lot] = done_at
    for visit_rows in timeline.visits.values():
        for visit in visit_rows:
            timeline.by_family.setdefault(visit.family, []).append(visit)
    for family, rows in timeline.by_family.items():
        rows.sort(key=lambda item: item.ready)
        timeline._ready_index[family] = [item.ready for item in rows]
    for moment, tool, lot in overrides:
        until = _busy_end(busy[tool], moment, horizon)
        timeline.displaced.setdefault(lot, []).append(
            Displacement(lot=lot, tool=tool, at=moment, until=until, source="qtime_override")
        )
    for row in ai_events:
        tool = int(row.get("tool", -1))
        if tool < 0:
            continue
        until = _busy_end(busy[tool], float(row["t"]), horizon)
        for lot in row.get("displaced", []) or []:
            timeline.displaced.setdefault(int(lot), []).append(
                Displacement(
                    lot=int(lot), tool=tool, at=float(row["t"]), until=until, source="ai_decision"
                )
            )
    return timeline


def _busy_end(spans: list[tuple[float, float]], moment: float, horizon: float) -> float:
    for left, right in spans:
        if left <= moment + 1e-6 and right > moment:
            return right
    return min(horizon, moment)


def _lot_visits(
    fab: Fab,
    lot: int,
    rows: list[tuple[tuple[int, int], tuple[Any, ...]]],
    setup_at: dict[int, float],
    held: float | None,
) -> tuple[list[Visit], list[Gap], float | None]:
    route = fab.routes[fab.lot_route[lot]]
    visits: list[Visit] = []
    gaps: list[Gap] = []
    current: Visit | None = None
    last_leave = 0.0
    last_outcome = "release_hold" if held else "start"
    redo_until = -1
    done_at: float | None = None
    for key, row in rows:
        kind = row[0]
        if kind == "ready":
            _, ready, _lot, step, _n = row
            if current is not None and current.outcome == "open":
                current.leave = ready
                current.outcome = "superseded"
                last_leave = ready
            gap_kind = {
                "done": "transport",
                "reclean": "transport",
                "rework": "rework_hold",
                "qhold": "qtime_hold",
                "release_hold": "release_hold",
            }.get(last_outcome, "transport")
            if ready > last_leave:
                gaps.append(Gap(lot=lot, start=last_leave, end=ready, kind=gap_kind))
            current = Visit(lot=lot, step=step, family=route.family[step], ready=ready)
            current.redo = step < redo_until
            if step >= redo_until:
                redo_until = -1
            visits.append(current)
        elif kind == "start":
            _, moment, tool, lots, _steps, _finish, reason, _chosen = row
            if current is None:
                continue
            current.start = moment
            current.tool = tool
            current.batch_lots = len(lots)
            current.reason = reason
            current.setup_sec = setup_at.get(key[0], 0.0)
        elif kind == "end":
            if current is None:
                continue
            current.leave = row[1]
            current.outcome = "done"
            last_leave, last_outcome = row[1], "done"
        elif kind == "rework":
            if current is None:
                continue
            current.leave = row[1]
            current.outcome = "rework"
            last_leave, last_outcome = row[1], "rework"
        elif kind in ("qhold", "reclean"):
            if current is not None and current.outcome == "open":
                current.leave = row[1]
                current.outcome = kind
            elif row[1] > last_leave:
                # Expired on arrival (no queue entry): the move came first.
                gaps.append(Gap(lot=lot, start=last_leave, end=row[1], kind="transport"))
            last_leave, last_outcome = row[1], kind
            if kind == "reclean":
                redo_until = max(redo_until, row[3])
            redo_until = max(redo_until, row[3])
    if visits and visits[-1].outcome == "done" and _finished(fab, lot, visits[-1].step):
        done_at = visits[-1].leave
    return visits, gaps, done_at


def _finished(fab: Fab, lot: int, step: int) -> bool:
    """True when no measured step follows ``step`` (the lot left the route)."""
    from resilimes.smt.fab import lot_number, measured

    route = fab.routes[fab.lot_route[lot]]
    number = lot_number(fab.lot_id[lot], lot)
    return all(not measured(route, nxt, number) for nxt in range(step + 1, len(route.family)))
