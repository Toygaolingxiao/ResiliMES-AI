"""Meterless Nightshift client. OpenAI-compatible, NVIDIA Nemotron behind it.

Nemotron turns a sentence into a tool call and writes feedback from the engine
result. The scheduler and the critic do not call a model. Every lane uses
NEMOTRON_MODEL.

Retries: 429 and connection / 5xx, with exponential backoff. The token is never logged.

Time budgets (resilimes.llm.deadline) apply to calls made inside an AI task deadline (the
investigator, explainer and handover): one ``complete`` call is capped at AI_CALL_DEADLINE_S
and by the task deadline, whichever is sooner; each request carries ``meterless-ttfb-ms`` so
Nightshift stops a stuck lane server-side; a larger empty-reply budget rung is not started
with less than 30 s left. Calls outside a task deadline (the sim-select / shift-lead studies,
which set their own long budgets) keep the plain METERLESS_TIMEOUT_S client timeout.
"""

from __future__ import annotations

import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from resilimes.config import Settings
from resilimes.llm import deadline
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


_MAX_BUDGET = 16384


def _budget_ladder(budget: int) -> tuple[int, ...]:
    """Budgets to try when the reply comes back empty: x1, x2, x4, capped at 16k."""
    ladder: list[int] = []
    for factor in (1, 2, 4):
        value = min(budget * factor, max(budget, _MAX_BUDGET))
        if value not in ladder:
            ladder.append(value)
    return tuple(ladder)


def _is_empty_response(exc: Exception) -> bool:
    """Nightshift returns 502 *_empty_response when reasoning used the whole budget."""
    return isinstance(exc, APIStatusError) and "empty_response" in str(exc)


def ttfb_ms(timeout_s: float, ttfb_s: float) -> int:
    """First-token limit for Nightshift: min(request timeout, ttfb_s), at most 300000 ms."""
    return max(1000, min(deadline.TTFB_MAX_MS, int(min(timeout_s, ttfb_s) * 1000)))


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
        call_end = self._call_end()
        response: Any = None
        content = ""
        budgets = _budget_ladder(budget)
        for index, max_tokens in enumerate(budgets):
            left = self._left(call_end)
            if index and left is not None and left < deadline.RUNG_MIN_S:
                logger.info(
                    "nightshift empty reply, no time for a larger budget",
                    extra={"fields": {"lane": lane, "max_tokens": max_tokens}},
                )
                break
            response = self._create(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                lane=lane,
                call_end=call_end,
            )
            content = strip_reasoning(_message_text(response)) if response is not None else ""
            if content or index == len(budgets) - 1:
                break
            logger.info(
                "nightshift empty reply, raising budget",
                extra={"fields": {"lane": lane, "max_tokens": max_tokens}},
            )
        elapsed = (time.perf_counter() - started) * 1000
        completion_id, meterless_request_id, provider_model = _response_ids(response)
        logger.info(
            "nightshift completion",
            extra={
                "fields": {
                    "lane": lane,
                    "model": model,
                    "latency_ms": round(elapsed, 1),
                    "empty": content == "",
                    "completion_id": completion_id,
                    "meterless_request_id": meterless_request_id,
                    "provider_model": provider_model,
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
            completion_id=completion_id,
            meterless_request_id=meterless_request_id,
            provider_model=provider_model,
            response_model=str(getattr(response, "model", "") or ""),
        )

    def _call_end(self) -> float | None:
        """End of this call's budget, or None outside an AI task deadline (no extra limits)."""
        if deadline.remaining() is None:
            return None
        cap = self._settings.ai_call_deadline_s
        cap = cap if cap > 0 else self._settings.meterless_timeout_s
        return deadline.now() + cap

    def _left(self, call_end: float | None) -> float | None:
        """Seconds left for this call: the per-call cap or the task deadline, whichever is sooner."""
        task = deadline.remaining()
        if call_end is None:
            return task
        left = call_end - deadline.now()
        return left if task is None else min(left, task)

    def _create(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        lane: str,
        call_end: float | None = None,
    ) -> Any | None:
        delay = 0.5
        attempts = max(1, self._settings.llm_max_retries)
        last_error: Exception | None = None
        for attempt in range(attempts):
            left = self._left(call_end)
            budget: dict[str, Any] = {}
            if left is not None:
                if left <= 0:
                    raise deadline.DeadlineExceeded(
                        f"Nightshift {lane}: time budget used before the request"
                    )
                timeout = min(left, self._settings.meterless_timeout_s)
                budget = {
                    "timeout": timeout,
                    "extra_headers": {
                        "meterless-ttfb-ms": str(ttfb_ms(timeout, self._settings.ai_ttfb_s))
                    },
                }
            try:
                return self._client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **budget,
                )
            except (RateLimitError, APIConnectionError, APIStatusError) as exc:
                if isinstance(exc, APITimeoutError) and left is not None:
                    raise deadline.DeadlineExceeded(
                        f"Nightshift {lane}: no reply within {budget['timeout']:.0f} s"
                    ) from exc
                if _is_empty_response(exc):
                    # Nemotron spent the whole budget reasoning. Retrying at the
                    # same budget only fails again; the caller raises the budget.
                    return None
                if isinstance(exc, APIStatusError) and exc.status_code not in {429, 500, 502, 503}:
                    raise
                last_error = exc
                left = self._left(call_end)
                if attempt + 1 >= attempts or (left is not None and left <= delay):
                    break
                time.sleep(delay)
                delay *= 2
        detail = f"{type(last_error).__name__}: {str(last_error)[:200]}" if last_error else ""
        raise RuntimeError(
            f"Nightshift {lane} failed after {attempts} attempts ({detail})"
        ) from last_error


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


def call_summary(result: LlmResult) -> str:
    """One line for the explain step: provider, model, latency, and request ids."""
    parts = [result.provider, result.model, f"{int(result.latency_ms)} ms"]
    if result.completion_id:
        parts.append(result.completion_id)
    if result.meterless_request_id:
        parts.append(result.meterless_request_id)
    if result.provider_model:
        parts.append(result.provider_model)
    return " · ".join(parts)


def _response_ids(response: Any) -> tuple[str, str, str]:
    if response is None:
        return "", "", ""
    completion_id = str(getattr(response, "id", "") or "")
    meterless = getattr(response, "meterless", None)
    dumped: dict[str, Any] = {}
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        raw = dump()
        if isinstance(raw, dict):
            dumped = raw
    if not completion_id:
        completion_id = str(dumped.get("id") or "")
    if meterless is None:
        meterless = dumped.get("meterless")
    extra = getattr(response, "model_extra", None)
    if meterless is None and isinstance(extra, dict):
        meterless = extra.get("meterless")
    request_id = ""
    provider_model = str(dumped.get("provider_model") or "")
    if isinstance(meterless, dict):
        request_id = str(meterless.get("request_id") or "")
        provider_model = str(meterless.get("provider_model") or provider_model)
    return completion_id, request_id, provider_model


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
