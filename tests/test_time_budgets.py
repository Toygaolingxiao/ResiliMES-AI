"""Time budgets: per-call cap, per-task deadline, elapsed_s, timeouts. Fake clock, no sleeps."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APITimeoutError
from tests.test_investigator import PLAIN_FINAL, Scripted, _window_call

from resilimes.config import Settings
from resilimes.evidence.toolkit import HOUR, Toolkit, record_run
from resilimes.insight import handover as ho
from resilimes.insight.explainer import base_run, explain
from resilimes.insight.injector import HORIZON_H, rebuild
from resilimes.insight.investigator import (
    DEGRADE_REASONS,
    Investigation,
    baseline_rank,
    investigate,
)
from resilimes.insight.study import (
    ai_score,
    load_cases,
    summarize_investigator,
    time_stats,
)
from resilimes.llm import deadline
from resilimes.llm.nightshift import NightshiftProvider, ttfb_ms
from resilimes.smt.fab import load_fab


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(deadline, "clock", fake)
    return fake


class Slow(Scripted):
    """Scripted replies; every model call costs ``cost`` fake seconds."""

    def __init__(self, replies, clock, cost):
        super().__init__(replies)
        self.clock, self.cost = clock, cost

    def complete(self, messages, *, lane, temperature=0.2):
        self.clock.advance(self.cost)
        return super().complete(messages, lane=lane, temperature=temperature)


@pytest.fixture(scope="module")
def fab():
    return load_fab()


@pytest.fixture(scope="module")
def starve(fab):
    case = {c.case_id: c for c in load_cases()}["upstream_starvation-s1"]
    base = record_run(fab, seed=case.seed, horizon=HORIZON_H * HOUR)
    return case, rebuild(fab, case, base)


# ---- deadline module -----------------------------------------------------------------------
def test_task_deadline_counts_down_and_nests_tighter(clock):
    assert deadline.remaining() is None and not deadline.expired()
    with deadline.task_deadline(180):
        assert deadline.remaining() == 180
        clock.advance(100)
        with deadline.task_deadline(500):  # an inner budget never extends the outer one
            assert deadline.remaining() == 80
        with deadline.task_deadline(30):
            assert deadline.remaining() == 30
        clock.advance(81)
        assert deadline.expired()
    assert deadline.remaining() is None


def test_default_task_budget_reads_env(monkeypatch):
    monkeypatch.delenv("AI_TASK_DEADLINE_S", raising=False)
    assert deadline.default_task_s() == 180.0
    monkeypatch.setenv("AI_TASK_DEADLINE_S", "45")
    assert deadline.default_task_s() == 45.0
    assert Settings().ai_call_deadline_s == 90.0 and Settings().ai_task_deadline_s == 180.0


def test_ttfb_header_value():
    assert ttfb_ms(90, 60) == 60_000
    assert ttfb_ms(12.5, 60) == 12_500
    assert ttfb_ms(900, 900) == 300_000


# ---- Nightshift per-call cap ---------------------------------------------------------------
def _provider(**overrides):
    settings = Settings(
        mode="live",
        meterless_runtime_token="real-token",
        llm_max_retries=1,
        zetaris_api_key="x",
        zetaris_rest_url="https://api.example.test/api/v1.0",
        zetaris_org_id="1",
        **overrides,
    )
    with patch("resilimes.llm.nightshift.build_openai_client", return_value=MagicMock()):
        provider = NightshiftProvider(settings)
    provider._client = MagicMock()
    return provider


def _reply(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_request_carries_timeout_and_ttfb_header(clock):
    provider = _provider()
    provider._client.chat.completions.create = MagicMock(return_value=_reply("ok"))
    with deadline.task_deadline(180):
        provider.complete([{"role": "user", "content": "x"}], lane="explainer")
    kwargs = provider._client.chat.completions.create.call_args.kwargs
    assert kwargs["timeout"] == 90
    assert kwargs["extra_headers"] == {"meterless-ttfb-ms": "60000"}
    with deadline.task_deadline(20):
        provider.complete([{"role": "user", "content": "x"}], lane="explainer")
    kwargs = provider._client.chat.completions.create.call_args.kwargs
    assert kwargs["timeout"] == 20
    assert kwargs["extra_headers"] == {"meterless-ttfb-ms": "20000"}


def test_empty_ladder_skips_a_rung_with_under_30_s_left(clock):
    provider = _provider()

    def slow_empty(**kwargs):
        clock.advance(65)  # 25 s of the 90 s call cap left after the first rung
        return _reply("")

    provider._client.chat.completions.create = MagicMock(side_effect=slow_empty)
    with deadline.task_deadline(180):
        result = provider.complete([{"role": "user", "content": "x"}], lane="explainer")
    assert result.content == ""
    calls = provider._client.chat.completions.create.call_args_list
    assert [call.kwargs["max_tokens"] for call in calls] == [4096]


def test_empty_ladder_respects_the_task_deadline(clock):
    provider = _provider()

    def quick_empty(**kwargs):
        clock.advance(10)
        return _reply("")

    provider._client.chat.completions.create = MagicMock(side_effect=quick_empty)
    with deadline.task_deadline(45):  # 35 s left after rung 1, 25 s after rung 2
        provider.complete([{"role": "user", "content": "x"}], lane="explainer")
    calls = provider._client.chat.completions.create.call_args_list
    assert [call.kwargs["max_tokens"] for call in calls] == [4096, 8192]


def test_client_timeout_raises_deadline_exceeded(clock):
    provider = _provider()
    request = httpx.Request("POST", "http://127.0.0.1:8088/v1/chat/completions")
    provider._client.chat.completions.create = MagicMock(
        side_effect=APITimeoutError(request=request)
    )
    with deadline.task_deadline(180), pytest.raises(deadline.DeadlineExceeded):
        provider.complete([{"role": "user", "content": "x"}], lane="explainer")


def test_no_request_once_the_task_deadline_is_gone(clock):
    provider = _provider()
    provider._client.chat.completions.create = MagicMock(return_value=_reply("ok"))
    with deadline.task_deadline(5):
        clock.advance(6)
        with pytest.raises(deadline.DeadlineExceeded):
            provider.complete([{"role": "user", "content": "x"}], lane="explainer")
    provider._client.chat.completions.create.assert_not_called()


# ---- investigator --------------------------------------------------------------------------
def test_investigator_timeout_degrades_to_the_rule_answer(starve, clock):
    case, run = starve
    replies = [_window_call(case.family, h) for h in (1, 2, 3)] + [PLAIN_FINAL]
    answer = investigate(
        Toolkit(run),
        case.question,
        case.family,
        case.t1_h,
        case.t2_h,
        Slow(replies, clock, 100),
        deadline_s=180,
    )
    # Round 1: call (t=100), tool. Round 2: call (t=200), deadline hit before the tool.
    assert len(answer.calls) == 1
    assert answer.timed_out and answer.error.startswith("timeout")
    assert answer.stop_reason == "degraded_to_rule"
    assert answer.degraded and answer.degrade_reason == "timeout"
    assert "timeout" in DEGRADE_REASONS
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    assert answer.system == {**answer.system, "source": "rule", "primary_cause": rank[0]}
    assert [s["status"] for s in answer.trace] == ["executed", "timeout"]
    assert [s["elapsed_s"] for s in answer.trace] == [100.0, 100.0]
    assert answer.elapsed_s == 200.0


def test_investigator_checks_the_deadline_before_every_model_call(starve, clock):
    case, run = starve
    replies = [_window_call(case.family, 1), PLAIN_FINAL]
    provider = Slow(replies, clock, 0)
    original = provider.complete

    def tool_then_late(messages, *, lane, temperature=0.2):
        reply = original(messages, lane=lane, temperature=temperature)
        clock.advance(200)
        return reply

    provider.complete = tool_then_late
    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, provider, deadline_s=180
    )
    assert provider.seen == 1  # the second model call never started
    assert answer.degrade_reason == "timeout" and answer.trace[-1]["status"] == "timeout"


def test_provider_deadline_exceeded_is_a_timeout(starve, clock):
    case, run = starve

    class Stuck(Scripted):
        def complete(self, messages, *, lane, temperature=0.2):
            raise deadline.DeadlineExceeded("Nightshift investigator: no reply within 90 s")

    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Stuck([""])
    )
    assert answer.degrade_reason == "timeout" and answer.stop_reason == "degraded_to_rule"
    assert answer.system["source"] == "rule"


def test_answer_within_budget_is_unchanged(starve, clock):
    case, run = starve
    replies = [_window_call(case.family, 1), PLAIN_FINAL]
    answer = investigate(
        Toolkit(run),
        case.question,
        case.family,
        case.t1_h,
        case.t2_h,
        Slow(replies, clock, 40),
        deadline_s=180,
    )
    assert not answer.timed_out and not answer.degraded
    assert answer.primary_cause == "upstream_starvation"
    assert answer.elapsed_s == 80.0


def test_timeout_is_an_ai_miss_and_counted_in_the_summary():
    timed = Investigation(question="q", family="f", t1_h=0, t2_h=1, primary_cause="tool_down")
    timed.timed_out = True
    assert ai_score("tool_down", timed) == {"top1": False, "top2": False}
    rows = [
        {
            "case_id": "a",
            "truth": "tool_down",
            "stop_reason": "degraded_to_rule",
            "degraded": True,
            "degrade_reason": "timeout",
            "timeout": True,
            "elapsed_s": 180.0,
            "baseline_score": {"top1": True, "top2": True},
            "ai_score": ai_score("tool_down", timed),
            "system_score": {"top1": True, "top2": True},
            "ai": {
                "fact_ok": False,
                "repaired": False,
                "primary_cause": "tool_down",
                "calls": [],
                "response_models": [],
            },
        }
    ]
    summary = summarize_investigator(rows, "test")
    assert summary["ai_top1"] == 0 and summary["system_top1"] == 1
    assert summary["degraded_by_reason"] == {"timeout": 1}
    assert summary["timeouts"] == 1 and summary["elapsed_s_p95"] == 180.0


def test_time_stats_percentiles():
    rows = [{"elapsed_s": float(v), "timeout": v >= 180} for v in range(1, 201)]
    stats = time_stats(rows)
    assert stats == {"elapsed_s_p50": 100.0, "elapsed_s_p95": 190.0, "timeouts": 21}
    assert time_stats([]) == {"elapsed_s_p50": 0.0, "elapsed_s_p95": 0.0, "timeouts": 0}


# ---- explainer and handover ----------------------------------------------------------------
@pytest.fixture(scope="module")
def run48(fab):
    return base_run(fab, 1)


def test_explainer_timeout_is_marked(run48, clock):
    from resilimes.evidence.lateness import late_lots

    lot_id = run48.fab.lot_id[late_lots(run48.timeline)[0]]
    answer = explain(Toolkit(run48), lot_id, Slow(["not json"], clock, 100), deadline_s=180)
    assert answer.timeout and answer.error.startswith("timeout")
    assert answer.lever is None and answer.llm_calls == 2
    assert answer.elapsed_s == 200.0


def test_handover_timeout_keeps_the_deterministic_parts(run48, clock):
    chunk = json.dumps({"notes": ["steady"], "open_issues": [], "resolved": []})
    result = ho.handover(run48, 12.0, Slow([chunk], clock, 50), deadline_s=120)
    assert result["timeout"] and result["error"].startswith("timeout")
    assert result["report"] is None
    assert result["llm_calls"] == 3  # 0, 50, 100 s; the 4th call would start at 150 s
    assert result["end_facts"] and result["must_mention"]
    assert result["elapsed_s"] == 150.0
    assert result["chunks_ok"] == 3 and len(result["chunks"]) == 7


def test_mock_handover_has_time_fields(run48):
    result = ho.handover(run48, 12.0, None)
    assert result["timeout"] is False and result["elapsed_s"] >= 0


def test_calls_outside_a_task_deadline_are_unchanged(clock):
    """Sim-select / shift-lead calls set their own long budgets: no cap, no header, full ladder."""
    provider = _provider()

    def slow_empty(**kwargs):
        clock.advance(500)
        return _reply("")

    provider._client.chat.completions.create = MagicMock(side_effect=slow_empty)
    provider.complete([{"role": "user", "content": "x"}], lane="shift_lead_select")
    calls = provider._client.chat.completions.create.call_args_list
    assert [call.kwargs["max_tokens"] for call in calls] == [4096, 8192, 16384]
    assert all("timeout" not in c.kwargs and "extra_headers" not in c.kwargs for c in calls)
