"""
Planner Agent — parse factory incidents and propose rescheduling strategies.

Uses Nemotron via agent.llm and returns structured JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .llm import chat_completion

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts" / "planner_system.md"
SAMPLE_DIR = ROOT / "data" / "sample"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_sample_context() -> dict[str, Any]:
    """Load lightweight local samples so planning works offline from Zetaris."""
    context: dict[str, Any] = {}
    for name in ("equipment.json", "wip_jobs.json", "bom.json"):
        path = SAMPLE_DIR / name
        if path.exists():
            context[name] = json.loads(path.read_text(encoding="utf-8"))
    maint = SAMPLE_DIR / "maintenance_logs.csv"
    if maint.exists():
        context["maintenance_logs.csv"] = maint.read_text(encoding="utf-8")[:4000]
    return context


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating optional fences."""
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


def plan_incident(
    incident: str,
    *,
    extra_context: dict[str, Any] | None = None,
    use_samples: bool = True,
) -> dict[str, Any]:
    """
    Parse an incident log (e.g. "Machine Litho-02 Down") and propose a plan.

    Returns a structured dict matching prompts/planner_system.md.
    """
    context: dict[str, Any] = {}
    if use_samples:
        context.update(_load_sample_context())
    if extra_context:
        context.update(extra_context)

    user_payload = {
        "incident": incident,
        "factory_context": context,
        "instruction": "Propose a constraint-aware rescheduling strategy as strict JSON.",
    }
    messages = [
        {"role": "system", "content": _load_prompt()},
        {"role": "user", "content": json.dumps(user_payload, indent=2)},
    ]
    raw = chat_completion(messages, temperature=0.1)
    try:
        plan = _extract_json(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Planner returned non-JSON output: {raw[:500]}") from exc

    # Ensure minimal schema keys exist for downstream agents.
    plan.setdefault("incident_id", "INC-LOCAL")
    plan.setdefault("affected_jobs", [])
    plan.setdefault("strategy", {"name": "unspecified", "actions": []})
    plan.setdefault("fallbacks", [])
    plan.setdefault("open_questions", [])
    plan.setdefault("confidence", 0.0)
    return plan


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "Machine Litho-02 Down"
    result = plan_incident(text)
    print(json.dumps(result, indent=2))
