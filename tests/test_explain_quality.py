"""Contract tests for quality metrics v0 (explain.quality).

The denominators are the contract. If one of these tests has to change,
the metrics version has to change too. See docs/QUALITY_METRICS.md.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resilimes.explain.quality import (
    METRICS_VERSION,
    AttributionSample,
    evaluate,
)


def _sample(**kw) -> AttributionSample:
    base = dict(sample_id="s", tier="attributed", predicted_cause="tool_down",
                true_cause="tool_down", confidence=None)
    base.update(kw)
    return AttributionSample(**base)


def test_empty_set_reports_no_data_not_zeros():
    report = evaluate([])
    assert report.metrics_version == METRICS_VERSION == "quality/v0"
    assert report.total_samples == 0
    assert report.misattribution.value is None
    assert report.misattribution.denominator == 0
    assert report.over_unknown.value is None
    assert report.unknown_share.value is None
    assert report.expected_calibration_error is None
    assert report.calibration_samples == 0
    assert len(report.calibration_bins) == 10
    assert all(b.count == 0 and b.accuracy is None for b in report.calibration_bins)


def test_misattribution_denominator_excludes_unknown_and_truthless():
    samples = [
        _sample(sample_id="right", predicted_cause="tool_down", true_cause="tool_down"),
        _sample(sample_id="wrong", predicted_cause="pm_in_peak", true_cause="tool_down"),
        _sample(sample_id="also-right", predicted_cause="batch_cap", true_cause="batch_cap"),
        # answered unknown: not in the misattribution denominator
        _sample(sample_id="silent", tier="unknown", predicted_cause=None, true_cause="tool_down"),
        # truth not known: not in the denominator either
        _sample(sample_id="unjudged", predicted_cause="tool_down", true_cause=None),
    ]
    report = evaluate(samples)
    assert report.misattribution.numerator == 1
    assert report.misattribution.denominator == 3
    assert report.misattribution.value == pytest.approx(1 / 3)


def test_over_unknown_denominator_is_truth_known():
    samples = [
        _sample(sample_id="a", predicted_cause="tool_down", true_cause="tool_down"),
        _sample(sample_id="b", predicted_cause="pm_in_peak", true_cause="tool_down"),
        _sample(sample_id="c", predicted_cause="batch_cap", true_cause="batch_cap"),
        _sample(sample_id="d", tier="unknown", predicted_cause=None, true_cause="tool_down"),
        # truth unknown: an unknown answer here is not over-unknown
        _sample(sample_id="e", tier="unknown", predicted_cause=None, true_cause=None),
    ]
    report = evaluate(samples)
    assert report.over_unknown.numerator == 1
    assert report.over_unknown.denominator == 4
    assert report.over_unknown.value == pytest.approx(0.25)
    assert report.unknown_answers == 2
    assert report.unknown_share.value == pytest.approx(2 / 5)


def test_tier_prediction_contradiction_is_rejected():
    with pytest.raises(ValidationError):
        _sample(tier="unknown", predicted_cause="tool_down")
    with pytest.raises(ValidationError):
        _sample(tier="attributed", predicted_cause=None)
    with pytest.raises(ValidationError):
        _sample(confidence=1.5)


def test_calibration_bins_and_ece_match_hand_computation():
    samples = [
        # bin [0.9, 1.0]: confidence 0.9, one right one wrong
        _sample(sample_id="c1", predicted_cause="tool_down", true_cause="tool_down", confidence=0.9),
        _sample(sample_id="c2", predicted_cause="pm_in_peak", true_cause="tool_down", confidence=0.9),
        # confidence exactly 1.0 lands in the last bin too
        _sample(sample_id="c3", predicted_cause="tool_down", true_cause="tool_down", confidence=1.0),
        # no confidence: excluded from calibration, counted apart
        _sample(sample_id="c4", predicted_cause="tool_down", true_cause="tool_down", confidence=None),
        # unknown answer with a confidence is not a calibration sample
        _sample(sample_id="c5", tier="unknown", predicted_cause=None, true_cause="tool_down", confidence=0.3),
    ]
    report = evaluate(samples)
    assert report.calibration_samples == 3
    assert report.calibration_excluded_no_confidence == 1
    last = report.calibration_bins[-1]
    assert last.count == 3
    assert last.mean_confidence == pytest.approx((0.9 + 0.9 + 1.0) / 3)
    assert last.accuracy == pytest.approx(2 / 3)
    expected_ece = abs(2 / 3 - (0.9 + 0.9 + 1.0) / 3)
    assert report.expected_calibration_error == pytest.approx(expected_ece)
    assert all(b.count == 0 for b in report.calibration_bins[:-1])


def test_calibration_spans_bins_and_weights_by_count():
    samples = [
        _sample(sample_id="lo", predicted_cause="tool_down", true_cause="tool_down", confidence=0.15),
        _sample(sample_id="hi", predicted_cause="pm_in_peak", true_cause="tool_down", confidence=0.85),
    ]
    report = evaluate(samples)
    low_bin = report.calibration_bins[1]
    high_bin = report.calibration_bins[8]
    assert (low_bin.count, low_bin.accuracy) == (1, 1.0)
    assert (high_bin.count, high_bin.accuracy) == (1, 0.0)
    expected = 0.5 * abs(1.0 - 0.15) + 0.5 * abs(0.0 - 0.85)
    assert report.expected_calibration_error == pytest.approx(expected)


def test_report_is_json_serializable_and_deterministic():
    samples = [_sample(sample_id="x", confidence=0.5)]
    first = evaluate(samples)
    second = evaluate(list(samples))
    assert first == second
    payload = first.model_dump(mode="json")
    assert payload["metrics_version"] == "quality/v0"
    assert payload["misattribution"] == {"numerator": 0, "denominator": 1, "value": 0.0}
