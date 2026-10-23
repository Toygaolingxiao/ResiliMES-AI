"""Labeled dispatcher set: regex accuracy and injection block rate."""

from __future__ import annotations

import pytest
from eval.run_eval import (
    load_rows,
    nightshift_reachable,
    offline_hallucination_detector,
    score_injection,
    score_regex,
)


def test_incident_set_size_and_languages() -> None:
    rows = load_rows()
    assert 40 <= len(rows) <= 60
    langs = {row["lang"] for row in rows if not row.get("injection")}
    assert langs == {"en", "zh", "ja"}


def test_regex_tool_call_accuracy_is_perfect_on_the_set() -> None:
    matched, checked = score_regex(load_rows())
    assert checked >= 36
    assert matched == checked


def test_injection_block_rate_is_one() -> None:
    blocked, total = score_injection(load_rows())
    assert total >= 8
    assert blocked == total


def test_offline_hallucination_detector_catches_planted_misses() -> None:
    caught, planted = offline_hallucination_detector()
    assert caught == planted == 2


@pytest.mark.skipif(not nightshift_reachable(), reason="Nightshift is not reachable")
def test_live_intent_round_trip() -> None:
    """Optional. CI skips this unless a real Nightshift health check succeeds."""
    from resilimes.agents.toolcall import parse_dispatch
    from resilimes.config import get_settings
    from resilimes.llm.factory import build_provider

    provider = build_provider(get_settings())
    parsed = parse_dispatch(provider, "hold lot LOT-1004")
    assert parsed.call is not None
    assert parsed.call["intent"] == "hold_lot"
