"""Tests for fab-notes -> structured events (resilimes/insight/notes.py).

Thresholds are set just below the numbers actually measured with
scripts/score_notes.py on this dataset (regex: overall P 0.973 / R 0.750,
plain subset P/R 1.0/1.0, hard subset recall 0.0). They are regression
floors, not aspirations.
"""

from __future__ import annotations

import re
from collections import Counter

from resilimes.insight.notes import (
    EVENT_TYPES,
    SCHEMA,
    LlmExtractor,
    RegexExtractor,
    ScriptedNotesCompleter,
    build_fab_index,
    event_key,
    extract_validated,
    load_notes,
    score_extractor,
    validate_events,
)

NOTES = load_notes()
INDEX = build_fab_index()


# ---------------------------------------------------------------- dataset
def test_dataset_size_and_language_mix() -> None:
    assert len(NOTES) >= 40
    langs = Counter(n["lang"] for n in NOTES)
    assert langs["zh"] >= 5
    assert langs["ja"] >= 5
    assert langs["en"] >= 20
    sources = Counter(n["source"] for n in NOTES)
    assert set(sources) == {"maintenance", "planning", "engineering", "shift"}
    hard = [n for n in NOTES if n["hard_for_regex"]]
    assert len(hard) >= 8


def test_gold_events_are_schema_legal_and_fact_valid() -> None:
    total = 0
    for note in NOTES:
        for event in note["gold"]:
            assert event["type"] in EVENT_TYPES
            assert set(event) <= set(SCHEMA[event["type"]]), (note["id"], event)
            total += 1
        accepted, rejected = validate_events(note["gold"], INDEX)
        assert rejected == [], (note["id"], rejected)
        assert len(accepted) == len(note["gold"])
    assert total >= 40


def test_gold_names_exist_in_repo_data() -> None:
    for note in NOTES:
        for event in note["gold"]:
            if "equipment" in event:
                assert event["equipment"] in INDEX.equipment, (note["id"], event)
            if event["type"] == "hold" and "step" in event:
                assert event["step"] in INDEX.steps, (note["id"], event)


# ---------------------------------------------------------------- regex baseline
def _subset(notes: list[dict]) -> tuple[float, float]:
    gold = Counter()
    pred = Counter()
    for note in notes:
        _, accepted, _ = extract_validated(RegexExtractor(), note, INDEX)
        gold.update(event_key(e) for e in note["gold"])
        pred.update(event_key(e) for e in accepted)
    tp = sum(min(gold[k], pred[k]) for k in gold)
    fp = sum(pred.values()) - tp
    fn = sum(gold.values()) - tp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return precision, recall


def test_regex_baseline_on_plain_subset() -> None:
    plain = [n for n in NOTES if not n["hard_for_regex"]]
    precision, recall = _subset(plain)
    # Measured: precision 1.000, recall 1.000 on the plain subset.
    assert precision >= 0.9
    assert recall >= 0.9


def test_regex_baseline_overall_floors() -> None:
    result = score_extractor(RegexExtractor(), NOTES, INDEX)
    # Measured: precision 0.973, recall 0.750.
    assert result["overall"]["precision"] >= 0.9
    assert result["overall"]["recall"] >= 0.65


def test_hard_notes_really_defeat_the_regex() -> None:
    """At least 3 hard notes must lose >=1 gold event under the regex baseline.

    Measured: all 11 hard notes with gold events lose every one of them
    (hard-subset recall 0.0); the floor of 3 only proves the subset serves
    its design purpose without pinning the exact gap.
    """
    misses = 0
    for note in NOTES:
        if not note["hard_for_regex"] or not note["gold"]:
            continue
        _, accepted, _ = extract_validated(RegexExtractor(), note, INDEX)
        if len(accepted) < len(note["gold"]):
            misses += 1
    assert misses >= 3


# ---------------------------------------------------------------- validation
def test_validate_rejects_unknown_names_and_out_of_range_numbers() -> None:
    bad = [
        {
            "type": "planned_down",
            "equipment": "LITHO-99",
            "start": "2026-10-22T10:00:00Z",
            "duration_min": 60,
        },
        {
            "type": "planned_down",
            "equipment": "LITHO-01",
            "start": "2026-10-22T10:00:00Z",
            "duration_min": 99999,
        },
        {"type": "priority_change", "lot": "LOT-9999", "priority": "hot"},
        {"type": "priority_change", "lot": "Init_Lot_99_1", "priority": "hot"},
        {"type": "priority_change", "lot": "LOT-1001", "new_due_h": -3},
        {"type": "hold", "scope": "step", "step": "POLISH", "reason": "other"},
        {"type": "hold", "scope": "lot", "lot": "LOT-1001", "reason": "whatever"},
        {"type": "capacity_derate", "equipment": "ETCH-01", "factor": 1.5, "window_h": 4},
        {"type": "capacity_derate", "equipment": "ETCH-01", "factor": 0.5, "window_h": 999},
        {"type": "surprise_me", "equipment": "ETCH-01"},
    ]
    accepted, rejected = validate_events(bad, INDEX)
    assert accepted == []
    assert len(rejected) == len(bad)
    assert all(r["reason"] for r in rejected)


def test_validate_drops_out_of_schema_fields_but_keeps_event() -> None:
    raw = [
        {
            "type": "planned_down",
            "equipment": "LITHO-01",
            "start": "2026-10-22T10:00:00Z",
            "duration_min": 60,
            "confidence": 0.99,
            "invented_field": "x",
        }
    ]
    accepted, rejected = validate_events(raw, INDEX)
    assert rejected == []
    assert accepted == [
        {
            "type": "planned_down",
            "equipment": "LITHO-01",
            "start": "2026-10-22T10:00:00Z",
            "duration_min": 60,
        }
    ]


# ---------------------------------------------------------------- llm pipeline
def test_llm_extractor_pipeline_with_scripted_completer() -> None:
    extractor = LlmExtractor(ScriptedNotesCompleter())
    assert extractor.provider.mocked  # offline: CI never touches Nightshift
    result = score_extractor(extractor, NOTES, INDEX)
    # The stand-in is deterministic and written against these constructions;
    # measured P/R are both 1.000. Floors sit below that so the test guards
    # the pipe (prompt -> JSON -> validate), not a claim about a live model.
    assert result["overall"]["precision"] >= 0.9
    assert result["overall"]["recall"] >= 0.9
    hard_recall = result["recall_by_flag"]["hard"]["recall"]
    regex_hard_recall = score_extractor(RegexExtractor(), NOTES, INDEX)["recall_by_flag"]["hard"][
        "recall"
    ]
    assert hard_recall > regex_hard_recall


def test_llm_output_with_hallucinated_name_is_caught_by_validation() -> None:
    class HallucinatingCompleter:
        name = "test-fake"
        mocked = True

        def model_for(self, lane: str) -> str:
            return "test-fake"

        def complete(self, messages, *, lane, temperature=0.0):
            from resilimes.llm.base import LlmResult

            return LlmResult(
                content=(
                    '{"events": [{"type": "planned_down", "equipment": "Litho_FE_999-1",'
                    ' "start": "2026-10-22T10:00:00Z", "duration_min": 60, "extra": 1}]}'
                ),
                model="test-fake",
                provider=self.name,
                lane=lane,
                latency_ms=0.1,
                mocked=True,
            )

    note = {"text": "anything", "ts": "2026-10-22T00:00:00Z"}
    raw, accepted, rejected = extract_validated(LlmExtractor(HallucinatingCompleter()), note, INDEX)
    assert len(raw) == 1
    assert accepted == []
    assert len(rejected) == 1
    assert "unknown equipment" in rejected[0]["reason"]


# ---------------------------------------------------------------- A/B/C arms
def _b_events(extractor) -> dict[str, list[dict]]:
    return {note["id"]: extract_validated(extractor, note, INDEX)[1] for note in NOTES}


def test_gap_closure_formula_and_undefined_case() -> None:
    from resilimes.insight.notes_ab import gap_closure

    assert gap_closure(100, 40, 20) == 0.75
    assert gap_closure(100, 100, 20) == 0.0
    assert gap_closure(50, 50, 50) is None  # A == C: gold adds nothing


def test_mock_arms_scripted_b_closes_gap_without_collateral() -> None:
    from resilimes.insight.notes_ab import MockScheduleRunner, compare_arms

    report = compare_arms(
        NOTES, _b_events(LlmExtractor(ScriptedNotesCompleter())), MockScheduleRunner()
    )
    assert report["is_mock"] is True
    # Scripted B equals gold on this dataset (measured), so B lands on C.
    assert report["arms"]["B"]["avoidable_qtime"] == report["arms"]["C"]["avoidable_qtime"]
    assert report["gap_closure"] == 1.0
    assert report["collateral"] == {
        "wrong_events_applied": 0,
        "new_violations": 0,
        "target": 0,
    }


def test_mock_arms_regex_b_partial_closure_and_one_collateral() -> None:
    from resilimes.insight.notes_ab import MockScheduleRunner, compare_arms

    report = compare_arms(NOTES, _b_events(RegexExtractor()), MockScheduleRunner())
    # Measured with the mock ledger: A=160, B=78, C=44 -> closure 0.7069;
    # the one FP is the negation-trap hold (n26), which takes effect in B.
    assert report["arms"]["A"]["avoidable_qtime"] == 160
    assert report["arms"]["C"]["avoidable_qtime"] == 44
    assert 0.0 < report["gap_closure"] < 1.0
    assert report["collateral"]["wrong_events_applied"] == 1
    assert report["collateral"]["new_violations"] == 0


def test_ab_report_template_has_headline_fields() -> None:
    from resilimes.insight.notes_ab import (
        MockScheduleRunner,
        compare_arms,
        render_markdown,
    )

    report = {
        "comparison": compare_arms(NOTES, _b_events(RegexExtractor()), MockScheduleRunner()),
        "extraction": {
            "regex": score_extractor(RegexExtractor(), NOTES, INDEX),
            "llm": score_extractor(LlmExtractor(ScriptedNotesCompleter()), NOTES, INDEX),
        },
    }
    md = render_markdown(report)
    assert "缺口弥合率" in md
    assert "误伤次数" in md
    assert "precision" in md and "recall" in md
    assert "MOCK" in md  # mock numbers must never pass as live results


def test_note_ids_unique_and_timestamps_parse() -> None:
    ids = [n["id"] for n in NOTES]
    assert len(ids) == len(set(ids))
    for note in NOTES:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", note["ts"])
