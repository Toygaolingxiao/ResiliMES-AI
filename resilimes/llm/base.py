"""LLM provider types."""

from __future__ import annotations

from pydantic import BaseModel


class LlmResult(BaseModel):
    content: str
    model: str
    provider: str
    lane: str
    latency_ms: float
    mocked: bool
