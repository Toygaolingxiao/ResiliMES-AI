"""LLM provider types."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class Completer(Protocol):
    """Nightshift or the offline mock. Both expose the same completion call."""

    name: str
    mocked: bool

    def model_for(self, lane: str) -> str: ...

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lane: str,
        temperature: float = 0.2,
    ) -> LlmResult: ...


class LlmResult(BaseModel):
    content: str
    model: str
    provider: str
    lane: str
    latency_ms: float
    mocked: bool
    completion_id: str = ""
    meterless_request_id: str = ""
    provider_model: str = ""
