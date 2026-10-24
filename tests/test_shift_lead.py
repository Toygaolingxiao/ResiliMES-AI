"""AI shift lead: detection, options, validation and fallback, mock provider, off = identical."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import pytest

from resilimes.agents.shift_lead import (
    HEURISTIC_NAME,
    Decision,
    HeuristicStandIn,
    LlmDecider,
    RuleDefault,
    ShiftLead,
    best_option,
    build_decider,
    build_messages,
    check_option,
    decision_rows,
)
from resilimes.llm.base import LlmResult
from resilimes.llm.mock import MockProvider
from resilimes.smt.exceptions import KINDS, FabException, Impact, Lever, Option
from resilimes.smt.fab import load_fab
from resilimes.smt.invariants import check_trace
from resilimes.smt.qtime_study import _setup
from resilimes.smt.simulate import run_policy

HORIZON_H = "4"
_FAB: list[Any] = []


def _fab() -> Any:
    if not _FAB:
        _FAB.append(load_fab())
    return _FAB[0]


def _run(
    book: str,
    lead: ShiftLead | None,
    monkeypatch: pytest.MonkeyPatch,
    seed: int = 1,
    hours: str = HORIZON_H,
) -> tuple[Any, Any]:
    monkeypatch.setenv("RESILIMES_STUDY_HORIZON_H", hours)
    plant, kwargs = _setup(_fab(), book, seed, "resilimes")
    return run_policy(plant, shift_lead=lead, **kwargs), (plant, kwargs)


def _core(events: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [event for event in events if event[0] != "ai_decision"]


def _impact(q: int = 0, late: int = 0, hot: int = 0, idle: float = 0.0) -> Impact:
    return Impact(qtime_violations=q, late_lots=late, hot_late=hot, idle_min=idle, queue_growth=0)


def _exc(*options: Option) -> FabException:
    return FabException(
        id="X1",
        kind="qtime_competition",
        t=600.0,
        family=0,
        tool=-1,
        lots=[1, 2],
        situation="2 Q-time lots compete",
        facts={},
        options=list(options),
    )


def _three() -> FabException:
    return _exc(
        Option("A", "keep the rule order", Lever(), True, _impact(q=3, idle=5)),
        Option("B", "boost", Lever("prio", prio={(1, 4): -1.0}, until=900.0), False, _impact(q=1)),
        Option("C", "hot first", Lever("prio", prio={(2, 4): -1.0}), False, _impact(q=0, hot=1)),
    )


# Off = bit-identical ---------------------------------------------------------


def test_off_and_rule_default_lead_are_bit_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    off, _ = _run("published", None, monkeypatch)
    again, _ = _run("published", None, monkeypatch)
    lead = ShiftLead(RuleDefault())
    ruled, _ = _run("published", lead, monkeypatch)
    assert off.events == again.events
    assert lead.log, "the published book raises exceptions within 4 h"
    assert _core(ruled.events) == off.events
    for key in ("on_time_pct", "qtime_violations", "completed_routes", "batch_starts"):
        assert getattr(ruled, key) == getattr(off, key)
    assert all(not entry["differs"] and not entry["fallback"] for entry in lead.log)


def test_shift_lead_needs_the_resilimes_policy() -> None:
    with pytest.raises(ValueError, match="shift_lead"):
        run_policy(
            _fab(),
            policy="edd",
            seed=1,
            horizon=600.0,
            downs=[],
            pm=[],
            shift_lead=ShiftLead(RuleDefault()),
        )


# Detection and options -------------------------------------------------------


# First occurrence on the 2-day study runs: Q-time competition at the first
# tick, a hot lot at 3.0 h and a scanner breakdown with pinned lots at 5.25 h
# (published, seed 1), PM conflicts from 8.7 h (pm_enforced).
@pytest.mark.parametrize(
    ("book", "seed", "hours", "kind"),
    [
        ("published", 1, "1", "qtime_competition"),
        ("published", 1, "6", "breakdown"),
        ("published", 1, "6", "hot_insertion"),
        ("pm_enforced", 1, "9.5", "pm_conflict"),
    ],
)
def test_detects_exceptions_with_legal_options(
    book: str, seed: int, hours: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead = ShiftLead(RuleDefault())
    result, (plant, kwargs) = _run(book, lead, monkeypatch, seed, hours)
    kinds = {entry["type"] for entry in lead.log}
    assert kind in kinds and kinds <= set(KINDS)
    for entry in lead.log:
        assert 2 <= len(entry["options"]) <= 4
        defaults = [option for option in entry["options"] if option["rule_default"]]
        assert len(defaults) == 1 and defaults[0]["id"] == entry["default"]
        assert all(option["impact"] is not None for option in entry["options"])
        assert entry["chosen"] in {option["id"] for option in entry["options"]}
        assert entry["provider"] == "rules"
    report = check_trace(plant, result, downs=kwargs["downs"], pm=kwargs["pm"])
    assert report["total"] == 0, report


def test_breakdown_options_reroute_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    lead = ShiftLead(RuleDefault())
    _run("published", lead, monkeypatch, hours="6")
    entry = next(entry for entry in lead.log if entry["type"] == "breakdown")
    actions = {option["id"]: option["action"] for option in entry["options"]}
    assert "re-route" in actions[entry["default"]]
    assert any("repair" in action for action in actions.values())


def test_stand_in_differs_and_changes_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    off, _ = _run("published", None, monkeypatch)
    lead = ShiftLead(HeuristicStandIn())
    on, _ = _run("published", lead, monkeypatch)
    summary = lead.summary()
    assert summary["differs"] > 0 and summary["fallbacks"] == 0
    assert _core(on.events) != off.events


# Stand-in, prompt and mock provider -----------------------------------------


def test_stand_in_is_lexicographic_and_never_makes_hot_late() -> None:
    exc = _three()
    assert best_option(exc.options).id == "C"  # lowest Q-time first ...
    chosen = HeuristicStandIn().decide(exc)
    assert chosen.option_id == "C"
    # ... but the guardrail rejects C (hot lot late versus the default).
    assert check_option(None, exc, exc.option("C")) == "invariant: makes a hot/VIP lot late"
    tie = _exc(
        Option("A", "rule", Lever(), True, _impact(q=1)),
        Option("B", "boost", Lever("prio", prio={(1, 4): -1.0}), False, _impact(q=1)),
    )
    assert best_option(tie.options).id == "A"


def test_prompt_is_compact_json_with_goal_and_options() -> None:
    messages = build_messages(_three(), "ja")
    assert [m["role"] for m in messages] == ["system", "user"]
    payload = json.loads(messages[1]["content"])
    assert payload["exception"] == "qtime_competition"
    assert [o["id"] for o in payload["options"]] == ["A", "B", "C"]
    assert payload["options"][0]["rule_default"] is True
    assert "whole fab" in payload["goal"] and "hot" in payload["goal"]
    assert payload["answer"]["lang"] == "ja" and "Japanese" in payload["answer"]["reason"]
    assert '"option_id"' in messages[0]["content"]


def test_mock_provider_answers_the_shift_lead_lane_deterministically() -> None:
    messages = build_messages(_three(), "zh")
    first = MockProvider().complete(messages, lane="shift_lead")
    second = MockProvider().complete(messages, lane="shift_lead")
    assert first.content == second.content and first.mocked
    body = json.loads(first.content)
    assert body["option_id"] == "C" and "模拟" in body["reason"]
    decision = LlmDecider(MockProvider(), lang="zh").decide(_three())
    assert decision.option_id == "C" and decision.provider == "mock (mock)"


# Validation and fallback -----------------------------------------------------


class _Fixed:
    name = "fixed"

    def __init__(self, option_id: str = "", error: Exception | None = None) -> None:
        self.option_id = option_id
        self.error = error

    def decide(self, exc: FabException) -> Decision:
        if self.error is not None:
            raise self.error
        return Decision(self.option_id, "because", "fixed")


class _Completer:
    name = "fake"

    def __init__(self, content: str, delay: float = 0.0) -> None:
        self.content = content
        self.delay = delay

    def model_for(self, lane: str) -> str:
        return "fake-model"

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.0
    ) -> LlmResult:
        time.sleep(self.delay)
        return LlmResult(
            content=self.content,
            model="fake-model",
            provider="fake",
            lane=lane,
            latency_ms=1.0,
            mocked=False,
        )


def _sim() -> Any:
    return SimpleNamespace(
        fab=SimpleNamespace(
            families=[SimpleNamespace(name="Fam", tool0=0, tools=1)],
            tool_name=["T0"],
            lot_id=["L0", "L1", "L2"],
        ),
        record=True,
        events=[],
        clock=600.0,
        running=[0],
        pm=[[]],
    )


@pytest.mark.parametrize(
    ("decider", "cause"),
    [
        (_Fixed("Z"), "unknown_option"),
        (_Fixed("C"), "invariant: makes a hot/VIP lot late"),
        (_Fixed(error=RuntimeError("boom")), "error: RuntimeError"),
        (LlmDecider(_Completer("no json here")), "bad_json"),
        (LlmDecider(_Completer('{"option_id": 2, "reason": "x"}')), "bad_json"),
        (LlmDecider(_Completer('{"option_id": "B"}', delay=1.0), timeout_s=0.05), "timeout"),
    ],
)
def test_bad_answers_fall_back_to_the_rule_default(decider: Any, cause: str) -> None:
    sim = _sim()
    lead = ShiftLead(decider)
    entry = lead.handle(sim, _three(), 600.0)
    assert entry["fallback"] is True
    assert str(entry["fallback_cause"]).startswith(cause)
    assert entry["chosen"] == "A" and entry["differs"] is False and entry["reason"] == ""
    assert lead.prio_map() == {}
    assert sim.events[-1][0] == "ai_decision"


def test_valid_llm_answer_is_applied_and_logged() -> None:
    sim = _sim()
    decider = LlmDecider(_Completer('Sure: {"option_id": "B", "reason": "保护Q-time"}'))
    lead = ShiftLead(decider)
    entry = lead.handle(sim, _three(), 600.0)
    assert entry["chosen"] == "B" and entry["differs"] and not entry["fallback"]
    assert entry["reason"] == "保护Q-time" and entry["provider"] == "fake"
    assert entry["model"] == "fake-model" and entry["latency_ms"] == 1.0
    assert lead.prio_map() == {(1, 4): -1.0}
    assert lead.bias(1, 4) == pytest.approx(-0.1)
    sim.clock = 900.0  # the lever expires
    assert lead.bias(1, 4) == 0.0
    rows = decision_rows(sim.events)
    assert rows[0][1] == "ai_decision" and rows[0][2]["label"] == "AI判断"
    assert rows[0][2]["chosen"] == "B"


def test_budget_caps_decider_calls() -> None:
    sim = _sim()
    lead = ShiftLead(_Fixed("B"), budget=1)
    assert lead.handle(sim, _three(), 600.0)["chosen"] == "B"
    second = lead.handle(sim, _three(), 600.0)
    assert second["fallback"] and str(second["fallback_cause"]).startswith("budget")


def test_build_decider_never_goes_live_without_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIMES_MODE", "mock")
    assert build_decider("heuristic").name == HEURISTIC_NAME
    assert isinstance(build_decider("mock"), LlmDecider)
    with pytest.raises(RuntimeError, match="nightshift"):
        build_decider("nightshift")
