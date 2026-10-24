"""SMT2020 master data in Zetaris: exporter, reader, and file/Zetaris parity.

The fake Zetaris is SQLite with three attached databases named after the
datasources. It runs the generated seed exactly as split by zetaris_setup.sh
and answers the reader's SELECTs with the REST shape: headers, all-string data,
total.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from resilimes.config import ROOT, Settings
from resilimes.data.smt2020_sql import (
    SMT_TABLES,
    TABLE_FOR_FILE,
    SmtZetarisError,
    ZetarisRows,
    read_file,
    render_smt_sql,
    sanitize,
)
from resilimes.data.zetaris_layout import (
    DATABASE_FOR_TABLE,
    DATASOURCE_FOR_DATABASE,
    SMT_DATABASE_FOR_TABLE,
    SMT_TABLE_SOURCES,
    split_sql,
)
from resilimes.smt import fab as fab_module
from resilimes.smt.fab import fab_digest, fab_source, load_fab, load_fab_zetaris

SMT = ROOT / "data" / "smt2020"
SEED = ROOT / "data" / "sql" / "smt2020_seed.sql"


class FakeZetaris:
    def __init__(self, seed: str, *, cap: int | None = None) -> None:
        self.db = sqlite3.connect(":memory:")
        for name in DATASOURCE_FOR_DATABASE.values():
            self.db.execute(f"ATTACH DATABASE ':memory:' AS {name}")
        for database, body in split_sql(seed).items():
            source = DATASOURCE_FOR_DATABASE[database]
            self.db.executescript(body.replace("resilimes.", f"{source}."))
        self.cap = cap
        self.calls: list[tuple[str, int | None]] = []

    def __call__(self, sql: str, *, timeout_s: float | None = None, limit: int | None = None):
        self.calls.append((sql, limit))
        cursor = self.db.execute(sql)
        headers = [item[0] for item in cursor.description]
        data = [["" if cell is None else str(cell) for cell in row] for row in cursor]
        total = len(data)
        if self.cap is not None:
            data = data[: self.cap]
        return {"headers": headers, "data": data, "total": total, "timeUsed": 1}


@pytest.fixture(scope="module")
def seed() -> str:
    return SEED.read_text(encoding="utf-8")


def _settings(**extra: Any) -> Settings:
    return Settings(mode="auto", smt_source="zetaris", **extra)


def test_committed_seed_matches_the_files(seed: str) -> None:
    assert render_smt_sql(SMT) == seed


def test_every_table_has_one_owner_and_routes(seed: str) -> None:
    buckets = split_sql(seed)
    for spec in SMT_TABLES:
        assert DATABASE_FOR_TABLE[spec.table] == spec.database
        assert f"resilimes.{spec.table} " in buckets[spec.database]
        source = SMT_TABLE_SOURCES.get(spec.table, "resilimes")
        assert source == DATASOURCE_FOR_DATABASE[spec.database]
    assert "CREATE TABLE resilimes.smt_pmcal " in buckets["fab_cmms"]
    assert "CREATE TABLE resilimes.smt_pmcal " not in buckets["fab_mes"]
    assert "CREATE TABLE resilimes.smt_order " in buckets["fab_erp"]
    assert "CREATE TABLE resilimes.smt_files " in buckets["fab_mes"]


def test_sanitize_headers() -> None:
    assert sanitize("StepPercent") == "steppercent"
    assert sanitize("STEP_CQT") == "step_cqt"
    assert sanitize("RPT#") == "rpt_no"
    assert sanitize("DESC") == "desc_col"
    assert sanitize("ORDER") == "order_col"
    assert sanitize("line_no") == "line_no_col"
    with pytest.raises(ValueError):
        sanitize("  ")


def test_exporter_refuses_ragged_rows(tmp_path: Path) -> None:
    bad = tmp_path / "part.txt"
    bad.write_text("A\tB\n1\t2\t3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_file(bad)


def test_exporter_quotes_and_orders(tmp_path: Path) -> None:
    for spec in SMT_TABLES:
        for name in spec.files:
            (tmp_path / name).write_bytes((SMT / name).read_bytes())
    part = tmp_path / "part.txt"
    rows = list(csv.reader(part.open(newline=""), delimiter="\t"))
    rows[1][0] = "O'Brien; DROP"
    part.write_text("\n".join("\t".join(row) for row in rows) + "\n", encoding="utf-8")
    fake = FakeZetaris(render_smt_sql(tmp_path))
    reader = ZetarisRows(fake)
    assert reader("part.txt")[0]["PARTGRP"] == "O'Brien; DROP"
    assert reader("part.txt") == read_file(part)[1]


def test_reader_rows_equal_csv_rows(seed: str) -> None:
    reader = ZetarisRows(FakeZetaris(seed))
    for name in TABLE_FOR_FILE:
        assert reader(name) == read_file(SMT / name)[1], name
    catalog = reader.catalog()
    assert catalog["route_3.txt"][0] == "smt_route"
    assert sum(item[1] for item in catalog.values()) == 6935


def test_reader_queries_are_datasource_qualified(seed: str) -> None:
    fake = FakeZetaris(seed)
    reader = ZetarisRows(fake)
    reader("pmcal.txt")
    reader("order.txt")
    reader("route_1.txt")
    reader("route_2.txt")
    sqls = [sql for sql, _limit in fake.calls]
    assert any("FROM fab_cmms.smt_pmcal ORDER BY line_no" in sql for sql in sqls)
    assert any("FROM fab_erp.smt_order" in sql for sql in sqls)
    assert sum("smt_route" in sql for sql in sqls) == 1
    assert all("LIMIT 100000" in sql for sql in sqls)
    assert all(limit == 100000 for _sql, limit in fake.calls)


def test_reader_refuses_a_truncated_table(seed: str) -> None:
    with pytest.raises(SmtZetarisError):
        ZetarisRows(FakeZetaris(seed, cap=1000))("WIP.txt")


def test_reader_refuses_missing_rows(seed: str) -> None:
    fake = FakeZetaris(seed)
    fake.db.execute("DELETE FROM resilimes.smt_wip WHERE line_no = 7")
    with pytest.raises(SmtZetarisError):
        ZetarisRows(fake)("WIP.txt")


def test_fab_via_zetaris_equals_fab_via_files(seed: str) -> None:
    fake = FakeZetaris(seed)
    via_zetaris = load_fab_zetaris(_settings(), fake, cache=False)
    via_files = load_fab(Settings(mode="mock"))
    assert via_zetaris == via_files
    assert fab_digest(via_zetaris) == fab_digest(via_files)
    source = fab_source(via_zetaris)
    assert source["source"] == "zetaris" and source["label"] == "SMT2020 via Zetaris"
    assert {item["table"] for item in source["tables"]} >= {"smt_tool", "smt_route", "smt_wip"}
    assert fab_source(via_files)["source"] == "file"


def test_default_and_mock_are_the_cached_file_fab() -> None:
    first = load_fab(Settings(mode="mock"))
    assert load_fab(Settings(mode="mock", smt_source="auto")) is first
    assert load_fab(Settings(mode="auto", smt_source="file")) is first
    assert load_fab(Settings(mode="auto")) is first  # no Zetaris credentials


def test_auto_falls_back_to_files_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(settings: Settings, run: Any = None, *, cache: bool = True) -> Any:
        raise SmtZetarisError("connection refused")

    calls: list[int] = []

    def counting(settings: Settings, run: Any = None, *, cache: bool = True) -> Any:
        calls.append(1)
        return broken(settings, run, cache=cache)

    monkeypatch.setattr(fab_module, "load_fab_zetaris", counting)
    monkeypatch.setattr(fab_module, "_ZETARIS_FAILED", {})
    live = Settings(
        mode="auto", zetaris_rest_url="http://x", zetaris_org_id="1", zetaris_api_key="k"
    )
    fab = load_fab(live)
    assert fab == load_fab(Settings(mode="mock"))
    source = fab_source(fab)
    assert source["fallback"] is True and source["source"] == "file"
    assert "connection refused" in source["error"]
    assert fab_source(load_fab(Settings(mode="mock")))["fallback"] is False
    assert fab_source(load_fab(live))["fallback"] is True
    assert len(calls) == 1  # a failed read is not retried for RETRY_AFTER_SEC
    with pytest.raises(SmtZetarisError):
        load_fab(live.model_copy(update={"smt_source": "zetaris"}))


def test_env_switch_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    from resilimes.config import ConfigError, load_settings

    monkeypatch.setenv("RESILIMES_SMT_SOURCE", "Zetaris")
    assert load_settings().smt_source == "zetaris"
    monkeypatch.setenv("RESILIMES_SMT_SOURCE", "ftp")
    with pytest.raises(ConfigError):
        load_settings()


def test_api_labels_the_master_data_source(seed: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from resilimes.api.app import create_app

    fake = FakeZetaris(seed)
    via_zetaris = load_fab_zetaris(_settings(), fake, cache=False)
    monkeypatch.setattr(fab_module, "load_fab_zetaris", lambda *a, **k: via_zetaris)
    live = Settings(
        mode="auto",
        smt_source="zetaris",
        zetaris_rest_url="http://x",
        zetaris_org_id="1",
        zetaris_api_key="secret-key-xyz",
    )
    client = TestClient(create_app(live))
    body = client.get("/api/scenarios").json()
    assert body["smt_source"]["label"] == "SMT2020 via Zetaris"
    assert body["smt_source"]["source"] == "zetaris"
    health = client.get("/api/health").json()
    assert health["smt_source"]["source"] == "zetaris"
    assert "secret-key-xyz" not in str(health["smt_source"])


def test_setup_probes_only_loaded_tables() -> None:
    from resilimes.data.zetaris_admin import loaded_tables, select_sql
    from resilimes.data.zetaris_layout import FEDERATED_SQL, tables_in

    smt_only = tables_in([ROOT / "data" / "sql" / "smt2020_seed.sql"])
    assert smt_only == sorted(SMT_DATABASE_FOR_TABLE)
    probes = select_sql(smt_only)
    assert len(probes) == len(SMT_DATABASE_FOR_TABLE)
    assert "fab_cmms.smt_pmcal" in " ".join(probes) and FEDERATED_SQL not in probes
    both = tables_in(
        [ROOT / "data" / "sql" / "seed.sql", ROOT / "data" / "sql" / "smt2020_seed.sql"]
    )
    assert select_sql(loaded_tables(",".join(both)))[-1] == FEDERATED_SQL
    assert loaded_tables("") is None and select_sql(None) == select_sql()
