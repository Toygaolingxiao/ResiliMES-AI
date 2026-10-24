"""Shift handover report: 2 h chunks on the Markovian engine, fact check, recall, API."""

from __future__ import annotations

import json

import pytest
from tests.test_investigator import Scripted

from resilimes.insight import handover as ho
from resilimes.insight.explainer import base_run
from resilimes.insight.study import summarize_handover
from resilimes.smt.fab import load_fab


@pytest.fixture(scope="module")
def run48():
    return base_run(load_fab(), 1)


@pytest.mark.parametrize("language", ["en", "zh", "ja"])
def test_mock_handover_is_complete_and_checked(run48, language):
    result = ho.handover(run48, 12.0, None, language=language)
    assert result["engine"] == "markovian", result["error"]
    assert result["chunks_ok"] == len(result["chunks"]) == 7  # six 2 h chunks + compose
    assert result["fact_ok"] and result["fact_misses"] == []
    assert result["must_mention"] and result["must_recall"] == 1.0
    assert result["checkpoint_units"] > 0 and result["advice_only"]
    for heading in ho.HEADINGS[language].values():
        assert heading in result["markdown"]
    assert len(result["chunk_notes"]) == 6


def test_end_facts_are_grounded(run48):
    end = ho.end_facts(run48, 24.0, 36.0)
    ids = set(run48.fab.lot_id)
    assert all(lot in ids for lot in end["must_mention"]["lots"])
    for row in end["tools_down_at_end"]:
        assert row["since_h"] <= 36.0 < row["eta_h"]
    assert all(row["slack_h"] < 2 for row in end["at_risk_lots"])
    keys = {(r["lot"], r["tool"], r["at_h"]) for r in end["overrides"]}
    assert len(keys) == len(end["overrides"])
    if not end["next_shift_pm"]:
        assert end["next_calendar_pm"] and end["next_calendar_pm"][0]["from_h"] >= 36.0


def test_refused_contract_falls_back_to_own_loop(run48, monkeypatch):
    original = ho.handover_contract
    monkeypatch.setattr(ho, "handover_contract", lambda secret, minutes=30: original("not-it"))
    result = ho.handover(run48, 12.0, None, language="en")
    assert result["engine"] == "own_loop"
    assert result["fact_ok"] and result["must_recall"] == 1.0


def test_invented_numbers_are_flagged_not_passed(run48):
    report = {
        "summary": "Tool XX_1-1 down for 987.6 h.",
        **{key: [] for key in ho.SECTIONS},
    }
    provider = Scripted([json.dumps(report)])
    result = ho.handover(run48, 12.0, provider, language="en")
    assert result["repaired"] and not result["fact_ok"]
    assert "987.6" in " ".join(result["fact_misses"])
    assert result["must_recall"] < 1.0
    assert all(m.startswith("unreported:") for m in result["response_models"])
    row = {"id": "s1-12h-en", "ai": result}
    summary = summarize_handover([row], "test")
    assert summary["fact_ok"] == 0 and summary["model_audit"]["non_nemotron_responses"] > 0


def test_api_handover():
    from fastapi.testclient import TestClient

    from resilimes.api.app import create_app
    from resilimes.config import Settings

    client = TestClient(create_app(Settings(mode="mock")))
    shifts = client.get("/api/ai/handover/shifts").json()
    assert len(shifts["shifts"]) == 4 and shifts["languages"] == ["en", "zh", "ja"]
    body = client.post("/api/ai/handover", json={"seed": 1, "start_h": 12, "lang": "zh"}).json()
    assert body["engine"] == "markovian" and body["fact_ok"] and body["mocked"]
    assert client.post("/api/ai/handover", json={"lang": "fr"}).status_code == 422
    assert client.post("/api/ai/handover", json={"start_h": 40}).status_code == 422
