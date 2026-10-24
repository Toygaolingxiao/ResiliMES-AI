"""About 5-minute probe of the local Meterless Nightshift endpoint (Nemotron).

    python scripts/probe_nightshift.py [--out probe_nightshift.json] [--repeats 3]

Reads ``.env`` like the app (``METERLESS_BASE_URL``, default
http://127.0.0.1:8088/v1, ``METERLESS_RUNTIME_TOKEN``, ``NEMOTRON_MODEL``).
Checks, each with its own timeout:

1. ``/healthz`` and ``/v1/models``.
2. Reasoning on vs off: the same short question with ``/think`` and
   ``/no_think`` system flags, and with ``chat_template_kwargs.enable_thinking``
   (whichever the server honours); reports whether reasoning text came back
   (``reasoning_content`` or a ``<think>`` block) and the latency.
3. OpenAI ``tools`` passthrough: one function tool with ``tool_choice=auto``
   and with a forced tool; reports whether ``tool_calls`` came back with JSON
   arguments that name the tool.
4. The two sim-select lanes (plan, select) on a small fixed situation: valid
   JSON, latency, finish_reason (``length`` means the token budget truncated).

The token is never printed: only "set (N chars)". Error texts are redacted.
Exit code 0 if the endpoint answered at all, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resilimes.agents.jsonutil import extract_json_object
from resilimes.agents.sim_select import PLAN_SYSTEM, SELECT_SYSTEM
from resilimes.config import load_settings
from resilimes.llm.nightshift import (
    _response_ids,
    build_openai_client,
    probe_nightshift,
    strip_reasoning,
)
from resilimes.llm.urls import normalize_base_url
from resilimes.smt.progress import redact

QUESTION = "A furnace batch holds 6 lots and 4 are waiting. Fill rate? Reply with one number."
TOOL = {
    "type": "function",
    "function": {
        "name": "get_lot_status",
        "description": "Status of one lot in the fab.",
        "parameters": {
            "type": "object",
            "properties": {"lot_id": {"type": "string"}},
            "required": ["lot_id"],
        },
    },
}
PLAN_INPUT = {
    "kind": "breakdown",
    "family": "Diffusion_FE_120",
    "situation": "Diffusion_FE_120_2 down for 3.5 h; 4 lots pinned",
    "lots": [
        {"lot": "L1", "class": "hot", "qtime_slack_h": 0.8, "due_slack_h": 2.0},
        {"lot": "L2", "class": "normal", "qtime_slack_h": None, "due_slack_h": 30.0},
    ],
    "tools": [
        {"tool": "Diffusion_FE_120_2", "down_until_h": 3.5},
        {"tool": "Diffusion_FE_120_3", "down_until_h": None, "next_pm_h": 9.0},
    ],
}
SELECT_INPUT = {
    "default": "A",
    "table": [
        {"plan_id": "A", "mean": {"wt_min": 120.4, "qviol": 2.0, "hot_late": 1.0}},
        {"plan_id": "P1", "mean": {"wt_min": 98.1, "qviol": 1.0, "hot_late": 1.0}},
    ],
}


def _reasoning(message: Any) -> bool:
    extra = getattr(message, "model_extra", None) or {}
    text = message.content or ""
    return bool(
        getattr(message, "reasoning_content", None)
        or extra.get("reasoning_content")
        or extra.get("reasoning")
        or "<think" in text.lower()
    )


def _call(client: Any, model: str, timeout: float, **kw: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.with_options(timeout=timeout).chat.completions.create(model=model, **kw)
    except Exception as error:  # reported, never raised
        return {
            "ok": False,
            "error": redact(f"{type(error).__name__}: {error}"),
            "ms": round((time.perf_counter() - started) * 1000),
        }
    choice = response.choices[0]
    usage = getattr(response, "usage", None)
    _cid, _rid, provider_model = _response_ids(response)
    served = provider_model or str(getattr(response, "model", "") or "")
    return {
        "ok": True,
        "response_model": str(getattr(response, "model", "") or ""),
        "provider_model": provider_model,
        "non_nemotron": "nemotron" not in served.lower(),
        "ms": round((time.perf_counter() - started) * 1000),
        "finish_reason": choice.finish_reason,
        "reasoning_returned": _reasoning(choice.message),
        "content": redact(choice.message.content or "", limit=20000),
        "tool_calls": [
            {"name": c.function.name, "arguments": c.function.arguments}
            for c in (choice.message.tool_calls or [])
        ],
        "completion_tokens": getattr(usage, "completion_tokens", None),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", default="probe_nightshift.json")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--timeout", type=float, default=60.0, help="per call, s")
    p.add_argument("--max-tokens", type=int, default=8192)
    args = p.parse_args(argv)
    settings = load_settings()
    if not settings.meterless_runtime_token:
        print("METERLESS_RUNTIME_TOKEN is not set (.env); liveness only:")
        print(json.dumps(probe_nightshift(settings, timeout_s=10.0), indent=1))
        return 1
    client = build_openai_client(
        base_url=settings.meterless_base_url,
        token=settings.meterless_runtime_token,
        timeout_s=args.timeout,
        app_id=settings.meterless_app_id,
    )
    model = settings.nemotron_model
    token = settings.meterless_runtime_token or ""
    report: dict[str, Any] = {
        "base_url": normalize_base_url(settings.meterless_base_url),
        "model": model,
        "token": f"set ({len(token)} chars)" if token else "NOT SET",
        "liveness": probe_nightshift(settings, timeout_s=10.0),
    }
    print(json.dumps(report, indent=1), flush=True)
    mt = args.max_tokens
    question = [{"role": "user", "content": QUESTION}]
    variants: dict[str, dict[str, Any]] = {
        "reasoning_on_flag": {"messages": [{"role": "system", "content": "/think"}, *question]},
        "reasoning_off_flag": {"messages": [{"role": "system", "content": "/no_think"}, *question]},
        "reasoning_on_kwargs": {
            "messages": question,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
        },
        "reasoning_off_kwargs": {
            "messages": question,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
        "tools_auto": {
            "messages": [
                {"role": "user", "content": "What is the status of lot L17? Use the tool."}
            ],
            "tools": [TOOL],
            "tool_choice": "auto",
        },
        "tools_forced": {
            "messages": [{"role": "user", "content": "Look up lot L17."}],
            "tools": [TOOL],
            "tool_choice": {"type": "function", "function": {"name": "get_lot_status"}},
        },
        "lane_plan": {
            "messages": [
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": json.dumps(PLAN_INPUT)},
            ]
        },
        "lane_select": {
            "messages": [
                {"role": "system", "content": SELECT_SYSTEM},
                {"role": "user", "content": json.dumps(SELECT_INPUT)},
            ]
        },
    }
    checks: dict[str, list[dict[str, Any]]] = {}
    deadline = time.monotonic() + 300.0
    for name, kw in variants.items():
        for _ in range(args.repeats):
            if time.monotonic() > deadline:
                break
            row = _call(client, model, args.timeout, max_tokens=mt, temperature=0.2, **kw)
            if name.startswith("tools") and row.get("tool_calls"):
                call = row["tool_calls"][0]
                try:
                    row["tool_args_json"] = isinstance(json.loads(call["arguments"]), dict)
                except (TypeError, ValueError):
                    row["tool_args_json"] = False
            if name.startswith("lane") and row.get("ok"):
                try:
                    extract_json_object(strip_reasoning(row["content"]))
                    row["json_ok"] = True
                except ValueError:
                    row["json_ok"] = False
            checks.setdefault(name, []).append(row)
            print(name, json.dumps(row)[:300], flush=True)
    report["checks"] = checks
    report["summary"] = {
        name: {
            "ok": sum(1 for r in rows if r.get("ok")),
            "n": len(rows),
            "ms_median": sorted(r["ms"] for r in rows)[len(rows) // 2] if rows else None,
            "reasoning_returned": sum(1 for r in rows if r.get("reasoning_returned")),
            "tool_calls": sum(1 for r in rows if r.get("tool_calls")),
            "truncated": sum(1 for r in rows if r.get("finish_reason") == "length"),
            "non_nemotron": sum(1 for r in rows if r.get("non_nemotron")),
        }
        for name, rows in checks.items()
    }
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"], indent=1))
    served = sorted(
        {
            str(r.get("provider_model") or r.get("response_model") or "")
            for rows in checks.values()
            for r in rows
        }
        - {""}
    )
    print("served models:", served)
    if any(r.get("non_nemotron") for rows in checks.values() for r in rows):
        print("WARNING: some replies were NOT served by Nemotron (see non_nemotron)")
    print(f"wrote {args.out} (no token inside)")
    answered = any(r.get("ok") for rows in checks.values() for r in rows)
    return 0 if answered else 1


if __name__ == "__main__":
    sys.exit(main())
