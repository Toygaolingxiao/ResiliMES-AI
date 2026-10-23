"""
Evaluator / Critic Agent — validate Planner proposals against physical constraints.

Checks due dates, tool setup time, operator capacity, capability, and equipment status.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .llm import chat_completion

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts" / "evaluator_system.md"
SAMPLE_DIR = ROOT / "data" / "sample"

DEFAULT_OPERATOR_POOL = 4


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_json(name: str) -> dict[str, Any]:
    path = SAMPLE_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def deterministic_checks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Fast, local constraint checks used alongside (or without) the LLM critic.

    Returns a list of violation dicts; empty means no hard failures found locally.
    """
    equipment = {e["equipment_id"]: e for e in _load_json("equipment.json").get("equipment", [])}
    jobs = {j["job_id"]: j for j in _load_json("wip_jobs.json").get("jobs", [])}
    violations: list[dict[str, Any]] = []

    strategy = plan.get("strategy") or {}
    actions = strategy.get("actions") or []
    assigned_load: dict[str, int] = {}
    operator_load = 0

    for action in actions:
        if action.get("type") != "reassign":
            continue
        to_eq = action.get("to_equipment")
        job_id = action.get("job_id")
        job = jobs.get(job_id or "", {})
        eq = equipment.get(to_eq or "")

        if to_eq and to_eq not in equipment:
            violations.append(
                {
                    "constraint": "other",
                    "severity": "high",
                    "detail": f"Unknown destination equipment {to_eq}",
                    "fix_hint": "Pick an equipment_id from the plant equipment list.",
                }
            )
            continue

        if eq:
            status = eq.get("status")
            if status in {"DOWN", "MAINTENANCE"}:
                violations.append(
                    {
                        "constraint": "equipment_status",
                        "severity": "high",
                        "detail": f"{to_eq} is {status}; cannot accept new work.",
                        "fix_hint": "Choose an IDLE/RUNNING alternate with matching capability.",
                    }
                )
            assigned_load[to_eq] = assigned_load.get(to_eq, 0) + 1
            if assigned_load[to_eq] > int(eq.get("max_wip", 1)):
                violations.append(
                    {
                        "constraint": "max_wip",
                        "severity": "high",
                        "detail": f"{to_eq} exceeds max_wip={eq.get('max_wip')}.",
                        "fix_hint": "Spread lots across alternate tools or delay lower priority WIP.",
                    }
                )
            operator_load += int(eq.get("operators_required", 1))

        due = _parse_dt(job.get("due_at"))
        if due and due < datetime.now(UTC) and job.get("priority", 99) <= 2:
            violations.append(
                {
                    "constraint": "due_date",
                    "severity": "medium",
                    "detail": f"{job_id} is already past due ({job.get('due_at')}).",
                    "fix_hint": "Expedite or escalate; document due-date risk in the plan.",
                }
            )

    if operator_load > DEFAULT_OPERATOR_POOL:
        violations.append(
            {
                "constraint": "operator_capacity",
                "severity": "high",
                "detail": f"Operator demand {operator_load} exceeds pool {DEFAULT_OPERATOR_POOL}.",
                "fix_hint": "Stagger concurrent starts or free operators from lower-priority tools.",
            }
        )

    return violations


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def evaluate_plan(
    plan: dict[str, Any],
    *,
    use_llm: bool = True,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Validate a Planner proposal.

    Always runs deterministic checks. When use_llm=True, also asks the Critic
    Agent (Nemotron) and merges violations.
    """
    local_violations = deterministic_checks(plan)
    result: dict[str, Any] = {
        "verdict": "reject" if local_violations else "accept",
        "score": 0.4 if local_violations else 0.85,
        "violations": local_violations,
        "accepted_actions": [],
        "rejected_actions": [],
        "metrics": {
            "lots_at_risk": len({v.get("detail", "") for v in local_violations}),
            "estimated_makespan_delta_min": 0,
            "setup_changes": 0,
        },
        "rationale": "Deterministic constraint pass."
        if not local_violations
        else "Deterministic constraints failed.",
        "confidence": 0.9 if not use_llm else 0.6,
        "source": "deterministic",
    }

    if not use_llm:
        return result

    payload = {
        "plan": plan,
        "local_violations": local_violations,
        "factory_context": {
            "equipment": _load_json("equipment.json"),
            "wip_jobs": _load_json("wip_jobs.json"),
            "bom": _load_json("bom.json"),
            "operator_pool": DEFAULT_OPERATOR_POOL,
        },
        "extra_context": extra_context or {},
        "instruction": "Validate the plan against physical constraints; return strict JSON.",
    }
    messages = [
        {"role": "system", "content": _load_prompt()},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]
    raw = chat_completion(messages, temperature=0.0)
    try:
        llm_result = _extract_json(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Evaluator returned non-JSON output: {raw[:500]}") from exc

    # Merge: keep all local hard violations, append unique LLM ones.
    merged = list(local_violations)
    seen = {(v.get("constraint"), v.get("detail")) for v in merged}
    for v in llm_result.get("violations") or []:
        key = (v.get("constraint"), v.get("detail"))
        if key not in seen:
            merged.append(v)
            seen.add(key)

    llm_result["violations"] = merged
    if merged and llm_result.get("verdict") == "accept":
        llm_result["verdict"] = "conditional"
    llm_result["source"] = "llm+deterministic"
    llm_result.setdefault("confidence", 0.7)
    return llm_result


if __name__ == "__main__":
    demo_plan = {
        "incident_id": "INC-DEMO",
        "strategy": {
            "name": "reassign-litho",
            "actions": [
                {
                    "type": "reassign",
                    "job_id": "LOT-1001",
                    "from_equipment": "LITHO-02",
                    "to_equipment": "LITHO-01",
                    "reason": "LITHO-02 down",
                }
            ],
        },
    }
    print(json.dumps(evaluate_plan(demo_plan, use_llm=False), indent=2))
