"""An MES event log says which evidence tier it can reach, then becomes a run record."""

from __future__ import annotations

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.explain.ingest import ingest_text

DECISION = """\
lot,step,tool,event_type,timestamp,decision,due
L1,0,EQ1,start,0,,120
L1,0,EQ1,end,300,hot lot,120
"""

EVENTS_ONLY = """\
lot,step,tool,event type,timestamp
L1,0,EQ1,track_in,0
L1,0,EQ1,track_out,50
"""

MISSING = """\
lot,tool,event_type,timestamp
L1,EQ1,start,0
"""

JSONL = """\
{"lot":"L1","step":0,"tool":"EQ1","event_type":"start","timestamp":"2026-01-01T00:00:00Z","due":"2026-01-01T00:02:00Z"}
{"lot":"L1","step":0,"tool":"EQ1","event_type":"end","timestamp":"2026-01-01T00:05:00Z","reason":"qtime"}
"""


def test_decision_rows_can_reach_recorded_and_the_split_runs():
    result = ingest_text(DECISION, "lots.csv")
    assert result.ceiling == "recorded"
    assert result.missing == []
    assert result.decision_rows == 1
    assert result.has_due is True
    assert result.record is not None
    assert result.report is not None
    assert result.report["verified"] is True
    assert result.report["content_hash"].startswith("sha256:")
    assert result.report["schema_version"] == "evidence/v0"
    lateness = next(row for row in result.report["statements"] if row["key"] == "lateness")
    assert lateness["tier"] == "recorded"
    assert lateness["sources"]
    assert lateness["value"] == 180.0
    assert result.record.notes["decisions"][0]["decision"] == "hot lot"


def test_events_only_stop_at_attributed_and_name_the_missing_due():
    result = ingest_text(EVENTS_ONLY)
    assert result.ceiling == "attributed"
    assert result.decision_rows == 0
    assert result.has_due is False
    assert result.report is not None
    assert result.report["verified"] is True
    unknown = [row for row in result.report["statements"] if row["tier"] == "unknown"]
    assert unknown
    assert unknown[0]["reason"] == "the log has no due time"
    assert unknown[0]["sources"] == []


def test_missing_required_field_is_unknown_and_lists_it():
    result = ingest_text(MISSING)
    assert result.ceiling == "unknown"
    assert "step" in result.missing
    assert result.record is None
    assert result.report is None


def test_json_lines_and_an_unknown_event_type():
    result = ingest_text(JSONL, "log.jsonl")
    assert result.ceiling == "recorded"
    assert result.report is not None
    assert result.report["verified"] is True
    lateness = next(row for row in result.report["statements"] if row["key"] == "lateness")
    assert lateness["value"] == 180.0
    odd = ingest_text(
        "lot,step,tool,event_type,timestamp\nL1,0,EQ1,scratch,10\n",
    )
    assert odd.ceiling == "attributed"
    assert odd.unrecognised == ["scratch"]


def test_blank_required_value_names_the_row():
    text = "lot,step,tool,event_type,timestamp\nL1,0,,start,1\n"
    result = ingest_text(text)
    assert result.ceiling == "unknown"
    assert any(item.startswith("tool (rows ") for item in result.missing)


def test_import_route_accepts_a_file_and_the_page_is_linked():
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    response = client.post(
        "/api/explain/import",
        json={"filename": "lots.csv", "text": DECISION},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ceiling"] == "recorded"
    assert body["report"]["verified"] is True
    checked = client.post("/api/explain/report/verify", json=body["report"]["bundle"])
    assert checked.json()["verified"] is True
    page = client.get("/import")
    assert page.status_code == 200
    assert "/assets/product/import/import.js" in page.text
    index = client.get("/")
    assert 'id="import-link"' in index.text
    assert 'href="/import"' in index.text
    assert 'id="panel-recover"' in index.text
