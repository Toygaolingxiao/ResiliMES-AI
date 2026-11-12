"""The run record: lot visits and tool states of one recorded run.

This is the read face the explain layer uses. It holds plain data and the
queries on it; it does not import the twin. The twin side fills it in
(``resilimes.evidence.timeline.build_timeline``).

A *visit* is one queue entry of one lot at one step: ready -> start -> leave.
"""

from __future__ import annotations

import bisect
from dataclasses import asdict, dataclass, field
from typing import Any

# The fab description the record refers to. On the twin side this is
# ``resilimes.smt.fab.Fab``; the record only reads ``families``, ``routes``,
# ``lot_route``, ``lot_due``, ``lot_id``, ``lot_product`` and ``lot_class``.
FabView = Any

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
    fab: FabView
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


# ---- dispatch-time decision records ---------------------------------------------------
# Written by the simulator at the decision moment (``resilimes.smt.dispatch_log``).
REASON_QTIME_GATE = "qtime_gate"
REASON_BATCH_WAIT = "batch_wait"
REASON_PM_AVOIDANCE = "pm_avoidance"

DISPATCH_REASONS = (REASON_QTIME_GATE, REASON_BATCH_WAIT, REASON_PM_AVOIDANCE)


@dataclass
class DispatchRecord:
    """One deliberate-gap decision, recorded when it was made."""

    reason: str  # one of DISPATCH_REASONS
    lot: int | None  # head / refused lot (index into fab.lot_id)
    lots: tuple[int, ...]  # every lot held by this decision
    step: int  # the step the lot(s) were held at
    tool: int  # the tool whose start was refused / held (-1 if not tool-bound)
    family: int
    t: float  # decision time, seconds after the snapshot
    wake: float | None = None  # when the decision is next re-evaluated, if known
    evidence: dict[str, Any] = field(default_factory=dict)
    count: int = 1  # coalesced re-evaluations of this same decision

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["lots"] = list(self.lots)
        return out


# ---- one recorded run -------------------------------------------------------------------
@dataclass
class RunRecord:
    """What the explain layer reads about one run. No simulator objects.

    ``class_tiers`` maps an order class to its dispatch tier. The twin side
    fills it from the priority rules (``resilimes.kernel.score``); classes not
    in the map get ``default_class_tier``.
    """

    fab: FabView
    seed: int
    horizon: float
    policy: str
    downs: list[list[tuple[float, float]]]
    pm: list[list[tuple[float, float]]]
    timeline: Timeline
    label: str = "baseline"
    notes: dict[str, Any] = field(default_factory=dict)
    class_tiers: dict[str, int] = field(default_factory=dict)
    default_class_tier: int = 2

    def class_tier(self, order_class: str) -> int:
        return self.class_tiers.get(order_class, self.default_class_tier)
