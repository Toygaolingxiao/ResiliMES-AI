#!/usr/bin/env python3
"""
ResiliMES — Open Agent Hackathon 2026 smoke test.

Checks:
  1) Zetaris Web   — GET ZETARIS_BASE_URL
  2) Zetaris REST  — POST SQL SELECT 1 via /sql-editor/sqls/run
  3) Nemotron API  — OpenAI-compatible chat via Meterless Nightshift

Usage:
  cp .env.example .env   # fill secrets
  pip install -r requirements.txt
  python smoke_test.py
"""

from __future__ import annotations

import os
import sys
from typing import Callable

from dotenv import load_dotenv

load_dotenv()


def _ok(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[PASS] {label}{suffix}")


def _fail(label: str, detail: str) -> None:
    print(f"[FAIL] {label} — {detail}")


def check_zetaris_web() -> bool:
    from agent.tools_zetaris import ZetarisError, check_web

    try:
        result = check_web()
        if not result.get("ok"):
            _fail("Zetaris Web", f"HTTP {result.get('status_code')} for {result.get('url')}")
            return False
        _ok("Zetaris Web", f"HTTP {result.get('status_code')} @ {result.get('url')}")
        return True
    except ZetarisError as exc:
        _fail("Zetaris Web", str(exc))
        return False
    except Exception as exc:  # noqa: BLE001 — smoke test surfaces any connector error
        _fail("Zetaris Web", f"{type(exc).__name__}: {exc}")
        return False


def check_zetaris_rest_sql() -> bool:
    from agent.tools_zetaris import ZetarisError, check_rest_sql

    try:
        result = check_rest_sql()
        _ok("Zetaris REST SQL", "SELECT 1 succeeded")
        # Keep payload off stdout secrets; only confirm structure.
        if not isinstance(result.get("result"), dict):
            _fail("Zetaris REST SQL", "Unexpected response shape")
            return False
        return True
    except ZetarisError as exc:
        _fail("Zetaris REST SQL", str(exc))
        return False
    except Exception as exc:  # noqa: BLE001
        _fail("Zetaris REST SQL", f"{type(exc).__name__}: {exc}")
        return False


def check_nemotron() -> bool:
    try:
        from agent.llm import chat_completion, get_model

        model = get_model()
        reply = chat_completion(
            [
                {
                    "role": "system",
                    "content": "Reply with exactly the single word: pong",
                },
                {"role": "user", "content": "ping"},
            ],
            temperature=0.0,
        )
        if not reply:
            _fail("Nemotron API", "Empty response")
            return False
        _ok("Nemotron API", f"model={model} reply={reply[:80]!r}")
        return True
    except Exception as exc:  # noqa: BLE001
        _fail("Nemotron API", f"{type(exc).__name__}: {exc}")
        return False


def main() -> int:
    print("ResiliMES smoke test (Zetaris Web · Zetaris REST SQL · Nemotron)")
    print("-" * 60)

    missing = [
        key
        for key in (
            "ZETARIS_BASE_URL",
            "ZETARIS_REST_URL",
            "ZETARIS_ORG_ID",
            "ZETARIS_API_KEY",
            "METERLESS_BASE_URL",
            "METERLESS_RUNTIME_TOKEN",
            "NEMOTRON_MODEL",
        )
        if not os.getenv(key, "").strip()
    ]
    if missing:
        print("[WARN] Missing env vars (checks may fail): " + ", ".join(missing))
        print("       Copy .env.example → .env and fill in values.")

    checks: list[tuple[str, Callable[[], bool]]] = [
        ("Zetaris Web", check_zetaris_web),
        ("Zetaris REST SQL", check_zetaris_rest_sql),
        ("Nemotron API", check_nemotron),
    ]
    results = []
    for _name, fn in checks:
        results.append(fn())

    print("-" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Result: {passed}/{total} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
