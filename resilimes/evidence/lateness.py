"""Why is this lot late? An exact split of its time in the fab.

For a lot due inside the horizon that finished after its due time (or is
still in the fab at the horizon), let ``C`` be the finish (or the horizon)
and ``D`` the due time, both in seconds after the snapshot. Two splits are
returned, and each sums *exactly* (float tolerance 1e-6 s) to its total:

* ``history``: every second of ``[0, C]`` goes to one bucket, so
  ``sum(history) == C`` and ``lateness == sum(history) - D``. ``D`` is the
  time the plan allowed (``allowance``).
* ``overrun``: the same buckets over ``[max(0, D), C]`` -- what the lot was
  doing while it was late -- plus ``late_at_snapshot`` when ``D < 0``. So
  ``sum(overrun) == lateness`` with no allowance term.

Buckets. Processing and setup come from the start events and setup rows;
transport and holds from the gaps between visits. A queue wait is cut at
every state change of the family's tools. On a piece where at least one
tool is idle, the whole piece is ``batch_wait`` (batch step), ``pm`` (an idle
tool would cross its next PM) or ``dispatch_other`` (dedication pin, gate,
wake latency). On a piece with no idle tool, the piece is shared by tool
count: down tools -> ``down``, PM -> ``pm``, tools held for a Q-time lot ->
``qtime``, busy tools -> ``lots_ahead``, except a busy tool that is running
a lot an explicit decision put ahead of this one -> ``qtime`` (rule-based
Q-time override) or ``ai_decision`` (an ``ai_decision`` event; none on main).
Steps repeated after a Q-time re-clean, and Q-time holds, are ``qtime``.
Work lost when a tool broke mid-process, and the rework hold, are ``down``.
"""

from __future__ import annotations

import itertools
from typing import Any

from resilimes.evidence.timeline import BUSY, DOWN, IDLE, PM, RESERVED, Timeline, Visit

BUCKETS = (
    "processing",
    "setup",
    "transport",
    "down",
    "pm",
    "batch_wait",
    "lots_ahead",
    "qtime",
    "ai_decision",
    "dispatch_other",
    "release_hold",
)
GAP_BUCKET = {
    "transport": "transport",
    "rework_hold": "down",
    "qtime_hold": "qtime",
    "release_hold": "release_hold",
}
TOLERANCE_SEC = 1e-6


def late_lots(tl: Timeline) -> list[int]:
    """Lots due inside the horizon that finished late or are unfinished, by lateness."""
    rows: list[tuple[float, int]] = []
    for lot, due in enumerate(tl.fab.lot_due):
        if due > tl.horizon:
            continue
        end = tl.completed.get(lot, tl.horizon)
        if end > due:
            rows.append((end - due, lot))
    rows.sort(reverse=True)
    return [lot for _late, lot in rows]


def decompose(tl: Timeline, lot: int) -> dict[str, Any]:
    fab = tl.fab
    due = float(fab.lot_due[lot])
    finished = lot in tl.completed
    end = tl.completed.get(lot, tl.horizon)
    lateness = end - due
    history = attribute(tl, lot, 0.0, end)
    overrun = attribute(tl, lot, max(0.0, due), end)
    if due < 0:
        overrun["late_at_snapshot"] = -due
    hist_sum = sum(history.values())
    over_sum = sum(overrun.values())
    return {
        "lot": lot,
        "lot_id": fab.lot_id[lot],
        "product": fab.lot_product[lot],
        "lot_class": fab.lot_class[lot],
        "due_sec": due,
        "end_sec": end,
        "finished": finished,
        "lateness_sec": lateness,
        "allowance_sec": due,
        "history_sec": history,
        "overrun_sec": overrun,
        "history_residual_sec": hist_sum - end,
        "overrun_residual_sec": over_sum - lateness,
        "exact": abs(hist_sum - end) <= TOLERANCE_SEC and abs(over_sum - lateness) <= TOLERANCE_SEC,
        "visits": len(tl.visits.get(lot, [])),
    }


def attribute(tl: Timeline, lot: int, lo: float, hi: float) -> dict[str, float]:
    """Bucket seconds of the lot's life inside ``[lo, hi]``."""
    out = dict.fromkeys(BUCKETS, 0.0)
    if hi <= lo:
        return out
    for gap in tl.gaps.get(lot, []):
        left, right = max(lo, gap.start), min(hi, gap.end)
        if right > left:
            out[GAP_BUCKET[gap.kind]] += right - left
    for visit in tl.visits.get(lot, []):
        began = visit.start
        left_at = visit.leave if visit.leave is not None else hi
        wait_end = began if began is not None else left_at
        _wait(tl, visit, max(lo, visit.ready), min(hi, wait_end), out)
        if began is None:
            continue
        p_left, p_right = max(lo, began), min(hi, left_at)
        if p_right <= p_left:
            continue
        if visit.redo:
            out["qtime"] += p_right - p_left
        elif visit.outcome == "rework":
            out["down"] += p_right - p_left
        else:
            setup_end = began + min(visit.setup_sec, left_at - began)
            s_left, s_right = p_left, min(p_right, setup_end)
            setup = max(0.0, s_right - s_left)
            out["setup"] += setup
            out["processing"] += (p_right - p_left) - setup
    return out


def visit_waits(tl: Timeline, lot: int, lo: float, hi: float) -> list[dict[str, Any]]:
    """Queue wait of each visit inside ``[lo, hi]``, split into the same buckets."""
    rows: list[dict[str, Any]] = []
    for visit in tl.visits.get(lot, []):
        left_at = visit.leave if visit.leave is not None else hi
        wait_end = visit.start if visit.start is not None else left_at
        out = dict.fromkeys(BUCKETS, 0.0)
        left, right = max(lo, visit.ready), min(hi, wait_end)
        _wait(tl, visit, left, right, out)
        total = sum(out.values())
        if total > 0:
            rows.append(
                {"visit": visit, "wait_sec": total, "buckets": out, "window": (left, right)}
            )
    return rows


def _wait(tl: Timeline, visit: Visit, left: float, right: float, out: dict[str, float]) -> None:
    if right <= left:
        return
    if visit.redo:
        out["qtime"] += right - left
        return
    fab = tl.fab
    tools = list(tl.family_tools(visit.family))
    route = fab.routes[fab.lot_route[visit.lot]]
    batch = route.batch_max[visit.step] > 0
    cycle = route.cycle[visit.step]
    displaced = [item for item in tl.displaced.get(visit.lot, []) if item.until > left]
    cuts = {left, right}
    for tool in tools:
        cuts.update(tl.tool_edges(tool, left, right))
    for item in displaced:
        for edge in (item.at, item.until):
            if left < edge < right:
                cuts.add(edge)
    ordered = sorted(cuts)
    count = len(tools) or 1
    for a, b in itertools.pairwise(ordered):
        span = b - a
        if span <= 0:
            continue
        mid = (a + b) / 2.0
        states = [tl.tool_state(tool, mid) for tool in tools]
        if IDLE in states:
            if batch:
                out["batch_wait"] += span
            elif any(
                state == IDLE and _pm_soon(tl, tool, mid, cycle)
                for tool, state in zip(tools, states, strict=True)
            ):
                out["pm"] += span
            else:
                out["dispatch_other"] += span
            continue
        share = span / count
        for tool, state in zip(tools, states, strict=True):
            if state == DOWN:
                out["down"] += share
            elif state == PM:
                out["pm"] += share
            elif state == RESERVED:
                out["qtime"] += share
            elif state == BUSY:
                source = next(
                    (d.source for d in displaced if d.tool == tool and d.at <= mid < d.until),
                    None,
                )
                if source == "ai_decision":
                    out["ai_decision"] += share
                elif source == "qtime_override":
                    out["qtime"] += share
                else:
                    out["lots_ahead"] += share
    if not tools:
        out["dispatch_other"] += right - left


def _pm_soon(tl: Timeline, tool: int, moment: float, cycle: float) -> bool:
    return any(moment < start < moment + cycle for start, _end in tl.pm[tool])


def rounded_minutes(values: dict[str, float]) -> dict[str, float]:
    """Minutes to 0.1, largest remainder, so the shown parts add up to the shown total."""
    tenths = {key: value / 6.0 for key, value in values.items()}
    total = round(sum(tenths.values()))
    floors = {key: int(value // 1) for key, value in tenths.items()}
    left = total - sum(floors.values())
    order = sorted(tenths, key=lambda key: tenths[key] - floors[key], reverse=True)
    for key in order[: max(0, left)]:
        floors[key] += 1
    return {key: floors[key] / 10.0 for key in values}
