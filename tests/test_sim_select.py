"""Sim-select: rules-first gate, guardrails, number checker, selection, fallbacks."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any

from resilimes.agents.sim_select import (
    PLAN_LANE,
    SimShiftLead,
    check_numbers,
    escalate,
    escalation_mode,
    flex_pm_error,
    numbers_table,
    pareto_pick,
    rule_trigger,
)
from resilimes.llm.base import LlmResult
from resilimes.llm.mock import MockProvider
from resilimes.smt.exceptions import FabException, Impact, Lever, Option
from resilimes.smt.twin import ForkKpis, PlanScore, Twin, TwinConfig

H = 3600.0


def _impact(q: int) -> Impact:
    return Impact(q, 0, 0, 0.0, 0)


def _exc(kind: str, default_q: int, best_q: int) -> FabException:
    return FabException(
        "x",
        kind,
        0.0,
        0,
        -1,
        [],
        "",
        {},
        [
            Option("A", "rule", Lever(), True, _impact(default_q)),
            Option("B", "edf", Lever("prio"), False, _impact(best_q)),
        ],
    )


def test_legacy_kind_filter_only_behind_the_switch() -> None:
    assert escalate(_exc("breakdown", 0, 0))
    assert escalate(_exc("pm_conflict", 0, 0))
    assert escalate(_exc("hot_insertion", 0, 0))
    assert escalate(_exc("batch_underfill", 0, 0))
    assert not escalate(_exc("qtime_competition", 3, 2))
    assert escalate(_exc("qtime_competition", 4, 2))


def _score(pid: str, **means: float) -> PlanScore:
    base = dict(wt_min=10.0, late_lots=0, on_time=5, due=5, qviol=1, qmissed=1, hot_late=0, moves=9)
    base.update(means)
    return PlanScore(pid, [ForkKpis(**base)])  # type: ignore[arg-type]


def test_rules_first_is_the_default_and_always_is_an_experiment(monkeypatch: Any) -> None:
    monkeypatch.delenv("SHIFT_LEAD_ESCALATE", raising=False)
    assert escalation_mode() == "exception"
    monkeypatch.setenv("SHIFT_LEAD_ESCALATE", "always")
    assert escalation_mode() == "always"
    assert escalation_mode("exception") == "exception"
    monkeypatch.setenv("SHIFT_LEAD_ESCALATE", "sometimes")
    try:
        escalation_mode()
    except ValueError:
        pass
    else:
        raise AssertionError("unknown mode must be refused")


def test_gate_escalates_only_avoidable_qtime_or_late_hot_lots() -> None:
    # Unavoidable misses (qviol without qavoid) and plain tardiness: rule ok.
    assert rule_trigger(_score("A", qviol=5, qavoid=0, wt_min=9e5, late_lots=40)) is None
    assert rule_trigger(_score("A", qavoid=1)) == "avoidable_qtime"
    assert rule_trigger(_score("A", hot_late=1)) == "hot_late"
    # Means over futures: one avoidable miss in one of three futures is < 1.
    runs = [ForkKpis(10.0, 0, 5, 5, 1, 1, 0, 9, qavoid=q) for q in (1, 0, 0)]
    assert rule_trigger(PlanScore("A", runs)) is None
    runs = [ForkKpis(10.0, 0, 5, 5, 1, 1, 0, 9, qavoid=q) for q in (2, 1, 0)]
    assert rule_trigger(PlanScore("A", runs)) == "avoidable_qtime"


def test_pareto_picks_only_a_plan_that_does_no_harm() -> None:
    scores = {
        "A": _score("A"),
        "B": _score("B", wt_min=5.0, qviol=2),  # better wt, worse qviol: not allowed
        "C": _score("C", wt_min=9.0),  # strictly better on wt, equal elsewhere
        "D": _score("D", wt_min=8.0, hot_late=1),  # makes a hot lot late
    }
    assert pareto_pick(scores, "A", list(scores)) == "C"
    tie = {"A": _score("A"), "B": _score("B")}
    assert pareto_pick(tie, "A", list(tie)) == "A"


def test_number_checker() -> None:
    scores = {"A": _score("A"), "P1": _score("P1", wt_min=7.5)}
    plans = {pid: SimpleNamespace(source="x", action="y") for pid in scores}
    table = numbers_table(scores, plans)  # type: ignore[arg-type]
    good = {"plan_id": "P1", "reason": "P1 wt 7.5 vs 10.0", "cited": {"P1.wt_min": 7.5}}
    assert check_numbers(good, table) is None
    assert check_numbers({**good, "cited": {}}, table) is not None
    assert check_numbers({**good, "cited": {"P1.wt_min": 3.0}}, table) is not None
    assert check_numbers({**good, "cited": {"P9.wt_min": 7.5}}, table) is not None
    assert check_numbers({**good, "reason": "saves 42 minutes"}, table) is not None


def _pm_sim() -> Any:
    # Two tools of one family; the calendar puts both in PM at 10-12 h.
    family = SimpleNamespace(tool0=0, tools=2)
    fab = SimpleNamespace(tool_family=[0, 0], families=[family])
    pm = [[(10 * H, 12 * H), (40 * H, 42 * H)], [(10 * H, 12 * H)]]
    return SimpleNamespace(pm=pm, clock=5 * H, fab=fab)


def test_flex_pm_rule() -> None:
    sim = _pm_sim()
    planned = [list(spans) for spans in sim.pm]
    assert flex_pm_error(sim, planned, 0, 0, 1 * H) is None  # less family overlap
    assert flex_pm_error(sim, planned, 0, 0, 3 * H) is None  # none
    assert flex_pm_error(sim, planned, 0, 0, -4 * H) is None  # earlier, still future
    assert flex_pm_error(sim, planned, 0, 0, -6 * H) is not None  # into the past
    assert flex_pm_error(sim, planned, 0, 0, 25 * H) is not None  # beyond 24 h
    assert flex_pm_error(sim, planned, 0, 0, 29 * H) is not None  # hits its next PM
    assert flex_pm_error(sim, planned, 0, 0, 0.0) is not None
    sim.pm[1] = [(14 * H, 16 * H)]  # sibling moved away: now moving onto it is new overlap
    assert flex_pm_error(sim, planned, 0, 0, 4 * H) is not None


class _Scripted:
    """A Completer that answers each lane from a function (or raises)."""

    name = "scripted"
    mocked = True

    def __init__(self, plan: Any, select: Any, served: str = "") -> None:
        self.plan, self.select, self.served = plan, select, served
        self.mock = MockProvider()

    def model_for(self, lane: str) -> str:
        return "scripted"

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.0
    ) -> LlmResult:
        real = self.mock.complete(messages, lane=lane)
        hook = self.plan if lane == PLAN_LANE else self.select
        content = hook(real.content) if hook is not None else real.content
        update: dict[str, Any] = {"content": content}
        if self.served:  # pretend to be a live reply served by this model
            update.update({"mocked": False, "provider_model": self.served})
        return real.model_copy(update=update)


def _run(lead_kwargs: dict[str, Any]) -> SimShiftLead:
    from resilimes.smt.fab import load_fab
    from resilimes.smt.qtime_study import _setup
    from resilimes.smt.simulate import run_policy

    os.environ["RESILIMES_STUDY_HORIZON_H"] = "5"
    try:
        fab = load_fab()
        plant, kw = _setup(fab, "published", 9, "resilimes")
    finally:
        del os.environ["RESILIMES_STUDY_HORIZON_H"]
    twin = Twin(plant, TwinConfig(horizon_sec=1 * H, futures=2))
    lead = SimShiftLead(twin, **lead_kwargs)
    run_policy(plant, shift_lead=lead, **kw)
    twin.close()
    return lead


def _escalated(lead: SimShiftLead) -> list[dict[str, Any]]:
    rows = [entry for entry in lead.log if entry.get("escalated")]
    assert rows, "the 5 h run should escalate at least one exception"
    return rows


def test_sim_only_and_mock_llm_lanes_end_to_end() -> None:
    lead = _run({"completer": MockProvider(), "selector": "llm", "escalation": "always"})
    for entry in _escalated(lead):
        assert entry["receipt"] is not None
        assert entry["fallback"] is False, entry["fallback_cause"]
        assert entry["chosen"] in entry["receipt"]["plans"]
        assert any(plan["source"] == "llm" for plan in entry["plans"])
        chosen, default = entry["receipt"]["chosen"], entry["receipt"]["default"]
        assert chosen["hot_late"] <= default["hot_late"]
    summary = lead.summary()
    assert summary["llm_calls"] >= 2 and summary["twin_forks"] > 0


def test_bad_output_falls_back_to_the_rule_default() -> None:
    lying = _Scripted(None, lambda content: content.replace('"reason": "', '"reason": "999999 '))
    lead = _run({"completer": lying, "selector": "llm", "escalation": "always"})
    for entry in _escalated(lead):
        assert entry["chosen"] == entry["default"]
        assert entry["fallback"] and "number_check" in entry["fallback_cause"]
    garbage = _Scripted(lambda _c: "not json", lambda _c: "{}")
    lead = _run({"completer": garbage, "selector": "llm", "escalation": "always"})
    for entry in _escalated(lead):
        assert entry["chosen"] == entry["default"] and entry["fallback"]
        assert entry["propose_fallback"] and "bad_json" in entry["propose_fallback"]


def test_out_of_scope_plans_are_rejected() -> None:
    def rogue(_content: str) -> str:
        plans = [
            {"id": "P1", "levers": [{"type": "boost", "lots": ["NOT-A-LOT"]}]},
            {"id": "P2", "levers": [{"type": "defer_pm", "tool": "nope", "shift_min": 60}]},
            {"id": "P3", "levers": [{"type": "teleport"}]},
        ]
        return json.dumps({"plans": plans})

    lead = _run({"completer": _Scripted(rogue, None), "selector": "llm", "escalation": "always"})
    for entry in _escalated(lead):
        llm = [plan for plan in entry["plans"] if plan["source"] == "llm"]
        assert llm and all(not plan["valid"] for plan in llm)
        assert entry["chosen"] in ("A", "B", "C", "D", "E")


def test_replies_not_served_by_nemotron_are_not_used() -> None:
    lead = _run(
        {
            "completer": _Scripted(None, None, served="google/gemini-2.5-flash"),
            "selector": "llm",
            "escalation": "always",
        }
    )
    assert _escalated(lead)
    for entry in _escalated(lead):
        assert entry["chosen"] == entry["default"] and entry["fallback"]
    summary = lead.summary()
    assert summary["non_nemotron_replies"] > 0
    assert summary["served_models"] == {"google/gemini-2.5-flash": summary["llm_calls"]}


def test_rules_first_gate_end_to_end() -> None:
    """Default mode: every exception runs the rule plan through the no-AI gate;
    the model is called only for escalated ones, and the counts add up."""
    lead = _run({"completer": MockProvider(), "selector": "llm"})
    summary = lead.summary()
    assert summary["escalation_mode"] == "exception"
    assert summary["exceptions"] == len(lead.log) > 0
    assert summary["rule_handled"] + summary["escalated"] == summary["exceptions"]
    assert summary["gate_checks"] == summary["exceptions"]
    assert summary["llm_calls"] == 2 * summary["escalated"]  # propose + select
    assert summary["rule_handled"] > 0
    for entry in lead.log:
        gate = entry["gate"]
        assert gate is not None and gate["ms"] >= 0
        if entry["escalated"]:
            assert entry["escalation_reason"] == gate["trigger"]
            assert entry["escalation_reason"] in ("avoidable_qtime", "hot_late")
            # The gate's default score is reused as the receipt's default.
            assert entry["receipt"]["default"] == gate["default"]
        else:
            assert entry["escalation_reason"] == "rule_ok" and gate["trigger"] is None
            assert entry["chosen"] == entry["default"] and not entry["fallback"]
            assert gate["default"]["qavoid"] < 1 and gate["default"]["hot_late"] < 1
