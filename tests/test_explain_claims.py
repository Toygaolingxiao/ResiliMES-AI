"""Contract tests for the claim ledger v0.

The ledger is the audit trail of the fact-check gate: every number and id an
explanation quotes, the sentence it was quoted in, and whether the gate
passed it. If one of these tests has to change, the ledger version has to
change too.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resilimes.common.textfacts import _norm

from resilimes.explain.claims import (
    KINDS,
    LEDGER_VERSION,
    RESULTS,
    Claim,
    ClaimLedger,
    build_ledger,
    ledger_for_explanation,
)
from resilimes.explain.explainer import Explanation
from resilimes.explain.factcheck import FactRegistry, check

TEXT = (
    "Lot-1 finished 120 min late; while late it spent down 40 min. "
    "Its longest wait was 30 min at Diffusion_FE_120."
)


def _registry() -> FactRegistry:
    registry = FactRegistry()
    registry.add_ids(["Lot-1", "Diffusion_FE_120"])
    registry.add_text("120 40 30")
    return registry


def test_version_and_fields_are_pinned():
    assert LEDGER_VERSION == "claim/v0"
    assert KINDS == ("number", "id")
    assert RESULTS == ("passed", "failed", "unchecked")
    assert set(ClaimLedger.model_fields) == {
        "ledger_version",
        "subject",
        "source",
        "claims",
        "content_hash",
    }
    assert set(Claim.model_fields) == {
        "claim_id",
        "kind",
        "value",
        "statement",
        "sources",
        "result",
        "checked_at",
        "reason",
    }


def test_known_values_pass_with_their_sentences():
    ledger = build_ledger(TEXT, _registry(), subject="Lot-1", source="explainer")
    assert ledger.subject == "Lot-1"
    assert ledger.source == "explainer"
    # Numbers are taken as the gate sees them, so "Lot-1" also quotes the
    # counting number 1 (passed, as the gate allows 0-10), and 120 is quoted
    # twice: once on its own, once inside Diffusion_FE_120.
    assert ledger.summary() == {"total": 7, "passed": 7, "failed": 0, "unchecked": 0}
    numbers = {c.value for c in ledger.claims if c.kind == "number"}
    ids = {c.value for c in ledger.claims if c.kind == "id"}
    assert numbers == {"1", "120", "40", "30"}
    assert ids == {"LOT-1", "DIFFUSION_FE_120"}
    by_value = ledger.by_value("120", kind="number")[0]
    assert by_value.statement.startswith("Lot-1 finished 120 min late")
    assert by_value.result == "passed"
    assert by_value.claim_id.startswith("claim-")


def test_unknown_number_and_id_fail():
    registry = FactRegistry()
    registry.add_ids(["Lot-1"])
    registry.add_text("120")
    ledger = build_ledger(
        "Lot-1 finished 120 min late, 999 min of it at Etch_X_9.",
        registry,
    )
    # 1 (inside Lot-1) and 9 (inside Etch_X_9) are counting words the gate
    # allows; 999 and Etch_X_9 fail.
    assert ledger.summary() == {"total": 6, "passed": 4, "failed": 2, "unchecked": 0}
    failed = {c.value for c in ledger.failed()}
    assert failed == {"999", "ETCH_X_9"}
    assert {m for m in check(
        "Lot-1 finished 120 min late, 999 min of it at Etch_X_9.", registry
    )} == {"unknown number 999", "unknown id Etch_X_9"}


def test_small_counting_numbers_pass_without_being_registered():
    ledger = build_ledger("Two causes and step 1.", FactRegistry())
    assert ledger.summary() == {"total": 1, "passed": 1, "failed": 0, "unchecked": 0}
    assert ledger.claims[0].value == "1"


def test_prose_tokens_are_not_claims():
    ledger = build_ledger("The tool-hours report needs a re-run.", _registry())
    assert ledger.summary() == {"total": 0, "passed": 0, "failed": 0, "unchecked": 0}


def test_empty_text_builds_an_empty_sealed_ledger():
    ledger = build_ledger("", _registry())
    assert ledger.claims == ()
    assert ledger.summary() == {"total": 0, "passed": 0, "failed": 0, "unchecked": 0}
    assert ledger.verify()


def test_hash_is_stable_and_tamper_evident():
    first = build_ledger(TEXT, _registry(), checked_at="2026-11-13T12:00:00+00:00")
    second = build_ledger(TEXT, _registry(), checked_at="2026-11-13T12:00:00+00:00")
    assert first.content_hash == second.content_hash
    assert first.verify()
    # The hash covers what was claimed and the verdicts, not when the check
    # ran: two builds without a pinned timestamp share the same hash.
    unpinned_first = build_ledger(TEXT, _registry())
    unpinned_second = build_ledger(TEXT, _registry())
    assert unpinned_first.content_hash == unpinned_second.content_hash
    tampered = first.model_copy(
        update={"claims": (first.claims[0].model_copy(update={"result": "failed"}), *first.claims[1:])}
    )
    assert not tampered.verify()
    tampered_subject = first.model_copy(update={"subject": "Lot-2"})
    assert not tampered_subject.verify()


def test_same_value_in_two_sentences_is_two_claims():
    ledger = build_ledger(
        "Lot-1 waited 30 min. The 30 min wait was at Diffusion_FE_120.",
        _registry(),
    )
    thirties = ledger.by_value("30", kind="number")
    assert len(thirties) == 2
    assert thirties[0].claim_id != thirties[1].claim_id
    assert thirties[0].statement != thirties[1].statement


def test_ledger_for_explanation_uses_lot_and_both_texts():
    explanation = Explanation(
        lot="Lot-1",
        explanation="Lot-1 finished 120 min late.",
        claim="Applying prioritise removes the waiting behind it.",
    )
    ledger = ledger_for_explanation(explanation, _registry())
    assert ledger.subject == "Lot-1"
    assert ledger.source == "explainer"
    assert ledger.by_value("120", kind="number")
    assert ledger.verify()


def test_ledger_for_explanation_reproduces_the_gate_registry():
    # The explainer adds expected_saving_min and the lot id to its registry
    # copy before checking; a claim sentence quoting the saving must pass
    # here exactly as it passed the gate, even though 25 is not evidence.
    explanation = Explanation(
        lot="Lot-1",
        explanation="Lot-1 finished 120 min late.",
        claim="Applying prioritise saves 25 min.",
        expected_saving_min=25.0,
    )
    registry = FactRegistry()
    registry.add_ids(["Lot-1"])
    registry.add_text("120")
    ledger = ledger_for_explanation(explanation, registry)
    assert ledger.summary() == {"total": 4, "passed": 4, "failed": 0, "unchecked": 0}
    assert ledger.by_value("25", kind="number")[0].result == "passed"
    # The caller's registry is not mutated by the augmentation.
    assert "25" not in registry.numbers
    # With a fixed timestamp the same explanation builds the same hash.
    first = ledger_for_explanation(
        explanation, registry, checked_at="2026-11-13T12:00:00+00:00"
    )
    second = ledger_for_explanation(
        explanation, registry, checked_at="2026-11-13T12:00:00+00:00"
    )
    assert first.content_hash == second.content_hash


def test_bogus_ledger_version_is_rejected():
    with pytest.raises(ValidationError):
        ClaimLedger(ledger_version="bogus/v9")
    with pytest.raises(ValidationError):
        ClaimLedger.model_validate(
            {"ledger_version": "bogus/v9", "claims": []}
        )


def test_by_value_normalises_the_query():
    ledger = build_ledger(TEXT, _registry())
    assert ledger.by_value("Lot-1", kind="id")
    assert ledger.by_value("120.0", kind="number")
    assert ledger.by_value("LOT-1")  # kind omitted: both normalisations tried
    assert not ledger.by_value("Lot-9", kind="id")


def test_failed_claims_carry_the_gate_miss_text():
    registry = FactRegistry()
    registry.add_ids(["Lot-1"])
    registry.add_text("120")
    ledger = build_ledger(
        "Lot-1 finished 120 min late, 999 min of it at Etch_X_9.",
        registry,
    )
    failed = {c.value: c.reason for c in ledger.failed()}
    assert failed == {"999": "unknown number 999", "ETCH_X_9": "unknown id Etch_X_9"}


def test_unchecked_requires_a_reason_and_checked_at_must_parse():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="claim-x",
            kind="id",
            value="LOT-9",
            statement="Lot-9 was mentioned in a note.",
            result="unchecked",
            checked_at="2026-11-13T12:00:00+00:00",
        )
    with pytest.raises(ValidationError):
        Claim(
            claim_id="claim-x",
            kind="id",
            value="LOT-9",
            statement="Lot-9 was mentioned in a note.",
            result="passed",
            checked_at="not-a-date",
        )


def test_abbreviations_do_not_split_sentences():
    ledger = build_ledger(
        "Lot-1 waited e.g. 30 min at Diffusion_FE_120.",
        _registry(),
    )
    thirty = ledger.by_value("30", kind="number")[0]
    assert thirty.statement == "Lot-1 waited e.g. 30 min at Diffusion_FE_120."


def test_explanation_without_final_period_keeps_sentences_apart():
    explanation = Explanation(
        lot="Lot-1",
        explanation="Lot-1 finished 120 min late",
        claim="It waited 999 min at Etch_X_9.",
    )
    registry = FactRegistry()
    registry.add_ids(["Lot-1"])
    registry.add_text("120")
    ledger = ledger_for_explanation(explanation, registry)
    failed = {c.value: c.statement for c in ledger.failed()}
    assert set(failed) == {"999", "ETCH_X_9"}
    assert failed["999"] == "It waited 999 min at Etch_X_9."
    assert failed["ETCH_X_9"] == "It waited 999 min at Etch_X_9."


@pytest.mark.parametrize(
    "text",
    [
        "Lot-1 waited 30 min at Diffusion_FE_120.",
        "Lot-1 waited 120.0 min, not 120.50 min.",
        "TOOL-12A took 12 min.",
        "Lot-1 waited 30 min. The 30 min wait was at Diffusion_FE_120.",
        "Fig. 2 shows Lot-1 waited 30 min.",
        "Lot-1 waited 1,000 min.",
        "Lot-1 waited 30 min at 3M_Lot_9.",
        "Lot-1 waited 30 min at Diffusion_FE-120.",
    ],
)
def test_ledger_failed_set_matches_the_gate(text):
    """Gate parity, not correctness: on the same text and registry the
    ledger's failed values are exactly the gate's misses. Where the gate
    itself is blind (digit-leading ids, thousands separators), the ledger
    shares the blind spot; that is a documented limit, not a divergence."""
    registry = FactRegistry()
    registry.add_ids(["Lot-1", "Diffusion_FE_120", "TOOL-12A"])
    registry.add_text("120 30 1000")
    ledger = build_ledger(text, registry)
    misses = check(text, registry)
    expected_failed_numbers = {
        miss[len("unknown number ") :]
        for miss in misses
        if miss.startswith("unknown number ")
    }
    expected_failed_ids = {
        miss[len("unknown id ") :].upper()
        for miss in misses
        if miss.startswith("unknown id ")
    }
    actual_failed_numbers = {
        c.value for c in ledger.failed() if c.kind == "number"
    }
    actual_failed_ids = {c.value for c in ledger.failed() if c.kind == "id"}
    # Numbers are normalised in the ledger, raw in the gate's misses.
    assert actual_failed_numbers == {_norm(v) for v in expected_failed_numbers}
    assert actual_failed_ids == expected_failed_ids


def test_sources_are_recorded_ledger_wide():
    ledger = build_ledger(
        TEXT, _registry(), sources=("lateness.while_late_min", "waits[0].family")
    )
    assert all(
        c.sources == ("lateness.while_late_min", "waits[0].family")
        for c in ledger.claims
    )


def test_unchecked_claims_can_be_recorded_manually():
    claim = Claim(
        claim_id="claim-manual-1",
        kind="id",
        value="LOT-9",
        statement="Lot-9 was mentioned in a note.",
        result="unchecked",
        checked_at="2026-11-13T12:00:00+00:00",
        reason="no registry available at audit time",
    )
    ledger = ClaimLedger(subject="Lot-9", claims=(claim,)).sealed()
    assert ledger.summary() == {"total": 1, "passed": 0, "failed": 0, "unchecked": 1}
    assert ledger.verify()
    with pytest.raises(ValidationError):
        Claim(
            claim_id="x",
            kind="date",
            value="2026-11-13",
            statement="s",
            result="passed",
            checked_at="2026-11-13T12:00:00+00:00",
        )
