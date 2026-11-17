"""Contract tests for ResiliTrace case coverage v0 (CaseBook.coverage).

Two rates over a caller-supplied denominator of late lots: triaged (any
case exists) and open (open, investigating, or waiting). The denominator
is the caller's responsibility; these tests pin the method's own rules.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resilimes.explain.cases import (
    COVERAGE_VERSION,
    CaseBook,
    CaseCoverage,
    Severity,
    Status,
)
from resilimes.explain.schema import RunRef

RUN = RunRef(seed=1, horizon_sec=172800.0, policy="baseline", label="baseline")
RUN2 = RunRef(seed=2, horizon_sec=172800.0, policy="baseline", label="baseline")
T0 = "2026-11-14T00:00:00Z"
T1 = "2026-11-14T01:00:00Z"


def _book_with_cases(*specs: tuple[str, Severity, float, RunRef, Status]) -> CaseBook:
    """Build a book from (lot, severity, lateness, run, status) specs."""
    book = CaseBook()
    for lot, severity, lateness, run, status in specs:
        book, case = book.add_case(
            lot=lot,
            run=run,
            title=f"{lot} late",
            severity=severity,
            lateness_min=lateness,
            created_at=T0,
        )
        if status != "open":
            book = book.transition(case.case_id, status, at=T1)
    return book


def test_coverage_version_is_locked() -> None:
    assert COVERAGE_VERSION == "coverage/v0"
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage(["LOT-1"])
    assert result.coverage_version == "coverage/v0"
    with pytest.raises(ValidationError):
        dumped = result.model_dump(mode="json")
        dumped["coverage_version"] = "coverage/v1"
        CaseCoverage(**dumped)


def test_two_rates_over_three_lots() -> None:
    book = _book_with_cases(
        ("LOT-1", "major", 45.0, RUN, "open"),
        ("LOT-2", "major", 45.0, RUN, "resolved"),
    )
    result = book.coverage(["LOT-1", "LOT-2", "LOT-3"])
    assert result.late_total == 3
    assert result.triaged_total == 2
    assert result.open_total == 1
    assert result.triaged_coverage.numerator == 2
    assert result.triaged_coverage.denominator == 3
    assert result.triaged_coverage.value == pytest.approx(2 / 3)
    assert result.open_coverage.numerator == 1
    assert result.open_coverage.denominator == 3
    assert result.open_coverage.value == pytest.approx(1 / 3)
    assert result.uncovered_lots == ("LOT-3",)
    assert result.without_open_case_lots == ("LOT-2", "LOT-3")
    assert result.run is None
    assert result.denominator_run is None


def test_empty_denominator_rates_are_none() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage([])
    assert result.late_total == 0
    assert result.triaged_total == 0
    assert result.open_total == 0
    assert result.triaged_coverage.value is None
    assert result.open_coverage.value is None
    assert result.uncovered_lots == ()
    assert result.without_open_case_lots == ()


def test_duplicate_denominator_counts_once() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage(["LOT-1", "LOT-1"])
    assert result.late_total == 1
    assert result.triaged_total == 1
    assert result.triaged_coverage.value == pytest.approx(1.0)


def test_run_scopes_numerator_not_denominator() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage(["LOT-1", "LOT-2"], run=RUN2, denominator_run=RUN2)
    assert result.run == RUN2
    assert result.denominator_run == RUN2
    assert result.triaged_total == 0
    assert result.open_total == 0
    assert result.uncovered_lots == ("LOT-1", "LOT-2")
    with pytest.raises(ValueError):
        book.coverage(["LOT-1"], run=RUN2, denominator_run=RUN)


def test_whitespace_is_stripped_before_matching() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage([" LOT-1 "])
    assert result.triaged_total == 1
    assert result.uncovered_lots == ()


def test_blank_lot_id_is_rejected() -> None:
    book = CaseBook()
    with pytest.raises(ValueError):
        book.coverage([""])
    with pytest.raises(ValueError):
        book.coverage([" "])


def test_waiting_counts_as_open() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "waiting"))
    result = book.coverage(["LOT-1", "LOT-2"])
    assert result.triaged_total == 1
    assert result.open_total == 1
    assert result.uncovered_lots == ("LOT-2",)
    assert result.without_open_case_lots == ("LOT-2",)


def test_dismissed_only_lot_is_triaged_not_open() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "dismissed"))
    result = book.coverage(["LOT-1"])
    assert result.triaged_total == 1
    assert result.open_total == 0
    assert result.triaged_coverage.value == pytest.approx(1.0)
    assert result.open_coverage.value == pytest.approx(0.0)
    assert result.uncovered_lots == ()
    assert result.without_open_case_lots == ("LOT-1",)


def test_info_watch_item_counts_as_triaged() -> None:
    # A watch-item case is still a case: triaged counts it. Severity does
    # not filter either rate; only status separates triaged from open.
    book = _book_with_cases(("LOT-1", "info", 0.0, RUN, "open"))
    result = book.coverage(["LOT-1"])
    assert result.triaged_total == 1
    assert result.open_total == 1


def test_coverage_does_not_change_the_book() -> None:
    book = _book_with_cases(
        ("LOT-1", "major", 45.0, RUN, "open"),
        ("LOT-2", "major", 45.0, RUN, "resolved"),
    )
    before = book.model_dump(mode="json")
    hashes_before = [case.content_hash for case in book.cases]
    book.coverage(["LOT-1", "LOT-2", "LOT-3"])
    assert book.model_dump(mode="json") == before
    assert [case.content_hash for case in book.cases] == hashes_before


def test_bare_string_denominator_is_rejected() -> None:
    book = CaseBook()
    with pytest.raises(TypeError):
        book.coverage("LOT-1")


def test_run_accepts_a_dict() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage(["LOT-1"], run=RUN.model_dump(mode="json"))
    assert result.run == RUN
    assert result.triaged_total == 1


def test_strip_then_dedup() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage([" LOT-1 ", "LOT-1"])
    assert result.late_total == 1
    assert result.triaged_total == 1


def test_non_string_denominator_element_is_rejected() -> None:
    book = CaseBook()
    with pytest.raises(TypeError):
        book.coverage([42])  # type: ignore[list-item]


def test_matching_is_case_sensitive() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    result = book.coverage(["lot-1"])
    assert result.triaged_total == 0
    assert result.uncovered_lots == ("lot-1",)


def test_uncovered_is_sorted_lexicographically() -> None:
    book = CaseBook()
    result = book.coverage(["LOT-9", "LOT-10"])
    assert result.uncovered_lots == ("LOT-10", "LOT-9")
    assert result.without_open_case_lots == ("LOT-10", "LOT-9")


def test_cases_outside_the_denominator_do_not_inflate() -> None:
    book = _book_with_cases(
        ("LOT-1", "major", 45.0, RUN, "open"),
        ("LOT-9", "major", 45.0, RUN, "open"),
    )
    result = book.coverage(["LOT-1"])
    assert result.late_total == 1
    assert result.triaged_total == 1


def test_json_round_trip() -> None:
    book = _book_with_cases(
        ("LOT-1", "major", 45.0, RUN, "open"),
        ("LOT-2", "major", 45.0, RUN, "resolved"),
    )
    result = book.coverage(["LOT-1", "LOT-2", "LOT-3"], denominator_run=RUN)
    restored = CaseCoverage.model_validate(result.model_dump(mode="json"))
    assert restored == result


def test_inconsistent_model_is_rejected() -> None:
    book = _book_with_cases(("LOT-1", "major", 45.0, RUN, "open"))
    good = book.coverage(["LOT-1"]).model_dump(mode="json")
    with pytest.raises(ValidationError):
        CaseCoverage(**{**good, "triaged_total": 5})
    with pytest.raises(ValidationError):
        CaseCoverage(**{**good, "uncovered_lots": ["LOT-1", "LOT-2"]})
    with pytest.raises(ValidationError):
        CaseCoverage(
            **{**good, "triaged_coverage": {"numerator": 0, "denominator": 1, "value": 0.0}}
        )
