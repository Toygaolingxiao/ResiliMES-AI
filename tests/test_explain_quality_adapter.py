"""Contract tests for the fault-injection benchmark adapter (adapter/v0).

The mapping rules are the contract. If one of these tests has to change,
the adapter version has to change too. See docs/QUALITY_ADAPTER.md.

These tests pin the mapping only. Rates are quality.evaluate's job (PR #88)
and are measured, not asserted, in docs/QUALITY_ADAPTER.md -- except for
the headline counts below, which are pure mapping facts (how many adapted
samples are right/wrong/unknown) and pin the documented numerators. The
evaluate() wiring (this PR's increment) is tested separately at the end of
this file: ``evaluate_adapted`` / ``evaluate_file`` / ``--report`` must
reproduce the documented first measurement through the real pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resilimes.insight.quality_adapter import (
    ADAPTER_VERSION,
    adapt_investigator_file,
    adapt_investigator_rows,
    evaluate_adapted,
    evaluate_file,
    main,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = "investigator"


def _row(case_id="tool_down-s1", truth="tool_down", primary="tool_down", **extra):
    ai = {"primary_cause": primary, "secondary_cause": None}
    ai.update(extra.pop("ai", {}))
    row = {"case_id": case_id, "truth": truth, "ai": ai}
    row.update(extra)
    return row


def _adapt(rows, source=SOURCE):
    return adapt_investigator_rows(rows, source=source)


def test_version_is_adapter_v0():
    assert ADAPTER_VERSION == "adapter/v0"


def test_legacy_row_maps_to_attributed_sample():
    adapted = _adapt([_row()])
    assert adapted.shape == "legacy"
    assert len(adapted.samples) == 1
    sample = adapted.samples[0]
    assert sample == {
        "sample_id": "investigator:tool_down-s1",
        "tier": "attributed",
        "predicted_cause": "tool_down",
        "true_cause": "tool_down",
        "confidence": None,
    }
    assert adapted.skipped == {}
    assert adapted.system_answers_used == 0
    assert adapted.system_answer_sample_ids == ()


def test_wrong_prediction_passes_through_unjudged():
    # The adapter maps; it does not score. Correctness is evaluate()'s job.
    adapted = _adapt([_row(primary="pm_in_peak")])
    assert adapted.samples[0]["predicted_cause"] == "pm_in_peak"
    assert adapted.samples[0]["true_cause"] == "tool_down"


def test_current_shape_degraded_row_prefers_system_answer():
    row = _row(
        primary="tool_down",
        ai={
            "primary_cause": "tool_down",
            "degraded": True,
            "stop_reason": "degraded_to_rule",
            "system": {
                "source": "rule",
                "primary_cause": "release_burst",
                "secondary_cause": None,
            },
        },
    )
    adapted = _adapt([row])
    assert adapted.shape == "current"
    assert adapted.samples[0]["predicted_cause"] == "release_burst"
    assert adapted.system_answers_used == 1
    assert adapted.system_answer_sample_ids == ("investigator:tool_down-s1",)


def test_current_shape_ai_source_uses_system_primary():
    row = _row(
        ai={
            "primary_cause": "tool_down",
            "degraded": False,
            "stop_reason": "final",
            "system": {
                "source": "ai",
                "primary_cause": "tool_down",
                "secondary_cause": None,
            },
        },
    )
    adapted = _adapt([row])
    assert adapted.shape == "current"
    assert adapted.samples[0]["predicted_cause"] == "tool_down"
    assert adapted.system_answers_used == 0
    assert adapted.system_answer_sample_ids == ()


def test_system_source_none_is_unknown_and_does_not_resurrect_ai_answer():
    row = _row(
        ai={
            "primary_cause": "tool_down",
            "degraded": True,
            "stop_reason": "error",
            "system": {"source": "none", "error": "KeyError: 'x'"},
        },
    )
    adapted = _adapt([row])
    sample = adapted.samples[0]
    assert sample["tier"] == "unknown"
    assert sample["predicted_cause"] is None
    assert sample["true_cause"] == "tool_down"


def test_stop_reason_error_is_unknown():
    row = _row(ai={"primary_cause": "tool_down", "stop_reason": "error"})
    adapted = _adapt([row])
    assert adapted.samples[0]["tier"] == "unknown"


def test_system_malformed_primary_is_skipped_not_silent_fallback():
    # Degraded row whose rule answer is malformed: the adapter must not
    # quietly report the AI answer instead.
    row = _row(
        ai={
            "primary_cause": "tool_down",
            "degraded": True,
            "system": {"source": "rule", "primary_cause": ["release_burst"]},
        },
    )
    adapted = _adapt([row])
    assert adapted.samples == ()
    assert adapted.skipped == {"malformed_predicted": 1}


def test_system_not_a_dict_is_skipped():
    row = _row(ai={"primary_cause": "tool_down", "system": "tool_down"})
    adapted = _adapt([row])
    assert adapted.samples == ()
    assert adapted.skipped == {"malformed_predicted": 1}


def test_system_rule_primary_empty_is_skipped():
    row = _row(
        ai={
            "primary_cause": "tool_down",
            "system": {"source": "rule", "primary_cause": ""},
        },
    )
    adapted = _adapt([row])
    assert adapted.samples == ()
    assert adapted.skipped == {"malformed_predicted": 1}


def test_system_unknown_source_is_skipped():
    row = _row(
        ai={
            "primary_cause": "tool_down",
            "system": {"source": "mystery", "primary_cause": "tool_down"},
        },
    )
    adapted = _adapt([row])
    assert adapted.samples == ()
    assert adapted.skipped == {"malformed_predicted": 1}


def test_system_without_source_tolerates_usable_primary():
    row = _row(ai={"primary_cause": "tool_down", "system": {"primary_cause": "pm_in_peak"}})
    adapted = _adapt([row])
    assert adapted.samples[0]["predicted_cause"] == "pm_in_peak"
    assert adapted.system_answers_used == 0


def test_timeout_row_is_unknown_despite_half_finished_answer():
    row = _row(primary="tool_down", ai={"primary_cause": "tool_down", "timed_out": True})
    adapted = _adapt([row])
    sample = adapted.samples[0]
    assert sample["tier"] == "unknown"
    assert sample["predicted_cause"] is None
    assert sample["true_cause"] == "tool_down"


def test_ai_timeout_key_is_unknown():
    row = _row(ai={"primary_cause": "tool_down", "timeout": True})
    adapted = _adapt([row])
    assert adapted.samples[0]["tier"] == "unknown"


def test_row_level_timeout_is_unknown():
    row = _row(primary="tool_down", timeout=True)
    adapted = _adapt([row])
    assert adapted.samples[0]["tier"] == "unknown"


def test_error_row_is_unknown():
    row = _row(primary="tool_down", ai={"primary_cause": "tool_down", "error": "no final answer"})
    adapted = _adapt([row])
    assert adapted.samples[0]["tier"] == "unknown"
    assert adapted.samples[0]["predicted_cause"] is None


def test_empty_string_error_is_unknown():
    row = _row(ai={"primary_cause": "tool_down", "error": ""})
    adapted = _adapt([row])
    assert adapted.samples[0]["tier"] == "unknown"


def test_row_level_error_is_unknown():
    row = _row(ai={"primary_cause": "tool_down"}, error="KeyError: 'x'")
    adapted = _adapt([row])
    assert adapted.samples[0]["tier"] == "unknown"


def test_missing_ai_answer_is_unknown_not_skipped():
    row = {"case_id": "tool_down-s1", "truth": "tool_down", "ai": None}
    adapted = _adapt([row])
    assert len(adapted.samples) == 1
    assert adapted.samples[0]["tier"] == "unknown"
    assert adapted.skipped == {}


def test_empty_primary_is_unknown():
    adapted = _adapt([_row(primary="")])
    assert adapted.samples[0]["tier"] == "unknown"
    assert adapted.samples[0]["predicted_cause"] is None


def test_missing_truth_row_is_skipped_and_counted():
    adapted = _adapt([_row(truth=None), _row(case_id="pm_in_peak-s1")])
    assert len(adapted.samples) == 1
    assert adapted.skipped == {"missing_truth": 1}


def test_empty_and_non_string_truth_are_skipped():
    adapted = _adapt([_row(case_id="a", truth=""), _row(case_id="b", truth=42)])
    assert adapted.samples == ()
    assert adapted.skipped == {"missing_truth": 2}


def test_missing_case_id_row_is_skipped():
    adapted = _adapt([{"truth": "tool_down", "ai": {"primary_cause": "tool_down"}}])
    assert adapted.samples == ()
    assert adapted.skipped == {"missing_case_id": 1}


def test_empty_case_id_is_skipped():
    adapted = _adapt([_row(case_id="")])
    assert adapted.samples == ()
    assert adapted.skipped == {"missing_case_id": 1}


def test_malformed_rows_are_skipped_and_counted():
    rows = [
        "not-a-dict",
        {"case_id": "a", "truth": "tool_down", "ai": "not-a-dict"},
        {"case_id": "b", "truth": "tool_down", "ai": {"primary_cause": ["tool_down"]}},
        _row(case_id="ok"),
    ]
    adapted = _adapt(rows)
    assert len(adapted.samples) == 1
    assert adapted.samples[0]["sample_id"] == "investigator:ok"
    assert adapted.skipped == {
        "malformed_row": 1,
        "malformed_ai": 1,
        "malformed_predicted": 1,
    }


def test_skipped_row_does_not_block_later_valid_row_with_same_id():
    rows = [
        {"case_id": "d1", "truth": None, "ai": {"primary_cause": "tool_down"}},
        _row(case_id="d1"),
    ]
    adapted = _adapt(rows)
    assert len(adapted.samples) == 1
    assert adapted.samples[0]["sample_id"] == "investigator:d1"
    assert adapted.skipped == {"missing_truth": 1}


def test_duplicate_case_id_fails_the_run():
    with pytest.raises(ValueError, match="duplicate case_id"):
        _adapt([_row(), _row()])


def test_empty_rows_adapt_to_empty_set():
    adapted = _adapt([])
    assert adapted.samples == ()
    assert adapted.skipped == {}


def test_non_list_rows_fail():
    with pytest.raises(ValueError, match="rows must be a list"):
        adapt_investigator_rows({"rows": []}, source=SOURCE)  # type: ignore[arg-type]


def test_source_is_required():
    with pytest.raises(TypeError):
        adapt_investigator_rows([_row()])  # type: ignore[call-arg]


def test_out_of_taxonomy_prediction_is_kept_and_counted():
    adapted = _adapt([_row(primary="mystery_cause")])
    assert adapted.samples[0]["predicted_cause"] == "mystery_cause"
    assert adapted.out_of_taxonomy_predicted == 1
    assert adapted.out_of_taxonomy_truth == 0


def test_out_of_taxonomy_truth_not_counted_for_skipped_rows():
    adapted = _adapt([{"case_id": "a", "truth": "mystery", "ai": "not-a-dict"}])
    assert adapted.samples == ()
    assert adapted.skipped == {"malformed_ai": 1}
    assert adapted.out_of_taxonomy_truth == 0


def test_all_emitted_samples_satisfy_tier_prediction_rule():
    rows = [
        _row(),
        _row(case_id="x2", primary=None),
        _row(case_id="x3", primary="pm_in_peak", truth="tool_down"),
    ]
    adapted = _adapt(rows)
    for sample in adapted.samples:
        assert set(sample) == {
            "sample_id",
            "tier",
            "predicted_cause",
            "true_cause",
            "confidence",
        }
        assert sample["confidence"] is None
        if sample["tier"] == "unknown":
            assert sample["predicted_cause"] is None
        else:
            assert isinstance(sample["predicted_cause"], str)


def test_real_v2_file_adapts_cleanly():
    path = REPO_ROOT / "results_pc" / "investigator_nightshift_v2.json"
    adapted = adapt_investigator_file(path)
    assert adapted.source == "investigator_nightshift_v2"
    assert adapted.shape == "legacy"
    assert len(adapted.samples) == 24
    assert adapted.skipped == {}
    assert adapted.system_answers_used == 0
    assert adapted.system_answer_sample_ids == ()
    assert len({s["sample_id"] for s in adapted.samples}) == 24
    assert all(s["tier"] == "attributed" for s in adapted.samples)
    assert all(
        s["true_cause"]
        in {
            "tool_down",
            "pm_in_peak",
            "release_burst",
            "setup_thrash",
            "batch_cap",
            "upstream_starvation",
        }
        for s in adapted.samples
    )


def test_real_v1_file_has_two_unknown_answers():
    path = REPO_ROOT / "results_pc" / "investigator_nightshift_v1.json"
    adapted = adapt_investigator_file(path)
    assert len(adapted.samples) == 24
    assert adapted.skipped == {}
    unknown = [s for s in adapted.samples if s["tier"] == "unknown"]
    assert len(unknown) == 2
    assert {s["sample_id"] for s in unknown} == {
        "investigator_nightshift_v1:tool_down-s1",
        "investigator_nightshift_v1:tool_down-s4",
    }


def test_real_files_pin_headline_counts():
    """The documented rates' numerators/denominators, as pure mapping facts.

    v2: 20 right / 4 wrong / 0 unknown of 24 -> misattribution 4/24.
    v1: 11 right / 11 wrong / 2 unknown of 24 -> misattribution 11/22.
    """
    for fname, right, wrong, unknown in (
        ("investigator_nightshift_v2.json", 20, 4, 0),
        ("investigator_nightshift_v1.json", 11, 11, 2),
    ):
        adapted = adapt_investigator_file(REPO_ROOT / "results_pc" / fname)
        got_right = sum(1 for s in adapted.samples if s["predicted_cause"] == s["true_cause"])
        got_wrong = sum(
            1
            for s in adapted.samples
            if s["predicted_cause"] is not None and s["predicted_cause"] != s["true_cause"]
        )
        got_unknown = sum(1 for s in adapted.samples if s["tier"] == "unknown")
        assert (got_right, got_wrong, got_unknown) == (right, wrong, unknown)


def test_adapter_validation_matches_quality_when_available():
    """Guard against contract drift: when quality/v0 is importable (#88
    merged), every emitted sample must pass the real AttributionSample,
    and the mirror validator must agree with it on adversarial dicts."""
    quality = pytest.importorskip("resilimes.explain.quality")
    from resilimes.insight.quality_adapter import _validate_sample

    for fname in ("investigator_nightshift_v1.json", "investigator_nightshift_v2.json"):
        adapted = adapt_investigator_file(REPO_ROOT / "results_pc" / fname)
        for sample in adapted.samples:
            quality.AttributionSample(**sample)

    good = {
        "sample_id": "x",
        "tier": "attributed",
        "predicted_cause": "tool_down",
        "true_cause": "tool_down",
        "confidence": None,
    }
    _validate_sample(good)
    quality.AttributionSample(**good)
    for bad in (
        {**good, "tier": "unknown"},
        {**good, "predicted_cause": None},
        {**good, "tier": "bogus"},
        {**good, "confidence": 1.5},
        {**good, "extra": 1},
    ):
        with pytest.raises(ValueError):
            _validate_sample(bad)
        with pytest.raises(ValidationError):
            quality.AttributionSample(**bad)


def test_file_without_rows_list_fails(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"summary": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected a JSON object with a 'rows' list"):
        adapt_investigator_file(bad)


def test_cli_adapts_file_and_writes_samples(tmp_path, capsys):
    src = REPO_ROOT / "results_pc" / "investigator_nightshift_v2.json"
    out = tmp_path / "samples.json"
    assert main([str(src), "--out", str(out)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["adapter_version"] == "adapter/v0"
    assert summary["samples"] == 24
    assert summary["skipped"] == {}
    assert summary["system_answer_sample_ids"] == []
    written = json.loads(out.read_text(encoding="utf-8"))
    assert len(written["samples"]) == 24
    assert written["samples"][0]["sample_id"].startswith("investigator_nightshift_v2:")
    assert written["summary"]["samples"] == 24
    assert written["summary"]["skipped"] == {}


def test_cli_missing_file_exits_nonzero(capsys):
    assert main(["/nonexistent/file.json"]) == 2


def test_cli_out_write_failure_exits_two(tmp_path, capsys):
    src = REPO_ROOT / "results_pc" / "investigator_nightshift_v2.json"
    assert main([str(src), "--out", str(tmp_path / "no-such-dir" / "samples.json")]) == 2
    assert "quality_adapter:" in capsys.readouterr().err


# --- evaluate() wiring (report/v0): adapt -> evaluate -> report. ---


def test_evaluate_adapted_rates_carry_denominators():
    """Four synthetic rows: 2 right, 1 wrong, 1 unknown, all truth known.

    misattribution 1/3 (unknown is not in its denominator), over-unknown
    1/4, unknown share 1/4; calibration empty by construction (no
    confidence anywhere), ECE None.
    """
    rows = [
        _row(case_id="c1", truth="tool_down", primary="tool_down"),
        _row(case_id="c2", truth="tool_down", primary="tool_down"),
        _row(case_id="c3", truth="tool_down", primary="release_burst"),
        _row(case_id="c4", truth="tool_down", primary=None, ai={"primary_cause": None}),
    ]
    # _row with primary=None still builds an ai dict with primary None; the
    # adapter treats a missing usable answer as unknown.
    report = evaluate_adapted(_adapt(rows))
    assert report.total_samples == 4
    assert report.truth_known == 4
    assert (report.misattribution.numerator, report.misattribution.denominator) == (1, 3)
    assert report.misattribution.value == pytest.approx(1 / 3)
    assert (report.over_unknown.numerator, report.over_unknown.denominator) == (1, 4)
    assert (report.unknown_share.numerator, report.unknown_share.denominator) == (1, 4)
    assert report.calibration_samples == 0
    assert report.expected_calibration_error is None


def test_evaluate_adapted_empty_set_has_none_rates():
    report = evaluate_adapted(_adapt([]))
    assert report.total_samples == 0
    assert report.misattribution.value is None
    assert report.misattribution.denominator == 0
    assert report.over_unknown.value is None
    assert report.unknown_share.value is None
    assert report.expected_calibration_error is None


def test_evaluate_adapted_does_not_mutate_the_adapted_set():
    adapted = _adapt([_row()])
    before = adapted.samples
    evaluate_adapted(adapted)
    assert adapted.samples == before


def test_evaluate_file_reproduces_first_measurement():
    """The documented first measurement, re-run through the real pipeline.

    Pins docs/QUALITY_ADAPTER.md: v2 misattribution 4/24, over-unknown
    0/24; v1 misattribution 11/22 (denominator 22, not 24: the 2 unknown
    rows are not in it), over-unknown 2/24; calibration 0 / ECE None on
    both (investigator emits no confidence).
    """
    _, v2 = evaluate_file(REPO_ROOT / "results_pc" / "investigator_nightshift_v2.json")
    assert v2.total_samples == 24
    assert (v2.misattribution.numerator, v2.misattribution.denominator) == (4, 24)
    assert (v2.over_unknown.numerator, v2.over_unknown.denominator) == (0, 24)
    assert v2.calibration_samples == 0
    assert v2.expected_calibration_error is None
    _, v1 = evaluate_file(REPO_ROOT / "results_pc" / "investigator_nightshift_v1.json")
    assert v1.total_samples == 24
    assert (v1.misattribution.numerator, v1.misattribution.denominator) == (11, 22)
    assert (v1.over_unknown.numerator, v1.over_unknown.denominator) == (2, 24)
    assert v1.calibration_samples == 0
    assert v1.expected_calibration_error is None


def test_evaluate_file_duplicate_case_id_fails(tmp_path):
    src = tmp_path / "dup.json"
    src.write_text(
        json.dumps({"rows": [_row(case_id="c1"), _row(case_id="c1", primary="release_burst")]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate case_id"):
        evaluate_file(src)


def test_cli_report_writes_quality_report(tmp_path, capsys):
    src = REPO_ROOT / "results_pc" / "investigator_nightshift_v2.json"
    report_path = tmp_path / "report.json"
    assert main([str(src), "--report", str(report_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["samples"] == 24
    assert summary["report"]["misattribution"] == {
        "numerator": 4,
        "denominator": 24,
        "value": pytest.approx(4 / 24),
    }
    assert summary["report"]["over_unknown"] == {
        "numerator": 0,
        "denominator": 24,
        "value": 0.0,
    }
    assert summary["report"]["calibration_samples"] == 0
    assert summary["report"]["expected_calibration_error"] is None
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["metrics_version"] == "quality/v0"
    assert written["adapter_version"] == "adapter/v0"
    assert written["report"]["total_samples"] == 24
    assert written["report"]["metrics_version"] == "quality/v0"
    assert written["report"]["misattribution"] == {
        "numerator": 4,
        "denominator": 24,
        "value": pytest.approx(4 / 24),
    }
    assert written["summary"]["samples"] == 24
    assert written["summary"]["skipped"] == {}


def test_cli_report_write_failure_exits_two(tmp_path):
    src = REPO_ROOT / "results_pc" / "investigator_nightshift_v2.json"
    assert main([str(src), "--report", str(tmp_path / "no-such-dir" / "report.json")]) == 2


def test_cli_out_and_report_together(tmp_path, capsys):
    src = REPO_ROOT / "results_pc" / "investigator_nightshift_v2.json"
    out = tmp_path / "samples.json"
    report_path = tmp_path / "report.json"
    assert main([str(src), "--out", str(out), "--report", str(report_path)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["samples"]) == 24
    assert json.loads(report_path.read_text(encoding="utf-8"))["report"]["total_samples"] == 24
