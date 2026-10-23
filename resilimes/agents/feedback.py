"""Business feedback from an engine result. Every number is checked."""

from __future__ import annotations

import json
from typing import Any

from resilimes.agents.facts import fact_table, narrative_mismatches
from resilimes.agents.jsonutil import SchemaError, extract_json_object
from resilimes.domain.kpis import KpiReport
from resilimes.domain.models import Plant
from resilimes.llm.base import Completer, LlmResult

_LANE = "feedback"


def write_feedback(
    provider: Completer,
    plant: Plant,
    execution: dict[str, Any],
) -> dict[str, Any]:
    """Turn the engine result into supervisor text.

    Mock mode and a failed or mismatched model call keep the deterministic
    sentence and say so. They do not claim the text came from Nemotron.
    """
    text = deterministic_feedback(execution)
    if provider.mocked or execution.get("kpis") is None:
        return _labeled(
            text,
            source="deterministic-fallback",
            request_id="",
            degraded=provider.mocked is False and execution.get("kpis") is None,
        )
    facts = _facts(plant, execution, text)
    try:
        result = provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You write one short business note for a shift supervisor. "
                        "Use only numbers and lot or tool ids that appear in the engine result. "
                        'Do not recompute KPIs. Return JSON {"feedback": "..."}.'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"engine_result": execution, "deterministic_feedback": text},
                        default=str,
                    ),
                },
            ],
            lane=_LANE,
            temperature=0.0,
        )
    except Exception as exc:
        return _labeled(
            text,
            source="deterministic-fallback",
            request_id="",
            degraded=True,
            reason=str(exc),
        )
    spoken = _feedback_from(result)
    if spoken is None:
        return _labeled(
            text,
            source="deterministic-fallback",
            request_id=result.meterless_request_id,
            degraded=True,
            reason="Feedback payload was not JSON.",
        )
    misses = narrative_mismatches(spoken, facts)
    if misses:
        return _labeled(
            text,
            source="deterministic-fallback",
            request_id=result.meterless_request_id,
            degraded=True,
            reason="; ".join(misses),
        )
    return {
        "feedback": spoken,
        "source": "nemotron",
        "narrative_degraded": False,
        "verified": True,
        "meterless_request_id": result.meterless_request_id,
    }


def deterministic_feedback(execution: dict[str, Any]) -> str:
    critique = execution.get("critique") or {}
    verdict = str(critique.get("verdict") or "")
    state = "committed" if execution.get("committed") else "not committed"
    affected = execution.get("affected_lots") or []
    names = ", ".join(str(item.get("lot_id")) for item in affected[:6] if isinstance(item, dict))
    parts = [f"Execution {state}."]
    if verdict:
        parts.append(f"Critic verdict {verdict}.")
    parts.append(f"Affected lots: {names or 'none'}.")
    kpis = execution.get("kpis") or {}
    before = kpis.get("before") if isinstance(kpis, dict) else None
    after = kpis.get("after") if isinstance(kpis, dict) else None
    if isinstance(before, dict) and isinstance(after, dict):
        if "weighted_tardiness_min" in before and "weighted_tardiness_min" in after:
            parts.append(
                "Priority-weighted tardiness "
                f"{_scalar(before['weighted_tardiness_min'])} → "
                f"{_scalar(after['weighted_tardiness_min'])}."
            )
        if "on_time_delivery_pct" in before and "on_time_delivery_pct" in after:
            parts.append(
                "On-time delivery "
                f"{_scalar(before['on_time_delivery_pct'])} → "
                f"{_scalar(after['on_time_delivery_pct'])}."
            )
        if "makespan_min" in before and "makespan_min" in after:
            parts.append(
                f"Makespan {_scalar(before['makespan_min'])} → {_scalar(after['makespan_min'])}."
            )
    errors = execution.get("errors") or []
    if errors:
        parts.append("Errors: " + "; ".join(str(item) for item in errors) + ".")
    return " ".join(parts)


def _facts(plant: Plant, execution: dict[str, Any], text: str) -> dict[str, set[str]]:
    kpis = execution.get("kpis") or {}
    before = KpiReport.model_validate(kpis["before"])
    after = KpiReport.model_validate(kpis["after"])
    extra = [json.dumps(execution, default=str), text]
    return fact_table(
        plant=plant, before=before, after=after, outcomes=[], narrative="", extra=extra
    )


def _feedback_from(result: LlmResult) -> str | None:
    try:
        payload = extract_json_object(result.content)
    except (SchemaError, ValueError, json.JSONDecodeError):
        return None
    spoken = payload.get("feedback")
    if isinstance(spoken, str) and spoken.strip():
        return spoken.strip()
    return None


def _labeled(
    text: str,
    *,
    source: str,
    request_id: str,
    degraded: bool,
    reason: str = "",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "feedback": text,
        "source": source,
        "narrative_degraded": degraded,
        "verified": not degraded,
        "meterless_request_id": request_id,
    }
    if reason:
        body["degraded_reason"] = reason
    return body


def _scalar(value: Any) -> str:
    encoded = json.dumps(value)
    if encoded.startswith('"') and encoded.endswith('"'):
        return encoded[1:-1]
    return encoded
