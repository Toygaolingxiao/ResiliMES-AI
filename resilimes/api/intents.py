"""POST /api/intents validates and signs. Confirm is what executes."""

from __future__ import annotations

import json
import secrets
from typing import Any

from pydantic import BaseModel, Field

from resilimes.agents.feedback import write_feedback
from resilimes.agents.review_panel import run_review_panel
from resilimes.agents.toolcall import (
    call_from_dump,
    id_errors,
    parse_dispatch,
    scout_model_intent,
)
from resilimes.config import Settings
from resilimes.data.factory import build_source
from resilimes.engines.contracts import verify_contract
from resilimes.engines.scout.engine import Scout, default_scout
from resilimes.llm.factory import build_provider
from resilimes.logging_config import get_logger
from resilimes.txn.engine import InMemoryEngine, lock_targets

logger = get_logger("resilimes.intents")

_CONFIRM_PREFIX = "confirm:"


class IntentBody(BaseModel):
    incident: str = Field(min_length=1, max_length=4000)
    actor_id: str = "planner.ops"
    actor_role: str = Field(default="planner", max_length=40)


class ConfirmBody(BaseModel):
    confirmation_id: str = Field(min_length=4, max_length=64)


class UnknownConfirmation(KeyError):
    pass


class ConfirmationState(RuntimeError):
    pass


def propose_intent(settings: Settings, engine: InMemoryEngine, body: IntentBody) -> dict[str, Any]:
    provider = build_provider(settings)
    scout = _scout(settings, provider.mocked)
    text = body.incident.strip()
    injection = scout.injection_hit(text)
    if injection:
        logger.info(
            "intent blocked",
            extra={"fields": {"reason": "prompt_injection"}},
        )
        return {
            "status": "rejected",
            "confirmation_id": None,
            "call": None,
            "contract": None,
            "source": "deterministic-fallback",
            "meterless_request_id": "",
            "errors": ["Prompt injection detected."],
        }
    parsed = parse_dispatch(provider, text)
    logger.info(
        "intent parsed",
        extra={
            "fields": {
                "source": parsed.source,
                "meterless_request_id": parsed.request_id,
                "intent": (parsed.call or {}).get("intent"),
            }
        },
    )
    if parsed.call is None:
        return _rejected(parsed.errors, parsed.source, parsed.request_id)
    call = call_from_dump(parsed.call)
    plant = engine.load_plant(_load_source_plant(settings))
    errors = id_errors(call, plant)
    if errors:
        rejected = _rejected(errors, parsed.source, parsed.request_id)
        rejected["call"] = call.model_dump()
        return rejected
    decision = scout.decide(
        {
            "prompt": text,
            "surface": "api",
            "user": {"id": body.actor_id, "role": body.actor_role},
        },
        model_intent=scout_model_intent(call, parsed.request_id),
    )
    if decision.execution_contract is None:
        reason = str(decision.risk.get("reason") or "Scout did not sign a contract.")
        return _rejected([reason], parsed.source, parsed.request_id)
    confirmation_id = secrets.token_hex(8)
    record = {
        "status": "pending",
        "incident": text,
        "actor_id": body.actor_id,
        "actor_role": body.actor_role,
        "call": call.model_dump(),
        "contract": decision.execution_contract,
        "source": parsed.source,
        "meterless_request_id": parsed.request_id,
        "fallback_reason": parsed.fallback_reason,
    }
    engine.store.set(f"{_CONFIRM_PREFIX}{confirmation_id}", json.dumps(record, default=str))
    return {
        "status": "pending_confirmation",
        "confirmation_id": confirmation_id,
        "call": call.model_dump(),
        "contract": _public_contract(decision.execution_contract),
        "source": parsed.source,
        "meterless_request_id": parsed.request_id,
        "errors": [],
    }


def confirm_intent(settings: Settings, engine: InMemoryEngine, body: ConfirmBody) -> dict[str, Any]:
    key = f"{_CONFIRM_PREFIX}{body.confirmation_id}"
    raw = engine.store.get(key)
    if raw is None:
        raise UnknownConfirmation(body.confirmation_id)
    record = json.loads(raw)
    if record.get("status") != "pending":
        raise ConfirmationState("This confirmation was already used.")
    record["status"] = "executing"
    if not engine.store.compare_and_set(key, raw, json.dumps(record, default=str)):
        raise ConfirmationState("This confirmation was already used.")
    contract = record.get("contract")
    if not isinstance(contract, dict):
        raise ConfirmationState("Scout did not sign this confirmation.")
    verify_contract(
        contract,
        secret=settings.scout_signing_secret,
        engine="orchestrator",
        required_capability=None,
    )
    call = call_from_dump(record["call"])
    plant = engine.load_plant(_load_source_plant(settings))
    provider = build_provider(settings)
    lock = engine.acquire_lock(lock_targets(call, plant))
    try:
        result = engine.apply(lock, call.model_dump(), plant)
    finally:
        engine.abort(lock)
    execution = result.model_dump()
    feedback = write_feedback(provider, result.draft or plant, execution)
    panel = None
    if result.book is not None and result.draft is not None and result.critique_obj is not None:
        panel = run_review_panel(
            provider,
            result.draft,
            result.book,
            result.critique_obj,
            allow_model=not provider.mocked,
        )
    record["status"] = "executed" if result.ok else "aborted"
    engine.store.set(key, json.dumps(record, default=str))
    logger.info(
        "intent confirmed",
        extra={
            "fields": {
                "confirmation_id": body.confirmation_id,
                "committed": result.committed,
                "meterless_request_id": feedback.get("meterless_request_id", ""),
                "lock_token": result.lock_token,
            }
        },
    )
    return {
        "status": "executed" if result.ok else "aborted",
        "confirmation_id": body.confirmation_id,
        "call": call.model_dump(),
        "committed": result.committed,
        "simulated": result.simulated,
        "lock_token": result.lock_token,
        "kpis": result.kpis,
        "affected_lots": result.affected_lots,
        "critique": result.critique,
        "feedback": feedback,
        "review_panel": panel,
        "trace": result.trace,
        "errors": result.errors,
        "fix_hint": result.fix_hint,
        "source": record.get("source"),
        "meterless_request_id": feedback.get("meterless_request_id")
        or record.get("meterless_request_id", ""),
    }


def _scout(settings: Settings, mocked: bool) -> Scout:
    return default_scout(
        signing_secret=settings.scout_signing_secret,
        provider_mode="mock" if mocked else "nightshift",
        ttl_seconds=settings.scout_ttl_seconds,
    )


def _load_source_plant(settings: Settings) -> Any:
    plant, _records = build_source(settings).load_plant(settings.horizon)
    return plant


def _rejected(errors: list[str], source: str, request_id: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "confirmation_id": None,
        "call": None,
        "contract": None,
        "source": source,
        "meterless_request_id": request_id,
        "errors": errors,
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
