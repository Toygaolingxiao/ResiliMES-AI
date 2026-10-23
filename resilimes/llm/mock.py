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
