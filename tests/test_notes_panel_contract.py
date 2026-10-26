"""Notes panel (ai.js) and GET /api/ai/notes (#62) agree on the payload fields.

The panel reads fields off the response by name; a renamed or dropped field
would render as "undefined" or "—" without any error. This test pins every
field name the panel reads to the fields the route actually returns, and
checks the panel's graceful paths (switched off, no notes) are wired.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings

ROOT = Path(__file__).resolve().parents[1]
AI_JS = ROOT / "resilimes/demo/static/ai.js"
I18N = ROOT / "resilimes/demo/static/i18n.json"


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="<redacted>"
    )
    return TestClient(create_app(settings))


def _notes_section() -> str:
    text = AI_JS.read_text(encoding="utf-8")
    start = text.index('id: "notes"')
    end = text.index("async function aiLoad")
    return text[start:end]


def _read(section: str, var: str) -> set[str]:
    return set(re.findall(rf"\b{var}\??\.([a-z_][a-z_0-9]*)", section))


def _comparison_fixture(tmp_path: Path) -> Path:
    report = {
        "b_extractor": "llm",
        "comparison": {
            "runner": "live-smt",
            "is_mock": False,
            "primary_metric": "avoidable_qtime_violations",
            "arms": {
                arm: {
                    "avoidable_qtime": value,
                    "qtime_violations": None,
                    "on_time_pct": None,
                    "completed": None,
                    "applied_events": 0,
                    "unsupported_events": 0,
                }
                for arm, value in (("A", 10), ("B", 4), ("C", 2))
            },
            "gap_closure": 0.75,
            "collateral": {"wrong_events_applied": 0, "new_violations": 0, "target": 0},
        },
    }
    path = tmp_path / "notes_ab.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_every_field_the_panel_reads_is_in_the_route(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RESILIMES_NOTES_AB_JSON", str(_comparison_fixture(tmp_path)))
    body = client.get("/api/ai/notes").json()
    section = _notes_section()

    top = _read(section, "data") - {"loading", "error", "status"}  # client-side states
    assert top <= set(body), top - set(body)
    assert _read(section, "summary") <= set(body["summary"])

    note_keys = set().union(*(n.keys() for n in body["notes"]))
    assert _read(section, "note") <= note_keys, _read(section, "note") - note_keys
    assert _read(section, "rejected") - {"length"} <= {"event", "reason"}

    cmp = body["comparison"]
    assert _read(section, "cmp") <= set(cmp), _read(section, "cmp") - set(cmp)
    assert _read(section, "arm") <= set(cmp["arms"]["A"])
    assert _read(section, "collateral") <= set(cmp["collateral"])


def test_panel_copy_keys_exist_in_all_languages() -> None:
    section = _notes_section()
    used = set(re.findall(r"copy\.([A-Za-z]+)", section))
    i18n = json.loads(I18N.read_text(encoding="utf-8"))
    for lang in ("en", "zh", "ja"):
        missing = used - set(i18n[lang]["ai"])
        assert not missing, (lang, missing)


def test_panel_degrades_when_notes_are_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = _notes_section()
    # Switched off -> 404 -> the panel shows ntUnavailable, not a raw error.
    monkeypatch.setenv("RESILIMES_NOTES_PANEL", "0")
    assert client.get("/api/ai/notes").status_code == 404
    assert "data.status === 404" in section
    assert "copy.ntUnavailable" in section
    # Empty or absent notes list is handled before any note is read.
    assert "!Array.isArray(data.notes)" in section
    # No A/B/C report -> comparison is null and the panel says it has not run.
    assert "copy.ntNotRun" in section


def test_panel_is_loaded_by_the_console() -> None:
    text = AI_JS.read_text(encoding="utf-8")
    assert 'getJson("/api/ai/notes")' in text
    index = (ROOT / "resilimes/demo/static/index.html").read_text(encoding="utf-8")
    assert "ai.js" in index
