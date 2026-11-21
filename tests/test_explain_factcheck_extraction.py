"""Extraction-shape tests for the fact-check gate and the claim ledger.

The gate's extraction used to miss three real shapes (recorded as known
blind spots when the claim ledger landed): ids that start with a digit
(``3M_Lot_9``), ids mixing ``-`` and ``_`` separators (``FE-120_A``), and
comma-grouped numbers (``1,000`` was read as ``1`` and ``000``, and the
``000`` then failed as an unknown number). Extraction now lives in
``common.textfacts`` and both the gate and the ledger read it there;
these tests pin the shapes and the gate/ledger agreement on them.
"""

from __future__ import annotations

from resilimes.common.textfacts import id_tokens, narrative_mismatches
from resilimes.explain.claims import ClaimLedger, build_ledger
from resilimes.explain.factcheck import FactRegistry, check


def _registry_with(*texts: str) -> FactRegistry:
    registry = FactRegistry()
    for text in texts:
        registry.add_text(text)
    return registry


# --- id shapes -----------------------------------------------------------


def test_digit_leading_id_passes_when_registered():
    registry = _registry_with("tool 3M_Lot_9 was down")
    assert check("the lot waited on 3M_Lot_9", registry) == []


def test_digit_leading_id_fails_as_one_token_when_unknown():
    registry = FactRegistry()
    assert check("the lot waited on 3M_Lot_9", registry) == ["unknown id 3M_Lot_9"]


def test_mixed_separator_id_passes_when_registered():
    registry = _registry_with("step FE-120_A finished")
    assert check("held at FE-120_A", registry) == []


def test_mixed_separator_id_fails_once_with_the_full_token():
    registry = FactRegistry()
    misses = check("held at FE-120_A", registry)
    assert "unknown id FE-120_A" in misses
    assert "unknown id FE-120" not in misses


def test_id_tokens_covers_the_new_shapes_and_skips_prose():
    text = "3M_Lot_9 FE-120_A Init_Lot_3_17 tool-hours snake_case 2026-11-18 5-10"
    assert id_tokens(text) == ["3M_Lot_9", "FE-120_A", "Init_Lot_3_17"]


def test_prose_and_dates_are_not_ids():
    registry = _registry_with("2026 11 18")
    misses = check("the tool-hours review covers 2026-11-18 and steps 5-10", registry)
    assert not any(miss.startswith("unknown id") for miss in misses)


def test_narrative_mismatches_sees_digit_leading_ids():
    facts = {"ids": set(), "numbers": {"3", "9"}}
    assert narrative_mismatches("held at 3M_Lot_9", facts) == ["unknown id 3M_Lot_9"]


# --- number shapes ---------------------------------------------------------


def test_grouped_number_is_one_number():
    registry = _registry_with("saving 1,000 minutes")
    assert check("saving 1,000 minutes", registry) == []
    assert check("saving 1000 minutes", registry) == []


def test_unknown_grouped_number_fails_as_written_not_as_000():
    registry = FactRegistry()
    assert check("saving 2,000 minutes", registry) == ["unknown number 2,000"]


def test_grouped_decimal_normalises():
    registry = _registry_with("rate 1,000.5 per hour")
    assert check("rate 1000.5 per hour", registry) == []


def test_plain_numbers_unchanged():
    registry = _registry_with("120 40")
    assert check("120 lots and 40 minutes", registry) == []
    assert check("121 lots", registry) == ["unknown number 121"]


# --- provenance on the new shapes ------------------------------------------


def test_provenance_records_digit_leading_id_but_not_its_digits():
    registry = FactRegistry()
    registry.add_text("tool 3M_Lot_9 was down", source="tool:status")
    assert registry.sources("id", "3M_Lot_9") == ("tool:status",)
    assert registry.sources("number", "9") == ()


# --- ledger agreement --------------------------------------------------------


def test_ledger_records_new_shapes_with_the_gate_verdict():
    registry = _registry_with("tool 3M_Lot_9 saving 1,000")
    ledger = build_ledger("3M_Lot_9 saved 1,000 but FE-120_A lost 2,000", registry)
    by_value = {(c.kind, c.value): c.result for c in ledger.claims}
    assert by_value[("id", "3M_LOT_9")] == "passed"
    assert by_value[("number", "1000")] == "passed"
    assert by_value[("id", "FE-120_A")] == "failed"
    assert by_value[("number", "2000")] == "failed"
    assert ledger.verify()


def test_ledger_and_gate_agree_on_every_new_shape():
    registry = _registry_with("Init_Lot_3_17")
    text = "Init_Lot_3_17 met 3M_Lot_9 at FE-120_A over 1,000 minutes"
    ledger = build_ledger(text, registry)
    failed = {(c.kind, c.value) for c in ledger.failed()}
    assert failed == {
        ("id", "3M_LOT_9"),
        ("id", "FE-120_A"),
        ("number", "1000"),
        ("number", "120"),  # the digits inside FE-120_A are a quoted number too
    }


def test_v0_ledgers_still_load_and_verify():
    ledger = build_ledger("120 lots", _registry_with("120"))
    old = ClaimLedger(
        ledger_version="claim/v0",
        subject=ledger.subject,
        source=ledger.source,
        claims=ledger.claims,
    ).sealed()
    loaded = ClaimLedger.model_validate_json(old.model_dump_json())
    assert loaded.ledger_version == "claim/v0"
    assert loaded.verify()


# --- tail-suppression regression (merged #108 follow-up) -------------------
#
# The merged #108 suppressed a legacy hyphen match only when it was the
# *head* of a longer mixed-separator token (``match.end() < end``). A
# legacy match that was the *tail* ("FE-120" inside "3M-FE-120") was not
# suppressed, so a registered id failed the gate while the ledger — which
# reads only the full token — passed it. The guard is now ``<=``: any
# legacy match fully inside a letter-and-digit token is judged once,
# below, as that token.


def test_tail_mixed_id_passes_when_registered():
    for token in (
        "3M-FE-120",
        "FE_120-AB-34",
        "Lot_3-FE-120",
        "Init_Lot_3-FE-120",
        "X-1_Y-2-Z-3",
    ):
        registry = _registry_with(f"held at {token}")
        assert check(f"held at {token}", registry) == []


def test_tail_mixed_id_fails_once_when_unknown():
    registry = FactRegistry()
    assert check("held at 3M-FE-120", registry) == [
        "unknown id 3M-FE-120",
        "unknown number 120",
    ]
    assert check("held at FE_120-AB-34", registry) == [
        "unknown id FE_120-AB-34",
        "unknown number 120",
        "unknown number 34",
    ]


def test_mid_token_tail_segment_is_not_a_separate_id():
    registry = FactRegistry()
    misses = check("held at FE-120_A-B", registry)
    assert misses == ["unknown id FE-120_A-B", "unknown number 120"]
    assert "unknown id A-B" not in misses


def test_head_suppression_shape_still_holds():
    registry = _registry_with("held at FE-120-A_B")
    assert check("held at FE-120-A_B", registry) == []
    assert check("held at FE-120-A_B", FactRegistry()) == [
        "unknown id FE-120-A_B",
        "unknown number 120",
    ]


def test_legacy_single_id_reported_once():
    registry = FactRegistry()
    assert check("held at FE-120", registry) == [
        "unknown id FE-120",
        "unknown number 120",
    ]
    assert check("held at FE-120", _registry_with("held at FE-120")) == []


# --- malformed grouped numbers (merged #108 follow-up) ---------------------
#
# The grouped branch of ``_NUMBER`` had no right anchor, so ``1,0005``
# was read as the valid ``1,000`` plus a trailing ``5`` that the 0-10
# counting-words allowance then swallowed. The branch now requires the
# character after a group not to be a digit, so the malformed token
# falls back to plain matching and its remainder is judged as written.


def test_malformed_grouped_number_with_trailing_digit_fails():
    registry = _registry_with("saving 1,000 minutes")
    assert check("saving 1,0005 minutes", registry) == ["unknown number 0005"]
    assert check("saving 1,0000 minutes", registry) == ["unknown number 0000"]
    registry = _registry_with("saving 2,000 minutes")
    assert check("saving 2,0005 minutes", registry) == ["unknown number 0005"]


def test_trailing_two_digit_group_fails_as_the_whole_fragment():
    registry = _registry_with("saving 1,000 minutes")
    # The miss names the malformed fragment as read ("00055"), not just
    # its tail ("55"): the gate judges the token it was given.
    assert check("saving 1,00055 minutes", registry) == ["unknown number 00055"]


def test_grouped_numbers_still_grouped():
    registry = _registry_with("cost $1,000 and 10,000 lots rate 12,345.67")
    assert check("cost $1,000 and 10,000+ lots", registry) == []
    assert check("rate 12,345.67", registry) == []
    assert check("saving 1,234,567 minutes", _registry_with("saving 1,234,567 minutes")) == []


def test_short_group_split_is_current_behaviour():
    # A short group ("1,00") is still read piecewise — "1" plus "00" —
    # because the grouped branch requires exactly three digits per group.
    # Explicitly rejecting malformed short groups is a follow-up, not
    # part of this fix; see docs/CLAIM_LEDGER.md Limits.
    assert check("saving 1,00 minutes", FactRegistry()) == ["unknown number 00"]


def test_ledger_and_gate_agree_on_tail_and_malformed_shapes():
    registry = _registry_with("3M-FE-120 saving 1,000")
    text = "3M-FE-120 saved 1,0005 but FE_120-AB-34 lost 2,000"
    ledger = build_ledger(text, registry)
    failed = {(c.kind, c.value) for c in ledger.failed()}
    assert failed == {
        ("id", "FE_120-AB-34"),
        ("number", "0005"),
        ("number", "2000"),
        ("number", "34"),
    }
    passed = {(c.kind, c.value) for c in ledger.passed()}
    assert ("id", "3M-FE-120") in passed
    assert ("number", "1000") not in passed  # the text quotes 1,0005, not 1,000
    assert ledger.verify()
