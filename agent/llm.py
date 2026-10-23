"""
Meterless Nightshift / NVIDIA Nemotron connector.

Uses the standard OpenAI-compatible SDK against:
  METERLESS_BASE_URL + chat/completions
Auth: Bearer METERLESS_RUNTIME_TOKEN
Model: NEMOTRON_MODEL

URL normalization and the rt-local rejection live in resilimes.llm so the
scaffold smoke test and the product share one client contract.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from resilimes.llm.nightshift import build_openai_client
from resilimes.llm.urls import normalize_base_url

load_dotenv()

DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEFAULT_APP_ID = "resilimes"
DEFAULT_TIMEOUT_S = 180.0


def _normalize_base_url(raw: str) -> str:
    """Normalize pasted URLs to <host>/v1 (never /v1/v1)."""
    return normalize_base_url(raw)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    """Build a cached OpenAI client pointed at Meterless Nightshift."""
    timeout = float(_env("METERLESS_TIMEOUT_S", str(DEFAULT_TIMEOUT_S)) or DEFAULT_TIMEOUT_S)
    return build_openai_client(
        base_url=_env("METERLESS_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
        token=_env("METERLESS_RUNTIME_TOKEN") or "",
        timeout_s=timeout,
        app_id=_env("METERLESS_APP_ID", DEFAULT_APP_ID) or DEFAULT_APP_ID,
    )


def get_model() -> str:
    return _env("NEMOTRON_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    response_format: dict[str, Any] | None = None,
) -> str:
    """
    Send a chat completion request and return the assistant text.

    Returns plain text content. Callers that need JSON should parse it.
    """
    client = get_openai_client()
    kwargs: dict[str, Any] = {
        "model": model or get_model(),
        "messages": messages,
        "temperature": temperature,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0].message
    content = choice.content
    if content is None:
        raise RuntimeError("Nemotron returned empty content")
    if isinstance(content, list):
        # Some OpenAI-compatible servers return multimodal content parts.
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts).strip()
    return str(content).strip()
