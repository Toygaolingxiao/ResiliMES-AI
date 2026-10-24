"""Replay a recorded SMT run and check what every start must satisfy.

Run ``run_policy(..., record=True)`` and pass the result to ``check_trace``.
Checks, one counter each:

- ``family``: the tool belongs to the station family of the lot's current step.
- ``route_order``: a lot starts only its next step, once, and never while it
  is already in process.
- ``tool_overlap``: a tool starts a piece only when it holds nothing.
- ``rework_redo``: a lot interrupted by a breakdown goes to rework and redoes
  the same step, not before the rework hold is over.
- ``stuck_on_down``: every lot on a tool that breaks leaves it at the
  breakdown (rework or done), and no lot is left on a tool that is down at
  the horizon.
- ``dedication``: a later litho layer runs on the scanner of the first layer,
  unless that scanner is down at the start (the lot is then re-pinned).
- ``down_start``: no start on a tool inside a breakdown window.
- ``pm_overlap``: no processing window crosses a PM window.
- ``batch``: a multi-lot start is a batch step for every member (each on its
  own route step), one recipe, within capacity.
- ``batch_all_started``: every lot the dispatcher chose for a start started.
- ``batch_min``: a batch under BATCHMN started only with a logged wait-rule
  reason (``hot_cap``, ``max_wait``, ``no_arrivals``, ``qtime_urgent``).
- ``qtime_recount``: Q-time violations recounted from the trace, with the
  simulator's strict ``>``, differ from the reported count.
- ``sampling``: a lot skips only steps the lot-ID rule leaves unmeasured,
  and never runs such a step (its snapshot step excepted).
- ``qtime_override``: a Q-time-urgent override happens only under ResiliMES,
  only on a lot inside an open window that a dataset CQT step opened (so never
  on a step outside a CQT origin-to-target span), only while the window can
  still be met (need <= remaining <= need + margin), and is followed at once
  by the start that lot leads.
- ``transport``: every start of a lot comes at least the fixed transport time
  (same STNGRP bay 1 min, other bay 3 min) after the lot's previous step
  ended, or after the re-clean that sent it back to its CQT origin.
- ``qtime_hold``: no start of a lot inside its Q-time hold.
- ``reservation`` (Q-time r2 fix 3): only ResiliMES reserves; at most one
  reserved tool per family at a time; a hold lasts at most RESERVE_MAX_SEC;
  never on a tool that is down or in PM at the reservation, nor one whose PM
  starts during the hold; a reserved tool starts nothing but its lot; every
  reservation is released; a tool starts a lot between two reservations (no
  chains); reserved minutes recount to the reported total.

This is a replay of the simulator's own events, not a second simulator.
"""

from __future__ import annotations

from typing import Any

from resilimes.smt.fab import (
    QTIME_URGENT_MARGIN_SEC,
    RESERVE_MAX_SEC,
    REWORK_SEC,
    Fab,
    inherited_windows,
    lot_number,
    measured,
    release_at,
    transport_seconds,
)
from resilimes.smt.layout import family_buildings, resolve

_WAFERS = 25
CHECKS = (
    "family",
    "route_order",
    "tool_overlap",
    "rework_redo",
    "stuck_on_down",
    "dedication",
    "down_start",
    "pm_overlap",
    "batch",
    "batch_all_started",
    "batch_min",
    "qtime_recount",
    "sampling",
    "qtime_override",
    "transport",
    "qtime_hold",
    "reservation",
    "release",
)
UNDER_MIN_REASONS = ("hot_cap", "max_wait", "no_arrivals", "qtime_urgent")


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
    rework_step = [-1] * n
    rework_at = [0.0] * n
    left_at: dict[int, float] = {}
    pinned = [-1] * n
    dropped_at = [-1.0] * n
    q_target = [-1] * n
    q_deadline = [0.0] * n
    q_origin = [-1] * n
    # Windows inherited from the snapshot open at t=0 and are counted apart.
    q_inherited = [False] * n
    hold_until: dict[int, float] = {}
    for lot, origin, target, limit in inherited_windows(fab):
        q_target[lot] = target
        q_origin[lot] = origin
        q_deadline[lot] = limit
        q_inherited[lot] = True
    # (tool, time, lead lot) of an override not yet matched to its start.
    open_override: tuple[int, float, int] | None = None
    policy = str(getattr(result, "policy", ""))
    moves = bool(getattr(result, "transport", True))
    # Multi-building layout of the run (None = one building, as main).
    layout = resolve((getattr(result, "layout", None) or {}).get("name") or False)
    buildings = family_buildings(fab, layout) if layout is not None else None
    cross_sec = layout.cross_building_sec if layout is not None else 0.0
    # (moment, family) the lot last left: a step end or a re-clean.
    released: list[tuple[float, int] | None] = [None] * n
    holding: list[set[int]] = [set() for _ in fab.tool_name]
    # Reservations: tool -> (lot, since); family -> reserved tool.
    reserved: dict[int, tuple[int, float]] = {}
    fam_reserved: dict[int, int] = {}
    cool = [False] * len(fab.tool_name)
    reserved_sec = 0.0
    violations = 0
    starts = 0
    for event in result.events:
        kind = event[0]
        if open_override is not None:
            o_tool, o_time, o_lot = open_override
            ok = kind == "start" and event[2] == o_tool and event[1] == o_time
            if not ok or event[3][0] != o_lot:
                flag("qtime_override", f"{fab.lot_id[o_lot]} override not followed by its start")
            open_override = None
        if kind == "override":
            _kind, moment, tool, lot, index, _plain, remaining, need, _displaced = event
            route = fab.routes[fab.lot_route[lot]]
            origin = q_origin[lot]
            target = q_target[lot]
            in_window = (
                target >= 0
                and 0 <= origin < index <= target
                and route.cqt_limit[origin] > 0
                and route.cqt_target[origin] == target
                and step[lot] == index
            )
            exact = abs((q_deadline[lot] - moment) - remaining) < 1e-6
            band = need - 1e-6 <= remaining <= need + QTIME_URGENT_MARGIN_SEC + 1e-6
            if policy != "resilimes" or not in_window or not exact or not band:
                flag(
                    "qtime_override",
                    f"{fab.lot_id[lot]} step {index} t={moment:.1f} target={target} origin={origin}",
                )
            open_override = (tool, moment, lot)
            continue
        if kind == "reserve":
            _kind, moment, tool, lot, until, _eta = event
            name = fab.tool_name[tool]
            fam = fab.tool_family[tool]
            bad = []
            if policy != "resilimes":
                bad.append("policy")
            if tool in reserved or fam in fam_reserved:
                bad.append("second hold in family")
            if until - moment > RESERVE_MAX_SEC + 1e-6 or until < moment:
                bad.append("too long")
            if any(a <= moment < b for a, b in downs[tool]):
                bad.append("tool down")
            if any(moment < b and until > a for a, b in pm[tool]):
                bad.append("PM")
            if holding[tool]:
                bad.append("tool busy")
            if cool[tool]:
                bad.append("chain")
            if bad:
                flag("reservation", f"{name} t={moment:.1f} {fab.lot_id[lot]}: {', '.join(bad)}")
            reserved[tool] = (lot, moment)
            fam_reserved[fam] = tool
            continue
        if kind == "release":
            _kind, moment, tool, lot, _outcome = event
            hold = reserved.pop(tool, None)
            if hold is None or hold[0] != lot:
                flag("reservation", f"{fab.tool_name[tool]} t={moment:.1f} release without hold")
            else:
                if moment - hold[1] > RESERVE_MAX_SEC + 1e-6:
                    flag("reservation", f"{fab.tool_name[tool]} held {moment - hold[1]:.0f}s")
                reserved_sec += max(0.0, min(moment, float(result.horizon_sec)) - hold[1])
            fam_reserved.pop(fab.tool_family[tool], None)
            cool[tool] = True
            continue
        if kind == "start":
            _kind, moment, tool, lots, steps, finish, reason, chosen = event
            starts += 1
            if tool in reserved:
                flag("reservation", f"{fab.tool_name[tool]} t={moment:.1f} started while reserved")
            cool[tool] = False
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
            if set(chosen) != set(lots):
                missing = len(set(chosen) - set(lots))
                flag("batch_all_started", f"{name} t={moment:.1f} {missing} chosen lots left")
            route0 = fab.routes[fab.lot_route[lots[0]]]
            in_range = all(
                index < len(fab.routes[fab.lot_route[lot]].family)
                for lot, index in zip(lots, steps, strict=True)
            )
            if in_range and route0.batch_max[steps[0]] > 0:
                cap = route0.batch_max[steps[0]]
                floor = route0.batch_min[steps[0]] or cap
                members = [fab.routes[fab.lot_route[lot]] for lot in lots]
                recipes = {route.recipe[index] for route, index in zip(members, steps, strict=True)}
                not_batch = any(
                    route.batch_max[index] <= 0 for route, index in zip(members, steps, strict=True)
                )
                if not_batch or len(recipes) > 1 or len(lots) * _WAFERS > cap:
                    flag("batch", f"{name} t={moment:.1f} lots={len(lots)} cap={cap}")
                if len(lots) * _WAFERS < floor and reason not in UNDER_MIN_REASONS:
                    flag("batch_min", f"{name} t={moment:.1f} lots={len(lots)} reason={reason!r}")
            elif len(lots) > 1:
                flag("batch", f"{name} t={moment:.1f} lots={len(lots)} not a batch step")
            for lot, index in zip(lots, steps, strict=True):
                lot_id = fab.lot_id[lot]
                route = fab.routes[fab.lot_route[lot]]
                if moment < release_at(fab, lot) - 1e-6:
                    flag("release", f"{lot_id} started t={moment:.1f} before its release")
                if index >= len(route.family) or route.family[index] != fam:
                    want = (
                        fab.families[route.family[index]].name
                        if index < len(route.family)
                        else "past route end"
                    )
                    flag("family", f"{lot_id} step {index} on {name}, needs {want}")
                if running[lot] or step[lot] != index:
                    flag("route_order", f"{lot_id} started step {index}, next is {step[lot]}")
                last = released[lot]
                if last is not None:
                    move = (
                        transport_seconds(fab, last[1], fam, buildings, cross_sec) if moves else 0.0
                    )
                    if moment < last[0] + move - 1e-6:
                        flag(
                            "transport",
                            f"{lot_id} step {index} at {moment:.1f}, left {last[0]:.1f}",
                        )
                start_step = fab.lot_step[lot]
                number = lot_number(lot_id, lot)
                if index != start_step and not measured(route, index, number):
                    flag("sampling", f"{lot_id} ran unsampled step {index}")
                if moment < hold_until.get(lot, 0.0) - 1e-6:
                    flag("qtime_hold", f"{lot_id} started at {moment:.1f} inside its Q-time hold")
                if rework_step[lot] >= 0:
                    early = moment < rework_at[lot] + REWORK_SEC - 1e-6
                    if index != rework_step[lot] or early:
                        flag("rework_redo", f"{lot_id} step {index} at {moment:.1f} after rework")
                    rework_step[lot] = -1
                if 0 <= index < len(route.dedicate_root) and route.dedicate_root[index] >= 0:
                    old = pinned[lot]
                    # The pin binds the later steps of its own layer only (the
                    # root step of a new layer, or another family, is free).
                    binds = (
                        route.dedicate_root[index] < index
                        and old >= 0
                        and fab.tool_family[old] == route.family[index]
                    )
                    if binds and old != tool:
                        down = any(a <= moment < b for a, b in downs[old])
                        if not down:
                            flag("dedication", f"{lot_id} step {index} on {name}")
                    pinned[lot] = tool
                if q_target[lot] == index:
                    if moment > q_deadline[lot] and not q_inherited[lot]:
                        violations += 1
                    q_target[lot] = -1
                    q_origin[lot] = -1
                    q_inherited[lot] = False
                running[lot] = True
                holding[tool].add(lot)
        elif kind == "interrupt":
            _kind, moment, tool, lots = event
            for lot in lots:
                running[lot] = False
                dropped_at[lot] = moment
                left_at[lot] = -1.0
            holding[tool].clear()
        elif kind == "rework":
            _kind, moment, tool, lot, index = event
            if left_at.get(lot) == -1.0:
                left_at[lot] = moment
            rework_step[lot] = index
            rework_at[lot] = moment
        elif kind == "end":
            _kind, moment, lot, index = event
            lot_id = fab.lot_id[lot]
            dropped_now = dropped_at[lot] == moment
            if (not running[lot] and not dropped_now) or step[lot] != index:
                flag("route_order", f"{lot_id} ended step {index}, next is {step[lot]}")
            if left_at.get(lot) == -1.0:
                left_at[lot] = moment
            running[lot] = False
            for held in holding:
                held.discard(lot)
            route = fab.routes[fab.lot_route[lot]]
            released[lot] = (moment, route.family[index])
            if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
                q_deadline[lot] = moment + route.cqt_limit[index]
                q_target[lot] = route.cqt_target[index]
                q_origin[lot] = index
                q_inherited[lot] = False
            step[lot] = index + 1
        elif kind == "skip":
            _kind, moment, lot, index = event
            route = fab.routes[fab.lot_route[lot]]
            if step[lot] != index or measured(route, index, lot_number(fab.lot_id[lot], lot)):
                flag("sampling", f"{fab.lot_id[lot]} skipped step {index}")
            if q_target[lot] == index:
                q_target[lot] = -1
                q_origin[lot] = -1
                q_inherited[lot] = False
            step[lot] = index + 1
        elif kind in ("reclean", "qhold"):
            # The deadline passed with the target not started: the lot is at a
            # step of the open span (origin excluded), waiting, not on a tool.
            _kind, moment, lot, index, origin = event
            in_span = q_origin[lot] < index <= q_target[lot] and step[lot] == index
            if in_span and moment > q_deadline[lot] and not running[lot]:
                violations += 0 if q_inherited[lot] else 1
            else:
                flag("qtime_recount", f"{fab.lot_id[lot]} {kind} without a missed window")
            rework_step[lot] = -1
            if kind == "qhold":
                hold_until[lot] = moment + REWORK_SEC
                q_target[lot] = -1
                q_origin[lot] = -1
                q_inherited[lot] = False
                continue
            q_target[lot] = -1
            q_origin[lot] = -1
            q_inherited[lot] = False
            q_deadline[lot] = 0.0
            released[lot] = (moment, fab.routes[fab.lot_route[lot]].family[index])
            step[lot] = origin
    horizon = float(result.horizon_sec)
    for lot, when in left_at.items():
        if when < 0:
            flag("stuck_on_down", f"{fab.lot_id[lot]} never left its broken tool")
    for tool, held in enumerate(holding):
        if held and any(a <= horizon < b for a, b in downs[tool]):
            flag("stuck_on_down", f"{fab.tool_name[tool]} down at horizon holding {len(held)}")
    for tool in reserved:
        flag("reservation", f"{fab.tool_name[tool]} hold never released")
    reported_min = getattr(result, "reserved_min", None)
    if reported_min is not None and abs(round(reserved_sec / 60.0, 1) - reported_min) > 0.11:
        flag("reservation", f"held {reserved_sec / 60.0:.1f} min vs reported {reported_min}")
    for lot in range(n):
        if q_target[lot] >= 0 and 0 < q_deadline[lot] <= horizon and not q_inherited[lot]:
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
