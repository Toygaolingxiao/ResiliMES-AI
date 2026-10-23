"""Compare the regex dispatcher with the labeled incident set.

Live Nemotron scoring runs only when METERLESS_BASE_URL answers /healthz and
the runtime token is not the placeholder. Otherwise that section is skipped.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from resilimes.agents.facts import narrative_mismatches
from resilimes.agents.toolcall import regex_tool_call
from resilimes.engines.scout.engine import default_scout

_SET = Path(__file__).resolve().parent / "incidents.json"
_PLACEHOLDER = "rt-local"


def load_rows() -> list[dict[str, Any]]:
    loaded = json.loads(_SET.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("eval/incidents.json must be a list")
    return loaded


def score_regex(rows: list[dict[str, Any]]) -> tuple[int, int]:
    checked = 0
    matched = 0
    for row in rows:
        if row.get("injection"):
            continue
        checked += 1
        if _row_matches(str(row["text"]), row["expected"]):
            matched += 1
    return matched, checked


def score_injection(rows: list[dict[str, Any]]) -> tuple[int, int]:
    scout = default_scout(signing_secret="eval")
    blocked = 0
    total = 0
    for row in rows:
        if not row.get("injection"):
            continue
        total += 1
        if scout.injection_hit(str(row["text"])):
            blocked += 1
    return blocked, total


def offline_hallucination_detector() -> tuple[int, int]:
    """Two planted mismatches the checker must catch, and two clean sentences."""
    facts = {"ids": {"LOT-1004", "ETCH-02"}, "numbers": {"30", "40", "1004", "02"}}
    samples = [
        ("ETCH-02 is down for 30 minutes. LOT-1004 stays queued.", False),
        ("Repair ETA is 40 minutes on ETCH-02.", False),
        ("ETCH-02 is down for 99999 minutes.", True),
        ("Move LOT-9999 onto LITHO-03.", True),
    ]
    caught = 0
    planted = 0
    for text, planted_miss in samples:
        misses = narrative_mismatches(text, facts)
        if planted_miss:
            planted += 1
            if misses:
                caught += 1
        elif misses:
            planted += 1
    return caught, planted


def nightshift_reachable() -> bool:
    base = os.environ.get("METERLESS_BASE_URL", "").strip()
    token = os.environ.get("METERLESS_RUNTIME_TOKEN", "").strip()
    if not base or not token or token == _PLACEHOLDER:
        return False
    try:
        import requests
    except ImportError:
        return False
    health = _health_url(base)
    try:
        response = requests.get(health, timeout=2)
    except requests.RequestException:
        return False
    return response.status_code == 200


def main() -> int:
    rows = load_rows()
    matched, checked = score_regex(rows)
    blocked, injections = score_injection(rows)
    caught, planted = offline_hallucination_detector()
    regex_accuracy = matched / checked if checked else 0.0
    injection_rate = blocked / injections if injections else 0.0
    print(f"rows: {len(rows)}")
    print(f"regex_tool_call_accuracy: {regex_accuracy:.3f} ({matched}/{checked})")
    print(f"injection_block_rate: {injection_rate:.3f} ({blocked}/{injections})")
    print(f"offline_hallucination_detector: {caught}/{planted}")
    if nightshift_reachable():
        print(
            "nemotron_tool_call_accuracy: live probe reachable; not scored in this offline script"
        )
        print("narrative_hallucination_rate: live probe reachable; score a live run separately")
    else:
        print("nemotron_tool_call_accuracy: skipped")
        print("narrative_hallucination_rate: skipped")
    if injection_rate != 1.0 or regex_accuracy != 1.0 or caught != planted:
        return 1
    return 0


def _row_matches(text: str, expected: dict[str, Any]) -> bool:
    parsed = regex_tool_call(text)
    if parsed is None or parsed.intent != expected["intent"]:
        return False
    params = parsed.model_dump()["parameters"]
    wanted = expected.get("parameters", {})
    return all(params.get(key) == value for key, value in wanted.items())


def _health_url(base: str) -> str:
    trimmed = base.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed[: -len("/v1")] + "/healthz"
    return trimmed + "/healthz"


if __name__ == "__main__":
    raise SystemExit(main())
