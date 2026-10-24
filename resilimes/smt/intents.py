"""Dispatcher sentences against the SMT2020 full fab.

The sample-plant parser knows ids like ``ETCH-03`` and ``LOT-1001``. On the
full fab a dispatcher names a tool (``Litho_FE_92-1``), a tool family
(``DE_BE_11``), an area (``Dry_Etch``) or a lot (``Init_Lot_3_17``). This
module finds those ids, validates them against the fab, and runs a confirmed
change as a what-if book on the recorded 48 h replay. It never writes to the
benchmark books.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from resilimes.agents.toolcall import ToolCall, regex_tool_call
from resilimes.smt import replay
from resilimes.smt.fab import Fab

_LOT = re.compile(r"\bInit_(?:SuperHot|Hot)?Lot_\d+_\d+\b", re.I)
_TOOL = re.compile(r"(?<![\w-])([A-Za-z][A-Za-z0-9_]*-\d+)(?![\w-])")
_WORD = re.compile(r"(?<![\w-])([A-Za-z][A-Za-z0-9_]*)(?![\w-])")


@dataclass(frozen=True)
class SmtIds:
    lot: str = ""
    tool: str = ""
    family: str = ""
    group: str = ""


def find_ids(fab: Fab, text: str) -> SmtIds:
    lots = {name.lower(): name for name in fab.lot_id}
    tools = {name.lower(): name for name in fab.tool_name}
    families = {item.name.lower(): item.name for item in fab.families}
    groups = {item.group.lower(): item.group for item in fab.families}
    lot = ""
    for match in _LOT.finditer(text):
        lot = lots.get(match.group(0).lower(), match.group(0))
        break
    tool = ""
    for match in _TOOL.finditer(text):
        token = match.group(1)
        if _LOT.fullmatch(token):
            continue
        found = tools.get(token.lower())
        if found:
            tool = found
            break
    family = ""
    group = ""
    for match in _WORD.finditer(text):
        token = match.group(1).lower()
        if not family and token in families:
            family = families[token]
        elif not group and token in groups:
            group = groups[token]
    if tool and not family:
        family = fab.families[fab.tool_family[fab.tool_name.index(tool)]].name
    return SmtIds(lot=lot, tool=tool, family=family, group=group)


def smt_tool_call(fab: Fab, text: str) -> ToolCall | None:
    """The deterministic parser with full-fab ids in place of sample ids."""
    ids = find_ids(fab, text)
    equipment = ids.tool or (ids.family if not ids.lot else "")
    area = ids.tool or ids.family or ids.group
    return regex_tool_call(text, lot_id=ids.lot, equipment_id=equipment, area_id=area)


def smt_id_errors(fab: Fab, call: ToolCall) -> list[str]:
    """Unknown full-fab ids. A failure signs nothing."""
    errors: list[str] = []
    params = call.parameters
    lots = set(fab.lot_id)
    tools = set(fab.tool_name)
    families = {item.name: item for item in fab.families}
    groups = {item.group for item in fab.families}
    lot_id = str(getattr(params, "lot_id", "") or "")
    if lot_id and lot_id not in lots:
        errors.append(f"Unknown lot {lot_id}.")
    equipment = str(getattr(params, "equipment_id", "") or "")
    if equipment and equipment not in tools:
        family = families.get(equipment)
        if family is not None:
            errors.append(
                f"{equipment} is a family of {family.tools} tools; name one tool, "
                f"for example {fab.tool_name[family.tool0]}."
            )
        else:
            errors.append(f"Unknown equipment {equipment}.")
    target = str(getattr(params, "target_station_group", "") or "")
    if target and target not in tools and target not in families and target not in groups:
        errors.append(f"Unknown station group {target}.")
    return errors


def _lead_end(rp: replay.Replay, lot: int) -> float:
    """How far along the lot is at the horizon, in seconds; due dates play no part.

    Finished lots count the time since they finished; open lots count minus the
    raw process time still left on their route. A larger value means further ahead.
    """
    if rp.finished[lot] >= 0:
        return rp.horizon - rp.finished[lot]
    step, _status = replay.lot_state(rp, lot, rp.horizon)
    return -rp.fab.routes[rp.fab.lot_route[lot]].remain[step]


def run_whatif(fab: Fab, call: ToolCall) -> dict[str, Any]:
    """Run a confirmed change as a what-if book. Returns a confirm-shaped body."""
    params = call.parameters
    equipment = str(getattr(params, "equipment_id", "") or "")
    lot_id = str(getattr(params, "lot_id", "") or "")
    eta = getattr(params, "eta_min", None)
    spec: replay.BookSpec | None = None
    if call.intent in {"mark_tool_down", "what_if"} and equipment in fab.tool_name:
        minutes = float(eta if isinstance(eta, int) else 60)
        spec = replay.whatif_spec(forced_tool=fab.tool_name.index(equipment), forced_min=minutes)
    elif call.intent in {"insert_hot_lot", "what_if"} and lot_id in fab.lot_id:
        spec = replay.whatif_spec(promote_lot=fab.lot_id.index(lot_id))
    if spec is None:
        return {
            "status": "aborted",
            "committed": False,
            "simulated": False,
            "kpis": {},
            "affected_lots": [],
            "trace": [],
            "errors": [],
            "fix_hint": (
                "The full-fab replay models a tool down (name a tool and minutes) or a lot "
                "made VIP (name a lot). Hold, release and PM moves stay on the sample plant."
            ),
            "book": None,
        }
    replay.register(spec)
    base = replay.get_replay(replay.base_spec())
    after = replay.get_replay(spec)
    deltas = []
    for lot in range(len(fab.lot_id)):
        change = _lead_end(after, lot) - _lead_end(base, lot)
        if abs(change) >= 60.0:
            deltas.append((change, lot))
    deltas.sort()
    picked = deltas[:6] + [row for row in deltas[-6:] if row[0] > 0 and row not in deltas[:6]]
    affected = [
        {
            "lot_id": fab.lot_id[lot],
            "kind": after.kind[lot],
            "ahead_change_min": round(change / 60.0),
        }
        for change, lot in picked
    ]
    return {
        "status": "executed",
        "committed": False,
        "simulated": True,
        "kpis": {
            "before": {
                "on_time_delivery_pct": base.result.on_time_pct,
                "weighted_tardiness_min": base.result.weighted_tardiness_min,
            },
            "after": {
                "on_time_delivery_pct": after.result.on_time_pct,
                "weighted_tardiness_min": after.result.weighted_tardiness_min,
            },
        },
        "affected_lots": affected,
        "lots_changed": len(deltas),
        "trace": [],
        "errors": [],
        "fix_hint": "",
        "book": spec.key,
    }
