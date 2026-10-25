"""AI investigator: fault cases, bounded loop, fact check, baseline, progress line, API."""

from __future__ import annotations

import io
import json

import pytest

from resilimes.evidence.toolkit import HOUR, Toolkit, record_run
from resilimes.insight.injector import HORIZON_H, TAXONOMY, rebuild
from resilimes.insight.investigator import MAX_CALLS, baseline_rank, investigate, score
from resilimes.insight.progress import Progress, redact
from resilimes.insight.study import load_cases
from resilimes.llm.base import LlmResult
from resilimes.smt.fab import load_fab


class Scripted:
    name = "test"
    mocked = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = 0

    def model_for(self, lane):
        return "test-model"

    def complete(self, messages, *, lane, temperature=0.2):
        reply = self.replies[min(self.seen, len(self.replies) - 1)]
        self.seen += 1
        return LlmResult(
            content=reply,
            model="test-model",
            provider="test",
            lane=lane,
            latency_ms=0.0,
            mocked=False,
        )


@pytest.fixture(scope="module")
def fab():
    return load_fab()


@pytest.fixture(scope="module")
def starve(fab):
    case = {c.case_id: c for c in load_cases()}["upstream_starvation-s1"]
    base = record_run(fab, seed=case.seed, horizon=HORIZON_H * HOUR)
    return case, rebuild(fab, case, base)


def test_committed_cases_cover_every_fault_and_seed():
    cases = load_cases()
    assert len(cases) == 24
    assert {c.fault for c in cases} == set(TAXONOMY)
    assert {(c.fault, c.seed) for c in cases} == {(f, s) for f in TAXONOMY for s in (1, 2, 3, 4)}


def test_mock_investigation_is_bounded_and_fact_checked(starve):
    case, run = starve
    answer = investigate(Toolkit(run), case.question, case.family, case.t1_h, case.t2_h)
    assert answer.mocked
    assert answer.primary_cause in TAXONOMY
    assert 1 <= len(answer.calls) <= MAX_CALLS
    assert answer.fact_ok, answer.fact_misses
    assert answer.causal_chain and answer.lever
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    assert rank[0] == answer.primary_cause  # the stand-in equals the baseline by design
    assert score(case.fault, *rank[:2])["top2"] in (True, False)


def _window_call(family, start_h):
    args = {"family": family, "start_h": start_h, "end_h": start_h + 1}
    return json.dumps({"tool": "family_window", "args": args})


PLAIN_FINAL = json.dumps(
    {
        "final": {
            "primary_cause": "upstream_starvation",
            "secondary_cause": None,
            "causal_chain": ["The upstream family was down, so this family drained."],
            "lever": "Recover the upstream family first.",
            "citations": [1],
        }
    }
)


def test_loop_stops_at_the_tool_budget(starve):
    case, run = starve
    calls = [_window_call(case.family, h) for h in range(1, 12)]
    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Scripted(calls)
    )
    assert len(answer.calls) == MAX_CALLS
    assert answer.primary_cause is None and answer.error
    assert answer.stop_reason == "degraded_to_rule"
    assert answer.degraded and answer.degrade_reason == "no_answer"
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    assert answer.system["source"] == "rule"
    assert answer.system["primary_cause"] == rank[0]


def test_repeat_call_is_blocked_and_ends_the_tool_phase(starve):
    case, run = starve
    first = json.dumps(
        {"tool": "family_window", "args": {"family": case.family, "start_h": 6, "end_h": 8}}
    )
    # Same call, args written differently (float, string, key order): still a repeat.
    again = json.dumps(
        {"tool": "family_window", "args": {"end_h": "8", "start_h": 6.0, "family": case.family}}
    )
    provider = Scripted([first, again, PLAIN_FINAL])
    answer = investigate(Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, provider)
    assert len(answer.calls) == 1
    assert answer.primary_cause == "upstream_starvation"
    assert answer.stop_reason == "repeat_call"
    assert [s["status"] for s in answer.trace] == ["executed", "repeat", "accepted"]
    assert answer.trace[1]["repeat_of"] == 1


def test_repeat_then_another_tool_call_stops_without_answer(starve):
    case, run = starve
    call = _window_call(case.family, 6)
    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Scripted([call])
    )
    assert len(answer.calls) == 1
    assert answer.primary_cause is None
    assert [s["status"] for s in answer.trace] == ["executed", "repeat", "tool_phase_closed"]
    assert answer.stop_reason == "degraded_to_rule"
    assert answer.degraded and answer.degrade_reason == "no_answer"
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    assert answer.system["source"] == "rule"
    assert answer.system["primary_cause"] == rank[0]


def test_budget_exhausted_then_answer(starve):
    case, run = starve
    replies = [_window_call(case.family, h) for h in (1, 2, 3)] + [PLAIN_FINAL]
    answer = investigate(
        Toolkit(run),
        case.question,
        case.family,
        case.t1_h,
        case.t2_h,
        Scripted(replies),
        max_calls=2,
    )
    assert len(answer.calls) == 2
    assert answer.primary_cause == "upstream_starvation"
    assert answer.stop_reason == "budget_exhausted"
    assert [s["status"] for s in answer.trace] == [
        "executed",
        "executed",
        "over_budget",
        "accepted",
    ]


def test_normal_case_is_answered_with_one_trace_entry_per_round(starve):
    case, run = starve
    replies = [_window_call(case.family, 6), PLAIN_FINAL]
    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Scripted(replies)
    )
    assert answer.stop_reason == "answered"
    assert len(answer.trace) == answer.turns == 2
    assert [s["round"] for s in answer.trace] == [1, 2]
    executed = answer.trace[0]
    assert executed["action"] == "family_window" and executed["result"] == 1
    assert executed["evidence"]["chars"] > 0 and executed["evidence"]["keys"]
    assert answer.trace[1]["action"] == "answer"
    # The mock stand-in gives one trace entry per round too, and compare_windows lists causes.
    mock = investigate(Toolkit(run), case.question, case.family, case.t1_h, case.t2_h)
    assert len(mock.trace) == mock.turns
    assert set(mock.trace[0]["evidence"]["causes"]) == set(TAXONOMY)
    assert mock.stop_reason in ("answered", "fact_check_repaired")


def test_provider_error_message_is_kept_and_redacted(starve):
    case, run = starve

    class Broken(Scripted):
        def complete(self, messages, *, lane, temperature=0.2):
            raise RuntimeError("upstream 502 empty_response token=sk-abcdef1234567890abcdef")

    answer = investigate(Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Broken([]))
    assert answer.stop_reason == "degraded_to_rule"
    assert answer.degraded and answer.degrade_reason == "provider_error"
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    assert answer.system["source"] == "rule"
    assert answer.system["primary_cause"] == rank[0]
    assert "RuntimeError" in answer.error and "502 empty_response" in answer.error
    assert "sk-abcdef1234567890abcdef" not in answer.error
    assert answer.trace == [
        {"round": 1, "action": "provider", "status": "error", "detail": answer.error}
    ]


def test_invented_numbers_are_flagged_after_one_repair(starve):
    case, run = starve
    final = json.dumps(
        {
            "final": {
                "primary_cause": "tool_down",
                "secondary_cause": None,
                "causal_chain": ["WIP rose by 987654 lots on tool XYZ-999."],
                "lever": "Fix it.",
                "citations": [],
            }
        }
    )
    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Scripted([final])
    )
    assert answer.repaired
    assert not answer.fact_ok
    assert any("987654" in miss for miss in answer.fact_misses)
    assert answer.stop_reason == "degraded_to_rule"
    assert answer.degraded and answer.degrade_reason == "fact_check_failed"
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    assert answer.system["source"] == "rule"
    assert answer.system["primary_cause"] == rank[0]
    assert answer.primary_cause == "tool_down"  # the AI answer is kept, not hidden
    assert [s["status"] for s in answer.trace] == ["fact_check_repair", "accepted"]


def test_sql_tool_goes_through_the_guard(starve):
    case, run = starve
    calls = [
        json.dumps({"tool": "sql", "args": {"sql": "DELETE FROM fab_ops.ops_events"}}),
        json.dumps(
            {"tool": "sql", "args": {"sql": "SELECT COUNT(*) AS n FROM fab_ops.ops_events"}}
        ),
        json.dumps(
            {
                "final": {
                    "primary_cause": "upstream_starvation",
                    "causal_chain": ["x"],
                    "lever": "y",
                    "citations": [2],
                }
            }
        ),
    ]
    provider = Scripted(calls)
    kit = Toolkit(run)
    answer = investigate(kit, case.question, case.family, case.t1_h, case.t2_h, provider)
    assert answer.primary_cause == "upstream_starvation"
    assert [c["tool"] for c in answer.calls] == ["sql", "sql"]


def test_prose_hyphen_words_are_not_ids():
    from resilimes.evidence.factcheck import FactRegistry, check

    registry = FactRegistry()
    registry.add({"family": "WE_BE_82"})
    assert check("WE_BE_82 lost tool-hours after a re-run", registry) == []
    assert "unknown id XYZ-999" in check("tool XYZ-999 went down", registry)


def test_progress_line_and_redaction():
    stream = io.StringIO()
    progress = Progress("investigator", 24, stream=stream, log_every=0)
    progress.update(6, extra="token=abc123secret nvapi-ABCDEFGH12345678")
    line = stream.getvalue()
    assert "investigator 6/24 25% [#####" in line and "eta" in line
    assert "abc123secret" not in line and "ABCDEFGH12345678" not in line
    assert redact("Bearer sk-1234567890abcdef").count("***") >= 1


def test_api_lists_cases_and_investigates():
    from fastapi.testclient import TestClient

    from resilimes.api.app import create_app
    from resilimes.config import Settings

    client = TestClient(create_app(Settings(mode="mock")))
    cases = client.get("/api/ai/investigator/cases").json()["cases"]
    assert len(cases) == 24
    body = client.post("/api/ai/investigate", json={"case_id": "upstream_starvation-s1"}).json()
    assert body["advice_only"] and body["answer"]["mocked"]
    assert body["answer"]["primary_cause"] in TAXONOMY
    assert client.post("/api/ai/investigate", json={"case_id": "nope"}).status_code == 404


def test_compare_windows_gives_before_window_change_for_every_cause(starve):
    from resilimes.insight.investigator import compare_windows, execute

    case, run = starve
    kit = Toolkit(run)
    out = compare_windows(kit, case.family, case.t1_h, case.t2_h)
    assert set(out["causes"]) == set(TAXONOMY)
    for row in out["causes"].values():
        assert {"indicator", "before", "window", "rel_change"} <= set(row)
    assert not {"winner", "rank", "ranking", "score"} & set(out)  # the model still decides
    starve_row = out["causes"]["upstream_starvation"]
    assert starve_row["upstream_family"] and len(starve_row["feed_from_upstream_per_h"]) == 2
    assert (
        starve_row["rel_change"] > 0
        and out["waiting_lots"]["at_window_end"] < (out["waiting_lots"]["at_window_start"])
    )
    # Its numbers are fact-registered like every other tool result.
    from resilimes.evidence.factcheck import check

    text = f"{starve_row['upstream_family']} went from {starve_row['before']} to " + (
        f"{starve_row['window']}, feed {starve_row['feed_from_upstream_per_h'][0]}"
    )
    assert check(text, kit.registry) == []
    assert kit.calls[-1]["tool"] == "compare_windows"
    # And it is reachable through the loop's tool dispatcher.
    via = execute(kit, "compare_windows", {"family": case.family, "start_h": 6, "end_h": 10}, None)
    assert set(via["causes"]) == set(TAXONOMY)


def test_prompt_carries_the_investigation_protocol():
    from resilimes.insight.investigator import SYSTEM, TOOLS_DOC

    assert "4 h before" in SYSTEM and "relative" in SYSTEM and "turn 6" in SYSTEM
    for indicator in ("down tool-hours", "PM tool-hours", "arrivals per hour", "setup minutes"):
        assert indicator in SYSTEM
    assert "compare_windows" in TOOLS_DOC


def test_answered_case_is_not_degraded(starve):
    case, run = starve
    replies = [_window_call(case.family, 6), PLAIN_FINAL]
    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Scripted(replies)
    )
    assert not answer.degraded and answer.degrade_reason is None
    assert answer.system == {
        "source": "ai",
        "primary_cause": "upstream_starvation",
        "secondary_cause": None,
    }


def test_study_summary_keeps_ai_and_system_scores_apart():
    from resilimes.insight.study import summarize_investigator

    def row(case_id, ai, system, degraded=None):
        return {
            "case_id": case_id,
            "truth": "tool_down",
            "stop_reason": "degraded_to_rule" if degraded else "answered",
            "degraded": bool(degraded),
            "degrade_reason": degraded,
            "baseline_score": {"top1": True, "top2": True},
            "ai_score": {"top1": ai, "top2": ai},
            "system_score": {"top1": system, "top2": system},
            "ai": {
                "fact_ok": True,
                "repaired": False,
                "primary_cause": "tool_down" if ai else None,
                "calls": [],
                "response_models": [],
            },
        }

    summary = summarize_investigator(
        [row("a", True, True), row("b", False, True, "no_answer")], "test"
    )
    assert summary["ai_top1"] == 1 and summary["system_top1"] == 2
    assert summary["degraded_count"] == 1
    assert summary["degraded_by_reason"] == {"no_answer": 1}
