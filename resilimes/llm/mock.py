# ruff: noqa: RUF001  (full-width punctuation in zh/ja reason text)
"""Offline provider. Same call shape as Nightshift, no network, labeled mock."""

from __future__ import annotations

import json
import re
from typing import Any

from resilimes.llm.base import LlmResult


class MockProvider:
    name = "mock"
    mocked = True

    def model_for(self, lane: str) -> str:
        return "resilimes-mock"

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lane: str,
        temperature: float = 0.0,
    ) -> LlmResult:
        del temperature
        if lane == "ping":
            content = "pong"
        elif lane == "shift_lead":
            content = json.dumps(_shift_lead_pick(messages), ensure_ascii=False)
        elif lane == "shift_lead_plan":
            content = json.dumps(_shift_lead_plans(messages), ensure_ascii=False)
        elif lane == "shift_lead_select":
            content = json.dumps(_shift_lead_select(messages), ensure_ascii=False)
        else:
            narrative = _narrative_from(messages) or (
                "Recovery evaluated by the deterministic planner and critic. "
                "Nightshift is not configured; this text did not come from a model."
            )
            content = json.dumps(
                {
                    "narrative": narrative,
                    "provider": "mock",
                    "lane": lane,
                }
            )
        return LlmResult(
            content=content,
            model=self.model_for(lane),
            provider=self.name,
            lane=lane,
            latency_ms=0.1,
            mocked=True,
        )


def _narrative_from(messages: list[dict[str, str]]) -> str:
    if not messages:
        return ""
    raw = messages[-1].get("content") or ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        text = payload.get("deterministic_narrative")
        if isinstance(text, str):
            return text
    return ""


_MOCK_REASON = {
    "zh": "模拟（非模型）：选择预测影响最低的选项。",
    "ja": "モック（モデルではない）：予測影響が最小の選択肢。",
    "en": "Mock (not a model): option with the lowest projected impact.",
}


def _shift_lead_pick(messages: list[dict[str, str]]) -> dict[str, str]:
    """Deterministic shift-lead answer: lowest (qtime, hot, late, idle) impact.

    Ties keep the option marked ``rule_default``. Labelled as a mock.
    """
    raw = messages[-1].get("content") if messages else ""
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError:
        return {"option_id": "", "reason": "mock: unreadable prompt"}
    options = payload.get("options") if isinstance(payload, dict) else None
    if not isinstance(options, list) or not options:
        return {"option_id": "", "reason": "mock: no options"}

    def key(option: dict[str, object]) -> tuple[float, ...]:
        impact = option.get("impact")
        if not isinstance(impact, dict):
            return (float("inf"),)
        return (
            float(impact.get("qtime_violations", 0)),
            float(impact.get("hot_late", 0)),
            float(impact.get("late_lots", 0)),
            float(impact.get("idle_min", 0)),
            0.0 if option.get("rule_default") else 1.0,
        )

    best = min(options, key=key)
    lang = str((payload.get("answer") or {}).get("lang", "en"))
    return {
        "option_id": str(best.get("id", "")),
        "reason": _MOCK_REASON.get(lang, _MOCK_REASON["en"]),
    }


def _payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    raw = messages[-1].get("content") if messages else ""
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _shift_lead_plans(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Deterministic typed plans for the sim-select plumbing. Not a model."""
    payload = _payload(messages)
    kind = payload.get("kind")
    lots = [row for row in payload.get("lots", []) if isinstance(row, dict)]
    names = [str(row.get("lot")) for row in lots]
    plans: list[dict[str, Any]] = []

    def slack(row: dict[str, Any], key: str) -> float:
        value = row.get(key)
        return float(value) if isinstance(value, (int, float)) else 1e9

    if kind in ("qtime_competition", "hot_insertion") and names:
        by_q = sorted(lots, key=lambda row: slack(row, "qtime_slack_min"))
        by_due = sorted(lots, key=lambda row: slack(row, "due_slack_min"))
        plans.append({"levers": [{"type": "boost", "lots": [r["lot"] for r in by_q[:8]]}]})
        plans.append({"levers": [{"type": "boost", "lots": [r["lot"] for r in by_due[:8]]}]})
    elif kind == "breakdown" and names:
        urgent = [
            str(row["lot"])
            for row in lots
            if row.get("class") != "normal" or row.get("qtime_slack_min") is not None
        ]
        rest = [name for name in names if name not in urgent]
        if urgent and rest:
            plans.append(
                {
                    "levers": [
                        {"type": "reroute", "lots": urgent},
                        {"type": "keep_pin", "lots": rest},
                    ]
                }
            )
        plans.append({"levers": [{"type": "keep_pin", "lots": names}]})
    elif kind == "pm_conflict":
        tool = (payload.get("facts") or {}).get("tool")
        for shift in (180, 360):
            plans.append({"levers": [{"type": "defer_pm", "tool": tool, "shift_min": shift}]})
    elif kind == "batch_underfill":
        found = re.search(r"recipe (\d+)", str(payload.get("situation", "")))
        if found:
            plans.append({"levers": [{"type": "start_batch", "recipe": int(found.group(1))}]})
    for k, plan in enumerate(plans):
        plan["id"] = f"P{k + 1}"
        plan["why"] = "mock (not a model): fixed template"
    return {"plans": plans}


def _shift_lead_select(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Lowest (qviol, hot_late, wt_min) mean, never more hot/VIP late than the
    rule default; cites the table. Not a model."""
    payload = _payload(messages)
    rows = [row for row in payload.get("candidates", []) if isinstance(row, dict)]
    default_id = payload.get("rule_default")
    base = next((row for row in rows if row.get("plan_id") == default_id), None)
    if base is None:
        return {"plan_id": "", "reason": "mock: no default", "cited": {}}
    allowed = [row for row in rows if row["mean"]["hot_late"] <= base["mean"]["hot_late"]]
    best = min(
        allowed,
        key=lambda row: (row["mean"]["qviol"], row["mean"]["hot_late"], row["mean"]["wt_min"]),
    )
    pid, did = best["plan_id"], base["plan_id"]
    return {
        "plan_id": pid,
        "reason": (
            f"mock (not a model): wt_min {best['mean']['wt_min']} vs "
            f"{base['mean']['wt_min']}, qviol {best['mean']['qviol']} vs {base['mean']['qviol']}"
        ),
        "cited": {
            f"{pid}.wt_min": best["mean"]["wt_min"],
            f"{did}.wt_min": base["mean"]["wt_min"],
            f"{pid}.qviol": best["mean"]["qviol"],
        },
    }
