"""ResiliTrace quality metrics v0.

The explain layer can say, for one lot, what it knows, what it inferred and
what it does not know. This module answers the next question: over an
evaluation set, how trustworthy is that behaviour? It computes three rates
that the project documents have promised but never implemented:

* misattribution rate: of the answers that named a cause and whose truth is
  known, how many named the wrong cause.
* over-unknown rate: of the samples whose truth is known (so an answer was
  possible in the evaluation), how many the system still answered unknown.
* confidence calibration: for answers that carried a confidence, do the
  confidences match the empirical accuracy (per-bin table plus ECE)?

Every rate is a ``Rate``: numerator, denominator and value. The denominator
is part of the result, never hidden, because this project's history shows
what a bare fraction hides ("1/12" was three different fractions). When a
denominator is zero the value is ``None``: not enough data. It is never
reported as 0.0, which would claim a measurement that was not made.

Truth here means evaluation truth: a cause the benchmark injected, or a
cause a reviewer established. A sample whose truth is not known
(``true_cause is None``) never enters a rate denominator.

Version rule: ``quality/v0``. Changing a denominator definition, a tier
rule or the bin edges is a new version, not an edit.
"""

from __future__ import annotations

from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resilimes.explain.schema import Tier

METRICS_VERSION: Literal["quality/v0"] = "quality/v0"

# Ten equal-width confidence bins: [0.0, 0.1), ..., [0.9, 1.0]. The last bin
# is closed on both ends so a confidence of exactly 1.0 has a home.
BIN_COUNT = 10


class AttributionSample(BaseModel):
    """One evaluated attribution: what the system said vs what is true."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_id: str
    tier: Tier
    predicted_cause: str | None = None
    true_cause: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _tier_matches_prediction(self) -> AttributionSample:
        if self.tier == "unknown" and self.predicted_cause is not None:
            raise ValueError(
                f"{self.sample_id}: an unknown answer cannot carry a predicted cause"
            )
        if self.tier != "unknown" and self.predicted_cause is None:
            raise ValueError(
                f"{self.sample_id}: a {self.tier} answer needs a predicted cause"
            )
        return self

    @property
    def answered(self) -> bool:
        return self.predicted_cause is not None

    @property
    def truth_known(self) -> bool:
        return self.true_cause is not None

    @property
    def correct(self) -> bool | None:
        """None when correctness cannot be judged for this sample."""
        if not self.answered or not self.truth_known:
            return None
        return self.predicted_cause == self.true_cause


class Rate(BaseModel):
    """A fraction with its denominator kept attached."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = None

    @model_validator(mode="after")
    def _value_matches_counts(self) -> Rate:
        if self.numerator > self.denominator:
            raise ValueError("numerator cannot exceed denominator")
        if self.denominator == 0:
            if self.value is not None:
                raise ValueError("a rate with denominator 0 has value None")
        elif self.value is None or abs(self.value - self.numerator / self.denominator) > 1e-9:
            raise ValueError("value must equal numerator / denominator")
        return self


def _rate(numerator: int, denominator: int) -> Rate:
    value = None if denominator == 0 else numerator / denominator
    return Rate(numerator=numerator, denominator=denominator, value=value)


class CalibrationBin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lower: float
    upper: float
    count: int = Field(ge=0)
    mean_confidence: float | None = None
    accuracy: float | None = None


class QualityReport(BaseModel):
    """The three promised rates over one evaluation set, with counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metrics_version: Literal["quality/v0"] = METRICS_VERSION
    total_samples: int = Field(ge=0)
    answered: int = Field(ge=0)
    unknown_answers: int = Field(ge=0)
    truth_known: int = Field(ge=0)
    misattribution: Rate
    over_unknown: Rate
    unknown_share: Rate
    calibration_samples: int = Field(ge=0)
    calibration_excluded_no_confidence: int = Field(ge=0)
    calibration_bins: tuple[CalibrationBin, ...] = ()
    expected_calibration_error: float | None = None


def _bin_index(confidence: float) -> int:
    return min(int(confidence * BIN_COUNT), BIN_COUNT - 1)


def evaluate(samples: Iterable[AttributionSample]) -> QualityReport:
    """Compute the quality/v0 report over an evaluation set.

    Pure function of its input: no I/O, no globals, samples are not mutated.
    """
    rows = list(samples)
    total = len(rows)
    answered_rows = [s for s in rows if s.answered]
    truth_rows = [s for s in rows if s.truth_known]

    judged = [s for s in answered_rows if s.truth_known]
    misattributed = sum(1 for s in judged if s.correct is False)
    over_unknown = sum(1 for s in truth_rows if not s.answered)

    calib_rows = [s for s in judged if s.confidence is not None]
    no_confidence = len(judged) - len(calib_rows)

    bins: list[CalibrationBin] = []
    ece = 0.0
    for idx in range(BIN_COUNT):
        members = [s for s in calib_rows if _bin_index(s.confidence) == idx]  # type: ignore[arg-type]
        lower = idx / BIN_COUNT
        upper = (idx + 1) / BIN_COUNT
        if not members:
            bins.append(CalibrationBin(lower=lower, upper=upper, count=0))
            continue
        mean_conf = sum(s.confidence for s in members) / len(members)  # type: ignore[arg-type]
        accuracy = sum(1 for s in members if s.correct) / len(members)
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(members),
                mean_confidence=mean_conf,
                accuracy=accuracy,
            )
        )
        if calib_rows:
            ece += (len(members) / len(calib_rows)) * abs(accuracy - mean_conf)

    return QualityReport(
        total_samples=total,
        answered=len(answered_rows),
        unknown_answers=total - len(answered_rows),
        truth_known=len(truth_rows),
        misattribution=_rate(misattributed, len(judged)),
        over_unknown=_rate(over_unknown, len(truth_rows)),
        unknown_share=_rate(total - len(answered_rows), total),
        calibration_samples=len(calib_rows),
        calibration_excluded_no_confidence=no_confidence,
        calibration_bins=tuple(bins),
        expected_calibration_error=ece if calib_rows else None,
    )
