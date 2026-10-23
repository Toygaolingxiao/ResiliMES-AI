"""Qualitative panel, explain fallback, and commit refusal."""

from __future__ import annotations

import json
from typing import Any

import pytest

from resilimes.agents.feedback import write_feedback
from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.agents.review_panel import run_review_panel
from resilimes.config import HORIZON, Settings
from resilimes.data.factory import build_source
from resilimes.domain.critique import critique_schedule
from resilimes.domain.models import Critique, Violation
from resilimes.domain.schedule import POLICY_RECOVER, schedule_plant
from resilimes.llm.base import LlmResult
from resilimes.llm.mock import MockProvider


def _settings() -> Settings:
    return Settings(mode="mock", horizon=HORIZON, scout_signing_secret="guard-secret")


class Scripted:
    name = "script"
    mocked = False

    def __init__(self, content: str, request_id: str = "req-script") -> None:
        self.content = content
        self.request_id = request_id
        self.lanes: list[str] = []

    def model_for(self, lane: str) -> str:
        return "script-model"

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lane: str,
        temperature: float = 0.0,
    ) -> LlmResult:
        del messages, temperature
        self.lanes.append(lane)
        return LlmResult(
            content=self.content,
            model=self.model_for(lane),
            provider=self.name,
            lane=lane,
            latency_ms=1.0,
            mocked=False,
            meterless_request_id=self.request_id,
        )


def test_panel_fallback_is_labeled_and_does_not_require_a_model() -> None:
    settings = _settings()
    plant, _records = build_source(settings).load_plant(settings.horizon)
    book = schedule_plant(plant, POLICY_RECOVER)
    critique = critique_schedule(plant, book)
    panel = run_review_panel(MockProvider(), plant, book, critique, allow_model=False)
    assert panel["source"] == "deterministic-fallback"
    assert panel["agreement"] in {"unanimous", "majority", "split"}
    assert len(panel["reviewers"]) == 3
    assert "do not change" in panel["note"]
    for reviewer in panel["reviewers"]:
        assert reviewer["source"] == "deterministic-fallback"
        assert reviewer["meterless_request_id"] == ""


def test_hallucinated_review_ids_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    settings = _settings()
    plant, _records = build_source(settings).load_plant(settings.horizon)
    book = schedule_plant(plant, POLICY_RECOVER)
    critique = critique_schedule(plant, book)
    scripted = Scripted(
        json.dumps(
            {
                "verdict": "reject",
                "concerns": [{"detail": "LOT-9999 is imaginary.", "ids": ["LOT-9999"]}],
                "suggestions": ["Move LOT-9999."],
            }
        )
    )
    panel = run_review_panel(scripted, plant, book, critique, allow_model=True)
    assert set(scripted.lanes) == {"review.process", "review.production", "review.risk"}
    assert len(scripted.lanes) == 3
    assert panel["source"] == "deterministic-fallback"
    for reviewer in panel["reviewers"]:
        assert reviewer["source"] == "deterministic-fallback"
        assert "LOT-9999" in reviewer["hallucinated_ids"][0]
        assert reviewer["meterless_request_id"] == "req-script"


def test_feedback_rejects_a_number_the_engine_did_not_return() -> None:
    settings = _settings()
    plant, _records = build_source(settings).load_plant(settings.horizon)
    execution = {
        "committed": True,
        "critique": {"verdict": "accept"},
        "affected_lots": [{"lot_id": "LOT-1004"}],
        "kpis": {
            "before": {
                "on_time_delivery_pct": 80.0,
                "weighted_tardiness_min": 10.0,
                "makespan_min": 100,
                "utilization_pct": 50.0,
                "lots_at_risk": 1,
                "setup_changes": 0,
                "mean_remaining_flow_min": 20.0,
                "late_lots": [],
                "unscheduled_lots": [],
            },
            "after": {
                "on_time_delivery_pct": 90.0,
                "weighted_tardiness_min": 4.0,
                "makespan_min": 110,
                "utilization_pct": 55.0,
                "lots_at_risk": 0,
                "setup_changes": 1,
                "mean_remaining_flow_min": 18.0,
                "late_lots": [],
                "unscheduled_lots": [],
            },
        },
        "errors": [],
    }
    bad = Scripted(json.dumps({"feedback": "Tardiness improved by 99999 minutes on LOT-1004."}))
    written = write_feedback(bad, plant, execution)
    assert written["source"] == "deterministic-fallback"
    assert written["narrative_degraded"] is True
    assert "99999" not in written["feedback"]
    assert written["meterless_request_id"] == "req-script"
    clean = Scripted(json.dumps({"feedback": "LOT-1004 stays in the book. Critic verdict accept."}))
    verified = write_feedback(clean, plant, execution)
    assert verified["source"] == "nemotron"
    assert verified["verified"] is True
    assert verified["narrative_degraded"] is False


def test_commit_refuses_a_reject_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    def _reject(plant: Any, schedule: Any) -> Critique:
        del plant, schedule
        return Critique(
            verdict="reject",
            score=0.0,
            violations=[
                Violation(
                    constraint="equipment_status",
                    severity="high",
                    detail="forced reject",
                    fix_hint="Do not commit.",
                )
            ],
            rationale="Hard constraints failed.",
        )

    monkeypatch.setattr("resilimes.agents.orchestrator.critique_schedule", _reject)
    report = run_recovery(_settings(), RecoverInput(scenario="litho_down"))
    assert report.world_model["refused"] is True
    assert report.world_model["replay_jobs"] == 0
    assert report.world_model["events"] == 0
    assert report.markovian["chunks"] == 5
    assert report.markovian["failed_chunks"] == 0


def test_explain_falls_back_when_nightshift_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Raising(MockProvider):
        def complete(
            self,
            messages: list[dict[str, str]],
            *,
            lane: str,
            temperature: float = 0.0,
        ) -> LlmResult:
            del messages, lane, temperature
            raise RuntimeError("nightshift down")

    monkeypatch.setattr(
        "resilimes.agents.orchestrator.build_provider",
        lambda settings: _Raising(),
    )
    report = run_recovery(_settings(), RecoverInput(scenario="litho_down"))
    assert report.provider_call is not None
    assert report.provider_call["narrative_degraded"] is True
    assert "LOT-1001" in report.narrative
    assert report.markovian["chunks"] == 5
    assert report.markovian["failed_chunks"] == 0
    assert report.rejected_alternative is not None
    assert report.rejected_alternative["label"] == "safety test"
    assert report.propose_loop is not None
    assert report.propose_loop["rounds"] == []
    assert "checkpoint tokens" not in json.dumps(report.markovian)
