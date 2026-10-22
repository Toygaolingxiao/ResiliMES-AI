"""
Zetaris REST API wrapper for factory table queries.

POST {ZETARIS_REST_URL}{ZETARIS_SQL_PATH}
Headers:
  Authorization: Bearer <ZETARIS_API_KEY>
  X-Org-ID: <ZETARIS_ORG_ID>
  X-Request-ID: <fresh UUID>
  Content-Type: application/json
Body: {"sql": "..."}
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

# Hackathon scaffold path; override with ZETARIS_SQL_PATH if your tenant uses run-query.
DEFAULT_SQL_PATH = "/sql-editor/sqls/run"
DEFAULT_TIMEOUT_S = 30


class ZetarisError(RuntimeError):
    """Raised when a Zetaris REST call fails."""


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ZetarisError(f"Missing required env var: {name}")
    return value


def _rest_base() -> str:
    return _require("ZETARIS_REST_URL").rstrip("/")


def _sql_url() -> str:
    path = os.getenv("ZETARIS_SQL_PATH", DEFAULT_SQL_PATH).strip() or DEFAULT_SQL_PATH
    if not path.startswith("/"):
        path = "/" + path
    return _rest_base() + path


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_require('ZETARIS_API_KEY')}",
        "X-Org-ID": _require("ZETARIS_ORG_ID"),
        "X-Request-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }


def run_sql(sql: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """
    Execute one Lightning SQL statement via Zetaris REST.

    Returns the parsed JSON body. Typical shape includes `headers` and `data`.
    """
    statement = (sql or "").strip()
    if not statement:
        raise ZetarisError("SQL statement is empty")

    response = requests.post(
        _sql_url(),
        headers=_headers(),
        json={"sql": statement},
        timeout=timeout_s,
    )
    if response.status_code >= 400:
        raise ZetarisError(
            f"Zetaris SQL failed ({response.status_code}): {response.text[:500]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ZetarisError(f"Zetaris returned non-JSON body: {response.text[:300]}") from exc


def rows_as_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a Zetaris SQL result (`headers` + `data`) into a list of dicts."""
    headers = result.get("headers") or result.get("columns") or []
    data = result.get("data") or result.get("rows") or []
    if not headers:
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, dict):
            out.append(row)
        else:
            out.append({str(h): v for h, v in zip(headers, row)})
    return out


def query_factory_table(table: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Convenience SELECT * FROM <table> with an optional LIMIT."""
    lim = limit if limit is not None else int(os.getenv("ZETARIS_QUERY_LIMIT", "1000"))
    sql = f"SELECT * FROM {table} LIMIT {int(lim)}"
    return rows_as_dicts(run_sql(sql))


def check_web(timeout_s: float = 10.0) -> dict[str, Any]:
    """Hit the Zetaris web UI origin (ZETARIS_BASE_URL) for liveness."""
    base = os.getenv("ZETARIS_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise ZetarisError("Missing required env var: ZETARIS_BASE_URL")
    response = requests.get(base, timeout=timeout_s, allow_redirects=True)
    return {
        "ok": response.status_code < 500,
        "status_code": response.status_code,
        "url": base,
    }


def check_rest_sql(timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Run SELECT 1 against the REST SQL endpoint."""
    result = run_sql("SELECT 1", timeout_s=timeout_s)
    return {"ok": True, "result": result}
