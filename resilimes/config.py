"""Environment-backed settings.

`RESILIMES_MODE=auto` (the default) uses Nightshift and Zetaris when their
credentials are present and the offline twins otherwise. `make demo` forces
`mock` so a fresh machine never needs credentials.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from resilimes.data.sql_catalog import validate_schema
from resilimes.data.zetaris_layout import parse_table_sources

ROOT = Path(__file__).resolve().parents[1]
HORIZON = datetime(2026, 10, 22, 6, 30, tzinfo=UTC)

# Dev HMAC key for local contract integrity. Not a cloud credential.
# Override with SCOUT_SIGNING_SECRET in any shared deployment.
DEV_SCOUT_SECRET = "resilimes-dev-signing-key"

PLACEHOLDER_TOKEN = "rt-local"


class ConfigError(RuntimeError):
    """Raised when live mode is selected without the required credentials."""


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


class Settings(BaseModel):
    mode: str = "auto"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    horizon: datetime = HORIZON
    data_dir: Path = Field(default_factory=lambda: ROOT / "data" / "sample")
    scout_signing_secret: str = DEV_SCOUT_SECRET
    scout_ttl_seconds: int = 300
    zetaris_base_url: str = ""
    zetaris_rest_url: str = ""
    zetaris_org_id: str = ""
    zetaris_api_key: str = ""
    zetaris_sql_path: str = "/sql-editor/sqls/run-query"
    zetaris_schema: str = "resilimes"
    zetaris_query_limit: int = 1000
    zetaris_timeout_s: float = 30.0
    # Override only. Empty means sql_catalog defaults (fab_cmms / fab_erp).
    zetaris_table_sources: dict[str, str] = Field(default_factory=dict)
    redis_url: str = ""
    meterless_base_url: str = "http://127.0.0.1:8088/v1"
    meterless_runtime_token: str = ""
    meterless_app_id: str = "resilimes"
    meterless_timeout_s: float = 180.0
    nemotron_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    nemotron_max_tokens: int = 4096
    llm_max_retries: int = 3

    @property
    def token_configured(self) -> bool:
        token = self.meterless_runtime_token
        return bool(token) and token != PLACEHOLDER_TOKEN

    @property
    def zetaris_configured(self) -> bool:
        return bool(self.zetaris_api_key and self.zetaris_rest_url and self.zetaris_org_id)

    @property
    def use_nightshift(self) -> bool:
        if self.mode == "mock":
            return False
        if self.mode == "live":
            if not self.token_configured:
                raise ConfigError(
                    "RESILIMES_MODE=live requires METERLESS_RUNTIME_TOKEN "
                    "(the Nightshift proxy token, not the rt-local placeholder) "
                    "and NEMOTRON_MODEL."
                )
            return True
        return self.token_configured

    @property
    def use_zetaris(self) -> bool:
        if self.mode == "mock":
            return False
        if self.mode == "live":
            if not self.zetaris_configured:
                raise ConfigError(
                    "RESILIMES_MODE=live requires ZETARIS_REST_URL, "
                    "ZETARIS_ORG_ID, and ZETARIS_API_KEY."
                )
            return True
        return self.zetaris_configured


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    mode = _env("RESILIMES_MODE", "auto").lower() or "auto"
    if mode not in {"auto", "mock", "live"}:
        raise ConfigError("RESILIMES_MODE must be auto, mock, or live")
    horizon_raw = _env("RESILIMES_HORIZON")
    horizon = HORIZON
    if horizon_raw:
        horizon = datetime.fromisoformat(horizon_raw.replace("Z", "+00:00"))
    data_dir = Path(_env("RESILIMES_DATA_DIR", str(ROOT / "data" / "sample")))
    try:
        table_sources = parse_table_sources(_env("ZETARIS_TABLE_SOURCES"))
        for source in table_sources.values():
            validate_schema(source)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    timeout_raw = _env("ZETARIS_TIMEOUT_S", "30") or "30"
    return Settings(
        mode=mode,
        host=_env("RESILIMES_HOST", "0.0.0.0"),
        port=int(_env("RESILIMES_PORT", "8000") or "8000"),
        log_level=_env("RESILIMES_LOG_LEVEL", "INFO"),
        horizon=horizon,
        data_dir=data_dir,
        scout_signing_secret=_env("SCOUT_SIGNING_SECRET", DEV_SCOUT_SECRET) or DEV_SCOUT_SECRET,
        scout_ttl_seconds=int(_env("SCOUT_TTL_SECONDS", "300") or "300"),
        zetaris_base_url=_env("ZETARIS_BASE_URL"),
        zetaris_rest_url=_env("ZETARIS_REST_URL"),
        zetaris_org_id=_env("ZETARIS_ORG_ID"),
        zetaris_api_key=_env("ZETARIS_API_KEY"),
        zetaris_sql_path=_env("ZETARIS_SQL_PATH", "/sql-editor/sqls/run-query")
        or "/sql-editor/sqls/run-query",
        zetaris_schema=_env("ZETARIS_SCHEMA", "resilimes") or "resilimes",
        zetaris_query_limit=int(_env("ZETARIS_QUERY_LIMIT", "1000") or "1000"),
        zetaris_timeout_s=float(timeout_raw),
        zetaris_table_sources=table_sources,
        redis_url=_env("REDIS_URL"),
        meterless_base_url=_env("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1"),
        meterless_runtime_token=_env("METERLESS_RUNTIME_TOKEN"),
        meterless_app_id=_env("METERLESS_APP_ID", "resilimes") or "resilimes",
        meterless_timeout_s=float(_env("METERLESS_TIMEOUT_S", "180") or "180"),
        nemotron_model=_env("NEMOTRON_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"),
        nemotron_max_tokens=int(_env("NEMOTRON_MAX_TOKENS", "4096") or "4096"),
        llm_max_retries=int(_env("LLM_MAX_RETRIES", "3") or "3"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
