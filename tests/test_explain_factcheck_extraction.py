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
