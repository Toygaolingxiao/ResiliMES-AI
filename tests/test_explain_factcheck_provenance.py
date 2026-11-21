"""Contract tests for FactRegistry provenance (provenance/v0).

Provenance is metadata layered on the fact-check gate: it records, per
registered value, the caller-supplied source label it came from. It must
never change what the gate accepts. The claim ledger (claim/v0) will later
read this map to attribute each claim to its evidence row.
"""

from __future__ import annotations

import json

import pytest

from resilimes.explain.factcheck import FactRegistry, check, number_known


def test_add_text_with_source_records_id_and_number() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited 42 min.", source="tool:investigator row 3")
    assert registry.sources("id", "Init_Lot_3_17") == ("tool:investigator row 3",)
    assert registry.sources("number", "42") == ("tool:investigator row 3",)


def test_sources_lookup_is_case_insensitive_for_ids() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited.", source="question")
    assert registry.sources("id", "init_lot_3_17") == ("question",)
    assert registry.sources("id", "INIT_LOT_3_17") == ("question",)


def test_sources_lookup_normalises_numbers() -> None:
    registry = FactRegistry()
    registry.add_text("waited 42.0 min.", source="tool:toolkit")
    assert registry.sources("number", "42.0") == ("tool:toolkit",)
    assert registry.sources("number", "42") == ("tool:toolkit",)


def test_hyphen_id_gets_provenance() -> None:
    registry = FactRegistry()
    registry.add_text("Lot-1 is late.", source="tool:investigator row 1")
    assert registry.sources("id", "Lot-1") == ("tool:investigator row 1",)


def test_add_payload_with_source() -> None:
    registry = FactRegistry()
    registry.add({"lot": "Init_Lot_3_17", "wait_min": 42}, source="run:seed1 record")
    assert registry.sources("id", "Init_Lot_3_17") == ("run:seed1 record",)
    assert registry.sources("number", "42") == ("run:seed1 record",)


def test_add_ids_with_source() -> None:
    registry = FactRegistry()
    registry.add_ids(["Init_Lot_3_17", "Diffusion_FE_120"], source="tool:toolkit")
    assert registry.sources("id", "Init_Lot_3_17") == ("tool:toolkit",)
    assert registry.sources("id", "Diffusion_FE_120") == ("tool:toolkit",)
    assert registry.sources("number", "42") == ()


def test_same_value_from_two_sources_keeps_first_seen_order() -> None:
    registry = FactRegistry()
    registry.add_text("42 min.", source="tool:a")
    registry.add_text("42 min.", source="tool:b")
    assert registry.sources("number", "42") == ("tool:a", "tool:b")


def test_same_source_twice_is_not_duplicated() -> None:
    registry = FactRegistry()
    registry.add_text("42 min.", source="tool:a")
    registry.add_text("42 min.", source="tool:a")
    assert registry.sources("number", "42") == ("tool:a",)


def test_value_added_without_source_stays_registered_but_unattributed() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited 42 min.")
    assert registry.sources("id", "Init_Lot_3_17") == ()
    assert registry.sources("number", "42") == ()
    assert check("Init_Lot_3_17 waited 42 min.", registry) == []
    assert number_known("42", registry)


def test_provenance_accumulates_across_calls_with_and_without_source() -> None:
    registry = FactRegistry()
    registry.add_text("42 min.")
    registry.add_text("42 min.", source="tool:b")
    assert registry.sources("number", "42") == ("tool:b",)


def test_unknown_value_has_no_sources() -> None:
    registry = FactRegistry()
    assert registry.sources("id", "Init_Lot_9_99") == ()
    assert registry.sources("number", "43") == ()


def test_unknown_kind_raises() -> None:
    registry = FactRegistry()
    with pytest.raises(ValueError, match="unknown provenance kind"):
        registry.sources("lot", "Init_Lot_3_17")


def test_empty_source_raises() -> None:
    registry = FactRegistry()
    with pytest.raises(ValueError, match="must not be empty"):
        registry.add_text("42 min.", source="")
    with pytest.raises(ValueError, match="must not be empty"):
        registry.add_text("42 min.", source="   ")
    with pytest.raises(ValueError, match="must not be empty"):
        registry.add_ids(["Init_Lot_3_17"], source="")
    # A rejected call registers nothing.
    assert registry.facts() == {
        "ids": set(),
        "numbers": {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"},
    }


def test_non_string_source_raises() -> None:
    registry = FactRegistry()
    with pytest.raises(TypeError):
        registry.add_text("42 min.", source=123)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        registry.add({"wait_min": 42}, source=7)  # type: ignore[arg-type]


def test_gate_is_unchanged_by_provenance() -> None:
    texts = [
        "Init_Lot_3_17 waited 42 min.",
        "Init_Lot_9_99 waited 43 min.",
        "Diffusion_FE_120 is down, tool-hours lost.",
        "two causes, step 1, 0.5 hours",
    ]
    plain = FactRegistry()
    plain.add_text("Init_Lot_3_17 waited 42 min. Diffusion_FE_120 is down.")
    with_sources = FactRegistry()
    with_sources.add_text(
        "Init_Lot_3_17 waited 42 min. Diffusion_FE_120 is down.",
        source="tool:investigator row 3",
    )
    assert plain.facts() == with_sources.facts()
    for text in texts:
        assert check(text, plain) == check(text, with_sources)


def test_provenance_snapshot_is_json_ready_and_a_copy() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited 42 min.", source="tool:a")
    snapshot = registry.provenance()
    # The gate still registers the digits inside the id ("3", "17") as
    # numbers, but provenance does not attribute them: they never occurred
    # as standalone data, so only "42" carries a source.
    assert snapshot == {
        "ids": {"INIT_LOT_3_17": ["tool:a"]},
        "numbers": {"42": ["tool:a"]},
    }
    assert registry.facts()["numbers"] >= {"3", "17", "42"}
    json.dumps(snapshot)  # must not raise
    snapshot["numbers"]["42"].append("tool:evil")
    snapshot["ids"]["FORGED"] = ["tool:evil"]
    assert registry.sources("number", "42") == ("tool:a",)
    assert registry.sources("id", "FORGED") == ()


def test_digits_inside_id_have_no_number_provenance() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited 42 min.", source="tool:a")
    assert registry.sources("number", "3") == ()
    assert registry.sources("number", "17") == ()
    assert registry.sources("id", "INIT_LOT_3_17") == ("tool:a",)
    # The gate is unchanged: the digits are still known numbers.
    assert number_known("3", registry)
    assert number_known("17", registry)


def test_number_inside_id_and_standalone_gets_source() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited 3 min.", source="tool:a")
    assert registry.sources("number", "3") == ("tool:a",)


def test_hyphen_id_digits_have_no_number_provenance() -> None:
    registry = FactRegistry()
    registry.add_text("Lot-1 is late.", source="tool:investigator row 1")
    assert registry.sources("id", "Lot-1") == ("tool:investigator row 1",)
    assert registry.sources("number", "1") == ()


def test_kind_namespaces_id_and_number_separately() -> None:
    registry = FactRegistry()
    registry.add_ids(["42"], source="tool:ids")
    registry.add_text("42 min.", source="tool:text")
    assert registry.sources("id", "42") == ("tool:ids",)
    assert registry.sources("number", "42") == ("tool:text",)


def test_add_ids_lookup_is_case_insensitive() -> None:
    registry = FactRegistry()
    registry.add_ids(["init_lot_3_17"], source="tool:toolkit")
    assert registry.sources("id", "Init_Lot_3_17") == ("tool:toolkit",)


def test_sources_rejects_non_string_value() -> None:
    registry = FactRegistry()
    with pytest.raises(TypeError, match="must be a string"):
        registry.sources("number", 42)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be a string"):
        registry.sources("id", 42)  # type: ignore[arg-type]


def test_sources_strips_padded_value() -> None:
    registry = FactRegistry()
    registry.add_text("42 min.", source="tool:a")
    assert registry.sources("number", " 42 ") == ("tool:a",)
    assert registry.sources("id", " Lot-1 ") == ()


def test_source_is_keyword_only() -> None:
    registry = FactRegistry()
    with pytest.raises(TypeError):
        registry.add_text("42 min.", "tool:a")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        registry.add({"wait_min": 42}, "tool:a")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        registry.add_ids(["Init_Lot_3_17"], "tool:a")  # type: ignore[call-arg]
    assert registry.facts()["numbers"] == {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}


def test_source_label_is_stripped_before_storing() -> None:
    registry = FactRegistry()
    registry.add_text("42 min.", source="  tool:a  ")
    registry.add_text("42 min.", source="tool:a")
    assert registry.sources("number", "42") == ("tool:a",)


def test_source_label_with_control_character_raises() -> None:
    registry = FactRegistry()
    # A trailing newline is normalised away by stripping, not stored.
    registry.add_text("42 min.", source="tool:a\n")
    assert registry.sources("number", "42") == ("tool:a",)
    # A control character inside the label is rejected.
    with pytest.raises(ValueError, match="control characters"):
        registry.add_text("42 min.", source="tool:\ta")
    with pytest.raises(ValueError, match="control characters"):
        registry.add_text("42 min.", source="tool:\u200ba")
    with pytest.raises(ValueError, match="control characters"):
        registry.add_text("42 min.", source="\u200b")
    assert registry.sources("number", "42") == ("tool:a",)


def test_source_label_over_200_chars_raises() -> None:
    registry = FactRegistry()
    with pytest.raises(ValueError, match="at most 200"):
        registry.add_text("42 min.", source="x" * 201)
    assert registry.provenance() == {"ids": {}, "numbers": {}}


def test_rejected_add_registers_nothing() -> None:
    registry = FactRegistry()
    with pytest.raises(TypeError):
        registry.add({"wait_min": 42}, source=7)  # type: ignore[arg-type]
    assert registry.facts() == {
        "ids": set(),
        "numbers": {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"},
    }
    assert registry.provenance() == {"ids": {}, "numbers": {}}


def test_add_validates_source_before_serializing() -> None:
    registry = FactRegistry()
    circular: dict[str, object] = {}
    circular["self"] = circular
    # An unserializable payload would raise from json.dumps; a bad source
    # must raise its own TypeError first.
    with pytest.raises(TypeError, match="must be a string"):
        registry.add(circular, source=7)  # type: ignore[arg-type]


def test_copy_preserves_provenance_and_is_independent() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited 42 min.", source="tool:a")
    copied = registry.copy()
    assert copied.facts() == registry.facts()
    assert copied.provenance() == registry.provenance()
    assert copied.sources("number", "42") == ("tool:a",)
    copied.add_text("43 min.", source="tool:b")
    assert registry.sources("number", "43") == ()
    assert copied.sources("number", "43") == ("tool:b",)
    # Copying only ids/numbers (the old pattern) drops provenance.
    rebuilt = FactRegistry()
    rebuilt.ids = set(registry.ids)
    rebuilt.numbers = set(registry.numbers)
    assert rebuilt.provenance() == {"ids": {}, "numbers": {}}


def test_gate_parity_includes_number_known() -> None:
    plain = FactRegistry()
    plain.add_text("Init_Lot_3_17 waited 42 min.")
    with_sources = FactRegistry()
    with_sources.add_text("Init_Lot_3_17 waited 42 min.", source="tool:a")
    for value in ("42", "3", "17", "43"):
        assert number_known(value, plain) == number_known(value, with_sources)


def test_provenance_snapshot_keys_are_sorted() -> None:
    registry = FactRegistry()
    registry.add_text("99 min, 7 lots, 42 min.", source="tool:a")
    snapshot = registry.provenance()
    assert list(snapshot["numbers"].keys()) == sorted(snapshot["numbers"].keys())


def test_empty_id_gets_no_provenance_but_stays_registered() -> None:
    registry = FactRegistry()
    registry.add_ids([""], source="row-x")
    assert "" in registry.facts()["ids"]
    assert registry.sources("id", "") == ()
    assert registry.provenance() == {"ids": {}, "numbers": {}}


def test_provenance_snapshot_empty_when_nothing_attributed() -> None:
    registry = FactRegistry()
    registry.add_text("Init_Lot_3_17 waited 42 min.")
    assert registry.provenance() == {"ids": {}, "numbers": {}}


def test_always_ok_numbers_can_still_carry_a_source() -> None:
    registry = FactRegistry()
    registry.add_text("two causes.", source="question")
    # "two" is prose, not a number; nothing is recorded for it.
    assert registry.provenance() == {"ids": {}, "numbers": {}}
    registry.add_text("5 lots.", source="question")
    assert registry.sources("number", "5") == ("question",)


def test_sources_returns_tuple_not_live_list() -> None:
    registry = FactRegistry()
    registry.add_text("42 min.", source="tool:a")
    first = registry.sources("number", "42")
    registry.add_text("42 min.", source="tool:b")
    assert first == ("tool:a",)
    assert registry.sources("number", "42") == ("tool:a", "tool:b")
