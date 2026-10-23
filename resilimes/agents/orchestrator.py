"""End-to-end recovery: Scout contract, specialist, solver, critic, engines."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, cast

from pydantic import BaseModel, Field

from resilimes.agents.brief import refusal_brief, schedule_brief, status_brief
from resilimes.agents.narrative import narrate
from resilimes.agents.planner import naive_alternative, reject_alternative
from resilimes.agents.specialist import gather
from resilimes.config import Settings
from resilimes.data.factory import build_source
from resilimes.domain.checks import validate
from resilimes.domain.critique import constraint_checks, critique_schedule
from resilimes.domain.gantt import annotate_moves, build_gantt, shared_window
from resilimes.domain.kpis import (
    bottleneck_report,
    compare_load,
    evaluate,
    fed_bottleneck,
    flow_metrics,
    job_outcomes,
    lots_moved,
    metric_tones,
    qtime_report,
    step_waits,
)
from resilimes.domain.loadmap import load_map
from resilimes.domain.scenarios import (
    Scenario,
    apply_free_text,
    get_scenario,
    plants_for_scenario,
)
from resilimes.domain.schedule import POLICY_EDD, POLICY_FROZEN, POLICY_RECOVER, schedule_plant
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
    timing: dict[str, Any] | None = None
    load: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    narrative: str = ""
    facts: list[dict[str, Any]] = Field(default_factory=list)
    markovian: dict[str, Any] = Field(default_factory=dict)
    world_model: dict[str, Any] = Field(default_factory=dict)
    provider_call: dict[str, Any] | None = None
    brief: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, str]] = Field(default_factory=list)
    validation: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)


def run_recovery(
    settings: Settings,
    request: RecoverInput,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> RecoveryReport:
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
    mode = _mode_banner(settings, provider.mocked, source.name)
    steps: list[dict[str, Any]] = []
    started = time.perf_counter()

    def emit(
        phase: str,
        agent: str,
        title: str,
        summary: str,
        evidence: list[str] | None = None,
        slots: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "type": "step",
            "seq": len(steps) + 1,
            "phase": phase,
            "agent": agent,
            "title": title,
            "summary": summary,
            "evidence": [item for item in (evidence or []) if item],
            "slots": slots or {},
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        steps.append(event)
        if on_event is not None:
            on_event(event)

    emit(
        "alert",
        "console",
        "Disruption",
        incident,
        [],
        {"scenario": scenario.id if scenario else ""},
    )
    decision = scout.decide(
        {
            "prompt": incident,
            "surface": "mes_console",
            "user": {"id": request.actor_id, "role": request.actor_role},
        }
    )
    trace: list[dict[str, Any]] = [
        _trace(
            1,
            "scout",
            f"Intent {decision.intent.get('primary')}",
            (f"Confidence {decision.intent.get('confidence')}. Risk {decision.risk.get('level')}."),
            [flag.get("code", "") for flag in decision.risk.get("flags") or []],
        )
    ]
    emit(
        "scout",
        "scout",
        "Intent signed" if decision.execution_contract else "Intent classified",
        (
            f"Intent {decision.intent.get('primary')}. "
            f"Confidence {decision.intent.get('confidence')}. "
            f"Risk {decision.risk.get('level')}."
        ),
        [flag.get("code", "") for flag in decision.risk.get("flags") or []],
        {
            "intent": decision.intent.get("primary"),
            "confidence": decision.intent.get("confidence"),
            "risk": decision.risk.get("level"),
        },
    )
    if decision.risk.get("level") == "block" or decision.execution_contract is None:
        reason = decision.risk.get("reason") or "Scout blocked the request."
        trace.append(_trace(2, "scout", "Guard refused the request", str(reason), []))
        emit("guard", "scout", "Guard refused the request", str(reason), [], {"reason": reason})
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
            steps=steps,
            brief=refusal_brief(str(reason)),
        )

    contract = decision.execution_contract
    verify_contract(
        contract,
        secret=settings.scout_signing_secret,
        engine="orchestrator",
        required_capability=None,
    )
    public = _public_contract(contract)
    emit(
        "contract",
        "scout",
        "Contract verified",
        f"Signature {public['signaturePrefix']} verified.",
        [],
        {
            "signature_prefix": public["signaturePrefix"],
            "contract_id": public["contractId"],
            "capabilities": public["capabilities"],
        },
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
        emit(
            "guard",
            "scout",
            "Approval required",
            "High-risk intents are not executed without an approval record.",
            [],
            {},
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
            steps=steps,
            brief=refusal_brief("approval required", approval=True),
        )

    if scenario is None and intent_id in _READ_ONLY:
        facts = gather(base, queries)
        narrative = _status_narrative(base)
        queries_only = [item for item in facts if str(item.get("name", "")).startswith("query.")]
        emit(
            "query",
            "specialist",
            "Zetaris read",
            f"{len(queries_only)} reads from {source.name}.",
            [str(item.get("evidence")) for item in queries_only],
            {"source": source.name, "reads": len(queries_only)},
        )
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
            steps=steps,
            brief=status_brief(
                [
                    item.equipment_id
                    for item in base.equipment
                    if item.status in {"DOWN", "MAINTENANCE"}
                ],
                [job.job_id for job in base.jobs if job.status == "BLOCKED"],
            ),
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

    if kind == "scale":
        before_policy = POLICY_EDD
    elif kind == "frozen_vs_recover":
        before_policy = POLICY_FROZEN
    else:
        before_policy = POLICY_RECOVER
    bundle: dict[str, Any] = {"queries": queries, "plants": plants, "kind": kind}

    def sense(carry: dict[str, Any]) -> dict[str, Any]:
        facts = gather(plants.after, queries)
        bundle["facts"] = facts
        queries_only = [item for item in facts if str(item.get("name", "")).startswith("query.")]
        emit(
            "query",
            "specialist",
            "Zetaris read",
            f"{len(queries_only)} reads from {source.name}.",
            [str(item.get("evidence")) for item in queries_only],
            {"source": source.name, "reads": len(queries_only), "checkpoint": 1, "checkpoints": 5},
        )
        emit(
            "sense",
            "specialist",
            "Sense",
            f"{len(facts)} facts on the disrupted plant.",
            [],
            {"facts": len(facts), "checkpoint": 1, "checkpoints": 5},
        )
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
        started_plan = time.perf_counter()
        before = schedule_plant(plants.before, before_policy)
        after = schedule_plant(plants.after, POLICY_RECOVER)
        bundle["schedule_ms"] = (time.perf_counter() - started_plan) * 1000
        bundle["before"] = before
        bundle["after"] = after
        emit(
            "plan",
            "planner",
            "Plan",
            (f"{len(after.operations)} operations, {len(after.unscheduled)} holds."),
            [action.reason for action in after.actions[:4]],
            {
                "operations": len(after.operations),
                "holds": len(after.unscheduled),
                "checkpoint": 2,
                "checkpoints": 5,
            },
        )
        state = dict(carry.get("state") or {})
        state["actions"] = [item.type + ":" + item.job_id for item in after.actions]
        return {
            "decisions": [*list(carry.get("decisions") or []), "planner: solver schedule ready"],
            "entities": dict(carry.get("entities") or {}),
            "open_issues": [item.job_id for item in after.unscheduled],
            "state": state,
        }

    def critique(carry: dict[str, Any]) -> dict[str, Any]:
        started_critic = time.perf_counter()
        committed = critique_schedule(plants.after, bundle["after"])
        rejected = reject_alternative(plants.after, naive_alternative(plants.after, kind))
        bundle["critic_ms"] = (time.perf_counter() - started_critic) * 1000
        bundle["committed"] = committed
        bundle["rejected"] = rejected
        refused = rejected.violations[0].constraint if rejected.violations else ""
        critic_line = (
            f"Verdict {committed.verdict}. Refused alternative: {refused}."
            if refused
            else f"Verdict {committed.verdict}. No unsafe alternative was proposed."
        )
        emit(
            "critique",
            "evaluator",
            "Critic",
            critic_line,
            [item.detail for item in rejected.violations[:2]],
            {
                "verdict": committed.verdict,
                "refused": refused,
                "checkpoint": 3,
                "checkpoints": 5,
            },
        )
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
        emit(
            "explain",
            "nightshift",
            "Explain",
            f"{result.provider} · {result.model} · {int(result.latency_ms)} ms.",
            [],
            {
                "provider": result.provider,
                "model": result.model,
                "mocked": result.mocked,
                "latency_ms": result.latency_ms,
                "checkpoint": 4,
                "checkpoints": 5,
            },
        )
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
                    "actionType": action.type,
                },
                contract=contract,
                idempotency_key=f"commit-{action.job_id}-{action.step}",
                required_capability="schedule.commit",
            )
        replay = world.query(contract, entity_type="job")
        bundle["world"] = world
        bundle["replay_jobs"] = len(replay)
        bundle["replayed"] = [
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "equipmentId": row.get("equipmentId"),
                "step": row.get("step"),
                "actionType": row.get("actionType"),
            }
            for row in replay
        ]
        emit(
            "commit",
            "world-model",
            "Commit",
            f"{len(world.events)} events, {len(replay)} job entities replayed.",
            [],
            {
                "events": len(world.events),
                "jobs": len(replay),
                "checkpoint": 5,
                "checkpoints": 5,
            },
        )
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
    started_validate = time.perf_counter()
    validated = validate(plants.after, bundle["after"])
    if kind == "scale":
        bundle["critic_ms"] = (
            float(bundle.get("critic_ms") or 0) + (time.perf_counter() - started_validate) * 1000
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
        kpis=_comparison_kpis(
            before_kpi.model_dump(),
            after_kpi.model_dump(),
            plants.before,
            bundle["before"],
            plants.after,
            bundle["after"],
        ),
        outcomes=[row.model_dump() for row in bundle["outcomes"]],
        gantt=(
            None
            if kind == "scale"
            else _gantt_pair(plants.before, bundle["before"], plants.after, bundle["after"])
        ),
        timing=_scale_timing(plants.after, bundle, validated) if kind == "scale" else None,
        load=_scale_load(plants.before, bundle["before"], plants.after, bundle["after"])
        if kind == "scale"
        else None,
        trace=trace,
        checks=constraint_checks(committed, rejected),
        validation=validated,
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
            "replayed": bundle.get("replayed") or [],
            "schema_version": bundle["world"].schema_version,
        },
        provider_call=bundle.get("provider_call"),
        needs_clarification=decision.needs_clarification,
        brief=schedule_brief(
            kind=kind,
            outcomes=bundle["outcomes"],
            before=before_kpi,
            after=after_kpi,
            rejected=rejected,
            verdict=committed.verdict,
            bottleneck=_kept_bottleneck(plants.after, bundle["before"], bundle["after"]),
            focus_equipment=_focus_equipment(scenario, decision),
            repair_min=_repair_min(scenario, decision),
        ),
        steps=steps,
    )


def _gantt_pair(before_plant: Any, before: Any, after_plant: Any, after: Any) -> dict[str, Any]:
    before_gantt = build_gantt(before_plant, before)
    after_gantt = build_gantt(after_plant, after)
    annotate_moves(before_gantt, after_gantt)
    return {
        "before": before_gantt,
        "after": after_gantt,
        "window": shared_window(before_gantt, after_gantt),
    }


def _kind_for(intent_id: str) -> str:
    if intent_id == "plant.rush_order":
        return "insert_lot"
    if intent_id == "plant.material_shortage":
        return "stockout"
    if intent_id == "plant.rework":
        return "rework"
    if intent_id == "plant.qtime":
        return "qtime"
    return "frozen_vs_recover"


def _kept_bottleneck(after_plant: Any, before: Any, after: Any) -> str:
    load = compare_load(after_plant, before, after_plant, after)
    before_side = cast(dict[str, Any], load["before"])
    after_side = cast(dict[str, Any], load["after"])
    return fed_bottleneck(
        before,
        after,
        after_plant,
        cast(list[dict[str, Any]], before_side["areas"]),
        cast(list[dict[str, Any]], after_side["areas"]),
    )


_SCALE_WINDOW_MIN = 12 * 60


def _scale_timing(plant: Any, bundle: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    schedule = bundle["after"]
    return {
        "schedule_ms": round(float(bundle.get("schedule_ms") or 0), 1),
        "critic_ms": round(float(bundle.get("critic_ms") or 0), 1),
        "lots": len(plant.jobs),
        "tools": len(plant.equipment),
        "steps": len(schedule.operations),
        "holds": len(schedule.unscheduled),
        "checks_passed": int(validated.get("passed") or 0),
        "checks_failed": int(validated.get("failed") or 0),
    }


def _scale_load(before_plant: Any, before: Any, after_plant: Any, after: Any) -> dict[str, Any]:
    return {
        "window_min": _SCALE_WINDOW_MIN,
        "before": load_map(before_plant, before, _SCALE_WINDOW_MIN),
        "after": load_map(after_plant, after, _SCALE_WINDOW_MIN),
    }


def _focus_equipment(scenario: Scenario | None, decision: Decision) -> str:
    if scenario is not None:
        return ""
    parameters = decision.intent.get("parameters") or {}
    if not isinstance(parameters, dict):
        return ""
    return str(parameters.get("equipment_id") or "")


def _repair_min(scenario: Scenario | None, decision: Decision) -> int | None:
    if scenario is not None:
        return None
    parameters = decision.intent.get("parameters") or {}
    if not isinstance(parameters, dict):
        return None
    repair = parameters.get("repair_min")
    if isinstance(repair, int):
        return repair
    return None


def _mode_banner(settings: Settings, mocked: bool, source_name: str) -> dict[str, Any]:
    llm = "mock" if mocked else "nightshift"
    return {
        "resilimes_mode": settings.mode,
        "llm": llm,
        "data": source_name,
        "label": "OFFLINE MOCK" if mocked and source_name == "sample" else llm.upper(),
        "nemotron_model": settings.nemotron_model if settings.token_configured else None,
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


def _comparison_kpis(
    before_dump: dict[str, Any],
    after_dump: dict[str, Any],
    before_plant: Any,
    before: Any,
    after_plant: Any,
    after: Any,
) -> dict[str, Any]:
    load = compare_load(before_plant, before, after_plant, after)
    before_side = cast(dict[str, Any], load["before"])
    after_side = cast(dict[str, Any], load["after"])
    before_dump["utilization_pct"] = before_side["utilization_pct"]
    after_dump["utilization_pct"] = after_side["utilization_pct"]
    before_dump.update(flow_metrics(before))
    after_dump.update(flow_metrics(after))
    return {
        "before": before_dump,
        "after": after_dump,
        "delta": _delta(before_dump, after_dump),
        "areas": {"before": before_side["areas"], "after": after_side["areas"]},
        "lots_moved": lots_moved(before, after),
        "tones": metric_tones(before_dump, after_dump),
        "horizon_min": load["horizon_min"],
        "down": {"before": before_side["down"], "after": after_side["down"]},
        "waits": {"before": step_waits(before), "after": step_waits(after)},
        "qtime": {
            "before": qtime_report(before_plant, before),
            "after": qtime_report(after_plant, after),
        },
        "bottleneck": bottleneck_report(
            before,
            after,
            cast(list[dict[str, Any]], before_side["areas"]),
            cast(list[dict[str, Any]], after_side["areas"]),
        ),
    }


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    keys = (
        "on_time_delivery_pct",
        "weighted_tardiness_min",
        "makespan_min",
        "utilization_pct",
        "lots_at_risk",
        "setup_changes",
        "mean_lead_min",
        "mean_wait_min",
        "mean_x_factor",
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
    steps: list[dict[str, Any]] | None = None,
    brief: dict[str, Any] | None = None,
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
        steps=steps or [],
        brief=brief or {},
    )
