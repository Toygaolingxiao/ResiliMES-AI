"""Verified Zetaris REST shape, source map, and datasource split."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from tests.test_recovery import _settings

from agent.tools_zetaris import ZetarisError, rows_as_dicts, run_sql
from resilimes.api.app import create_app
from resilimes.config import HORIZON, ConfigError, Settings, load_settings
from resilimes.data.factory import build_source
from resilimes.data.sample_source import SampleSource
from resilimes.data.sql_catalog import kernel_statements, statements
from resilimes.data.zetaris_admin import api_key_body, login_body, register
from resilimes.data.zetaris_layout import (
    FEDERATED_SQL,
    datasource_ddl,
    scrub,
    split_sql,
    write_split,
)
from resilimes.data.zetaris_source import ZetarisDataError, ZetarisSource


def test_statements_default_to_the_verified_sources() -> None:
    queries = statements("resilimes")
    assert queries["maintenance_logs"].endswith("FROM fab_cmms.maintenance_logs")
    assert queries["bom"].endswith("FROM fab_erp.bom")
    assert queries["materials"].endswith("FROM fab_erp.materials")
    assert queries["equipment"].endswith("FROM resilimes.equipment")
    assert queries["wip_jobs"].endswith("FROM resilimes.wip_jobs")
    assert all(sql.startswith("SELECT ") for sql in queries.values())
    assert "::" not in "\n".join(queries.values())
    assert "::" not in FEDERATED_SQL
    assert "fab_cmms.maintenance_logs" in FEDERATED_SQL
    assert "fab_erp.materials" in FEDERATED_SQL


def test_source_override_replaces_one_table_and_rejects_bad_names() -> None:
    queries = statements("resilimes", {"bom": "other_erp"})
    assert queries["bom"].endswith("FROM other_erp.bom")
    assert queries["materials"].endswith("FROM fab_erp.materials")
    with pytest.raises(ValueError):
        statements("resilimes", {"bom": "fab erp"})
    with pytest.raises(ValueError):
        statements("resilimes;drop", None)


def test_kernel_statements_follow_ownership() -> None:
    queries = kernel_statements("resilimes")
    assert queries["lots"].endswith("FROM resilimes.lots")
    assert queries["operations"].endswith("FROM resilimes.operations")
    assert queries["setup_matrix"].endswith("FROM resilimes.setup_matrix")
    assert queries["pm_calendar"].endswith("FROM fab_cmms.pm_calendar")
    assert queries["orders"].endswith("FROM fab_erp.orders")
    moved = kernel_statements("resilimes", {"orders": "custom_erp"})
    assert moved["orders"].endswith("FROM custom_erp.orders")


def test_table_sources_env_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZETARIS_TABLE_SOURCES", "")
    monkeypatch.setenv("ZETARIS_TIMEOUT_S", "12.5")
    monkeypatch.setenv("ZETARIS_SQL_PATH", "/sql-editor/sqls/run-query")
    settings = load_settings()
    assert settings.zetaris_table_sources == {}
    assert settings.zetaris_timeout_s == 12.5
    assert settings.zetaris_sql_path == "/sql-editor/sqls/run-query"
    monkeypatch.setenv(
        "ZETARIS_TABLE_SOURCES",
        "maintenance_logs=fab_cmms,bom=fab_erp,materials=fab_erp",
    )
    parsed = load_settings()
    assert parsed.zetaris_table_sources["materials"] == "fab_erp"
    monkeypatch.setenv("ZETARIS_TABLE_SOURCES", "bom=fab erp")
    with pytest.raises(ConfigError):
        load_settings()


def test_run_sql_uses_verified_shape_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZETARIS_REST_URL", "http://127.0.0.1:8888/api/v1.0")
    monkeypatch.setenv("ZETARIS_ORG_ID", "1")
    monkeypatch.setenv("ZETARIS_API_KEY", "test-key")
    monkeypatch.delenv("ZETARIS_SQL_PATH", raising=False)
    monkeypatch.setenv("ZETARIS_TIMEOUT_S", "7")
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {
        "headers": ["equipment_id", "qty"],
        "data": [["LITHO-02", "25"]],
        "total": 1,
        "timeUsed": 0.7,
    }
    with patch("agent.tools_zetaris.requests.post", return_value=ok) as post:
        payload = run_sql("SELECT equipment_id FROM resilimes.equipment")
    assert post.call_args.args[0] == ("http://127.0.0.1:8888/api/v1.0/sql-editor/sqls/run-query")
    assert post.call_args.kwargs["json"] == {"sql": "SELECT equipment_id FROM resilimes.equipment"}
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert post.call_args.kwargs["headers"]["X-Org-ID"] == "1"
    assert post.call_args.kwargs["timeout"] == 7.0
    assert rows_as_dicts(payload) == [{"equipment_id": "LITHO-02", "qty": "25"}]
    with patch("agent.tools_zetaris.requests.post", return_value=ok) as post:
        run_sql("SELECT 1", timeout_s=3)
    assert post.call_args.kwargs["timeout"] == 3
    bad = MagicMock()
    bad.status_code = 400
    bad.text = '{"msg": "parse error"}'
    with (
        patch("agent.tools_zetaris.requests.post", return_value=bad),
        pytest.raises(ZetarisError, match="parse error"),
    ):
        run_sql("NOT SQL")


def test_zetaris_source_receives_the_map_and_timeout() -> None:
    settings = Settings(
        mode="live",
        zetaris_rest_url="http://127.0.0.1:8888/api/v1.0",
        zetaris_org_id="1",
        zetaris_api_key="k",
        zetaris_timeout_s=11,
        zetaris_table_sources={"bom": "custom_erp"},
    )
    source = build_source(settings)
    assert isinstance(source, ZetarisSource)
    assert source._timeout_s == 11
    assert source._sources == {"bom": "custom_erp"}
    captured: list[tuple[str, float]] = []

    def fake_run(sql: str, timeout_s: float | None = None) -> dict[str, object]:
        captured.append((sql, timeout_s or 0))
        return {}

    with (
        patch("agent.tools_zetaris.run_sql", fake_run),
        patch("agent.tools_zetaris.rows_as_dicts", return_value=[]),
        patch("resilimes.data.zetaris_source.plant_from_rows", return_value=MagicMock()),
    ):
        source.load_plant(HORIZON)
    sql = "\n".join(item[0] for item in captured)
    assert "custom_erp.bom" in sql
    assert "fab_cmms.maintenance_logs" in sql
    assert "resilimes.equipment" in sql
    assert captured[0][1] == 11


def test_sample_source_still_loads_and_records_qualified_sql() -> None:
    from resilimes.config import ROOT

    plant, records = SampleSource(ROOT / "data" / "sample").load_plant(HORIZON)
    assert plant.jobs
    assert any(record.sql.endswith("FROM fab_cmms.maintenance_logs") for record in records)
    assert all(record.mode == "sample-equivalent" for record in records)


def test_scenarios_returns_503_when_the_warehouse_fails() -> None:
    source = MagicMock()
    source.load_plant.side_effect = ZetarisDataError("warehouse down")
    with patch("resilimes.api.app.build_source", return_value=source):
        client = TestClient(create_app(_settings()))
        response = client.get("/api/scenarios")
    assert response.status_code == 503
    assert response.json()["detail"] == "warehouse down"


def test_split_keeps_each_database_to_its_own_tables(tmp_path) -> None:
    from resilimes.config import ROOT

    seed = (ROOT / "data" / "sql" / "seed.sql").read_text(encoding="utf-8")
    buckets = split_sql(seed)
    assert "resilimes.maintenance_logs" in buckets["fab_cmms"]
    assert "maintenance_logs" not in buckets["fab_mes"]
    assert "resilimes.bom" in buckets["fab_erp"]
    assert "resilimes.materials" in buckets["fab_erp"]
    assert "resilimes.equipment" in buckets["fab_mes"]
    assert "resilimes.orders" not in buckets["fab_mes"]
    with pytest.raises(ValueError, match="spans databases"):
        split_sql(
            "SELECT * FROM resilimes.equipment e "
            "JOIN resilimes.maintenance_logs m ON e.equipment_id = m.equipment_id;"
        )
    written = write_split([ROOT / "data" / "sql" / "seed.sql"], tmp_path)
    text = written["fab_cmms"].read_text(encoding="utf-8")
    assert text.startswith("DROP SCHEMA IF EXISTS resilimes CASCADE;")
    assert "CREATE SCHEMA resilimes;" in text
    assert "maintenance_logs" in text
    assert "CREATE TABLE resilimes.equipment" not in text


def test_datasource_ddl_matches_the_verified_shape() -> None:
    drop, create, register_sql = datasource_ddl("fab_mes", user="fab", password="abc123")
    assert drop == "DROP DATASOURCE resilimes"
    assert 'DESCRIBE BY "fab_mes.resilimes"' in create
    assert " " not in create.split('DESCRIBE BY "', 1)[1].split('"', 1)[0]
    assert 'jdbcurl "jdbc:postgresql://fab-mes:5432/fab_mes"' in create
    assert 'schema "resilimes"' in create
    assert register_sql == "REGISTER DATASOURCE TABLES FROM resilimes"
    with pytest.raises(ValueError):
        datasource_ddl("fab_mes", user="fab", password="has space")
    assert scrub("password=abc123 user=fab", ["abc123"]) == "password=*** user=fab"


def test_register_scrubs_secrets_and_skips_a_missing_drop() -> None:
    calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def post(
        url: str, body: dict[str, object], headers: dict[str, str]
    ) -> tuple[int, dict[str, object]]:
        calls.append((url, body, headers))
        if url.endswith("/api/auth/login"):
            return 200, {"idToken": "jwt-token", "refreshToken": "refresh", "orgId": 1}
        if url.endswith("/auth/api-key"):
            return 200, {"apiKey": "secret-key"}
        sql = str(body["sql"])
        if sql.startswith("DROP"):
            return 400, {"msg": "missing"}
        if "JOIN" in sql:
            return 200, {
                "headers": ["equipment_id"],
                "data": [["LITHO-02"]],
                "total": 1,
                "timeUsed": 1,
            }
        return 200, {"headers": ["c"], "data": [["1"]], "total": 1, "timeUsed": 0}

    lines, key = register(
        post,
        base_url="http://localhost:3000",
        rest_url="http://127.0.0.1:8888/api/v1.0",
        email="admin@example.com",
        password="admin-secret",
        jdbc_user="fab",
        jdbc_password="dbsecret",
    )
    assert login_body("admin@example.com", "admin-secret")["username"] == "admin@example.com"
    assert api_key_body() == {"name": "resilimes-ai", "expiryDate": "2099-01-01T00:00:00.000Z"}
    assert key == "secret-key"
    blob = "\n".join(lines)
    for secret in ("admin-secret", "dbsecret", "secret-key", "jwt-token", "admin@example.com"):
        assert secret not in blob
    assert "drop fab_mes skipped" in blob
    assert "probe federated status=200 rows=1" in blob
    sql_calls = [item for item in calls if item[0].endswith("/sql-editor/sqls/run-query")]
    assert sql_calls
    assert sql_calls[0][2]["Authorization"] == "Bearer secret-key"
    assert sql_calls[0][2]["X-Org-ID"] == "1"
    assert set(sql_calls[0][1]) == {"sql"}
