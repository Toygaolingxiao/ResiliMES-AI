"""Twin-side adapter: build the run record from one simulator run.

Needs ``run_policy(..., record=True, lot_log=True)``. The rows come straight
from the simulator (``lot_log["ready"]``, ``events``), so nothing here is
estimated; the only reconstruction is the ordering of the two streams, which
uses the ``n_events`` index each lot-log row carries.

The record types live in ``resilimes.explain.record`` and are re-exported here
for old imports.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from resilimes.explain.record import (
    BUSY,
    DOWN,
    IDLE,
    PM,
    RESERVED,
    Displacement,
    FabView,
    Gap,
    Timeline,
    Visit,
    _covers_sorted,
    _merge,
)
from resilimes.smt.fab import Fab
from resilimes.smt.simulate import RunResult

__all__ = [
    "BUSY",
    "DOWN",
    "IDLE",
    "PM",
    "RESERVED",
    "Displacement",
    "FabView",
    "Gap",
    "Timeline",
    "Visit",
    "_covers_sorted",
    "_merge",
    "build_timeline",
]


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
    for family, fam_visits in timeline.by_family.items():
        fam_visits.sort(key=lambda item: item.ready)
        timeline._ready_index[family] = [item.ready for item in fam_visits]
    for moment, tool, lot in overrides:
        until = _busy_end(busy[tool], moment, horizon)
        timeline.displaced.setdefault(lot, []).append(
            Displacement(lot=lot, tool=tool, at=moment, until=until, source="qtime_override")
        )
    for decision in ai_events:
        tool = int(decision.get("tool", -1))
        if tool < 0:
            continue
        until = _busy_end(busy[tool], float(decision["t"]), horizon)
        for lot in decision.get("displaced", []) or []:
            timeline.displaced.setdefault(int(lot), []).append(
                Displacement(
                    lot=int(lot),
                    tool=tool,
                    at=float(decision["t"]),
                    until=until,
                    source="ai_decision",
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
