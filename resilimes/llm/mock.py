# ruff: noqa: RUF001  (full-width punctuation in zh/ja reason text)
"""Offline provider. Same call shape as Nightshift, no network, labeled mock."""

from __future__ import annotations

import json

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
