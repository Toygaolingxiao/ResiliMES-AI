"""End-to-end recovery: Scout contract, specialist, solver, critic, engines."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from resilimes.agents.narrative import narrate
from resilimes.agents.planner import naive_alternative, reject_alternative
from resilimes.agents.specialist import gather
from resilimes.config import Settings
from resilimes.data.factory import build_source
from resilimes.domain.critique import critique_schedule
from resilimes.domain.gantt import build_gantt
from resilimes.domain.kpis import evaluate, job_outcomes
from resilimes.domain.scenarios import (
    Scenario,
    apply_free_text,
    get_scenario,
    plants_for_scenario,
)
from resilimes.domain.schedule import POLICY_FROZEN, POLICY_RECOVER, schedule_plant
from resilimes.engines.contracts import verify_contract
from resilimes.engines.markovian.engine import MarkovianEngine
from resilimes.engines.scout.engine import Decision, default_scout
from resilimes.engines.world_model.engine import WorldModel
from resilimes.llm.factory import build_provider
from resilimes.logging_config import get_logger

logger = get_logger("resilimes.recover")

_READ_ONLY = {"plant.explain", "plant.query_status"}


class RecoverInput(BaseModel):
    scenario: str | None = None
    incident: str | None = None
    actor_id: str = "planner.ops"
    actor_role: str = "planner"


class RecoveryReport(BaseModel):
    blocked: bool = False
    needs_clarification: bool = False
    approval_required: bool = False
    block_reason: str | None = None
    scenario_id: str | None = None
    incident: str
    horizon: str
    before_label: str = "Before"
    after_label: str = "After"
    mode: dict[str, Any] = Field(default_factory=dict)
    intent: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)
    contract: dict[str, Any] | None = None
    verdict: dict[str, Any] | None = None
    rejected_alternative: dict[str, Any] | None = None
    kpis: dict[str, Any] | None = None
    outcomes: list[dict[str, Any]] = Field(default_factory=list)
    gantt: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    narrative: str = ""
    facts: list[dict[str, Any]] = Field(default_factory=list)
    markovian: dict[str, Any] = Field(default_factory=dict)
    world_model: dict[str, Any] = Field(default_factory=dict)
    provider_call: dict[str, Any] | None = None


def run_recovery(settings: Settings, request: RecoverInput) -> RecoveryReport:
    scenario: Scenario | None = None
    if request.scenario:
        scenario = get_scenario(request.scenario)
        incident = request.incident or scenario.incident
    else:
        incident = (request.incident or "").strip()
        if not incident:
            raise ValueError("Provide a scenario id or an incident description.")

    source = build_source(settings)
    provider = build_provider(settings)
    base, queries = source.load_plant(settings.horizon)
    scout = default_scout(
        signing_secret=settings.scout_signing_secret,
        provider_mode="mock" if provider.mocked else "nightshift",
        ttl_seconds=settings.scout_ttl_seconds,
    )
    decision = scout.decide(
        {
            "prompt": incident,
            "surface": "mes_console",
            "user": {"id": request.actor_id, "role": request.actor_role},
        }
    )
    mode = _mode_banner(settings, provider.mocked, source.name)
    trace: list[dict[str, Any]] = [
        _trace(
            1,
            "scout",
            f"Intent {decision.intent.get('primary')}",
            (f"Confidence {decision.intent.get('confidence')}. Risk {decision.risk.get('level')}."),
            [flag.get("code", "") for flag in decision.risk.get("flags") or []],
        )
    ]
    if decision.risk.get("level") == "block" or decision.execution_contract is None:
        reason = decision.risk.get("reason") or "Scout blocked the request."
        trace.append(_trace(2, "scout", "Guard refused the request", str(reason), []))
        return _shell(
            incident=incident,
            scenario=scenario,
            decision=decision,
            mode=mode,
            horizon=settings.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            trace=trace,
            narrative=str(reason),
            blocked=True,
            block_reason=str(reason),
        )

    contract = decision.execution_contract
    verify_contract(
        contract,
        secret=settings.scout_signing_secret,
        engine="orchestrator",
        required_capability=None,
    )
    intent_id = str(decision.intent.get("primary"))
    if decision.risk.get("level") == "high" and not (decision.risk.get("approvals") or []):
        trace.append(
            _trace(
                2,
                "scout",
                "Approval required",
                "High-risk intents are not executed without an approval record.",
                [],
            )
        )
        return _shell(
            incident=incident,
            scenario=scenario,
            decision=decision,
            mode=mode,
            horizon=settings.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            trace=trace,
            narrative="This intent is high risk. Record an approval before any tool is stopped.",
            approval_required=True,
        )

    if scenario is None and intent_id in _READ_ONLY:
        facts = gather(base, queries)
        narrative = _status_narrative(base)
        trace.append(
            _trace(
                2,
                "specialist",
                "Plant status",
                narrative,
                ["Read-only contract. No schedule is committed."],
            )
        )
        return _shell(
            incident=incident,
            scenario=scenario,
            decision=decision,
            mode=mode,
            horizon=settings.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            trace=trace,
            narrative=narrative,
            facts=_public_facts(facts),
            needs_clarification=decision.needs_clarification,
        )

    if scenario is not None:
        plants = plants_for_scenario(base, scenario.id)
        kind = scenario.kind
    else:
        parameters = decision.intent.get("parameters") or {}
        if not isinstance(parameters, dict):
            parameters = {}
        plants = apply_free_text(base, incident, intent_id, parameters)
        kind = _kind_for(intent_id)

    before_policy = POLICY_FROZEN if kind == "frozen_vs_recover" else POLICY_RECOVER
    bundle: dict[str, Any] = {"queries": queries, "plants": plants, "kind": kind}

    def sense(carry: dict[str, Any]) -> dict[str, Any]:
        facts = gather(plants.after, queries)
        bundle["facts"] = facts
        state = dict(carry.get("state") or {})
        state["fact_count"] = len(facts)
        entities = dict(carry.get("entities") or {})
        entities["plant"] = plants.after.plant_id
        return {
            "decisions": [*list(carry.get("decisions") or []), "specialist: facts gathered"],
            "entities": entities,
            "open_issues": list(carry.get("open_issues") or []),
            "state": state,
        }

    def plan(carry: dict[str, Any]) -> dict[str, Any]:
        before = schedule_plant(plants.before, before_policy)
        after = schedule_plant(plants.after, POLICY_RECOVER)
        bundle["before"] = before
        bundle["after"] = after
        state = dict(carry.get("state") or {})
        state["actions"] = [item.type + ":" + item.job_id for item in after.actions]
        return {
            "decisions": [*list(carry.get("decisions") or []), "planner: solver schedule ready"],
            "entities": dict(carry.get("entities") or {}),
            "open_issues": [item.job_id for item in after.unscheduled],
            "state": state,
        }

    def critique(carry: dict[str, Any]) -> dict[str, Any]:
        committed = critique_schedule(plants.after, bundle["after"])
        rejected = reject_alternative(plants.after, naive_alternative(plants.after, kind))
        bundle["committed"] = committed
        bundle["rejected"] = rejected
        state = dict(carry.get("state") or {})
        state["verdict"] = committed.verdict
        issues = [item.constraint for item in rejected.violations]
        return {
            "decisions": [
                *list(carry.get("decisions") or []),
                f"critic: {committed.verdict}",
            ],
            "entities": dict(carry.get("entities") or {}),
            "open_issues": issues,
            "state": state,
        }

    def explain(carry: dict[str, Any]) -> dict[str, Any]:
        outcomes = job_outcomes(plants.before, bundle["before"], plants.after, bundle["after"])
        before_kpi = evaluate(plants.before, bundle["before"])
        after_kpi = evaluate(plants.after, bundle["after"])
        bundle["outcomes"] = outcomes
        bundle["before_kpi"] = before_kpi
        bundle["after_kpi"] = after_kpi
        text = narrate(
            incident=incident,
            before=before_kpi,
            after=after_kpi,
            outcomes=outcomes,
            committed=bundle["committed"],
            rejected=bundle["rejected"],
        )
        result = provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the ResiliMES explainer. Rewrite the narrative for a "
                        "production supervisor. Do not invent equipment, lots, or numbers. "
                        'Return JSON {"narrative": "..."}.'
                    ),
                },
                {"role": "user", "content": json.dumps({"deterministic_narrative": text})},
            ],
            lane="explainer",
            temperature=0.2,
        )
        bundle["provider_call"] = result.model_dump()
        spoken = _narrative_from_model(result.content, text)
        bundle["narrative"] = spoken
        state = dict(carry.get("state") or {})
        state["narrative"] = spoken[:500]
        return {
            "decisions": [*list(carry.get("decisions") or []), "explainer: narrative ready"],
            "entities": dict(carry.get("entities") or {}),
            "open_issues": list(carry.get("open_issues") or []),
            "state": state,
        }

    def commit(carry: dict[str, Any]) -> dict[str, Any]:
        world = WorldModel(settings.scout_signing_secret)
        for equipment in plants.after.equipment:
            world.ingest(
                event_type="equipment.observed",
                entity_type="equipment",
                entity_id=equipment.equipment_id,
                payload={
                    "status": equipment.status,
                    "availableAtMin": equipment.available_at_min,
                    "faultCode": equipment.fault_code,
                },
                contract=contract,
                idempotency_key=f"boot-{equipment.equipment_id}",
                required_capability="world.sync",
            )
        for action in bundle["after"].actions:
            if not action.to_equipment:
                continue
            world.ingest(
                event_type="job.assigned",
                entity_type="job",
                entity_id=action.job_id,
                payload={
                    "equipmentId": action.to_equipment,
                    "step": action.step,
                    "type": action.type,
                },
                contract=contract,
                idempotency_key=f"commit-{action.job_id}-{action.step}",
                required_capability="schedule.commit",
            )
        replay = world.query(contract, entity_type="job")
        bundle["world"] = world
        bundle["replay_jobs"] = len(replay)
        state = dict(carry.get("state") or {})
        state["committed_jobs"] = len(replay)
        return {
            "decisions": [*list(carry.get("decisions") or []), "world-model: schedule committed"],
            "entities": {"jobs": [row.get("id") for row in replay]},
            "open_issues": [],
            "state": state,
        }

    engine = MarkovianEngine(settings.scout_signing_secret, max_chunks=8)
    run = engine.run_from_contract(
        contract,
        [sense, plan, critique, explain, commit],
        {"scenario": scenario.id if scenario else kind},
    )
    facts = bundle.get("facts") or []
    committed = bundle["committed"]
    rejected = bundle["rejected"]
    before_kpi = bundle["before_kpi"]
    after_kpi = bundle["after_kpi"]
    trace.extend(
        [
            _trace(
                2,
                "specialist",
                "Factory evidence",
                f"{len(facts)} facts from {source.name}.",
                [str(item.get("evidence")) for item in facts[:6]],
            ),
            _trace(
                3,
                "planner",
                "Constraint-aware schedule",
                f"{len(bundle['after'].operations)} operations, "
                f"{len(bundle['after'].unscheduled)} holds.",
                [action.reason for action in bundle["after"].actions[:4]],
            ),
            _trace(
                4,
                "evaluator",
                f"Critic {committed.verdict}",
                committed.rationale,
                [item.detail for item in rejected.violations[:3]],
            ),
            _trace(
                5,
                "markovian",
                "Bounded chunks",
                (
                    f"{len(run.chunks)} chunks, checkpoint tokens {run.input_tokens}, "
                    f"naive history would be {run.naive_tokens}."
                ),
                [chunk.marker for chunk in run.chunks],
            ),
            _trace(
                6,
                "world-model",
                "Event log committed",
                (
                    f"{len(bundle['world'].events)} events, "
                    f"{bundle['replay_jobs']} job entities replayed."
                ),
                [],
            ),
        ]
    )
    logger.info(
        "recovery complete",
        extra={
            "fields": {
                "scenario": scenario.id if scenario else "free-text",
                "verdict": committed.verdict,
                "provider": provider.name,
            }
        },
    )
    return RecoveryReport(
        scenario_id=scenario.id if scenario else None,
        incident=incident,
        horizon=settings.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
        before_label=scenario.before_label if scenario else "Before",
        after_label=scenario.after_label if scenario else "Recovered",
        mode=mode,
        intent=decision.intent,
        risk=decision.risk,
        contract=_public_contract(contract),
        verdict=committed.model_dump(),
        rejected_alternative={
            "actions": [item.model_dump() for item in naive_alternative(plants.after, kind)],
            "critique": rejected.model_dump(),
        },
        kpis={
            "before": before_kpi.model_dump(),
            "after": after_kpi.model_dump(),
            "delta": _delta(before_kpi.model_dump(), after_kpi.model_dump()),
        },
        outcomes=[row.model_dump() for row in bundle["outcomes"]],
        gantt={
            "before": build_gantt(plants.before, bundle["before"]),
            "after": build_gantt(plants.after, bundle["after"]),
        },
        trace=trace,
        narrative=str(bundle.get("narrative") or ""),
        facts=_public_facts(facts),
        markovian={
            "chunks": len(run.chunks),
            "input_tokens": run.input_tokens,
            "naive_tokens": run.naive_tokens,
            "marker": run.marker,
            "failed_chunks": sum(1 for chunk in run.chunks if not chunk.ok),
        },
        world_model={
            "events": len(bundle["world"].events),
            "replay_jobs": bundle["replay_jobs"],
            "schema_version": bundle["world"].schema_version,
        },
        provider_call=bundle.get("provider_call"),
        needs_clarification=decision.needs_clarification,
    )


def _kind_for(intent_id: str) -> str:
    if intent_id == "plant.rush_order":
        return "insert_lot"
    if intent_id == "plant.material_shortage":
        return "stockout"
    return "frozen_vs_recover"


def _mode_banner(settings: Settings, mocked: bool, source_name: str) -> dict[str, Any]:
    llm = "mock" if mocked else "nightshift"
    return {
        "resilimes_mode": settings.mode,
        "llm": llm,
        "data": source_name,
        "label": "OFFLINE MOCK" if mocked and source_name == "sample" else llm.upper(),
        "nemotron_model": settings.nemotron_model,
        "critic_model": settings.nemotron_critic_model or settings.nemotron_model,
    }


def _public_contract(contract: dict[str, Any]) -> dict[str, Any]:
    signature = str(contract.get("signature") or "")
    scope = contract.get("scope") or {}
    profile = contract.get("modelProfile") or {}
    return {
        "contractId": contract.get("contractId"),
        "traceId": contract.get("traceId"),
        "expiresAt": contract.get("expiresAt"),
        "verified": True,
        "signedBy": contract.get("signedBy"),
        "signaturePrefix": signature[:12],
        "capabilities": scope.get("capabilities") if isinstance(scope, dict) else [],
        "modelProfile": profile.get("id") if isinstance(profile, dict) else profile,
        "model": profile.get("model") if isinstance(profile, dict) else None,
    }


def _public_facts(facts: list[dict[str, object]]) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for fact in facts:
        if str(fact.get("name", "")).startswith("query."):
            continue
        public.append(
            {
                "name": fact.get("name"),
                "source": fact.get("source"),
                "evidence": fact.get("evidence"),
            }
        )
    return public


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    keys = (
        "on_time_delivery_pct",
        "weighted_tardiness_min",
        "makespan_min",
        "utilization_pct",
        "lots_at_risk",
        "setup_changes",
    )
    return {key: float(after[key]) - float(before[key]) for key in keys}


def _narrative_from_model(content: str, fallback: str) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        text = content.strip()
        return text[:1200] if text else fallback
    if isinstance(parsed, dict):
        narrative = parsed.get("narrative")
        if isinstance(narrative, str) and narrative.strip():
            return narrative.strip()[:1200]
    return fallback


def _status_narrative(plant: Any) -> str:
    down = [item.equipment_id for item in plant.equipment if item.status in {"DOWN", "MAINTENANCE"}]
    blocked = [job.job_id for job in plant.jobs if job.status == "BLOCKED"]
    return (
        f"Plant {plant.plant_id} at the scenario clock. "
        f"Tools down or in maintenance: {', '.join(down) or 'none'}. "
        f"Blocked lots: {', '.join(blocked) or 'none'}. "
        "Ask about a breakdown, a rush order, or a material shortage to reschedule."
    )


def _trace(step: int, agent: str, title: str, summary: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "step": step,
        "agent": agent,
        "title": title,
        "summary": summary,
        "evidence": [item for item in evidence if item],
    }


def _shell(
    *,
    incident: str,
    scenario: Scenario | None,
    decision: Decision,
    mode: dict[str, Any],
    horizon: str,
    trace: list[dict[str, Any]],
    narrative: str,
    blocked: bool = False,
    approval_required: bool = False,
    needs_clarification: bool = False,
    block_reason: str | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> RecoveryReport:
    return RecoveryReport(
        blocked=blocked,
        approval_required=approval_required,
        needs_clarification=needs_clarification,
        block_reason=block_reason,
        scenario_id=scenario.id if scenario else None,
        incident=incident,
        horizon=horizon,
        before_label=scenario.before_label if scenario else "Before",
        after_label=scenario.after_label if scenario else "After",
        mode=mode,
        intent=decision.intent,
        risk=decision.risk,
        contract=_public_contract(decision.execution_contract)
        if decision.execution_contract
        else None,
        trace=trace,
        narrative=narrative,
        facts=facts or [],
    )
