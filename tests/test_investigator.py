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


def test_loop_stops_at_the_tool_budget(starve):
    case, run = starve
    call = json.dumps(
        {"tool": "family_window", "args": {"family": case.family, "start_h": 6, "end_h": 8}}
    )
    answer = investigate(
        Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, Scripted([call])
    )
    assert len(answer.calls) == MAX_CALLS
    assert answer.primary_cause is None and answer.error


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
