"""Export one recorded run as the ``fab_ops`` datasource (Postgres/Zetaris SQL).

Tables (schema ``resilimes`` in database ``fab_ops``):

* ``ops_events``: one row per lot per start, plus rework, Q-time hold,
  re-clean, interrupt, reserve/release, override and every down/PM window.
  ``end``/``skip`` rows are left out to keep the seed small; a lot's leave
  time is its next ``start`` minus transport, or ``ops_kpi_hourly``.
* ``ops_ai_decisions``: ``ai_decision`` events if the run had an AI shift
  lead; otherwise the rule-based Q-time overrides, labelled ``source='rule'``.
* ``ops_kpi_hourly``: per family and hour -- lots waiting at the hour start,
  arrivals, lot starts, busy/down/PM tool hours, setup minutes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from resilimes.evidence.toolkit import HOUR, RecordedRun, Toolkit

DDL = {
    "ops_events": (
        "run_id TEXT, seq INTEGER, t_sec DOUBLE PRECISION, kind TEXT, tool TEXT, "
        "lot_id TEXT, step INTEGER, family TEXT, detail TEXT"
    ),
    "ops_ai_decisions": (
        "run_id TEXT, seq INTEGER, t_sec DOUBLE PRECISION, source TEXT, tool TEXT, "
        "lead_lot TEXT, displaced_lot TEXT, detail TEXT"
    ),
    "ops_kpi_hourly": (
        "run_id TEXT, hour INTEGER, family TEXT, wip_waiting INTEGER, arrivals INTEGER, "
        "lot_starts INTEGER, busy_tool_h DOUBLE PRECISION, down_tool_h DOUBLE PRECISION, "
        "pm_tool_h DOUBLE PRECISION, setup_min DOUBLE PRECISION"
    ),
}


def run_id(run: RecordedRun) -> str:
    return f"{run.policy}-s{run.seed}-{int(run.horizon // HOUR)}h-{run.label}"


def ops_rows(run: RecordedRun) -> dict[str, list[tuple[Any, ...]]]:
    fab = run.fab
    rid = run_id(run)
    tool_name, lot_id = fab.tool_name, fab.lot_id
    fam_name = [f.name for f in fab.families]
    events: list[tuple[Any, ...]] = []
    decisions: list[tuple[Any, ...]] = []

    def add(t: float, kind: str, tool: int, lot: int, step: int, detail: str) -> None:
        fam = fab.tool_family[tool] if tool >= 0 else -1
        events.append(
            (
                rid,
                len(events),
                round(t, 1),
                kind,
                tool_name[tool] if tool >= 0 else None,
                lot_id[lot] if lot >= 0 else None,
                step,
                fam_name[fam] if fam >= 0 else None,
                detail,
            )
        )

    timed: list[tuple[float, int, tuple[Any, ...]]] = []
    for index, event in enumerate(run.result.events):
        timed.append((float(event[1]), index, event))
    for tool, spans in enumerate(run.downs):
        for a, b in spans:
            if a < run.horizon:
                timed.append((max(0.0, a), -1, ("down", a, tool, b)))
    for tool, spans in enumerate(run.pm):
        for a, b in spans:
            if a < run.horizon:
                timed.append((max(0.0, a), -1, ("pm", a, tool, b)))
    timed.sort(key=lambda item: (item[0], item[1]))
    for moment, _index, event in timed:
        kind = event[0]
        if kind == "start":
            _, _t, tool, lots, steps, finish, reason, _chosen = event
            for lot, step in zip(lots, steps, strict=False):
                add(
                    moment,
                    "start",
                    tool,
                    lot,
                    step,
                    f"finish={finish:.0f} lots={len(lots)} {reason}",
                )
        elif kind == "rework":
            add(moment, "rework", event[2], event[3], event[4], "tool failed in process")
        elif kind == "qhold":
            add(moment, "qhold", -1, event[2], event[3], f"target={event[4]}")
        elif kind == "reclean":
            add(moment, "reclean", -1, event[2], event[3], f"origin={event[4]}")
        elif kind == "interrupt":
            add(moment, "interrupt", event[2], -1, -1, f"lots={len(event[3])}")
        elif kind == "reserve":
            add(moment, "reserve", event[2], event[3], -1, f"until={event[4]:.0f}")
        elif kind == "release":
            add(moment, "release", event[2], event[3], -1, str(event[4]))
        elif kind == "override":
            _, _t, tool, lead, step, plain, remaining, need, _displaced = event
            add(moment, "override", tool, lead, step, f"plain={lot_id[plain]}")
            decisions.append(
                (
                    rid,
                    len(decisions),
                    round(moment, 1),
                    "rule",
                    tool_name[tool],
                    lot_id[lead],
                    lot_id[plain],
                    f"qtime override remaining={remaining:.0f} need={need:.0f}",
                )
            )
        elif kind == "ai_decision":
            payload = event[2] if len(event) > 2 and isinstance(event[2], dict) else {}
            tool = int(payload.get("tool", -1))
            for lot in payload.get("displaced", []) or [None]:
                decisions.append(
                    (
                        rid,
                        len(decisions),
                        round(moment, 1),
                        "ai",
                        tool_name[tool] if tool >= 0 else None,
                        lot_id[int(payload["lead"])] if "lead" in payload else None,
                        lot_id[int(lot)] if lot is not None else None,
                        str(payload.get("reason", ""))[:200],
                    )
                )
        elif kind in ("down", "pm"):
            add(moment, kind, event[2], -1, -1, f"until={event[3]:.0f}")
    kit = Toolkit(run)
    kpis: list[tuple[Any, ...]] = []
    hours = int(run.horizon // HOUR)
    for fam in range(len(fab.families)):
        if fam not in kit.tl.by_family:
            continue
        for hour in range(hours):
            raw = kit.window_stats(fam, hour * HOUR, (hour + 1) * HOUR)
            kpis.append(
                (
                    rid,
                    hour,
                    fam_name[fam],
                    int(raw["waiting_start"]),
                    int(raw["arrivals"]),
                    int(raw["lot_starts"]),
                    round(raw["busy_tool_h"], 2),
                    round(raw["down_tool_h"], 2),
                    round(raw["pm_tool_h"], 2),
                    round(raw["setup_min"], 1),
                )
            )
    return {"ops_events": events, "ops_ai_decisions": decisions, "ops_kpi_hourly": kpis}


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _chunks(rows: list[tuple[Any, ...]], size: int) -> Iterator[list[tuple[Any, ...]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def ops_sql(tables: dict[str, list[tuple[Any, ...]]], header: Iterable[str] = ()) -> str:
    """Postgres SQL (schema ``resilimes``); the setup script routes it to ``fab_ops``."""
    lines = [f"-- {line}" for line in header]
    for table, columns in DDL.items():
        lines.append(f"CREATE TABLE resilimes.{table} ({columns});")
        for chunk in _chunks(tables.get(table, []), 500):
            values = ",\n".join("(" + ", ".join(_literal(v) for v in row) + ")" for row in chunk)
            lines.append(f"INSERT INTO resilimes.{table} VALUES\n{values};")
    return "\n".join(lines) + "\n"
