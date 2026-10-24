"""PED risk stays finite for lots far past their CQT window (7 d runs overflowed)."""

from __future__ import annotations

import math

import pytest

from resilimes.kernel.score import PED_EXP_CAP, dispatch_score, ped_risk, tiered_key

K = 6.0  # the k the SMT simulator uses
LIMIT = 3600.0


def test_unchanged_inside_and_just_past_the_window() -> None:
    for remaining in (3000.0, 1800.0, 0.0, -3600.0, -50 * LIMIT):
        ratio = remaining / LIMIT
        assert ped_risk(remaining, LIMIT, K) == math.exp(K * (1.0 - ratio)) - 1.0
    assert ped_risk(LIMIT, LIMIT, K) == 0.0
    assert ped_risk(None, LIMIT, K) == 0.0
    assert ped_risk(100.0, 0.0, K) == 0.0


@pytest.mark.parametrize("windows_late", [117.0, 118.0, 1e3, 1e6, 1e300])
def test_far_past_window_saturates_without_overflow(windows_late: float) -> None:
    # Before the fix: exp(6 * (1 + 118)) raised OverflowError.
    risk = ped_risk(-windows_late * LIMIT, LIMIT, K)
    assert math.isfinite(risk)
    assert risk == pytest.approx(math.exp(PED_EXP_CAP) - 1.0)


def test_monotone_and_usable_in_keys_and_scores() -> None:
    values = [ped_risk(-w * LIMIT, LIMIT, K) for w in (0, 1, 10, 100, 116, 117, 1e4)]
    assert values == sorted(values)
    late = ped_risk(-1e6 * LIMIT, LIMIT, K)
    key = tiered_key(order_class="normal", slack_sec=100.0, setup_sec=0.0, ped=late)
    assert all(not math.isnan(part) for part in key)
    assert math.isfinite(dispatch_score(dpi=1.0, setup_sec=0.0, ped=late))


def test_infinite_or_nan_remaining_does_not_raise() -> None:
    assert math.isfinite(ped_risk(-math.inf, LIMIT, K))
    assert ped_risk(math.inf, LIMIT, K) == 0.0
    assert math.isfinite(ped_risk(math.nan, LIMIT, K))
