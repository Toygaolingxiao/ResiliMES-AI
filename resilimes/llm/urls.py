"""Normalize Nightshift base URLs. Shared with the scaffold client."""

from __future__ import annotations

DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
PLACEHOLDER_TOKEN = "rt-local"


def normalize_base_url(raw: str | None) -> str:
    """Normalize a pasted URL to <origin>/v1. Never produce /v1/v1."""
    url = (raw or DEFAULT_BASE_URL).strip().rstrip("/")
    for suffix in ("/v1/chat/completions", "/v1/models", "/healthz", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/") + "/v1"


def assert_runtime_token(token: str | None) -> str:
    value = (token or "").strip()
    if not value:
        raise RuntimeError(
            "METERLESS_RUNTIME_TOKEN is not set. Copy .env.example to .env and "
            "paste the Nightshift runtime token from <stateDir>/proxy-token."
        )
    if value == PLACEHOLDER_TOKEN:
        raise RuntimeError(
            "METERLESS_RUNTIME_TOKEN is the placeholder rt-local. Nightshift rejects it. "
            "Paste the runtime token from <stateDir>/proxy-token."
        )
    return value
