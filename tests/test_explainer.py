"""Late-lot explainer: exact lateness split, waits, counterfactual re-run, API."""

from __future__ import annotations

import json

import pytest
from tests.test_investigator import Scripted

from resilimes.evidence.lateness import late_lots
from resilimes.evidence.toolkit import HOUR, Toolkit, record_run
from resilimes.insight.explainer import exact_split, explain, verify
from resilimes.insight.study import summarize_explainer
from resilimes.smt.fab import load_fab


@pytest.fixture(scope="module")
def fab():
    return load_fab()


@pytest.fixture(scope="module")
def run24(fab):
    return record_run(fab, seed=1, horizon=24 * HOUR)


def test_every_late_lot_splits_exactly(run24):
    lots = late_lots(run24.timeline)
    assert lots, "a 24 h run should have late lots"
    kit = Toolkit(run24)
    for lot in lots:
        split = exact_split(run24, lot)
        assert split["exact"] and split["shown_sum_ok"], split
        assert abs(split["residual_sec"]) < 1e-6
        shown = kit.lot_lateness(run24.fab.lot_id[lot])
        assert abs(sum(shown["while_late_min"].values()) - shown["late_min"]) < 0.051


def test_lot_waits_are_bounded_by_the_stay(run24):
    lot = late_lots(run24.timeline)[0]
    waits = Toolkit(run24).lot_waits(run24.fab.lot_id[lot])
    assert waits["steps_waited"] >= len(waits["longest_waits"])
    for row in waits["longest_waits"]:
        assert row["wait_min"] >= 0 and row["to_h"] >= row["from_h"]
        assert abs(sum(row["buckets_min"].values()) - row["wait_min"]) < 0.2


def test_drop_downs_removes_overlapping_spans(fab, run24):
    tool = next(i for i, spans in enumerate(run24.downs) if spans)
    rerun = record_run(fab, seed=1, horizon=24 * HOUR, drop_downs={tool: [(0.0, 24 * HOUR)]})
    assert rerun.downs[tool] == []
    other = [i for i, spans in enumerate(run24.downs) if spans and i != tool]
    assert all(rerun.downs[i] == run24.downs[i] for i in other)


def test_mock_explain_and_verify(run24):
    lot = late_lots(run24.timeline)[0]
    lot_id = run24.fab.lot_id[lot]
    answer = explain(Toolkit(run24), lot_id, None)
    assert answer.mocked and answer.lever and answer.fact_ok, answer
    cf = verify(run24, lot_id, answer)
    assert cf["verified"] and cf["late_before_min"] > 0
    assert cf["saving_min"] == pytest.approx(cf["late_before_min"] - cf["late_after_min"], abs=0.11)
    row = {
        "seed": 1,
        "lot": lot_id,
        "split": exact_split(run24, lot),
        "true_dominant": answer.dominant,
        "ai": answer.to_json(),
        "cf": cf,
    }
    summary = summarize_explainer([row], "mock")
    assert summary["exact_sum"] == 1 and summary["cf_verified"] == 1


def test_invalid_lever_is_rejected_after_repairs(run24):
    lot_id = run24.fab.lot_id[late_lots(run24.timeline)[0]]
    bad = json.dumps(
        {
            "explanation": "It waited.",
            "dominant": "lots_ahead",
            "counterfactual": {"lever": "buy_more_tools", "expected_saving_min": 30},
        }
    )
    provider = Scripted([bad])
    answer = explain(Toolkit(run24), lot_id, provider)
    assert answer.lever is None and answer.error
    assert provider.seen == 3  # first try + 2 schema repairs


def test_api_lists_and_explains_late_lots():
    from fastapi.testclient import TestClient

    from resilimes.api.app import create_app
    from resilimes.config import Settings

    client = TestClient(create_app(Settings(mode="mock")))
    lots = client.get("/api/ai/explainer/lots?seed=1").json()["lots"]
    assert len(lots) >= 20
    body = client.post("/api/ai/explain", json={"lot_id": lots[0]["lot"], "lang": "ja"}).json()
    assert body["advice_only"] and body["split"]["exact"]
    assert body["answer"]["mocked"] and body["counterfactual"]["verified"]
    assert client.post("/api/ai/explain", json={"lot_id": "nope"}).status_code == 404
    assert client.post("/api/ai/explain", json={"lot_id": "x", "lang": "fr"}).status_code == 422


def test_model_audit_flags_non_nemotron_responses():
    from resilimes.insight.study import is_nemotron, model_audit

    rows = [
        {
            "lot": "A_1",
            "ai": {"response_models": ["nvidia/nemotron-3-super", "nvidia/nemotron-3-super"]},
        },
        {"lot": "B_2", "ai": {"response_models": ["gpt-4o-mini"]}},
        {"lot": "C_3", "ai": {"response_models": ["unreported:nvidia/nemotron-3-super"]}},
        {"lot": "D_4", "error": "x"},
    ]
    audit = model_audit(rows)
    assert audit["responses"] == 4 and audit["non_nemotron_responses"] == 2
    assert audit["non_nemotron_items"] == ["B_2", "C_3"]
    assert is_nemotron("NVIDIA/Nemotron-Nano") and not is_nemotron("")


def test_explainer_records_the_reported_model(run24):
    lot_id = run24.fab.lot_id[late_lots(run24.timeline)[0]]
    answer = explain(Toolkit(run24), lot_id, Scripted(["not json"]))
    assert answer.response_models and all(
        m.startswith("unreported:") for m in answer.response_models
    )
