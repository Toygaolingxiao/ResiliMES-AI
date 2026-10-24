"""Replay a recorded SMT run and check what every start must satisfy.

Run ``run_policy(..., record=True)`` and pass the result to ``check_trace``.
Checks, one counter each:

- ``family``: the tool belongs to the station family of the lot's current step.
- ``route_order``: a lot starts only its next step, once, and never while it
  is already in process.
- ``tool_overlap``: a tool starts a piece only when it holds nothing.
- ``resume_tool``: an interrupted lot resumes on the tool that held it.
- ``dedication``: a later litho layer runs on the scanner of the first layer.
- ``down_start``: no start inside a breakdown window.
- ``pm_overlap``: no processing window crosses a PM window.
- ``batch``: a multi-lot start is a batch step, one recipe, within capacity.
- ``qtime_recount``: Q-time violations recounted from the trace, with the
  simulator's strict ``>``, differ from the reported count.

This is a replay of the simulator's own events, not a second simulator.
"""

from __future__ import annotations

from typing import Any

from resilimes.smt.fab import Fab

_WAFERS = 25
CHECKS = (
    "family",
    "route_order",
    "tool_overlap",
    "resume_tool",
    "dedication",
    "down_start",
    "pm_overlap",
    "batch",
    "qtime_recount",
)


def check_trace(
    fab: Fab,
    result: Any,
    *,
    downs: list[list[tuple[float, float]]],
    pm: list[list[tuple[float, float]]],
    examples: int = 3,
) -> dict[str, Any]:
    """Counts per check, plus the first few offending rows."""
    counts = {name: 0 for name in CHECKS}
    found: dict[str, list[str]] = {name: [] for name in CHECKS}

    def flag(name: str, text: str) -> None:
        counts[name] += 1
        if len(found[name]) < examples:
            found[name].append(text)

    n = len(fab.lot_id)
    step = list(fab.lot_step)
    running = [False] * n
    bound = [-1] * n
    pinned = [-1] * n
    dropped_at = [-1.0] * n
    q_target = [-1] * n
    q_deadline = [0.0] * n
    holding: list[set[int]] = [set() for _ in fab.tool_name]
    violations = 0
    starts = 0
    for event in result.events:
        kind = event[0]
        if kind == "start":
            _kind, moment, tool, lots, index, finish = event
            starts += 1
            name = fab.tool_name[tool]
            fam = fab.tool_family[tool]
            if holding[tool]:
                flag("tool_overlap", f"{name} t={moment:.1f}")
            for start_at, end_at in downs[tool]:
                if start_at <= moment < end_at:
                    flag("down_start", f"{name} t={moment:.1f} down {start_at:.1f}-{end_at:.1f}")
                    break
            for start_at, end_at in pm[tool]:
                if moment < end_at and finish > start_at:
                    flag("pm_overlap", f"{name} {moment:.1f}-{finish:.1f} pm {start_at:.1f}")
                    break
            if len(lots) > 1:
                route0 = fab.routes[fab.lot_route[lots[0]]]
                cap = route0.batch_max[index]
                recipes = {fab.routes[fab.lot_route[lot]].recipe[index] for lot in lots}
                if cap <= 0 or len(recipes) > 1 or len(lots) * _WAFERS > cap:
                    flag("batch", f"{name} t={moment:.1f} lots={len(lots)} cap={cap}")
            for lot in lots:
                lot_id = fab.lot_id[lot]
                route = fab.routes[fab.lot_route[lot]]
                if index >= len(route.family) or route.family[index] != fam:
                    want = (
                        fab.families[route.family[index]].name
                        if index < len(route.family)
                        else "past route end"
                    )
                    flag("family", f"{lot_id} step {index} on {name}, needs {want}")
                if running[lot] or step[lot] != index:
                    flag("route_order", f"{lot_id} started step {index}, next is {step[lot]}")
                if bound[lot] >= 0 and bound[lot] != tool:
                    flag("resume_tool", f"{lot_id} resumed on {name}")
                if 0 <= index < len(route.dedicate_root) and route.dedicate_root[index] >= 0:
                    if pinned[lot] >= 0 and pinned[lot] != tool:
                        flag("dedication", f"{lot_id} step {index} on {name}")
                    elif pinned[lot] < 0:
                        pinned[lot] = tool
                if q_target[lot] == index:
                    if moment > q_deadline[lot]:
                        violations += 1
                    q_target[lot] = -1
                running[lot] = True
                holding[tool].add(lot)
        elif kind == "interrupt":
            _kind, moment, tool, lots = event
            for lot in lots:
                running[lot] = False
                bound[lot] = tool
                dropped_at[lot] = moment
            holding[tool].clear()
        elif kind == "end":
            _kind, moment, lot, index = event
            lot_id = fab.lot_id[lot]
            dropped_now = dropped_at[lot] == moment
            if (not running[lot] and not dropped_now) or step[lot] != index:
                flag("route_order", f"{lot_id} ended step {index}, next is {step[lot]}")
            running[lot] = False
            bound[lot] = -1
            for held in holding:
                held.discard(lot)
            route = fab.routes[fab.lot_route[lot]]
            if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
                q_deadline[lot] = moment + route.cqt_limit[index]
                q_target[lot] = route.cqt_target[index]
            step[lot] = index + 1
        elif kind == "reclean":
            _kind, moment, lot, index, origin = event
            if q_target[lot] == index and moment > q_deadline[lot]:
                violations += 1
            else:
                flag("qtime_recount", f"{fab.lot_id[lot]} re-clean without a missed window")
            q_target[lot] = -1
            q_deadline[lot] = 0.0
            step[lot] = origin
    horizon = float(result.horizon_sec)
    for lot in range(n):
        if q_target[lot] >= 0 and 0 < q_deadline[lot] <= horizon:
            violations += 1
    if violations != result.qtime_violations:
        flag(
            "qtime_recount",
            f"recount {violations} vs reported {result.qtime_violations}",
        )
    return {
        "starts": starts,
        "counts": counts,
        "total": sum(counts.values()),
        "qtime_recount": violations,
        "qtime_reported": result.qtime_violations,
        "examples": {name: rows for name, rows in found.items() if rows},
    }
