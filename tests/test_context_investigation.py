"""Context investigation: Gantt right-click queries (bar / gap / window), API split."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.evidence.toolkit import HOUR, Toolkit, record_run
from resilimes.insight.context_investigation import (
    ContextError,
    ContextQuery,
    investigate_context,
)
from resilimes.insight.injector import rebuild
from resilimes.insight.investigator import TAXONOMY
from resilimes.insight.study import load_cases
from resilimes.llm.base import LlmResult
from resilimes.smt.fab import load_fab


@pytest.fixture(scope="module")
def fab():
    return load_fab()


@pytest.fixture(scope="module")
def run24(fab):
    return record_run(fab, seed=1, horizon=24 * HOUR)


def _started_visit(run):
    """A started visit with a real wait and a recorded start reason, if any."""
    fallback = None
    for _lot, visits in run.timeline.visits.items():
        for visit in visits:
            if visit.start is None or visit.start - visit.ready < 60.0:
                continue
            if fallback is None:
                fallback = visit
            if visit.reason:
                return visit
    assert fallback is not None, "a 24 h run should have waited, started visits"
    return fallback


def test_bar_answer_quotes_real_visit_evidence(run24):
    visit = _started_visit(run24)
    lot_id = run24.fab.lot_id[visit.lot]
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="bar", lot=lot_id, step=visit.step)
    )
    assert answer.status == "answered"
    assert answer.source == "scripted" and answer.mocked
    assert answer.fact_ok, answer.fact_misses
    assert lot_id in answer.answer
    kinds = {entry["kind"] for entry in answer.basis}
    assert {"visit", "lot", "queue_at_start", "wait_split", "tool", "emergent"} <= kinds
    visit_facts = next(e["facts"] for e in answer.basis if e["kind"] == "visit")
    assert visit_facts["tool"] == run24.fab.tool_name[visit.tool]
    assert visit_facts["start_h"] == round(visit.start / HOUR, 2)
    assert visit_facts["start_reason"] == (visit.reason or None)
    assert answer.citations == [entry["n"] for entry in answer.basis]
    # The honesty rule: the ranking is emergent, never dressed up as a record.
    assert "emergent" in answer.answer


def test_bar_unknown_lot_is_an_error(run24):
    with pytest.raises(ContextError):
        investigate_context(Toolkit(run24), ContextQuery(type="bar", lot="Init_Lot_999_999"))


class _Polisher:
    """Non-mocked provider stand-in: one canned reply per call."""

    name = "test-polisher"
    mocked = False

    def __init__(self, content: str) -> None:
        self.content = content

    def model_for(self, lane: str) -> str:
        return "nemotron-test"

    def complete(self, messages, *, lane, temperature=0.2):
        return LlmResult(
            content=self.content,
            model="nemotron-test",
            provider="test-polisher",
            lane=lane,
            latency_ms=0.0,
            mocked=False,
            provider_model="nemotron-test",
        )


def test_bar_llm_rewrite_must_pass_the_fact_check(run24):
    visit = _started_visit(run24)
    lot_id = run24.fab.lot_id[visit.lot]
    bad = _Polisher(json.dumps({"answer": f"{lot_id} waited 9999 min because of magic."}))
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="bar", lot=lot_id, step=visit.step), bad
    )
    assert answer.source == "scripted"  # the invented rewrite was refused
    assert answer.degraded and answer.degrade_reason == "fact_check_failed"
    assert answer.fact_ok, answer.fact_misses
    assert "9999" not in answer.answer

    good = _Polisher(json.dumps({"answer": "The lot waited, then started."}))
    polished = investigate_context(
        Toolkit(run24), ContextQuery(type="bar", lot=lot_id, step=visit.step), good
    )
    assert polished.source == "llm" and not polished.degraded
    assert polished.fact_ok and polished.answer == "The lot waited, then started."


def test_gap_without_waiting_lots_answers_unknown(run24):
    kit = Toolkit(run24)
    found = None
    for tool in range(0, len(run24.fab.tool_name), 7):
        tool_name = run24.fab.tool_name[tool]
        for start_h in range(0, 24, 3):
            answer = investigate_context(
                kit,
                ContextQuery(type="gap", tool=tool_name, t1_h=float(start_h), t2_h=start_h + 1.0),
            )
            if answer.status == "unknown":
                found = answer
                break
        if found is not None:
            break
    if found is None:
        pytest.skip("no idle-without-waiters window in the sampled scan")
    assert "unknown" in found.answer
    assert found.fact_ok, found.fact_misses
    kinds = {entry["kind"] for entry in found.basis}
    assert {"tool_window", "waiting_lots", "wait_causes"} <= kinds


def test_gap_on_a_busy_tool_reports_no_idle(run24):
    # Find a tool busy for a full hour and ask about that window.
    tl = run24.timeline
    target = None
    for tool in range(len(run24.fab.tool_name)):
        for start_h in range(0, 24):
            states = tl.state_seconds(tool, start_h * HOUR, (start_h + 1) * HOUR)
            if states["busy"] >= 3500.0:
                target = (run24.fab.tool_name[tool], float(start_h))
                break
        if target:
            break
    assert target is not None, "a 24 h run should have a fully busy tool-hour"
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="gap", tool=target[0], t1_h=target[1], t2_h=target[1] + 1)
    )
    assert answer.status == "answered"
    assert "not idle" in answer.answer
    assert answer.fact_ok, answer.fact_misses


def test_window_routes_to_the_investigator(fab):
    case = {c.case_id: c for c in load_cases()}["upstream_starvation-s1"]
    base = record_run(fab, seed=case.seed, horizon=48 * HOUR)
    run = rebuild(fab, case, base)
    answer = investigate_context(
        Toolkit(run),
        ContextQuery(
            type="window",
            family=case.family,
            t1_h=case.t1_h,
            t2_h=case.t2_h,
            question_preset="what_happened",
            question=case.question,
        ),
    )
    assert answer.primary_cause in TAXONOMY
    assert answer.primary_cause == case.fault  # scripted stand-in on a known case
    assert answer.basis and answer.basis[0]["kind"] == "investigation"
    assert answer.fact_ok, answer.fact_misses
    assert answer.answer  # the causal chain, as text


def _settings() -> Settings:
    return Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="<redacted>")


def test_api_context_mode_validates_the_query():
    client = TestClient(create_app(_settings()))
    response = client.post("/api/ai/investigate", json={"type": "bar"})
    assert response.status_code == 400
    response = client.post("/api/ai/investigate", json={})
    assert response.status_code == 400
    response = client.post("/api/ai/investigate", json={"case_id": "no-such-case"})
    assert response.status_code == 404  # the original case mode is untouched


# ---- tiers are decided by code, not by the model ---------------------------------------------


def test_bar_with_a_recorded_reason_is_decision_record_tier(run24):
    # Frozen from the seed-1 run: this start carries a recorded reason.
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="bar", lot="Init_Lot_1_54", step=399)
    )
    assert answer.tier == "decision_record"
    assert answer.fact_ok


def test_bar_without_a_recorded_reason_is_rule_emergent(run24):
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="bar", lot="Init_Lot_1_1", step=505)
    )
    assert answer.tier == "rule_emergent"
    assert answer.fact_ok


def test_rule_emergent_rewrite_cannot_use_decision_language(run24):
    upgrade = _Polisher(
        json.dumps({"answer": "The dispatcher decided to start it then, in order to win time."})
    )
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="bar", lot="Init_Lot_1_1", step=505), upgrade
    )
    assert answer.source == "scripted"  # the tier upgrade was refused
    assert answer.degraded and answer.degrade_reason == "tier_upgrade_refused"
    assert "decided" not in answer.answer


def test_gap_unknown_also_carries_the_unknown_tier(run24):
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="gap", tool="DE_BE_69-3", t1_h=0, t2_h=1)
    )
    assert answer.status == "unknown" and answer.tier == "unknown"


# ---- free questions chain the evidence sources ------------------------------------------------


def test_free_gap_question_chains_classifier_and_notes_placeholder(run24):
    answer = investigate_context(
        Toolkit(run24),
        ContextQuery(
            type="free",
            tool="DE_BE_11-1",
            t1_h=2,
            t2_h=3,
            question="Why is this tool idle in this window?",
        ),
    )
    sources = {entry["source"] for entry in answer.basis}
    assert "gap_classifier" in sources and "fab_notes" in sources
    assert answer.part_tiers.get("gap_classifier") == "rule_emergent"
    assert answer.tier == "rule_emergent"
    notes = next(e for e in answer.basis if e["source"] == "fab_notes")
    assert notes["facts"]["available"] is False  # dataset not in this tree: placeholder


def test_free_lot_question_keeps_the_decision_record_tier(run24):
    answer = investigate_context(
        Toolkit(run24),
        ContextQuery(
            type="free", lot="Init_Lot_1_54", step=399, question="Why did this lot wait so long?"
        ),
    )
    assert answer.part_tiers.get("run_record") == "decision_record"
    assert answer.tier == "decision_record"


def test_free_without_any_anchor_is_unknown(run24):
    answer = investigate_context(
        Toolkit(run24), ContextQuery(type="free", question="Why is the fab slow?")
    )
    assert answer.status == "unknown" and answer.tier == "unknown"


# ---- wire contract: minutes, scenario_id, lang -------------------------------------------------


def test_context_query_maps_minutes_scenario_and_lang():
    from resilimes.api.insight import InvestigateBody, _context_query

    body = InvestigateBody(
        type="gap",
        tool="DE_BE_11-1",
        t1_min=120,
        t2_min=180,
        scenario_id="seed-2",
        lang="zh",
    )
    query = _context_query(body)
    assert query.t1_h == 2.0 and query.t2_h == 3.0
    assert body.seed == 2 and query.scenario_id == "seed-2" and query.lang == "zh"
    hours = _context_query(InvestigateBody(type="gap", tool="X", t1_h=1.5))
    assert hours.t1_h == 1.5  # hours still work when minutes are absent
    assert InvestigateBody(case_id="c").type is None  # case mode untouched
    assert InvestigateBody(type="free").type == "free"


# ---- evaluation fixture ------------------------------------------------------------------------


def _eval_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_context_eval.py"
    spec = importlib.util.spec_from_file_location("run_context_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_fixture_covers_all_four_types():
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "eval" / "context_questions.json").read_text()
    )
    questions = fixture["questions"]
    assert 8 <= len(questions) <= 12
    assert {q["query"]["type"] for q in questions} == {"bar", "gap", "window", "free"}
    assert all(q["points"] for q in questions)


def test_eval_two_arms_on_a_subset(run24):
    module = _eval_module()
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "eval" / "context_questions.json").read_text()
    )
    report = module.evaluate(fixture, {"smt24": Toolkit(run24)}, limit=3)
    for arm in ("template", "full"):
        data = report["arms"][arm]
        assert data["fact_check_pass_rate"] == 1.0, data["rows"]
        assert data["expect_pass_rate"] == 1.0, data["rows"]
        assert data["evidence_point_coverage"] > 0.0
    assert report["arms"]["template"]["tier_distribution"] == {
        "decision_record": 1,
        "rule_emergent": 1,
        "unknown": 1,
    }
