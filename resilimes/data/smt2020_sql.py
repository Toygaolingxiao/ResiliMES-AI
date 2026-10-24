"""SMT2020 master data as raw SQL tables, and a row reader for Zetaris.

One table per SMT2020 file. Columns are the file headers, lower-cased and made
safe as identifiers, every value TEXT exactly as written in the file.
``line_no`` (1-based, header excluded) keeps the file order. The ten route
files share one table, ``smt_route``, with a ``route_file`` column.

Two catalog tables describe the load:

* ``smt_files``: file name, table, row count, and SHA-256 of the source file.
* ``smt_columns``: table, position, column name, original header.

The reader asks Zetaris for the catalog first, then one ``SELECT ... ORDER BY
line_no`` per table it needs, and returns the same ``dict[str, str]`` rows as
``csv.DictReader`` on the file. Row counts are checked against ``smt_files`` so
a server-side row cap cannot pass silently.

Ownership mirrors a fab's fragmented systems: MES tables in ``fab_mes``
(datasource ``resilimes``), PM and breakdown calendars in ``fab_cmms``, the
order book in ``fab_erp``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resilimes.data.sample_source import QueryRecord
from resilimes.data.zetaris_layout import (
    SMT_DATABASE_FOR_TABLE,
    SMT_TABLE_SOURCES,
    qualify,
    validate_ident,
)


@dataclass(frozen=True)
class SmtTable:
    table: str
    files: tuple[str, ...]
    database: str


ROUTE_FILES = tuple(f"route_{n}.txt" for n in range(1, 11))

SMT_TABLES: tuple[SmtTable, ...] = (
    SmtTable("smt_tool", ("tool.txt.1l",), "fab_mes"),
    SmtTable("smt_wip", ("WIP.txt",), "fab_mes"),
    SmtTable("smt_part", ("part.txt",), "fab_mes"),
    SmtTable("smt_route", ROUTE_FILES, "fab_mes"),
    SmtTable("smt_setup", ("setup.txt",), "fab_mes"),
    SmtTable("smt_setupgrp", ("setupgrp.txt",), "fab_mes"),
    SmtTable("smt_fromto", ("fromto.txt",), "fab_mes"),
    SmtTable("smt_pmcal", ("pmcal.txt",), "fab_cmms"),
    SmtTable("smt_attach", ("attach.txt",), "fab_cmms"),
    SmtTable("smt_downcal", ("downcal.txt",), "fab_cmms"),
    SmtTable("smt_order", ("order.txt",), "fab_erp"),
)
CATALOG_TABLES = ("smt_files", "smt_columns")
TABLE_FOR_FILE: dict[str, str] = {name: item.table for item in SMT_TABLES for name in item.files}
if {item.table: item.database for item in SMT_TABLES} | dict.fromkeys(
    CATALOG_TABLES, "fab_mes"
) != SMT_DATABASE_FOR_TABLE:
    raise RuntimeError("SMT_TABLES and zetaris_layout.SMT_DATABASE_FOR_TABLE disagree")
META_COLUMNS = ("line_no", "route_file")
# Words that are reserved, or awkward, in Postgres or Spark SQL. A header that
# sanitizes to one of these gets a ``_col`` suffix (DESC -> desc_col).
RESERVED = frozenset(
    {
        "all", "and", "as", "asc", "between", "by", "case", "cast", "check", "column",
        "create", "current", "date", "default", "desc", "distinct", "drop", "else", "end",
        "false", "for", "from", "full", "group", "having", "ignore", "in", "insert",
        "interval", "is", "join", "left", "like", "limit", "not", "null", "on", "or",
        "order", "range", "repeat", "right", "rows", "select", "start", "step", "table",
        "then", "time", "timestamp", "to", "true", "union", "user", "when", "where", "with",
    }
)  # fmt: skip
# Above any table here (smt_route is 4,013 rows). A larger table is refused.
READ_LIMIT = 100_000
INSERT_CHUNK = 500


def sanitize(header: str) -> str:
    """``StepPercent`` -> ``steppercent``, ``RPT#`` -> ``rpt_no``, ``DESC`` -> ``desc_col``."""
    text = header.strip().replace("#", "_no").lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text:
        raise ValueError(f"Header {header!r} has no usable characters")
    if text[0].isdigit():
        text = "c_" + text
    if text in RESERVED or text in META_COLUMNS:
        text += "_col"
    return validate_ident(text, "column")


def read_file(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Headers and rows, the same parse ``fab.py`` uses. Ragged rows are refused."""
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    for number, row in enumerate(rows, start=1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{path.name} line {number + 1} does not match its header")
    return headers, rows


def file_sha256(path: Path) -> str:
    """SHA-256 of the file with CRLF read as LF, so a Windows checkout hashes the same."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def columns_for(headers: list[str], file_name: str) -> list[str]:
    names = [sanitize(item) for item in headers]
    if len(set(names)) != len(names):
        raise ValueError(f"{file_name}: headers collide after sanitizing: {names}")
    return names


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _insert(table: str, columns: list[str], rows: list[list[str]]) -> list[str]:
    out: list[str] = []
    for start in range(0, len(rows), INSERT_CHUNK):
        chunk = rows[start : start + INSERT_CHUNK]
        body = ",\n".join("(" + ", ".join(cells) + ")" for cells in chunk)
        out.append(f"INSERT INTO resilimes.{table} ({', '.join(columns)}) VALUES\n{body};")
    return out


def render_smt_sql(root: Path) -> str:
    """DDL and inserts for every SMT2020 table plus the two catalog tables."""
    lines = [
        "-- SMT2020 LV/HM master data, one raw TEXT table per file.",
        "-- Generated by scripts/export_smt2020_sql.py from data/smt2020. Do not edit.",
        "-- Routed by resilimes.data.zetaris_layout.split_sql: MES tables to fab_mes,",
        "-- smt_pmcal/smt_attach/smt_downcal to fab_cmms, smt_order to fab_erp.",
        "",
    ]
    file_rows: list[list[str]] = []
    column_rows: list[list[str]] = []
    for spec in SMT_TABLES:
        columns: list[str] | None = None
        headers0: list[str] | None = None
        values: list[list[str]] = []
        for file_name in spec.files:
            path = root / file_name
            headers, rows = read_file(path)
            if headers0 is None:
                headers0 = headers
                columns = columns_for(headers, file_name)
            elif headers != headers0:
                raise ValueError(f"{file_name} headers differ from {spec.files[0]}")
            assert columns is not None
            for line_no, row in enumerate(rows, start=1):
                cells = [str(line_no)]
                if len(spec.files) > 1:
                    cells.append(_q(file_name))
                cells.extend(_q(row[header]) for header in headers)
                values.append(cells)
            digest = file_sha256(path)
            file_rows.append([_q(file_name), _q(spec.table), str(len(rows)), _q(digest)])
        assert columns is not None and headers0 is not None
        meta = ["line_no"] + (["route_file"] if len(spec.files) > 1 else [])
        for pos, (name, header) in enumerate(zip(columns, headers0, strict=True), start=1):
            column_rows.append([_q(spec.table), str(pos), _q(name), _q(header)])
        ddl = ["  line_no INTEGER NOT NULL"]
        if len(spec.files) > 1:
            ddl.append("  route_file TEXT NOT NULL")
        ddl.extend(f"  {name} TEXT NOT NULL" for name in columns)
        key = "route_file, line_no" if len(spec.files) > 1 else "line_no"
        ddl.append(f"  PRIMARY KEY ({key})")
        lines.append(f"DROP TABLE IF EXISTS resilimes.{spec.table};")
        lines.append(f"CREATE TABLE resilimes.{spec.table} (\n" + ",\n".join(ddl) + "\n);")
        lines.extend(_insert(spec.table, meta + columns, values))
        lines.append("")
    lines.append("DROP TABLE IF EXISTS resilimes.smt_files;")
    lines.append(
        "CREATE TABLE resilimes.smt_files (\n  file_name TEXT PRIMARY KEY,\n"
        "  table_name TEXT NOT NULL,\n  row_count INTEGER NOT NULL,\n  sha256 TEXT NOT NULL\n);"
    )
    lines.extend(
        _insert("smt_files", ["file_name", "table_name", "row_count", "sha256"], file_rows)
    )
    lines.append("DROP TABLE IF EXISTS resilimes.smt_columns;")
    lines.append(
        "CREATE TABLE resilimes.smt_columns (\n  table_name TEXT NOT NULL,\n"
        "  col_pos INTEGER NOT NULL,\n  column_name TEXT NOT NULL,\n  header TEXT NOT NULL,\n"
        "  PRIMARY KEY (table_name, col_pos)\n);"
    )
    lines.extend(
        _insert("smt_columns", ["table_name", "col_pos", "column_name", "header"], column_rows)
    )
    return "\n".join(lines) + "\n"


class SmtZetarisError(RuntimeError):
    """The SMT2020 tables could not be read through Zetaris, or did not match."""


RunSql = Callable[..., dict[str, Any]]


def _cell(value: Any) -> str:
    # Every file cell is a string, never null; an empty cell is "".
    return "" if value is None else str(value)


class ZetarisRows:
    """``rows(file_name)`` backed by Zetaris, one SELECT per table, cached."""

    name = "zetaris"

    def __init__(
        self,
        run: RunSql | None = None,
        *,
        schema: str = "resilimes",
        sources: Mapping[str, str] | None = None,
        timeout_s: float = 30.0,
        limit: int = READ_LIMIT,
    ) -> None:
        self._run = run
        self._schema = validate_ident(schema, "schema")
        self._sources = dict(sources or {})
        self._timeout_s = timeout_s
        self._limit = int(limit)
        self.records: list[QueryRecord] = []
        self._files: dict[str, tuple[str, int, str]] | None = None
        self._columns: dict[str, list[tuple[str, str]]] = {}
        self._tables: dict[str, dict[str, list[dict[str, str]]]] = {}

    def qualified(self, table: str) -> str:
        return qualify(table, self._schema, self._sources, base=SMT_TABLE_SOURCES)

    def _select(self, name: str, sql: str) -> list[dict[str, str]]:
        run = self._run
        if run is None:
            from agent.tools_zetaris import run_sql

            run = run_sql
        from agent.tools_zetaris import rows_as_dicts

        try:
            payload = run(sql, timeout_s=self._timeout_s, limit=self._limit)
        except Exception as exc:
            raise SmtZetarisError(f"{name}: {exc}") from exc
        rows = [
            {str(k).lower(): _cell(v) for k, v in row.items()} for row in rows_as_dicts(payload)
        ]
        total = payload.get("total") if isinstance(payload, dict) else None
        if isinstance(total, int | str) and str(total).isdigit() and int(total) > len(rows):
            raise SmtZetarisError(f"{name}: Zetaris returned {len(rows)} of {total} rows")
        self.records.append(QueryRecord(name=name, sql=sql, mode="zetaris", row_count=len(rows)))
        return rows

    def catalog(self) -> dict[str, tuple[str, int, str]]:
        """file name -> (table, row count, sha256), from ``smt_files``."""
        if self._files is None:
            sql = (
                "SELECT file_name, table_name, row_count, sha256 FROM "
                f"{self.qualified('smt_files')} ORDER BY file_name LIMIT {self._limit}"
            )
            files = {
                row["file_name"]: (row["table_name"], int(row["row_count"]), row["sha256"])
                for row in self._select("smt_files", sql)
            }
            sql = (
                "SELECT table_name, col_pos, column_name, header FROM "
                f"{self.qualified('smt_columns')} ORDER BY table_name, col_pos LIMIT {self._limit}"
            )
            columns: dict[str, list[tuple[int, str, str]]] = {}
            for row in self._select("smt_columns", sql):
                columns.setdefault(row["table_name"], []).append(
                    (int(row["col_pos"]), row["column_name"].lower(), row["header"])
                )
            self._columns = {
                table: [(name, header) for _pos, name, header in sorted(items)]
                for table, items in columns.items()
            }
            self._files = files
        return self._files

    def _table(self, table: str) -> dict[str, list[dict[str, str]]]:
        cached = self._tables.get(table)
        if cached is not None:
            return cached
        self.catalog()
        spec = next((item for item in SMT_TABLES if item.table == table), None)
        if spec is None:
            raise SmtZetarisError(f"Unknown SMT2020 table {table}")
        columns = self._columns.get(table)
        if not columns:
            raise SmtZetarisError(f"smt_columns has no columns for {table}")
        for name, _header in columns:
            validate_ident(name, "column")
        multi = len(spec.files) > 1
        select = ["line_no"] + (["route_file"] if multi else []) + [name for name, _ in columns]
        order = "route_file, line_no" if multi else "line_no"
        sql = (
            f"SELECT {', '.join(select)} FROM {self.qualified(table)} "
            f"ORDER BY {order} LIMIT {self._limit}"
        )
        raw = self._select(table, sql)
        by_file: dict[str, list[tuple[int, dict[str, str]]]] = {}
        for row in raw:
            file_name = row.get("route_file", "") if multi else spec.files[0]
            missing = [name for name in select if name not in row]
            if missing:
                raise SmtZetarisError(f"{table}: Zetaris rows lack columns {missing}")
            by_file.setdefault(file_name, []).append(
                (int(row["line_no"]), {header: row[name] for name, header in columns})
            )
        out: dict[str, list[dict[str, str]]] = {}
        for file_name in spec.files:
            items = sorted(by_file.get(file_name, []), key=lambda item: item[0])
            expected = self._files[file_name][1] if self._files and file_name in self._files else -1
            if expected < 0:
                raise SmtZetarisError(f"smt_files has no entry for {file_name}")
            numbers = [number for number, _row in items]
            if numbers != list(range(1, expected + 1)):
                raise SmtZetarisError(
                    f"{file_name}: Zetaris returned {len(items)} rows, smt_files says {expected}"
                )
            out[file_name] = [row for _number, row in items]
        self._tables[table] = out
        return out

    def __call__(self, file_name: str) -> list[dict[str, str]]:
        table = TABLE_FOR_FILE.get(file_name.strip())
        if table is None:
            raise SmtZetarisError(f"No SMT2020 table holds {file_name!r}")
        return [dict(row) for row in self._table(table)[file_name.strip()]]


def rows_hash(rows: list[dict[str, str]]) -> str:
    """Order-sensitive SHA-256 of a file's rows (header -> cell)."""
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def parity_report(reader: ZetarisRows, root: Path) -> dict[str, Any]:
    """Per table: rows and a row hash read through Zetaris vs the local files.

    Also checks the ``smt_files`` sha256 against the local file bytes. Holds no
    credentials, so it is safe to print.
    """
    catalog = reader.catalog()
    tables: list[dict[str, Any]] = []
    overall_z = hashlib.sha256()
    overall_f = hashlib.sha256()
    for spec in SMT_TABLES:
        z_rows = 0
        f_rows = 0
        z_hash = hashlib.sha256()
        f_hash = hashlib.sha256()
        sha_ok = True
        for file_name in spec.files:
            path = root / file_name
            local = read_file(path)[1]
            remote = reader(file_name)
            z_rows += len(remote)
            f_rows += len(local)
            z_hash.update(rows_hash(remote).encode())
            f_hash.update(rows_hash(local).encode())
            entry = catalog.get(file_name)
            sha_ok = sha_ok and bool(entry and entry[2] == file_sha256(path))
        z_hex, f_hex = z_hash.hexdigest(), f_hash.hexdigest()
        overall_z.update(z_hex.encode())
        overall_f.update(f_hex.encode())
        tables.append(
            {
                "table": spec.table,
                "datasource": reader.qualified(spec.table).split(".", 1)[0],
                "files": len(spec.files),
                "zetaris_rows": z_rows,
                "file_rows": f_rows,
                "zetaris_hash": z_hex[:16],
                "file_hash": f_hex[:16],
                "file_sha_ok": sha_ok,
                "ok": z_rows == f_rows and z_hex == f_hex and sha_ok,
            }
        )
    return {
        "tables": tables,
        "zetaris_hash": overall_z.hexdigest(),
        "file_hash": overall_f.hexdigest(),
        "ok": all(item["ok"] for item in tables) and overall_z.digest() == overall_f.digest(),
    }
