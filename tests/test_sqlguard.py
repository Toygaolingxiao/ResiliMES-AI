"""Agent SQL guard: SELECT-only, allowlisted tables, LIMIT enforced; local mirror."""

from __future__ import annotations

import pytest

from resilimes.config import Settings
from resilimes.evidence.sqlguard import MAX_LIMIT, SqlRejected, allowlist, guard
from resilimes.evidence.sqlrun import run_guarded


def test_allowlist_covers_four_datasources():
    allowed = allowlist()
    assert set(allowed) == {"resilimes", "fab_cmms", "fab_erp", "fab_ops"}
    assert "ops_events" in allowed["fab_ops"]
    assert "smt_downcal" in allowed["fab_cmms"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT family, SUM(down_tool_h) FROM fab_ops.ops_kpi_hourly GROUP BY family",
        "select * from fab_cmms.smt_downcal limit 5",
        "SELECT e.kind FROM fab_ops.ops_events e JOIN resilimes.smt_tool t ON e.tool = t.STNFAM",
        "WITH x AS (SELECT * FROM fab_ops.ops_events) SELECT kind FROM x",
        "SELECT * FROM fab_ops.ops_events WHERE detail = 'drop table; -- x'",
        "SELECT * FROM (SELECT kind FROM fab_ops.ops_events) s",
    ],
)
def test_accepts_plain_selects(sql):
    out = guard(sql)
    assert out.upper().rstrip().split()[-2] == "LIMIT"


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DELETE FROM fab_ops.ops_events", "only SELECT"),
        ("DROP TABLE fab_ops.ops_events", "only SELECT"),
        ("SELECT 1; DROP TABLE fab_ops.ops_events", "one statement"),
        ("SELECT * FROM fab_ops.ops_events -- hi", "comments"),
        ("SELECT * FROM fab_ops.ops_events /* hi */", "comments"),
        ("SELECT * INTO fab_ops.copy FROM fab_ops.ops_events", "INTO"),
        ("SELECT * FROM ops_events", "<datasource>.<table>"),
        ("SELECT * FROM fab_ops.secret_table", "allowlist"),
        ("SELECT * FROM pg_catalog.pg_user", "allowlist"),
        ("SELECT * FROM fab_ops.ops_events a, fab_erp.orders b", "comma joins"),
        ('SELECT * FROM "fab_ops"."ops_events"', "quoted"),
        ("SELECT pg_sleep(5) FROM fab_ops.ops_events", "PG_SLEEP"),
        ("SELECT * FROM fab_ops.ops_events LIMIT 5 OFFSET 2", "LIMIT"),
        ("SELECT * FROM fab_ops.ops_events WHERE kind = 'x", "unbalanced"),
        ("SHOW DATASOURCES", "only SELECT"),
        ("REGISTER DATASOURCE TABLES FROM fab_ops", "only SELECT"),
        ("", "empty"),
        ("SELECT 1", "no FROM"),
    ],
)
def test_rejects_everything_else(sql, reason):
    with pytest.raises(SqlRejected) as caught:
        guard(sql)
    assert reason.lower() in str(caught.value).lower()


def test_limit_is_clamped_and_appended():
    assert guard("SELECT * FROM fab_ops.ops_events LIMIT 99999").endswith(f"LIMIT {MAX_LIMIT}")
    assert guard("SELECT * FROM fab_ops.ops_events;").endswith("LIMIT 50")
    assert guard("SELECT * FROM fab_ops.ops_events LIMIT 3").endswith("LIMIT 3")


def test_local_mirror_runs_the_same_sql():
    out = run_guarded(
        "SELECT family, SUM(arrivals) AS n FROM fab_ops.ops_kpi_hourly GROUP BY family ORDER BY n DESC",
        _local(),
    )
    assert out["ok"], out
    assert out["source"] == "local_sqlite_mirror"
    assert out["sql"].endswith("LIMIT 50")
    assert out["rows"]
    bad = run_guarded("DELETE FROM fab_ops.ops_events", _local())
    assert not bad["ok"] and bad["error"].startswith("rejected")


def _local() -> Settings:
    from resilimes.config import get_settings

    settings = get_settings()
    assert not settings.use_zetaris, "tests run without Zetaris credentials"
    return settings
