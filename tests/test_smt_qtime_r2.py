"""Q-time r2: window buckets, deadline event, batching, shortlist, urgency, reservation."""

from __future__ import annotations

from tests.test_smt_invariants import _two_family_fab

from resilimes.smt.fab import inherited_windows, load_fab
from resilimes.smt.invariants import check_trace
from resilimes.smt.qtime_kpi import bucket_counts, qtime_buckets
from resilimes.smt.simulate import run_policy

NO_DOWNS: list[list[tuple[float, float]]] = [[], []]


def _run(fab, policy="edd", horizon=5000.0, **kwargs):
    return run_policy(
        fab,
        policy=policy,
        seed=1,
        horizon=horizon,
        downs=NO_DOWNS,
        pm=NO_DOWNS,
        record=True,
        **kwargs,
    )


# Fix 6: reporting -----------------------------------------------------------


def test_inherited_window_is_counted_apart_from_dispatcher_windows() -> None:
    # L_B sits at B (inside the A->B span) at t=0: an inherited window with the
    # full 899 s limit, met at 0 s. L_AB opens a dispatcher window at 100 s and
    # starts B at 1180 s, late.
    fab = _two_family_fab(cqt_limit=899.0)
    assert inherited_windows(fab) == [(1, 0, 1, 899.0)]
    result = _run(fab)
    assert result.qtime_inherited["met"] == 1
    assert result.qtime_inherited_windows == 1
    assert result.qtime_windows["late"] == 1
    assert result.qtime_violations == 1
    assert result.qtime_rate_pct == 0.0
    assert check_trace(fab, result, downs=NO_DOWNS, pm=NO_DOWNS)["total"] == 0


def test_true_rate_counts_every_missed_bucket() -> None:
    # 2692 met of 3108 scored windows (the PR #18 total; the split of the 416
    # misses here is illustrative). met / (met + late) overstates the rate.
    body = bucket_counts({"met": 2692, "late": 190, "recleaned": 36, "expired": 190})
    assert body["scored"] == 3108
    assert body["rate_pct"] == 86.6
    assert round(100 * 2692 / (2692 + 190), 1) == 93.4
    held = bucket_counts({"met": 1, "late": 1, "held": 2})
    assert held["started_late"] == 3 and held["rate_pct"] == 25.0


def test_api_block_reports_four_buckets_and_inherited() -> None:
    result = _run(_two_family_fab(cqt_limit=899.0))
    body = qtime_buckets(result)
    for key in ("met", "started_late", "recleaned", "open_expired", "rate_pct"):
        assert key in body
    assert body["inherited"]["met"] == 1


def test_full_fab_has_433_inherited_windows() -> None:
    assert len(inherited_windows(load_fab())) == 433
