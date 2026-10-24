"""Run guarded agent SQL: Zetaris when configured, else a local SQLite mirror.

The mirror loads the same seed files the Zetaris setup script loads
(seed.sql, smt2020_seed.sql, kernel.sql, fab_ops_seed.sql), split by the same
layout, into SQLite databases named like the datasources (``resilimes``,
``fab_cmms``, ``fab_erp``, ``fab_ops``). So ``SELECT ... FROM fab_cmms.smt_downcal``
runs unchanged on both. The connection is opened read-only after loading
(``PRAGMA query_only``), on top of the guard.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from resilimes.config import Settings, get_settings
from resilimes.data.zetaris_layout import DATASOURCE_FOR_DATABASE, split_sql
from resilimes.evidence.sqlguard import SqlRejected, guard

ROOT = Path(__file__).resolve().parents[2]
SEED_FILES = ("seed.sql", "smt2020_seed.sql", "kernel.sql", "fab_ops_seed.sql")
_LOCK = threading.Lock()
_MIRROR: sqlite3.Connection | None = None


def mirror() -> sqlite3.Connection:
    global _MIRROR
    with _LOCK:
        if _MIRROR is not None:
            return _MIRROR
        con = sqlite3.connect(":memory:", check_same_thread=False)
        for source in DATASOURCE_FOR_DATABASE.values():
            if source != "main":
                con.execute(f"ATTACH ':memory:' AS {source}")
        paths = [ROOT / "data" / "sql" / name for name in SEED_FILES]
        text = "\n".join(p.read_text("utf-8").replace("\r\n", "\n") for p in paths if p.is_file())
        for database, body in split_sql(text).items():
            source = DATASOURCE_FOR_DATABASE[database]
            if body.strip():
                con.executescript(
                    body.replace("resilimes.", f"{source}.") if source != "resilimes" else body
                )
        con.execute("PRAGMA query_only = ON")
        _MIRROR = con
        return con


def run_guarded(
    sql: str, settings: Settings | None = None, *, max_rows: int = 200
) -> dict[str, Any]:
    """Guard, then run. Returns columns/rows or ``{"error": ...}`` (never raises on bad SQL)."""
    settings = settings or get_settings()
    try:
        safe = guard(sql, max_limit=max_rows)
    except SqlRejected as exc:
        return {"ok": False, "error": f"rejected: {exc}", "sql": sql}
    if settings.use_zetaris:
        try:
            from agent.tools_zetaris import rows_as_dicts, run_sql

            rows = rows_as_dicts(run_sql(safe, timeout_s=30.0, limit=max_rows))[:max_rows]
            columns = list(rows[0].keys()) if rows else []
            return {
                "ok": True,
                "source": "zetaris",
                "sql": safe,
                "columns": columns,
                "rows": [[row.get(c) for c in columns] for row in rows],
            }
        except Exception as exc:  # network/auth: say so, never echo secrets
            return {
                "ok": False,
                "source": "zetaris",
                "sql": safe,
                "error": f"zetaris error: {type(exc).__name__}",
            }
    try:
        cursor = mirror().execute(safe)
        columns = [item[0] for item in cursor.description or []]
        table = [list(row) for row in cursor.fetchmany(max_rows)]
        return {
            "ok": True,
            "source": "local_sqlite_mirror",
            "sql": safe,
            "columns": columns,
            "rows": table,
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "source": "local_sqlite_mirror",
            "sql": safe,
            "error": f"sql error: {exc}",
        }
