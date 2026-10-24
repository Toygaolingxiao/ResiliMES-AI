"""Verified Zetaris REST shape, source map, and datasource split."""

from __future__ import annotations

from pathlib import Path
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
from resilimes.data.zetaris_admin import (
    _read_env_file,
    api_key_body,
    credentials,
    login_body,
    register,
)
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
    assert 'DESCRIBE BY "ResiliMES_MES.fab_mes"' in create
    assert (
        'DESCRIBE BY "Maintenance_CMMS.fab_cmms"'
        in datasource_ddl("fab_cmms", user="fab", password="abc123")[1]
    )
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
        if sql == "SHOW DATASOURCES":
            return 200, {"headers": ["name"], "data": [["fab_cmms"], ["fab_erp"]], "total": 2}
        if sql.startswith("SHOW TABLES FROM"):
            return 200, {"headers": ["name"], "data": [["resilimes.machines"]], "total": 1}
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
    # resilimes is not registered yet, so its DROP is never sent; fab_cmms is, and its
    # DROP returning 400 is tolerated.
    assert "drop fab_mes skipped (not registered)" in blob
    assert "drop fab_cmms skipped status=400" in blob
    assert "datasource resilimes -> fab_mes.resilimes: 1 tables machines" in blob
    assert "probe federated status=200 rows=1 cols=1" in blob
    sql_calls = [item for item in calls if item[0].endswith("/sql-editor/sqls/run-query")]
    assert sql_calls[0][1] == {"sql": "SHOW DATASOURCES"}
    assert not any(item[1]["sql"] == "DROP DATASOURCE resilimes" for item in sql_calls)
    # Like the owner's script: the setup SQL runs with the login token, not an API key.
    for _, body, headers in sql_calls:
        assert headers["Authorization"] == "Bearer jwt-token"
        assert headers["X-Org-ID"] == "1"
        assert headers["X-Request-ID"]
        assert set(body) == {"sql"}
    assert calls[-1][0].endswith("/auth/api-key")


def test_register_keeps_an_existing_key_and_survives_a_failed_mint() -> None:
    def post(
        url: str, body: dict[str, object], headers: dict[str, str]
    ) -> tuple[int, dict[str, object]]:
        if url.endswith("/api/auth/login"):
            return 200, {"idToken": "jwt-token", "orgId": 7}
        if url.endswith("/auth/api-key"):
            return 403, {"msg": "nope"}
        return 200, {"headers": ["c"], "data": [["1"]], "total": 1}

    common = {
        "base_url": "http://localhost:3000",
        "rest_url": "http://127.0.0.1:8888/api/v1.0",
        "email": "a@b.c",
        "password": "pw",
        "jdbc_user": "fab",
        "jdbc_password": "dbpw",
    }
    lines, key = register(post, **common)  # type: ignore[arg-type]
    assert key == ""
    assert any("api key not created status=403" in line for line in lines)
    assert not any(line.startswith(("sql failed", "login failed")) for line in lines)
    lines, key = register(post, api_key="kept-key", **common)  # type: ignore[arg-type]
    assert key == "kept-key"
    assert not any("api key" in line for line in lines)


def test_credentials_prefer_fab_pg_names_and_fall_back_to_postgres(tmp_path: Path) -> None:
    new = tmp_path / "env"
    new.write_bytes(
        b"FAB_PG_USER=fab\r\nFAB_PG_PASSWORD=Abc123\r\nZETARIS_USER=z@x.io\r\n"
        b"ZETARIS_PASSWORD=zpw\r\nexport ZETARIS_API=http://127.0.0.1:9999/api/v1.0\r\n"
    )
    found = credentials({}, _read_env_file(new), {})
    assert found["jdbc_user"] == "fab"
    assert found["jdbc_password"] == "Abc123"
    assert found["email"] == "z@x.io"
    assert found["password"] == "zpw"
    assert found["rest_url"] == "http://127.0.0.1:9999/api/v1.0"
    assert found["base_url"] == "http://localhost:3000"

    old = {"POSTGRES_USER": "olduser", "POSTGRES_PASSWORD": "oldpw"}
    admin = {"ZETARIS_ADMIN_EMAIL": "admin@zetaris.com", "ZETARIS_ADMIN_PASSWORD": "apw"}
    found = credentials(admin, old, {"ZETARIS_REST_URL": "http://h/api/v1.0"})
    assert (found["jdbc_user"], found["jdbc_password"]) == ("olduser", "oldpw")
    assert (found["email"], found["password"]) == ("admin@zetaris.com", "apw")
    assert found["rest_url"] == "http://h/api/v1.0"
    both = {**old, "FAB_PG_USER": "fab", "FAB_PG_PASSWORD": "newpw"}
    assert credentials({}, both, {})["jdbc_password"] == "newpw"
    assert credentials({}, {}, {})["email"] == "admin@zetaris.com"


def test_splitter_ignores_semicolons_in_comments_quotes_and_identifiers() -> None:
    from resilimes.data.zetaris_layout import _sql_statements

    sql = (
        "-- header; run: python scripts/export_zetaris_sql.py\n"
        "--\n"
        "/* block; comment /* nested; */ still; */\n"
        "INSERT INTO resilimes.bom VALUES ('a;b', 'it''s; fine', '-- not; a comment');\n"
        'CREATE TABLE resilimes."odd;name" (x TEXT); -- trailing; note\n'
        "/* only a comment; */ -- and another;\n"
    )
    statements = _sql_statements(sql)
    assert statements == [
        "INSERT INTO resilimes.bom VALUES ('a;b', 'it''s; fine', '-- not; a comment')",
        'CREATE TABLE resilimes."odd;name" (x TEXT)',
    ]
    with pytest.raises(ValueError):
        _sql_statements("SELECT 'open;")
    with pytest.raises(ValueError):
        _sql_statements("/* open; SELECT 1;")


_SQL_START = ("CREATE ", "DROP ", "INSERT ", "ALTER ", "COMMENT ", "UPDATE ", "DELETE ")


def test_write_split_on_the_committed_seeds_emits_only_sql(tmp_path: Path) -> None:
    from resilimes.config import ROOT
    from resilimes.data.zetaris_layout import tables_in

    sql_dir = ROOT / "data" / "sql"
    seeds = [sql_dir / "seed.sql", sql_dir / "smt2020_seed.sql", sql_dir / "kernel.sql"]
    # The header that broke the PC load: a ';' inside a '--' comment.
    assert "hand; run:" in seeds[0].read_text(encoding="utf-8")
    written = write_split(seeds, tmp_path)
    assert sorted(written) == ["fab_cmms", "fab_erp", "fab_mes"]
    from resilimes.data.zetaris_layout import _sql_statements

    for database, path in written.items():
        statements = _sql_statements(path.read_text(encoding="utf-8"))
        assert statements[:2] == [
            "DROP SCHEMA IF EXISTS resilimes CASCADE",
            "CREATE SCHEMA resilimes",
        ]
        for statement in statements:
            assert statement.upper().startswith(_SQL_START), (database, statement[:80])
            assert "run: python" not in statement
    assert len(tables_in(seeds)) == 30
    scale = sql_dir / "scale_seed.sql"
    if scale.is_file():
        for statement in _sql_statements(scale.read_text(encoding="utf-8")):
            assert statement.upper().startswith(_SQL_START), statement[:80]


def _pg_bin() -> Path | None:
    import shutil

    found = shutil.which("pg_ctl")
    if found:
        return Path(found).parent
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin/pg_ctl"))
    return candidates[-1].parent if candidates else None


@pytest.mark.skipif(_pg_bin() is None, reason="no local PostgreSQL binaries")
def test_split_files_load_into_a_real_postgres(tmp_path: Path) -> None:
    """Apply all three split files with ON_ERROR_STOP to a throwaway local cluster."""
    import os
    import subprocess

    from resilimes.config import ROOT

    if os.geteuid() == 0:
        pytest.skip("initdb refuses to run as root")
    bin_dir = _pg_bin()
    assert bin_dir is not None
    sql_dir = ROOT / "data" / "sql"
    written = write_split(
        [sql_dir / "seed.sql", sql_dir / "smt2020_seed.sql", sql_dir / "kernel.sql"],
        tmp_path / "split",
    )
    data = tmp_path / "pgdata"
    sock = tmp_path / "sock"
    sock.mkdir()
    run = subprocess.run
    run(
        [str(bin_dir / "initdb"), "-D", str(data), "-U", "fab", "-A", "trust"],
        check=True,
        capture_output=True,
    )
    options = f"-c listen_addresses='' -c unix_socket_directories={sock}"
    # The server must not inherit our pipes, or run() waits for it to exit.
    run(
        [
            str(bin_dir / "pg_ctl"),
            *("-D", str(data), "-o", options, "-l", str(tmp_path / "pg.log"), "-w", "start"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
    try:
        psql = [str(bin_dir / "psql"), "-h", str(sock), "-U", "fab", "-X", "-q"]
        counts: dict[str, int] = {}
        for database, path in written.items():
            run(
                [*psql, "-d", "postgres", "-c", f"CREATE DATABASE {database}"],
                check=True,
                capture_output=True,
                timeout=60,
            )
            for _ in range(2):  # a reload over an existing schema must also apply
                run(
                    [*psql, "-v", "ON_ERROR_STOP=1", "-d", database, "-f", str(path)],
                    check=True,
                    capture_output=True,
                )
            out = run(
                [
                    *psql,
                    "-At",
                    "-d",
                    database,
                    "-c",
                    "select count(*) from pg_tables where schemaname='resilimes'",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            counts[database] = int(out.stdout.strip())
        assert sum(counts.values()) == 30
        assert all(counts.values())
        rows = run(
            [*psql, "-At", "-d", "fab_mes", "-c", "select count(*) from resilimes.smt_route"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert int(rows.stdout.strip()) == 4013
    finally:
        run(
            [str(bin_dir / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"],
            check=False,
            capture_output=True,
            timeout=60,
        )
