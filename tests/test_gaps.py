"""Deliberate-gap classification and explanation (Plan 4 v1, post-hoc inference)."""

from __future__ import annotations

import json

import pytest

from resilimes.evidence.timeline import Timeline, Visit
from resilimes.insight.gap_explainer import explain_gap
from resilimes.insight.gaps import (
    GapEvidence,
    GapReason,
    GapRecord,
    classify_gap,
    find_gaps,
    gaps_from_run,
)
from resilimes.llm.base import LlmResult
from resilimes.smt.fab import Fab, load_fab


@pytest.fixture(scope="module")
def fab() -> Fab:
    return load_fab()


# ---------------------------------------------------------------------------
# classify_gap: one reason per evidence pattern, fixed priority, no guessing
# ---------------------------------------------------------------------------


def test_classify_pm_avoidance_wins_over_batch() -> None:
    ev = GapEvidence(pm_at=100.0, next_batch_lots=3, batch_min_lots=2)
    assert classify_gap(ev) is GapReason.PM_AVOIDANCE


def test_classify_qtime_gate() -> None:
    ev = GapEvidence(qtime_blocked_lot=7, qtime_target_step=12)
    assert classify_gap(ev) is GapReason.QTIME_GATE


def test_classify_batch_wait() -> None:
    ev = GapEvidence(next_batch_lots=3, batch_min_lots=4)
    assert classify_gap(ev) is GapReason.BATCH_WAIT


def test_classify_plan_wait() -> None:
    assert classify_gap(GapEvidence(plan_wait_until=500.0)) is GapReason.PLAN_WAIT


def test_classify_capacity_reserve() -> None:
    assert classify_gap(GapEvidence(reserve_for_lot=3)) is GapReason.CAPACITY_RESERVE


def test_classify_setup_saving() -> None:
    assert classify_gap(GapEvidence(same_recipe_next=True)) is GapReason.SETUP_SAVING


def test_classify_downstream_blocked() -> None:
    assert classify_gap(GapEvidence(downstream_busy=True)) is GapReason.DOWNSTREAM_BLOCKED


def test_classify_unknown_without_evidence() -> None:
    assert classify_gap(GapEvidence()) is GapReason.UNKNOWN


# ---------------------------------------------------------------------------
# find_gaps / gaps_from_run on a synthetic timeline
# ---------------------------------------------------------------------------


def _timeline(fab: Fab, busy: dict[int, list[tuple[float, float]]]) -> Timeline:
    tools = len(fab.tool_family)
    return Timeline(
        fab=fab,
        horizon=7200.0,
        downs=[[] for _ in range(tools)],
        pm=[[] for _ in range(tools)],
        busy=[list(busy.get(tool, [])) for tool in range(tools)],
    )


def test_find_gaps_complement_of_busy(fab: Fab) -> None:
    tl = _timeline(fab, {0: [(0.0, 1000.0), (4600.0, 7200.0)]})
    gaps = [gap for gap in find_gaps(tl, min_gap_s=300.0) if gap[0] == 0]
    assert gaps == [(0, 1000.0, 4600.0)]


def _batch_visit(fab: Fab, tool: int, start: float) -> Visit:
    """A real lot visit at a batch step of the tool's family, starting at ``start``."""
    family = fab.tool_family[tool]
    for want_cqt in (False, True):
        for lot, route_i in enumerate(fab.lot_route):
            route = fab.routes[route_i]
            for step, fam in enumerate(route.family):
                if fam == family and route.batch_max[step] > 0:
                    if not want_cqt and route.cqt_limit[step] > 0:
                        continue  # keep Q-time evidence out of the batch case
                    return Visit(
                        lot=lot,
                        step=step,
                        family=family,
                        ready=start - 3600.0,
                        start=start,
                        tool=tool,
                        leave=start + 600.0,
                        batch_lots=3,
                    )
    raise AssertionError("no batch step found")


def test_gaps_from_run_batch_wait(fab: Fab) -> None:
    batch_families = {
        route.family[step]
        for route in fab.routes
        for step in range(len(route.family))
        if route.batch_max[step] > 0
    }
    tool = next(t for t, fam in enumerate(fab.tool_family) if fam in batch_families)
    tl = _timeline(fab, {tool: [(0.0, 1000.0), (4600.0, 7200.0)]})
    visit = _batch_visit(fab, tool, 4600.0)
    tl.by_family.setdefault(visit.family, []).append(visit)
    tl.visits.setdefault(visit.lot, []).append(visit)

    class _Run:
        timeline = tl

    records = gaps_from_run(_Run(), min_gap_s=300.0)
    mine = [rec for rec in records if rec.tool == tool]
    assert len(mine) == 1
    assert mine[0].reason is GapReason.BATCH_WAIT
    assert mine[0].source == "inferred"
    assert mine[0].counterfactual is None


# ---------------------------------------------------------------------------
# explain_gap: scripted determinism and LLM fact-check fallback
# ---------------------------------------------------------------------------


def _gap(reason: GapReason = GapReason.BATCH_WAIT) -> GapRecord:
    return GapRecord(
        tool=5,
        family=2,
        start=600.0,
        end=4200.0,
        reason=reason,
        evidence={"next_batch_lots": 3, "batch_min_lots": 4},
    )


def test_explain_scripted_fact_ok() -> None:
    out = explain_gap(_gap())
    assert out.source == "scripted"
    assert out.fact_ok and not out.fact_misses
    assert "60" in out.text  # the 3,600 s gap quoted as minutes
    assert out.counterfactual is None


class _FakeProvider:
    name = "fake"
    mocked = False

    def __init__(self, text: str) -> None:
        self.text = text

    def model_for(self, lane: str) -> str:
        return "fake-1"

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.2
    ) -> LlmResult:
        return LlmResult(
            content=json.dumps({"explanation": self.text}),
            model="fake-1",
            provider="fake",
            lane=lane,
            latency_ms=0.0,
            mocked=False,
        )


def test_explain_llm_invented_number_falls_back() -> None:
    out = explain_gap(_gap(), _FakeProvider("Tool 5 waited 999 min for a batch."))
    assert out.source == "scripted_fallback"
    assert out.fact_ok
    assert out.llm_calls >= 1


def test_explain_unknown_reason_says_unknown() -> None:
    out = explain_gap(_gap(GapReason.UNKNOWN))
    assert out.tier == "inferred_evidence" or out.reason == "unknown"
    assert "unknown" in out.text
    assert out.fact_ok
