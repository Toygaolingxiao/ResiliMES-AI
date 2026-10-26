"""Read-only /api/ai/notes: endpoint shape, honest labels, the switch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="<redacted>"
    )
    return TestClient(create_app(settings))


def test_notes_endpoint_shape_and_labels(client: TestClient) -> None:
    body = client.get("/api/ai/notes").json()
    assert body["enabled"] is True
    assert body["extractor"] == "scripted"
    assert body["mocked"] is True  # offline stand-in must say so
    assert body["truncated"] is False
    assert len(body["notes"]) == 46
    summary = body["summary"]
    assert summary["notes"] == 46
    assert summary["accepted"] == sum(len(n["events"]) for n in body["notes"])
    assert summary["rejected"] == sum(len(n["rejected"]) for n in body["notes"])
    assert summary["gold_events"] == sum(len(n["gold"]) for n in body["notes"])
    for note in body["notes"]:
        assert note["note_id"].startswith("n")
        assert note["lang"] in ("en", "zh", "ja")
        for event in note["events"]:
            assert event["type"] in (
                "planned_down",
                "priority_change",
                "hold",
                "capacity_derate",
            )
        for rejected in note["rejected"]:
            assert rejected["reason"]


def test_notes_endpoint_scripted_matches_gold_better_than_regex(
    client: TestClient,
) -> None:
    scripted = client.get("/api/ai/notes?extractor=scripted").json()
    regex = client.get("/api/ai/notes?extractor=regex").json()
    assert scripted["summary"]["accepted"] > regex["summary"]["accepted"]


def test_notes_endpoint_live_falls_back_honestly_without_a_model(
    client: TestClient,
) -> None:
    body = client.get("/api/ai/notes?extractor=live&limit=3").json()
    assert body["extractor"] == "scripted"  # no live model in mock settings
    assert body["mocked"] is True
    assert len(body["notes"]) == 3
    assert body["truncated"] is True


def test_notes_endpoint_comparison_null_until_the_run_exists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "absent.json"
    monkeypatch.setenv("RESILIMES_NOTES_AB_JSON", str(missing))
    assert client.get("/api/ai/notes").json()["comparison"] is None

    report = {
        "b_extractor": "llm",
        "comparison": {
            "runner": "live-smt",
            "is_mock": False,
            "arms": {
                arm: {"avoidable_qtime": value, "applied_events": 0}
                for arm, value in (("A", 10), ("B", 4), ("C", 2))
            },
            "gap_closure": 0.75,
            "collateral": {"wrong_events_applied": 0, "new_violations": 0, "target": 0},
        },
        "extraction": {},
    }
    present = tmp_path / "notes_ab.json"
    present.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("RESILIMES_NOTES_AB_JSON", str(present))
    body = client.get("/api/ai/notes").json()
    assert body["comparison"]["gap_closure"] == 0.75
    assert body["comparison"]["is_mock"] is False
    assert body["comparison"]["b_extractor"] == "llm"


def test_notes_endpoint_switch_off_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESILIMES_NOTES_PANEL", "0")
    assert client.get("/api/ai/notes").status_code == 404
