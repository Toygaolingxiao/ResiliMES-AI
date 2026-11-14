"""Contract tests for ResiliTrace cases/v0 (resilimes/explain/cases.py)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from resilimes.explain.cases import (
    CASES_VERSION,
    Case,
    CaseBook,
    CaseBookSummary,
    LotSummary,
    StatusEvent,
    _case_id_key,
    suggest_severity,
)
from resilimes.explain.schema import RunRef

RUN = RunRef(seed=1, horizon_sec=172800.0, policy="baseline", label="baseline")
RUN2 = RunRef(seed=2, horizon_sec=172800.0, policy="baseline", label="baseline")
GOOD_HASH = "sha256:" + "a" * 64
T0 = "2026-11-14T00:00:00Z"
T1 = "2026-11-14T01:00:00Z"
T2 = "2026-11-14T02:00:00Z"


def _book_with(*specs):
    """Build a book from (lot, severity, lateness) specs."""
    book = CaseBook()
    made = []
    for lot, severity, lateness in specs:
        book, case = book.add_case(
            lot=lot,
            run=RUN,
            title=f"{lot} late",
            severity=severity,
            lateness_min=lateness,
            created_at=T0,
        )
        made.append(case)
    return book, made


def _case_kwargs(**overrides):
    kwargs = {
        "case_id": "case-0001",
        "lot": "LOT-1",
        "run": RUN,
        "title": "late",
        "severity": "major",
        "severity_reason": "reason",
        "created_at": T0,
        "updated_at": T0,
    }
    kwargs.update(overrides)
    return kwargs


def test_version_is_locked() -> None:
    assert CASES_VERSION == "cases/v0"
    with pytest.raises(ValidationError):
        Case(**_case_kwargs(cases_version="cases/v1"))  # type: ignore[arg-type]


def test_suggest_severity_thresholds() -> None:
    assert suggest_severity(None) is None
    assert suggest_severity(0) == "info"
    assert suggest_severity(0.5) == "minor"
    assert suggest_severity(29.9) == "minor"
    assert suggest_severity(30.0) == "major"
    assert suggest_severity(119.9) == "major"
    assert suggest_severity(120.0) == "critical"
    assert suggest_severity(900.0) == "critical"
    with pytest.raises(ValueError):
        suggest_severity(-1.0)
    with pytest.raises(ValueError):
        suggest_severity(math.nan)
    with pytest.raises(ValueError):
        suggest_severity(math.inf)
    with pytest.raises(ValueError):
        suggest_severity(True)  # type: ignore[arg-type]


def test_add_case_assigns_sequential_ids_and_seals() -> None:
    book = CaseBook()
    book, first = book.add_case(
        lot="LOT-1", run=RUN, title="late", severity="major",
        severity_reason="120 min late blocks the next step", created_at=T0,
    )
    book, second = book.add_case(
        lot="LOT-1", run=RUN, title="late again", severity="minor",
        severity_reason="5 min late", created_at=T0,
    )
    assert first.case_id == "case-0001"
    assert second.case_id == "case-0002"
    assert book.next_seq == 3
    assert first.verify() and second.verify()
    assert first.status == "open"
    assert len(first.history) == 1
    assert first.history[0] == StatusEvent(
        previous=None, status="open", at=T0, note="created"
    )


def test_add_case_auto_reason_from_suggestion() -> None:
    book, case = CaseBook().add_case(
        lot="LOT-1", run=RUN, title="late", severity="critical",
        lateness_min=150.0, created_at=T0,
    )
    assert case.severity_reason == "suggested from lateness 150 min -> critical"
    assert case.verify()


def test_add_case_auto_reason_refuses_mismatch() -> None:
    # A reason that names one severity while the field names another is a
    # contradiction, not an audit trail: it must be an explicit reason.
    with pytest.raises(ValueError, match="differs from the suggestion"):
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="late", severity="minor",
            lateness_min=150.0, created_at=T0,
        )
    with pytest.raises(ValueError, match="differs from the suggestion"):
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="late", severity="critical",
            lateness_min=5.0, created_at=T0,
        )
    book, case = CaseBook().add_case(
        lot="LOT-1", run=RUN, title="late", severity="minor",
        severity_reason="human override: 150 min but the lot recovered",
        lateness_min=150.0, created_at=T0,
    )
    assert case.severity == "minor"
    assert case.verify()


def test_add_case_requires_reason_when_lateness_unknown() -> None:
    with pytest.raises(ValueError, match="severity_reason is required"):
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="watch", severity="info", created_at=T0
        )


def test_add_case_rejects_empty_fields_and_multiline_title() -> None:
    for kwargs in (
        {"lot": " ", "title": "t", "severity_reason": "r"},
        {"lot": "LOT-1", "title": " ", "severity_reason": "r"},
        {"lot": "LOT-1", "title": "t", "severity_reason": " "},
        {"lot": "LOT-1", "title": "t\nINJECTED", "severity_reason": "r"},
    ):
        with pytest.raises(ValidationError):
            CaseBook().add_case(run=RUN, severity="minor", created_at=T0, **kwargs)


def test_add_case_normalises_lot_whitespace() -> None:
    book, case = CaseBook().add_case(
        lot=" LOT-1 ", run=RUN, title="t", severity="minor",
        severity_reason="r", lateness_min=5.0, created_at=T0,
    )
    assert case.lot == "LOT-1"
    assert book.cases_for_lot("LOT-1") == (case,)
    assert book.lots()[0].lot == "LOT-1"


def test_add_case_rejects_negative_and_nonfinite_lateness_and_bad_hash() -> None:
    for bad in (-5.0, math.nan, math.inf):
        with pytest.raises(ValidationError):
            CaseBook().add_case(
                lot="LOT-1", run=RUN, title="t", severity="minor",
                severity_reason="r", lateness_min=bad, created_at=T0,
            )
    with pytest.raises(ValidationError, match="evidence_hash"):
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="t", severity="minor",
            severity_reason="r", evidence_hash="not-a-hash", created_at=T0,
        )
    with pytest.raises(ValidationError, match="evidence_hash"):
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="t", severity="minor",
            severity_reason="r", evidence_hash="sha256:xyz", created_at=T0,
        )
    with pytest.raises(ValidationError, match="evidence_hash"):
        # Uppercase hex is rejected; EvidenceBundle produces lowercase.
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="t", severity="minor",
            severity_reason="r", evidence_hash="sha256:" + "A" * 64, created_at=T0,
        )
    book, case = CaseBook().add_case(
        lot="LOT-1", run=RUN, title="t", severity="minor",
        severity_reason="r", evidence_hash=GOOD_HASH, created_at=T0,
    )
    assert case.evidence_hash == GOOD_HASH


def test_add_case_rejects_string_notes() -> None:
    with pytest.raises(TypeError, match="tuple of strings"):
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="t", severity="minor",
            severity_reason="r", lateness_min=5.0,
            notes="check pump",  # type: ignore[arg-type]
            created_at=T0,
        )
    with pytest.raises(ValidationError):
        CaseBook().add_case(
            lot="LOT-1", run=RUN, title="t", severity="minor",
            severity_reason="r", lateness_min=5.0,
            notes=("",), created_at=T0,
        )


def test_timestamps_must_carry_a_timezone() -> None:
    for bad in ("2026-11-14", "2026-11-14T00:00:00", "not-a-time"):
        with pytest.raises(ValidationError):
            Case(**_case_kwargs(created_at=bad))
        with pytest.raises(ValidationError):
            StatusEvent(previous="open", status="investigating", at=bad)
    with pytest.raises(ValidationError):
        Case(**_case_kwargs(created_at="", updated_at=""))


def test_case_hash_stable_and_tamper_evident() -> None:
    book, (case,) = _book_with(("LOT-1", "major", 45.0))
    again = Case.model_validate(case.model_dump(mode="json"))
    assert again.content_hash == case.content_hash
    assert again.verify()
    tampered = case.model_copy(update={"severity": "info"})
    assert not tampered.verify()
    restamped = case.model_copy(update={"updated_at": T2})
    assert restamped.verify(), "re-stamping must not change the hash"


def test_transitions_legal_path_and_history() -> None:
    book, (case,) = _book_with(("LOT-1", "major", 45.0))
    book = book.transition(case.case_id, "investigating", "looking at the waits", at=T1)
    moved = book.get(case.case_id)
    assert moved.status == "investigating"
    assert len(moved.history) == 2  # creation + move
    assert moved.history[1] == StatusEvent(
        previous="open", status="investigating", at=T1, note="looking at the waits"
    )
    assert moved.updated_at == T1
    assert moved.verify()
    book = book.transition(case.case_id, "resolved", "lever applied", at=T2)
    assert book.get(case.case_id).status == "resolved"
    book = book.transition(case.case_id, "open", "late again", at=T2)
    assert book.get(case.case_id).status == "open"
    assert len(book.get(case.case_id).history) == 4


@pytest.mark.parametrize("path", [["resolved"], ["dismissed"]])
def test_open_can_resolve_or_dismiss_directly(path: list[str]) -> None:
    # Triage may resolve outright (duplicate, lot recovered) without a
    # faked investigating step; the history must not lie about it.
    book, (case,) = _book_with(("LOT-1", "major", 45.0))
    for step in path:
        book = book.transition(case.case_id, step, at=T1)  # type: ignore[arg-type]
    assert book.get(case.case_id).status == path[-1]
    assert book.get(case.case_id).history[-1].previous == "open"


def test_resolved_can_be_dismissed_and_dismissed_can_be_investigated() -> None:
    book, (case,) = _book_with(("LOT-1", "major", 45.0))
    book = book.transition(case.case_id, "resolved", at=T1)
    book = book.transition(case.case_id, "dismissed", "duplicate of case-0002", at=T2)
    assert book.get(case.case_id).status == "dismissed"
    book = book.transition(case.case_id, "investigating", "new evidence", at=T2)
    assert book.get(case.case_id).status == "investigating"
    book = book.transition(case.case_id, "open", at=T2)
    assert book.get(case.case_id).status == "open"


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("open", "open"),
        ("investigating", "investigating"),
        ("resolved", "resolved"),
        ("dismissed", "dismissed"),
        ("resolved", "investigating"),
        ("dismissed", "resolved"),
    ],
)
def test_transitions_illegal_are_rejected(from_status: str, to_status: str) -> None:
    book, (case,) = _book_with(("LOT-1", "major", 45.0))
    path = {"investigating": ["investigating"], "resolved": ["resolved"],
            "dismissed": ["dismissed"]}.get(from_status, [])
    for step in path:
        book = book.transition(case.case_id, step, at=T1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot move"):
        book.transition(case.case_id, to_status, at=T2)  # type: ignore[arg-type]


def test_transition_unknown_case_and_bad_timestamp() -> None:
    book, _ = _book_with(("LOT-1", "major", 45.0))
    with pytest.raises(KeyError):
        book.transition("case-9999", "investigating")
    with pytest.raises(KeyError):
        book.get("case-9999")
    with pytest.raises(ValidationError):
        StatusEvent(previous="open", status="investigating", at="not-a-time")


def test_add_note_appends_without_status_change() -> None:
    book, (case,) = _book_with(("LOT-1", "major", 45.0))
    book = book.add_note(case.case_id, "called the etch bay", at=T1)
    moved = book.get(case.case_id)
    assert moved.status == "open"
    assert moved.notes == ("called the etch bay",)
    assert moved.updated_at == T1
    assert moved.verify()
    with pytest.raises(ValueError):
        book.add_note(case.case_id, "  ")
    with pytest.raises(KeyError):
        book.add_note("case-9999", "x")


def test_cases_for_lot_orders_by_severity_then_age() -> None:
    book = CaseBook()
    book, minor = book.add_case(
        lot="LOT-1", run=RUN, title="m", severity="minor",
        severity_reason="r", lateness_min=5.0, created_at=T0,
    )
    book, critical = book.add_case(
        lot="LOT-1", run=RUN, title="c", severity="critical",
        severity_reason="r", lateness_min=200.0, created_at=T1,
    )
    book, major = book.add_case(
        lot="LOT-1", run=RUN, title="j", severity="major",
        severity_reason="r", lateness_min=45.0, created_at=T2,
    )
    assert [c.case_id for c in book.cases_for_lot("LOT-1")] == [
        critical.case_id, major.case_id, minor.case_id,
    ]
    assert book.cases_for_lot("LOT-9") == ()


def test_cases_for_lot_same_severity_orders_by_created_time() -> None:
    book = CaseBook()
    book, late = book.add_case(
        lot="LOT-1", run=RUN, title="late", severity="major",
        severity_reason="r", lateness_min=45.0, created_at=T1,
    )
    book, early = book.add_case(
        lot="LOT-1", run=RUN, title="early", severity="major",
        severity_reason="r", lateness_min=50.0, created_at=T0,
    )
    assert [c.case_id for c in book.cases_for_lot("LOT-1")] == [
        early.case_id, late.case_id,
    ]


def test_lots_orders_worst_open_severity_first() -> None:
    # A lot whose only critical case is already resolved sorts behind lots
    # with open major cases: the queue is for work still waiting.
    book = CaseBook()
    book, _ = book.add_case(
        lot="LOT-B", run=RUN, title="b", severity="major",
        severity_reason="r", lateness_min=45.0, created_at=T0,
    )
    book, _ = book.add_case(
        lot="LOT-A", run=RUN, title="a", severity="info",
        severity_reason="watch", created_at=T0,
    )
    book, resolved_critical = book.add_case(
        lot="LOT-C", run=RUN, title="c", severity="critical",
        severity_reason="r", lateness_min=200.0, created_at=T0,
    )
    book = book.transition(resolved_critical.case_id, "resolved", at=T1)
    rows = book.lots()
    assert [r.lot for r in rows] == ["LOT-B", "LOT-A", "LOT-C"]
    assert rows[0].worst_open_severity == "major"
    assert rows[0].worst_severity == "major"
    assert rows[1].worst_open_severity == "info"
    assert rows[2].open_count == 0
    assert rows[2].worst_severity == "critical"
    assert rows[2].worst_open_severity is None
    assert isinstance(rows[0], LotSummary)


def test_lots_tiebreak_is_open_count_then_lot_id() -> None:
    book = CaseBook()
    for lot in ("LOT-Z", "LOT-Y"):
        book, _ = book.add_case(
            lot=lot, run=RUN, title="t", severity="major",
            severity_reason="r", lateness_min=45.0, created_at=T0,
        )
    book, _ = book.add_case(
        lot="LOT-Y", run=RUN, title="t2", severity="major",
        severity_reason="r", lateness_min=50.0, created_at=T0,
    )
    rows = book.lots()
    assert [r.lot for r in rows] == ["LOT-Y", "LOT-Z"]  # more open first
    assert rows[0].open_count == 2


def test_for_run_filters_and_lots_accepts_run() -> None:
    book = CaseBook()
    book, _ = book.add_case(
        lot="LOT-1", run=RUN, title="seed1", severity="major",
        severity_reason="r", lateness_min=45.0, created_at=T0,
    )
    book, second = book.add_case(
        lot="LOT-1", run=RUN2, title="seed2", severity="minor",
        severity_reason="r", lateness_min=5.0, created_at=T0,
    )
    assert [c.case_id for c in book.for_run(RUN2)] == [second.case_id]
    assert len(book.cases_for_lot("LOT-1")) == 2
    assert len(book.cases_for_lot("LOT-1", run=RUN2)) == 1
    assert len(book.lots(run=RUN2)) == 1


def test_summary_counts_only() -> None:
    book, made = _book_with(
        ("LOT-1", "critical", 200.0), ("LOT-1", "minor", 5.0), ("LOT-2", "major", 45.0),
    )
    book = book.transition(made[1].case_id, "dismissed", at=T1)
    summary = book.summary()
    assert isinstance(summary, CaseBookSummary)
    assert summary.total == 3
    assert summary.lots == 2
    assert summary.open_total == 2
    assert summary.by_status == {
        "open": 2, "investigating": 0, "resolved": 0, "dismissed": 1,
    }
    assert summary.by_severity == {
        "critical": 1, "major": 1, "minor": 1, "info": 0,
    }


def test_empty_book_behaviour() -> None:
    book = CaseBook()
    assert book.cases_for_lot("LOT-1") == ()
    assert book.lots() == ()
    assert book.for_run(RUN) == ()
    summary = book.summary()
    assert summary.total == 0 and summary.lots == 0 and summary.open_total == 0
    assert summary.by_status == {
        "open": 0, "investigating": 0, "resolved": 0, "dismissed": 0,
    }
    assert book.verify_all() == []


def test_verify_all_finds_tampered_case() -> None:
    book, made = _book_with(("LOT-1", "major", 45.0), ("LOT-2", "minor", 5.0))
    tampered = made[0].model_copy(update={"title": "edited"})
    book = book.model_copy(update={"cases": (tampered, made[1])})
    assert book.verify_all() == [made[0].case_id]


def test_case_id_key_orders_numerically() -> None:
    ids = ["case-10000", "case-9999", "case-0002", "other"]
    assert sorted(ids, key=_case_id_key) == [
        "case-0002", "case-9999", "case-10000", "other",
    ]


def test_from_json_rejects_duplicate_ids_and_rewound_seq() -> None:
    book, _ = _book_with(("LOT-1", "major", 45.0))
    payload = book.to_json()
    payload["cases"].append(payload["cases"][0])
    with pytest.raises(ValidationError, match="duplicate case_id"):
        CaseBook.from_json(payload)
    payload = book.to_json()
    payload["next_seq"] = 1
    with pytest.raises(ValidationError, match="next_seq"):
        CaseBook.from_json(payload)
    payload = book.to_json()
    payload["book_version"] = "cases/v1"
    with pytest.raises(ValidationError):
        CaseBook.from_json(payload)


def test_from_json_rejects_illegal_history() -> None:
    book, (case,) = _book_with(("LOT-1", "major", 45.0))
    payload = book.to_json()
    # resolved with no history: the state machine was bypassed.
    payload["cases"][0]["status"] = "resolved"
    payload["cases"][0]["history"] = []
    with pytest.raises(ValidationError):
        CaseBook.from_json(payload)
    payload = book.to_json()
    # History whose last event disagrees with the status.
    payload["cases"][0]["status"] = "investigating"
    with pytest.raises(ValidationError):
        CaseBook.from_json(payload)
    payload = book.to_json()
    # History chain is broken: the second event claims to follow
    # "resolved", but the case was only ever open.
    payload["cases"][0]["history"] = [
        {"previous": None, "status": "open", "at": T0, "note": "created"},
        {"previous": "resolved", "status": "dismissed", "at": T1, "note": "jump"},
    ]
    payload["cases"][0]["status"] = "dismissed"
    with pytest.raises(ValidationError):
        CaseBook.from_json(payload)


def test_direct_construction_cannot_bypass_the_machine() -> None:
    with pytest.raises(ValidationError):
        Case(**_case_kwargs(status="resolved", history=()))
    with pytest.raises(ValidationError):
        Case(
            **_case_kwargs(
                status="investigating",
                history=(StatusEvent(previous=None, status="open", at=T0, note="created"),),
            )
        )


def test_json_round_trip_preserves_seal() -> None:
    book, made = _book_with(("LOT-1", "critical", 200.0))
    book = book.transition(made[0].case_id, "investigating", "on it", at=T1)
    book = book.add_note(made[0].case_id, "called the etch bay", at=T1)
    restored = CaseBook.from_json(book.to_json())
    assert restored == book
    assert restored.verify_all() == []
    assert restored.get(made[0].case_id).status == "investigating"
    assert restored.get(made[0].case_id).notes == ("called the etch bay",)
