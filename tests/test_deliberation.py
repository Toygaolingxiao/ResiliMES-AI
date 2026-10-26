"""Three-role deliberation: kernel adjudication, honesty flags, adapters.

The contexts here are hand-built in the exact shapes the planning layer and
the exception engine produce; the cases mirror scripts/run_deliberation_demo.py.
"""

from __future__ import annotations

import copy
import json

from resilimes.insight.deliberation import (
    deliberate,
    exception_views,
    plan_view,
)
from resilimes.llm.base import LlmResult
from resilimes.llm.mock import MockProvider
from resilimes.smt.exceptions import FabException, Impact, Lever, Option
from resilimes.smt.planning import LotPlan, PlanningOutput

LOT = "Init_Lot_3_17"


def _impact(qviol: int, hot: int, late: int, idle: float) -> dict:
    return {
        "qtime_violations": qviol,
        "hot_late": hot,
        "late_lots": late,
        "idle_min": idle,
        "queue_growth": 0,
    }


def _expedite_context(boost_impact: dict) -> dict:
    return {
        "plan": {
            "now_h": 6.0,
            "bands": {"critical": 2, "behind": 5, "on_plan": 40, "ahead": 12},
            "qtime_at_risk": 7,
            "lots": {
                LOT: {"band": "on_plan", "score": 0.42, "plan_slack_h": 9.5, "qtime_at_risk": 1}
            },
            "litho_overload_days": {},
            "pm_windows": {},
        },
        "shift": {
            "exceptions": [
                {
                    "id": "E1",
                    "kind": "hot_insertion",
                    "family": "Litho_FE_92",
                    "tool": None,
                    "lots": [LOT, "Init_Lot_5_9"],
                    "options": [
                        {
                            "id": "A",
                            "action": "rule_default",
                            "lever": "none",
                            "rule_default": True,
                            "impact": _impact(1, 0, 2, 35.0),
                        },
                        {
                            "id": "B",
                            "action": "expedite",
                            "lever": "prio",
                            "rule_default": False,
                            "impact": boost_impact,
                        },
                    ],
                }
            ],
            "queues": {"Litho_FE_92": 4},
        },
        "field": {
            "observations": [
                {"kind": "lot_location", "subject": LOT, "detail": "queued at Litho_FE_92"}
            ]
        },
    }


EXPEDITE_EVENT = {
    "type": "priority_change",
    "lot": LOT,
    "priority": "hot",
    "new_due_h": 26.0,
    "source": "fab_note (customer request)",
    "validated": True,
}


def _by_role(record) -> dict:
    return {item.role: item for item in record.assessments}


def test_qtime_gate_conflict_keeps_rule_default():
    """Floor wants the expedite; the projection says it costs a Q-time violation."""
    record = deliberate(EXPEDITE_EVENT, _expedite_context(_impact(2, 0, 1, 30.0)))
    roles = _by_role(record)
    assert roles["field"].verdict == "support"
    assert roles["short_term"].verdict == "oppose"
    assert any(r["code"] == "qtime_gate" for r in roles["short_term"].risks)
    # The due change is recorded, but dispatch stays with the rule default.
    assert record.decision["action"] == "rule_default"
    assert record.decision["intake"] == "accepted"
    kinds = {c["kind"] for c in record.conflicts}
    assert "qtime_gate" in kinds and "verdict_split" in kinds
    gate = next(c for c in record.decision_basis["candidates"] if c["option_id"] == "B")
    assert gate["feasible"] is False and gate["rejected_by"] == "hard_qtime_gate"


def test_expedite_approved_when_gate_passes():
    record = deliberate(EXPEDITE_EVENT, _expedite_context(_impact(1, 0, 1, 30.0)))
    # Same Q-time as the default, fewer late lots: lexicographically better.
    assert record.decision["action"] == "expedite"
    assert record.decision["option_id"] == "B"
    assert not any(c["kind"] == "qtime_gate" for c in record.conflicts)


def test_breakdown_option_chosen_lexicographically():
    event = {"type": "breakdown", "family": "Litho_FE_92", "tool": "Litho_FE_92-1"}
    context = {
        "plan": {
            "now_h": 6.0,
            "bands": {"critical": 0, "behind": 1, "on_plan": 45, "ahead": 14},
            "qtime_at_risk": 1,
            "lots": {},
            "litho_overload_days": {},
            "pm_windows": {},
        },
        "shift": {
            "exceptions": [
                {
                    "id": "E2",
                    "kind": "breakdown",
                    "family": "Litho_FE_92",
                    "tool": "Litho_FE_92-1",
                    "lots": ["Init_Lot_7_21"],
                    "options": [
                        {
                            "id": "A",
                            "action": "rule_default",
                            "lever": "none",
                            "rule_default": True,
                            "impact": _impact(0, 1, 3, 10.0),
                        },
                        {
                            "id": "B",
                            "action": "keep_pin",
                            "lever": "keep_pin",
                            "rule_default": False,
                            "impact": _impact(0, 0, 2, 25.0),
                        },
                    ],
                }
            ],
            "queues": {},
        },
        "field": {
            "observations": [
                {"kind": "down_report", "subject": "Litho_FE_92", "detail": "scanner down"}
            ]
        },
    }
    record = deliberate(event, context)
    assert record.decision["action"] == "keep_pin"
    assert record.decision["option_id"] == "B"
    assert _by_role(record)["field"].verdict == "support"


def test_planned_down_pm_overlap_is_a_recorded_conflict():
    event = {
        "type": "planned_down",
        "equipment": "Litho_FE_98",
        "start": "2026-10-27T06:00:00Z",
        "start_h": 30.0,
        "duration_min": 240,
        "source": "fab_note (maintenance)",
        "validated": True,
    }
    context = {
        "plan": {
            "now_h": 6.0,
            "bands": {"critical": 1, "behind": 3, "on_plan": 44, "ahead": 11},
            "qtime_at_risk": 3,
            "lots": {},
            "litho_overload_days": {},
            "pm_windows": {"Litho_FE_98": [[32.0, 36.0]]},
        },
        "shift": {"exceptions": [], "queues": {}},
        "field": {"observations": []},
    }
    record = deliberate(event, context)
    roles = _by_role(record)
    assert roles["long_term"].verdict == "oppose"
    assert any(r["code"] == "pm_window_overlap" for r in roles["long_term"].risks)
    kinds = {c["kind"] for c in record.conflicts}
    assert "pm_band_risk" in kinds and "verdict_split" in kinds
    # Intake stands (it is a floor fact); the conflict is on the record.
    assert record.decision["action"] == "accept_event"


def test_field_contradiction_rejects_the_event():
    event = {
        "type": "planned_down",
        "equipment": "Litho_FE_98",
        "start_h": 30.0,
        "duration_min": 240,
    }
    context = {
        "field": {
            "observations": [
                {
                    "kind": "tool_state",
                    "subject": "Litho_FE_98",
                    "state": "running",
                    "detail": "tool is processing normally",
                }
            ]
        }
    }
    record = deliberate(event, context)
    assert _by_role(record)["field"].verdict == "oppose"
    assert record.decision["action"] == "reject_event"
    assert any(c["kind"] == "evidence_mismatch" for c in record.conflicts)


def test_no_evidence_means_abstentions_and_unknowns():
    record = deliberate({"type": "breakdown", "family": "Litho_FE_92"}, {})
    assert [item.verdict for item in record.assessments] == ["abstain"] * 3
    assert record.decision["action"] == "rule_default"
    unknown = record.decision_basis["unknown"]
    assert len(unknown) == 3
    assert {entry.split(":")[0] for entry in unknown} == {"long_term", "short_term", "field"}


def test_notes_priority_change_dict_is_consumed_as_is():
    """The exact dict shape resilimes.insight.notes.validate_events produces."""
    event = {"type": "priority_change", "lot": LOT, "new_due_h": 26.0, "priority": "hot"}
    record = deliberate(event, {})
    roles = _by_role(record)
    assert roles["field"].verdict == "support"
    assert roles["field"].evidence[0]["kind"] == "notification"
    # No projection exists, so the kernel records the due change but does not
    # approve an unprojected dispatch change.
    assert record.decision["action"] == "rule_default"
    assert record.decision["intake"] == "accepted"
    assert any("no projected impact" in entry for entry in record.decision_basis["unknown"])


class _FabricatingCompleter:
    """Always answers with an invented lot id and an invented count."""

    name = "fabricator"
    mocked = False

    def model_for(self, lane: str) -> str:
        return "fabricator"

    def complete(self, messages, *, lane, temperature=0.2):
        return LlmResult(
            content=json.dumps(
                {
                    "narrative": "Init_Lot_9_999 will miss its Q-time window and "
                    "97 lots are affected, so the expedite is approved."
                }
            ),
            model="fabricator",
            provider=self.name,
            lane=lane,
            latency_ms=1.0,
            mocked=False,
        )


def test_llm_rewrite_failing_fact_check_degrades_to_scripted():
    context = _expedite_context(_impact(1, 0, 1, 30.0))
    scripted = deliberate(EXPEDITE_EVENT, context)
    record = deliberate(EXPEDITE_EVENT, context, _FabricatingCompleter())
    assert record.degraded is True
    assert record.degrade_reason == "fact_check_failed"
    assert record.fact_ok is False
    assert record.fact_misses
    assert record.source == "scripted"
    assert record.narrative == scripted.narrative
    assert record.llm_calls == 2  # one attempt + one repair turn


def test_mock_provider_rewrite_passes_and_is_labelled():
    context = _expedite_context(_impact(1, 0, 1, 30.0))
    record = deliberate(EXPEDITE_EVENT, context, MockProvider())
    assert record.mocked is True
    assert record.source == "mock"
    assert record.fact_ok is True
    assert record.degraded is False
    assert record.llm_calls == 1


def test_inputs_are_never_mutated():
    event = copy.deepcopy(EXPEDITE_EVENT)
    context = _expedite_context(_impact(2, 0, 1, 30.0))
    snapshot = copy.deepcopy(context)
    deliberate(event, context, MockProvider())
    assert event == EXPEDITE_EVENT
    assert context == snapshot


def test_exception_views_adapter_maps_levers_and_impacts():
    exc = FabException(
        id="E9",
        kind="hot_insertion",
        t=0.0,
        family=1,
        tool=-1,
        lots=[7],
        situation="",
        facts={},
        options=[
            Option("A", "keep the rule order", Lever(), True, Impact(1, 2, 0, 35.0, 0)),
            Option(
                "B",
                "boost the hot lot",
                Lever("prio", prio={(7, 0): 0.0}),
                False,
                Impact(1, 1, 0, 30.0, 0),
            ),
        ],
    )
    views = exception_views([exc], family_names=["Diffusion_FE_1", "Litho_FE_92"])
    assert views[0]["family"] == "Litho_FE_92"
    default, boost = views[0]["options"]
    assert default["action"] == "rule_default" and default["rule_default"] is True
    assert boost["action"] == "expedite" and boost["lever"] == "prio"
    assert boost["impact"]["qtime_violations"] == 1


def test_plan_view_adapter_uses_planning_output():
    lot = LotPlan(
        index=0,
        lot_id=LOT,
        route_id="R1",
        order_class="hot",
        tier=1,
        released=False,
        ready_sec=0.0,
        due_sec=40 * 3600.0,
        step=0,
        remaining_raw_sec=20 * 3600.0,
        raw_finish_sec=26 * 3600.0,
        plan_finish_sec=30 * 3600.0,
        raw_slack_sec=14 * 3600.0,
        plan_slack_sec=10 * 3600.0,
        litho_wait_sec=4 * 3600.0,
        score=0.5,
        band="on_plan",
        rank=3,
        qtime_windows=2,
        qtime_at_risk=1,
        steps=(0,),
        step_due=(30 * 3600.0,),
        latest_start=(10 * 3600.0,),
        plan_start=(10 * 3600.0,),
        plan_end=(30 * 3600.0,),
    )
    output = PlanningOutput(
        scenario_id="demo",
        now=6 * 3600.0,
        lots=[lot],
        litho=[],
        availability={},
        release_until=48 * 3600.0,
        runtime_ms=1.0,
    )
    view = plan_view(output, pm_windows={"Litho_FE_98": [(32 * 3600.0, 36 * 3600.0)]})
    assert view["now_h"] == 6.0
    assert view["lots"][LOT]["band"] == "on_plan"
    assert view["pm_windows"]["Litho_FE_98"] == [[32.0, 36.0]]
    record = deliberate(EXPEDITE_EVENT, {"plan": view})
    assert _by_role(record)["long_term"].verdict == "caution"
