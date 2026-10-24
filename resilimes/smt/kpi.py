"""Daily KPIs, ported from Schedule_Viewer's KPI engine to plain Python.

Each function keeps the definition of one module in Schedule_Viewer
``apps/kpi/kpi_engine/src/kpi_modules/`` (written by the same author), with
the pandas frame replaced by small records read from the SMT2020 replay.
The inputs are the simulator trace only; no Schedule_Viewer data is used.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from resilimes.smt.replay import Replay

DAY_SEC = 86400.0
WAFERS_PER_LOT = 25


@dataclass(frozen=True)
class Op:
    """One lot on one tool for one step (Schedule_Viewer: one schedule row)."""

    lot: str
    kind: str
    tool: str
    start: float
    end: float
    setup: float = 0.0
    recipe: str = ""


@dataclass(frozen=True)
class Run:
    """One tool occupation: a single lot or a whole batch."""

    tool: str
    group: str
    start: float
    end: float
    setup: float
    recipe: str
    lots: int
    cap_lots: int = 0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _var(values: Sequence[float]) -> float:
    """Sample variance, like pandas ``var()`` (ddof=1)."""
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _clip(start: float, end: float, lo: float, hi: float) -> float:
    return max(0.0, min(end, hi) - max(start, lo))


def due_date_adherence(finished: dict[str, float], due: dict[str, float]) -> dict[str, float]:
    """``due_date_adherence.py``: final-step completion against the due date.

    Counts completed lots only. Delay statistics cover the late lots.
    """
    late: list[float] = []
    on_time = 0
    for lot, done in finished.items():
        if done <= due[lot]:
            on_time += 1
        else:
            late.append((done - due[lot]) / 60.0)
    total = on_time + len(late)
    return {
        "completed": total,
        "on_time": on_time,
        "late": len(late),
        "on_time_rate": round(100.0 * on_time / total, 2) if total else 0.0,
        "avg_delay_min": round(_mean(late), 1),
        "max_delay_min": round(max(late), 1) if late else 0.0,
    }


def qtime_achievement(outcomes: Iterable[str]) -> dict[str, float]:
    """``qtime_achievement_rate.py``: share of checked Q-time zones kept.

    Schedule_Viewer reads QTIME_ZONE rows; here a zone is one simulator window
    (end of the origin step to start of the target step). Windows that were
    still open, skipped, or ended by a reclean are not checked.
    """
    met = violated = 0
    for outcome in outcomes:
        if outcome == "met":
            met += 1
        elif outcome == "violated":
            violated += 1
    checked = met + violated
    return {
        "checked": checked,
        "violated": violated,
        "rate": round(100.0 * met / checked, 2) if checked else 100.0,
    }


def lot_step_stats(ops: Iterable[Op]) -> dict[str, Any]:
    """``queue_time_stats.py``, ``lead_time_stats.py`` and ``xfactor_stats.py``.

    Per lot in start order: queue = start - previous end, lead = end -
    previous end, x-factor = lead / processing. The first operation of a lot
    has no previous end and is dropped, as in Schedule_Viewer.
    """
    by_lot: dict[str, list[Op]] = {}
    for op in ops:
        by_lot.setdefault(op.lot, []).append(op)
    queue: dict[str, list[float]] = {}
    lead: dict[str, list[float]] = {}
    xfac: dict[str, list[float]] = {}
    for rows in by_lot.values():
        rows.sort(key=lambda op: op.start)
        for prev, op in pairwise(rows):
            q = max(0.0, op.start - prev.end) / 60.0
            ld = max(0.0, op.end - prev.end) / 60.0
            proc = (op.end - op.start) / 60.0
            for key in (op.kind, "all"):
                queue.setdefault(key, []).append(q)
                lead.setdefault(key, []).append(ld)
                if proc > 0:
                    xfac.setdefault(key, []).append(ld / proc)
    out: dict[str, Any] = {}
    for key in sorted(lead):
        total_lead = sum(lead[key])
        out[key] = {
            "ops": len(lead[key]),
            "queue_mean_min": round(_mean(queue[key]), 1),
            "lead_mean_min": round(_mean(lead[key]), 1),
            "lead_var": round(_var(lead[key]), 1),
            "queue_ratio": round(sum(queue[key]) / total_lead, 3) if total_lead else 0.0,
            "xfactor_mean": round(_mean(xfac.get(key, [])), 2),
            "xfactor_var": round(_var(xfac.get(key, [])), 2),
        }
    return out


def setup_time(runs: Iterable[Run], tools: int, lo: float, hi: float) -> dict[str, float]:
    """``setup_time.py``: setup minutes in the period and setup share of tool time."""
    total = sum(_clip(run.start, run.start + run.setup, lo, hi) for run in runs)
    span = max(1.0, tools * (hi - lo))
    return {"setup_min": round(total / 60.0, 1), "setup_rate": round(100.0 * total / span, 2)}


def equipment_stats(
    runs: Iterable[Run], tool_names: Sequence[str], lo: float, hi: float
) -> dict[str, float]:
    """``equipment_stats.py``: merged busy intervals, idle minutes and wait rate."""
    busy: dict[str, list[tuple[float, float]]] = {name: [] for name in tool_names}
    for run in runs:
        start, end = max(run.start, lo), min(run.end, hi)
        if end > start:
            busy.setdefault(run.tool, []).append((start, end))
    idle_total = 0.0
    for spans in busy.values():
        spans.sort()
        merged = 0.0
        cur_s, cur_e = None, None
        for start, end in spans:
            if cur_e is None or start > cur_e:
                if cur_e is not None and cur_s is not None:
                    merged += cur_e - cur_s
                cur_s, cur_e = start, end
            else:
                cur_e = max(cur_e, end)
        if cur_e is not None and cur_s is not None:
            merged += cur_e - cur_s
        idle_total += (hi - lo) - merged
    span = max(1.0, len(busy) * (hi - lo))
    return {
        "idle_min": round(idle_total / 60.0, 1),
        "wait_rate": round(100.0 * idle_total / span, 2),
    }


def throughput(runs: Iterable[Run], lo: float, hi: float) -> dict[str, float]:
    """``throughput.py``: wafers processed, counted at the end of each run."""
    lots = sum(run.lots for run in runs if lo <= run.end < hi)
    return {"lots": lots, "wafers": lots * WAFERS_PER_LOT}


def batch_formation(runs: Iterable[Run]) -> dict[str, float]:
    """``batch_formation_rate.py``: lots per batch over the tool's lot capacity.

    Only tools whose capacity is more than one lot count, and the fill rate
    is capped at 100 %.
    """
    fills: list[float] = []
    sizes: list[int] = []
    for run in runs:
        if run.cap_lots > 1:
            sizes.append(run.lots)
            fills.append(min(1.0, run.lots / run.cap_lots))
    return {
        "batches": len(fills),
        "avg_lots": round(_mean([float(size) for size in sizes]), 2),
        "fill_rate": round(100.0 * _mean(fills), 2),
    }


def same_recipe_runs(runs: Iterable[Run]) -> dict[str, float]:
    """``same_recipe_consecutive_runs.py``: recipe blocks per tool.

    A block ends when the tool or the recipe changes. Grouping rate is
    1 - blocks / operations; average consecutive runs is the mean block size.
    """
    by_tool: dict[str, list[Run]] = {}
    for run in runs:
        by_tool.setdefault(run.tool, []).append(run)
    blocks: list[int] = []
    total = 0
    for rows in by_tool.values():
        rows.sort(key=lambda run: run.start)
        size = 0
        last = None
        for run in rows:
            total += 1
            if run.recipe != last:
                if size:
                    blocks.append(size)
                size = 0
                last = run.recipe
            size += 1
        if size:
            blocks.append(size)
    return {
        "operations": total,
        "avg_consecutive": round(_mean([float(size) for size in blocks]), 2),
        "grouping_rate": round(100.0 * (1.0 - len(blocks) / total), 2) if total else 0.0,
    }


def load_by_group(
    runs: Iterable[Run], tools_per_group: dict[str, int], lo: float, hi: float
) -> list[dict[str, Any]]:
    """``equipment_load_summary.py``: busy (process + setup) time over tool time, per group."""
    busy: dict[str, float] = dict.fromkeys(tools_per_group, 0.0)
    for run in runs:
        busy[run.group] = busy.get(run.group, 0.0) + _clip(run.start, run.end, lo, hi)
    rows: list[dict[str, Any]] = []
    for group, tools in tools_per_group.items():
        span = max(1.0, tools * (hi - lo))
        rows.append(
            {
                "group": group,
                "tools": tools,
                "busy_h": round(busy[group] / 3600.0, 1),
                "load_rate": round(100.0 * busy[group] / span, 1),
            }
        )
    rows.sort(key=lambda row: -row["load_rate"])
    return rows


def activity(
    runs: Iterable[Run],
    downs: Iterable[tuple[float, float]],
    pms: Iterable[tuple[float, float]],
    tools: int,
    lo: float,
    hi: float,
) -> dict[str, float]:
    """``equipment_activity_analysis.py``: share of tool time by category.

    Schedule_Viewer gives each minute one category by priority (production,
    setup, constraint, planned stop, then waiting). Here the categories are
    production, setup, breakdown, PM and idle, in that priority order.
    Overlaps are rare in the trace, so the shares are summed, not minute-painted.
    """
    prod = setup = 0.0
    for run in runs:
        setup_end = run.start + run.setup
        setup += _clip(run.start, min(setup_end, run.end), lo, hi)
        prod += _clip(min(setup_end, run.end), run.end, lo, hi)
    down = sum(_clip(start, end, lo, hi) for start, end in downs)
    pm = sum(_clip(start, end, lo, hi) for start, end in pms)
    span = max(1.0, tools * (hi - lo))
    idle = max(0.0, span - prod - setup - down - pm)
    return {
        key: round(100.0 * value / span, 2)
        for key, value in (
            ("production", prod),
            ("setup", setup),
            ("down", down),
            ("pm", pm),
            ("idle", idle),
        )
    }


# --------------------------------------------------------------------------- replay adapter


def records(rp: Replay) -> tuple[list[Op], list[Run]]:
    fab = rp.fab
    ops: list[Op] = []
    runs: list[Run] = []
    for piece in rp.pieces:
        tool = fab.tool_name[piece.tool]
        recipe = fab.recipe_name[piece.recipe] if piece.recipe < len(fab.recipe_name) else ""
        route = fab.routes[fab.lot_route[piece.lots[0]]]
        cap = route.batch_max[piece.steps[0]] // WAFERS_PER_LOT if piece.batch else 0
        runs.append(
            Run(
                tool=tool,
                group=fab.families[piece.family].group,
                start=piece.start,
                end=min(piece.end, rp.horizon),
                setup=piece.setup,
                recipe=recipe,
                lots=len(piece.lots),
                cap_lots=cap,
            )
        )
        for lot in piece.lots:
            ops.append(
                Op(
                    lot=fab.lot_id[lot],
                    kind=rp.kind[lot],
                    tool=tool,
                    start=piece.start,
                    end=min(piece.end, rp.horizon),
                    setup=piece.setup,
                    recipe=recipe,
                )
            )
    return ops, runs


def daily(rp: Replay) -> dict[str, Any]:
    """Schedule_Viewer KPI panel for each day of the run and for the whole run."""
    cache = getattr(rp, "_kpis", None)
    if cache is not None:
        return cache
    fab = rp.fab
    ops, runs = records(rp)
    tools = len(fab.tool_name)
    per_group: dict[str, int] = {}
    for item in fab.families:
        per_group[item.group] = per_group.get(item.group, 0) + item.tools
    downs = [window for rows in rp.downs for window in rows]
    pms = [window for rows in rp.pm for window in rows]
    periods: list[tuple[str, float, float]] = []
    start = 0.0
    day = 1
    while start < rp.horizon:
        end = min(rp.horizon, start + DAY_SEC)
        periods.append((f"day{day}", start, end))
        start = end
        day += 1
    periods.append(("all", 0.0, rp.horizon))
    out: dict[str, Any] = {"periods": []}
    for name, lo, hi in periods:
        finished = {
            fab.lot_id[lot]: done for lot, done in enumerate(rp.finished) if lo <= done < hi
        }
        due = {fab.lot_id[lot]: rp.due[lot] for lot in range(len(fab.lot_id))}
        closed = [
            window.outcome
            for window in rp.qwins
            if window.closed is not None and lo <= window.closed < hi
        ]
        in_ops = [op for op in ops if lo <= op.end < hi]
        in_runs = [run for run in runs if run.end > lo and run.start < hi]
        ended = [run for run in runs if lo <= run.end < hi]
        out["periods"].append(
            {
                "name": name,
                "t0": lo,
                "t1": hi,
                "due_date": due_date_adherence(finished, due),
                "qtime": qtime_achievement(closed),
                "lot_steps": lot_step_stats(in_ops),
                "setup": setup_time(in_runs, tools, lo, hi),
                "equipment": equipment_stats(in_runs, fab.tool_name, lo, hi),
                "throughput": throughput(runs, lo, hi),
                "batch": batch_formation(ended),
                "same_recipe": same_recipe_runs(ended),
                "load_by_group": load_by_group(in_runs, per_group, lo, hi),
                "activity": activity(in_runs, downs, pms, tools, lo, hi),
            }
        )
    object.__setattr__(rp, "_kpis", out)
    return out
