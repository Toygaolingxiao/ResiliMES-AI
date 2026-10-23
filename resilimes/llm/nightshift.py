"""Meterless Nightshift client. OpenAI-compatible, NVIDIA Nemotron behind it.

Nightshift explains. The critic is deterministic code and does not call a model.
Every lane uses NEMOTRON_MODEL.

Retries: 429 and connection / 5xx, with exponential backoff. The token is never logged.
"""

from __future__ import annotations

import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from resilimes.config import Settings
from resilimes.llm.base import LlmResult
from resilimes.llm.urls import assert_runtime_token, normalize_base_url
from resilimes.logging_config import get_logger

logger = get_logger("resilimes.llm")

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE = "</think>"


def strip_reasoning(text: str) -> str:
    """Drop reasoning spans. A leaked prefix ends at </think>."""
    cleaned = _THINK_BLOCK.sub("", text)
    close = cleaned.lower().rfind(_THINK_CLOSE)
    if close >= 0:
        cleaned = cleaned[close + len(_THINK_CLOSE) :]
    return cleaned.strip()


def _token_budget(settings: Settings) -> int:
    raw = settings.nemotron_max_tokens
    return raw if raw > 0 else 4096


def build_openai_client(
    *,
    base_url: str,
    token: str,
    timeout_s: float,
    app_id: str,
) -> OpenAI:
    runtime_token = assert_runtime_token(token)
    return OpenAI(
        base_url=normalize_base_url(base_url),
        api_key=runtime_token,
        timeout=timeout_s,
        default_headers={
            "meterless-app": app_id,
            "meterless-scope": "user",
        },
    )


class NightshiftProvider:
    name = "nightshift"
    mocked = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = build_openai_client(
            base_url=settings.meterless_base_url,
            token=settings.meterless_runtime_token,
            timeout_s=settings.meterless_timeout_s,
            app_id=settings.meterless_app_id,
        )

    def model_for(self, lane: str) -> str:
        del lane
        return self._settings.nemotron_model

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lane: str,
        temperature: float = 0.2,
    ) -> LlmResult:
        model = self.model_for(lane)
        budget = _token_budget(self._settings)
        started = time.perf_counter()
        response: Any = None
        content = ""
        for index, max_tokens in enumerate((budget, budget * 2)):
            response = self._create(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                lane=lane,
            )
            content = strip_reasoning(_message_text(response))
            if content or index == 1:
                break
        elapsed = (time.perf_counter() - started) * 1000
        logger.info(
            "nightshift completion",
            extra={
                "fields": {
                    "lane": lane,
                    "model": model,
                    "latency_ms": round(elapsed, 1),
                    "empty": content == "",
                }
            },
        )
        return LlmResult(
            content=content,
            model=model,
            provider=self.name,
            lane=lane,
            latency_ms=elapsed,
            mocked=False,
        )

    def _create(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        lane: str,
    ) -> Any:
        delay = 0.5
        attempts = max(1, self._settings.llm_max_retries)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except (RateLimitError, APIConnectionError, APIStatusError) as exc:
                if isinstance(exc, APIStatusError) and exc.status_code not in {429, 500, 502, 503}:
                    raise
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                time.sleep(delay)
                delay *= 2
        raise RuntimeError(f"Nightshift {lane} failed after {attempts} attempts") from last_error


def probe_nightshift(settings: Settings, timeout_s: float = 3.0) -> dict[str, Any]:
    """Short liveness probe. Does not print the token."""
    import requests

    base = normalize_base_url(settings.meterless_base_url)
    origin = base[: -len("/v1")] if base.endswith("/v1") else base
    try:
        health = requests.get(origin + "/healthz", timeout=timeout_s)
    except requests.RequestException as exc:
        return {"ok": False, "detail": type(exc).__name__}
    models_status = None
    if settings.token_configured:
        try:
            listed = requests.get(
                base + "/models",
                headers={"Authorization": f"Bearer {settings.meterless_runtime_token}"},
                timeout=timeout_s,
            )
            models_status = listed.status_code
        except requests.RequestException:
            models_status = None
    return {
        "ok": health.status_code < 500,
        "health_status": health.status_code,
        "models_status": models_status,
        "base_url": base,
    }


def _message_text(response: Any) -> str:
    choice = response.choices[0].message
    content = choice.content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)
