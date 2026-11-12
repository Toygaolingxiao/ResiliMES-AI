"""Read an MES-style event log into a run record.

The file is CSV or JSON lines (a JSON array is accepted too). Each row has:

* required: ``lot``, ``step``, ``tool``, ``event_type``, ``timestamp``
* optional: ``recipe``, ``reason``, ``decision``, ``due``

``timestamp`` and ``due`` are seconds or an ISO-8601 time. Times are shifted so
the earliest timestamp is 0.

The ceiling is how far an explanation of this file can go:

* a ``reason`` or ``decision`` on any row: recorded (記録) is possible
* only events and timestamps: attributed (観測帰因) at most
* a required field missing: unknown (不明), and the missing names are listed

When the required fields are present, the rows become a ``RunRecord`` and the
lateness split runs on it. Without ``due``, lateness stays unknown instead of
inventing a due time.

Event types: ``ready`` / ``arrive`` / ``queue``, ``start`` / ``track_in``,
``end`` / ``track_out``, ``hold_start`` / ``hold_end``, ``down_start`` /
``down_end``, ``pm_start`` / ``pm_end``, ``decision``.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from resilimes.explain.lateness import decompose
from resilimes.explain.record import Gap, RunRecord, Timeline, Visit
from resilimes.explain.report import build_report
from resilimes.explain.schema import (
    EvidenceBundle,
    EvidenceItem,
    RunRef,
    Subject,
    lateness_bundle,
)

REQUIRED = ("lot", "step", "tool", "event_type", "timestamp")
OPTIONAL = ("recipe", "reason", "decision", "due")
_ALIASES = {
    "lot_id": "lot",
    "equipment": "tool",
    "equipment_id": "tool",
    "event": "event_type",
    "type": "event_type",
    "time": "timestamp",
    "occurred_at": "timestamp",
    "ts": "timestamp",
}
_READY = {"ready", "arrive", "queue"}
_START = {"start", "track_in", "trackin"}
_END = {"end", "track_out", "trackout"}
_KNOWN = (
    _READY
    | _START
    | _END
    | {
        "hold_start",
        "hold_end",
        "down_start",
        "down_end",
        "pm_start",
        "pm_end",
        "decision",
    }
)


@dataclass
class ImportResult:
    """What the file can support, and the report when the record could be built."""

    ceiling: str
    missing: list[str] = field(default_factory=list)
    rows: int = 0
    decision_rows: int = 0
    unrecognised: list[str] = field(default_factory=list)
    has_due: bool = False
    record: RunRecord | None = None
    report: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "ceiling": self.ceiling,
            "missing": self.missing,
            "rows": self.rows,
            "decision_rows": self.decision_rows,
            "unrecognised": self.unrecognised,
            "has_due": self.has_due,
            "report": self.report,
        }


@dataclass
class _Row:
    lot: str
    step: int
    tool: str
    event_type: str
    t: float
    recipe: str
    reason: str
    decision: str
    due: float | None


def ingest_text(text: str, filename: str = "") -> ImportResult:
    """Validate ``text`` and, when it is complete, run the lateness split."""
    try:
        raw_rows = _parse(text, filename)
    except ValueError as exc:
        return ImportResult(ceiling="unknown", missing=[str(exc)])
    if not raw_rows:
        return ImportResult(
            ceiling="unknown",
            missing=list(REQUIRED),
        )
    missing = _missing(raw_rows)
    decision_rows = sum(1 for row in raw_rows if _decision(row))
    unrecognised = sorted(
        {
            _cell(row, "event_type")
            for row in raw_rows
            if _cell(row, "event_type") and _key(_cell(row, "event_type")) not in _KNOWN
        }
    )
    if missing:
        return ImportResult(
            ceiling="unknown",
            missing=missing,
            rows=len(raw_rows),
            decision_rows=decision_rows,
            unrecognised=unrecognised,
        )
    try:
        parsed = _typed(raw_rows)
    except ValueError as exc:
        return ImportResult(
            ceiling="unknown",
            missing=[str(exc)],
            rows=len(raw_rows),
            decision_rows=decision_rows,
            unrecognised=unrecognised,
        )
    ceiling = "recorded" if decision_rows else "attributed"
    record = _record(parsed, filename)
    report = _report(record, parsed)
    return ImportResult(
        ceiling=ceiling,
        rows=len(raw_rows),
        decision_rows=decision_rows,
        unrecognised=unrecognised,
        has_due=any(row.due is not None for row in parsed),
        record=record,
        report=report,
    )


def _parse(text: str, filename: str) -> list[dict[str, str]]:
    body = text.lstrip("\ufeff").strip()
    if not body:
        return []
    name = filename.lower()
    if body.startswith("[") or name.endswith(".json"):
        loaded = json.loads(body)
        if not isinstance(loaded, list):
            raise ValueError("JSON must be a list of rows or one object per line")
        return [_stringify(item) for item in loaded]
    if body.startswith("{") or name.endswith(".jsonl"):
        rows = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("each JSON line must be an object")
            rows.append(_stringify(item))
        return rows
    reader = csv.DictReader(io.StringIO(body))
    if reader.fieldnames is None:
        return []
    return [_stringify(row) for row in reader]


def _stringify(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ValueError("each row must be an object")
    out: dict[str, str] = {}
    for key, value in item.items():
        name = _ALIASES.get(_key(str(key)), _key(str(key)))
        out[name] = "" if value is None else str(value).strip()
    return out


def _key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _cell(row: dict[str, str], name: str) -> str:
    return row.get(name, "").strip()


def _decision(row: dict[str, str]) -> bool:
    return bool(
        _cell(row, "reason")
        or _cell(row, "decision")
        or _key(_cell(row, "event_type")) == "decision"
    )


def _missing(rows: list[dict[str, str]]) -> list[str]:
    present = {key for row in rows for key in row}
    blank: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        for name in REQUIRED:
            if name in present and not _cell(row, name):
                blank[name].append(index)
    missing: list[str] = []
    for name in REQUIRED:
        if name not in present:
            missing.append(name)
        elif blank[name]:
            shown = ", ".join(str(number) for number in blank[name][:8])
            if len(blank[name]) > 8:
                shown += ", …"
            missing.append(f"{name} (rows {shown})")
    return missing


def _typed(rows: list[dict[str, str]]) -> list[_Row]:
    parsed: list[_Row] = []
    for index, row in enumerate(rows, start=1):
        stamp = _time(_cell(row, "timestamp"))
        due = _time(_cell(row, "due")) if _cell(row, "due") else None
        if stamp is None:
            raise ValueError(f"timestamp (row {index})")
        if due is None and _cell(row, "due"):
            raise ValueError(f"due (row {index})")
        try:
            step = int(float(_cell(row, "step")))
        except ValueError:
            raise ValueError(f"step (row {index})") from None
        if step < 0:
            raise ValueError(f"step (row {index})")
        parsed.append(
            _Row(
                lot=_cell(row, "lot"),
                step=step,
                tool=_cell(row, "tool"),
                event_type=_key(_cell(row, "event_type")),
                t=stamp,
                recipe=_cell(row, "recipe"),
                reason=_cell(row, "reason"),
                decision=_cell(row, "decision"),
                due=due,
            )
        )
    origin = min(item.t for item in parsed)
    for item in parsed:
        item.t -= origin
        if item.due is not None:
            item.due -= origin
    return parsed


def _time(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp()


def _record(rows: list[_Row], filename: str) -> RunRecord:
    lots = list(dict.fromkeys(row.lot for row in rows))
    tools = list(dict.fromkeys(row.tool for row in rows))
    lot_index = {lot: index for index, lot in enumerate(lots)}
    tool_index = {tool: index for index, tool in enumerate(tools)}
    steps = max(row.step for row in rows) + 1
    families = [
        SimpleNamespace(name=tool, tool0=index, tools=1) for index, tool in enumerate(tools)
    ]
    route = SimpleNamespace(batch_max=[0] * steps, cycle=[0.0] * steps)
    dues = [0.0] * len(lots)
    has_due = [False] * len(lots)
    products = [""] * len(lots)
    for row in rows:
        index = lot_index[row.lot]
        if row.due is not None and not has_due[index]:
            dues[index] = row.due
            has_due[index] = True
        if row.recipe and not products[index]:
            products[index] = row.recipe
    fab = SimpleNamespace(
        families=families,
        routes=[route],
        lot_route=[0] * len(lots),
        lot_due=dues,
        lot_id=lots,
        lot_product=products,
        lot_class=["regular"] * len(lots),
    )
    visits: dict[int, list[Visit]] = defaultdict(list)
    open_visit: dict[int, Visit] = {}
    gaps: dict[int, list[Gap]] = defaultdict(list)
    holds: dict[int, float] = {}
    downs: list[list[tuple[float, float]]] = [[] for _ in tools]
    pm: list[list[tuple[float, float]]] = [[] for _ in tools]
    open_down: dict[int, float] = {}
    open_pm: dict[int, float] = {}
    decisions: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (item.t, item.lot)):
        lot = lot_index[row.lot]
        tool = tool_index[row.tool]
        kind = row.event_type
        if row.reason or row.decision or kind == "decision":
            decisions.append(
                {
                    "lot": row.lot,
                    "step": row.step,
                    "tool": row.tool,
                    "t": row.t,
                    "reason": row.reason,
                    "decision": row.decision,
                }
            )
        if kind in _READY or kind in _START:
            visit = open_visit.get(lot)
            if visit is None:
                visit = Visit(lot=lot, step=row.step, family=tool, ready=row.t, tool=tool)
                open_visit[lot] = visit
            if kind in _START:
                visit.start = row.t
                visit.tool = tool
                visit.family = tool
            if row.reason or row.decision:
                visit.reason = row.decision or row.reason
        elif kind in _END:
            visit = open_visit.pop(lot, None)
            if visit is None:
                visit = Visit(
                    lot=lot, step=row.step, family=tool, ready=row.t, start=row.t, tool=tool
                )
            visit.leave = row.t
            visit.outcome = "done"
            visits[lot].append(visit)
        elif kind == "hold_start":
            holds[lot] = row.t
        elif kind == "hold_end" and lot in holds:
            gaps[lot].append(Gap(lot=lot, start=holds.pop(lot), end=row.t, kind="release_hold"))
        elif kind == "down_start":
            open_down[tool] = row.t
        elif kind == "down_end" and tool in open_down:
            downs[tool].append((open_down.pop(tool), row.t))
        elif kind == "pm_start":
            open_pm[tool] = row.t
        elif kind == "pm_end" and tool in open_pm:
            pm[tool].append((open_pm.pop(tool), row.t))
    horizon = max(row.t for row in rows)
    for lot, visit in list(open_visit.items()):
        visits[lot].append(visit)
        horizon = max(horizon, visit.ready)
    for tool, start in open_down.items():
        downs[tool].append((start, horizon))
    for tool, start in open_pm.items():
        pm[tool].append((start, horizon))
    busy: list[list[tuple[float, float]]] = [[] for _ in tools]
    completed: dict[int, float] = {}
    by_family: dict[int, list[Visit]] = defaultdict(list)
    for lot, lot_visits in visits.items():
        lot_visits.sort(key=lambda visit: visit.ready)
        previous: Visit | None = None
        for visit in lot_visits:
            if previous is not None and previous.leave is not None and visit.ready > previous.leave:
                gaps[lot].append(
                    Gap(lot=lot, start=previous.leave, end=visit.ready, kind="transport")
                )
            if visit.start is not None and visit.leave is not None and visit.tool >= 0:
                busy[visit.tool].append((visit.start, visit.leave))
            by_family[visit.family].append(visit)
            previous = visit
        if lot not in open_visit and previous is not None and previous.leave is not None:
            completed[lot] = previous.leave
            horizon = max(horizon, previous.leave)
    if horizon <= 0:
        horizon = 1.0
    timeline = Timeline(
        fab=fab,
        horizon=horizon,
        downs=downs,
        pm=pm,
        visits=dict(visits),
        gaps=dict(gaps),
        busy=busy,
        reserved=[[] for _ in tools],
        completed=completed,
        by_family=dict(by_family),
    )
    return RunRecord(
        fab=fab,
        seed=0,
        horizon=horizon,
        policy="import",
        downs=downs,
        pm=pm,
        timeline=timeline,
        label=filename or "import",
        notes={"decisions": decisions, "due_known": has_due},
    )


def _report(record: RunRecord, rows: list[_Row]) -> dict[str, Any]:
    known = record.notes["due_known"]
    items: list[EvidenceItem] = []
    bundles: list[EvidenceBundle] = []
    for lot, lot_id in enumerate(record.fab.lot_id):
        if not known[lot]:
            items.append(
                EvidenceItem(
                    key=f"lateness.{lot_id}",
                    tier="unknown",
                    reason="the log has no due time",
                )
            )
            continue
        bundles.append(lateness_bundle(decompose(record.timeline, lot), _ref(record)))
    if len(bundles) == 1 and not items:
        return build_report(bundles[0])
    for bundle in bundles:
        for item in bundle.items:
            items.append(item.model_copy(update={"key": f"{bundle.subject.id}:{item.key}"}))
    subject_id = record.fab.lot_id[0] if len(record.fab.lot_id) == 1 else "import"
    kind = "lot" if len(record.fab.lot_id) == 1 else "window"
    combined = EvidenceBundle(
        subject=Subject(kind=kind, id=subject_id),
        run=_ref(record),
        items=tuple(items),
    ).sealed()
    report = build_report(combined)
    report["lots"] = list(record.fab.lot_id)
    return report


def _ref(record: RunRecord) -> RunRef:
    return RunRef(
        seed=record.seed,
        horizon_sec=float(record.horizon),
        policy=record.policy,
        label=record.label,
    )
