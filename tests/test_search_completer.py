"""Lever-search: the non-LLM same-budget proposer of the sim_search arm.

Seeded sampling of the same DSL lever space the model proposes in. These
tests pin the contract the study relies on: exactly the plan budget,
legal levers, payload references only, seed reproducibility, and the
study wiring (arm present, completer honest, selector always pareto).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from resilimes.agents.sim_select import PLAN_LANE, PLAN_SYSTEM, SELECT_LANE
from resilimes.llm.search import LEVER_TYPES, SearchCompleter
from resilimes.smt import sim_select_study as study


def _payload(kind: str = "qtime_competition", n: int = 10) -> dict[str, Any]:
    lots = [
        {
            "lot": f"LOT-{i}",
            "class": ("VIP", "hot", "normal")[i % 3],
            "queued_here": True,
            "qtime_slack_min": 10.0 * i + 5,
            "due_slack_min": 30.0 * i + 7,
        }
        for i in range(n)
    ]
    return {
        "kind": kind,
        "family": "Fam_A",
        "situation": "Fam_A: 2 idle furnace(s); recipe 42 batch has 60 of min 96 wafers",
        "facts": {"tool": "T-1"},
        "lots": lots,
        "tools": [{"tool": "T-1"}, {"tool": "T-2"}],
        "engine_options": [],
        "max_plans": 4,
    }


def _ask(
    completer: SearchCompleter, payload: dict[str, Any], lane: str = PLAN_LANE
) -> tuple[dict[str, Any], Any]:
    messages = [
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": json.dumps(payload)},
    ]
    result = completer.complete(messages, lane=lane)
    return json.loads(result.content), result


def _lever_refs(plans: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    lots: set[str] = set()
    tools: set[str] = set()
    for plan in plans:
        for lever in plan["levers"]:
            lots.update(str(name) for name in lever.get("lots", []))
            if lever.get("tool") is not None:
                tools.add(str(lever["tool"]))
    return lots, tools


def test_generates_exactly_the_plan_budget_labelled_not_a_model() -> None:
    answer, result = _ask(SearchCompleter(seed=7), _payload())
    plans = answer["plans"]
    assert len(plans) == 4
    assert [plan["id"] for plan in plans] == ["P1", "P2", "P3", "P4"]
    for plan in plans:
        assert 1 <= len(plan["levers"]) <= 4
        assert all(lever["type"] in LEVER_TYPES for lever in plan["levers"])
        assert "not a model" in plan["why"]
    assert result.mocked is True
    assert result.provider == "lever-search"
    assert result.model == "lever-search"


def test_kind_specific_levers_and_payload_references_only() -> None:
    known_lots = {f"LOT-{i}" for i in range(10)}
    known_tools = {"T-1", "T-2"}
    by_kind = {
        "breakdown": {"boost", "keep_pin", "reroute"},
        "pm_conflict": {"boost", "defer_pm"},
        "batch_underfill": {"boost", "start_batch"},
        "qtime_competition": {"boost"},
    }
    for kind, expected in by_kind.items():
        answer, _ = _ask(SearchCompleter(seed=7), _payload(kind))
        plans = answer["plans"]
        assert len(plans) == 4, kind
        types = {lever["type"] for plan in plans for lever in plan["levers"]}
        assert types == expected, (kind, types)
        lots, tools = _lever_refs(plans)
        assert lots <= known_lots and tools <= known_tools, kind
        for plan in plans:  # PlanBuilder rejects a lot kept and rerouted at once
            kept = {
                name
                for lever in plan["levers"]
                if lever["type"] == "keep_pin"
                for name in lever["lots"]
            }
            moved = {
                name
                for lever in plan["levers"]
                if lever["type"] == "reroute"
                for name in lever["lots"]
            }
            assert not kept & moved, kind


def test_pm_plans_defer_the_facts_tool_with_varied_shifts() -> None:
    answer, _ = _ask(SearchCompleter(seed=7), _payload("pm_conflict"))
    defers = [
        lever for plan in answer["plans"] for lever in plan["levers"] if lever["type"] == "defer_pm"
    ]
    assert defers and all(lever["tool"] == "T-1" for lever in defers)
    assert all(lever["shift_min"] != 0 for lever in defers)


def test_batch_plans_start_the_recipe_named_in_the_situation() -> None:
    answer, _ = _ask(SearchCompleter(seed=7), _payload("batch_underfill"))
    starts = [
        lever
        for plan in answer["plans"]
        for lever in plan["levers"]
        if lever["type"] == "start_batch"
    ]
    assert starts and all(lever["recipe"] == 42 for lever in starts)


def test_same_seed_reproduces_and_other_seeds_differ() -> None:
    payload = _payload()
    first, _ = _ask(SearchCompleter(seed=1), payload)
    again, _ = _ask(SearchCompleter(seed=1), payload)
    other, _ = _ask(SearchCompleter(seed=2), payload)
    assert first == again
    assert first != other


def test_select_lane_is_a_labelled_noop_and_other_lanes_refuse() -> None:
    completer = SearchCompleter(seed=1)
    answer, result = _ask(completer, _payload(), lane=SELECT_LANE)
    assert answer["plans"] == [] and "pareto" in answer["note"]
    assert result.mocked is True
    with pytest.raises(ValueError, match="lever-search"):
        completer.complete([{"role": "user", "content": "{}"}], lane="narrative", temperature=0.0)


def test_sim_search_arm_wiring() -> None:
    assert "sim_search" in study.ARMS
    assert "sim_search" not in study.LLM_ARMS
    assert "sim_search" not in study.MEMORY_ARMS
    completer = study._completer("sim_search")
    assert isinstance(completer, SearchCompleter)
    assert completer.name == "lever-search" and completer.mocked is True
    assert study._selector("sim_search", completer) == "pareto"
    assert study._selector("sim_llm", completer) == "llm"
    assert study._selector("sim", None) == "pareto"


def test_search_seed_comes_from_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIMES_SEARCH_SEED", "99")
    completer = study._completer("sim_search")
    assert isinstance(completer, SearchCompleter) and completer.seed == 99
    monkeypatch.delenv("RESILIMES_SEARCH_SEED")
    default = study._completer("sim_search")
    assert isinstance(default, SearchCompleter) and default.seed != 99


def test_sim_shift_lead_consumes_search_plans_end_to_end() -> None:
    """The _run pattern of test_sim_select, with the sampler + pareto:
    escalated exceptions get valid sampled plans and a counterfactual
    receipt, and the model lanes are only ever the plan lane."""
    from resilimes.agents.sim_select import SimShiftLead
    from resilimes.smt.fab import load_fab
    from resilimes.smt.qtime_study import _setup
    from resilimes.smt.simulate import run_policy
    from resilimes.smt.twin import Twin, TwinConfig

    os.environ["RESILIMES_STUDY_HORIZON_H"] = "5"
    try:
        fab = load_fab()
        plant, kwargs = _setup(fab, "published", 9, "resilimes")
    finally:
        del os.environ["RESILIMES_STUDY_HORIZON_H"]
    twin = Twin(plant, TwinConfig(horizon_sec=3600.0, futures=2))
    lead = SimShiftLead(
        twin,
        completer=SearchCompleter(seed=5),
        selector="pareto",
        escalation="always",
    )
    try:
        run_policy(plant, shift_lead=lead, **kwargs)
    finally:
        twin.close()
    escalated = [entry for entry in lead.log if entry.get("escalated")]
    assert escalated, "the 5 h run should escalate at least one exception"
    for entry in escalated:
        assert entry["provider"] == "sim+lever-search"
        assert entry["selector"] == "pareto"
        assert entry["propose_fallback"] is None
        assert entry["receipt"] is not None
        assert any(plan["source"] == "llm" for plan in entry["plans"])
    summary = lead.summary()
    assert summary["llm_calls"] == summary["escalated"]  # propose only, never select
    assert summary["served_models"] == {"lever-search": summary["llm_calls"]}
