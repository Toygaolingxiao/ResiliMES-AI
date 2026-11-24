"""Default plan-mode KPI lock (F0 of epic #137).

Locks the published HARD_QTIME.md numbers for planning + hard Q-time on the
published book, seeds 1-3, 7 days. This is the regression rope for later
``priority/`` and ``decide()`` extractions: those moves must not change these
figures without an explicit doc + PR note.

Marked ``kpi_baseline`` so the default suite stays fast; CI runs this marker
in a dedicated job.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import pytest

# docs/HARD_QTIME.md — "Current default vs references", planning + hard.
EXPECTED_AVOIDABLE = {1: 29, 2: 29, 3: 13}
EXPECTED_AVOIDABLE_TOTAL = 71
EXPECTED_COMPLETED_MEAN = 486.7
EXPECTED_ON_TIME_PCT = 82.12
HORIZON_H = 168.0
SEEDS = (1, 2, 3)


def _one_seed(seed: int) -> dict[str, Any]:
    """Worker: one published-book plan+hard run. Env must be set before import paths."""
    os.environ.pop("RESILIMES_SCHED_MODE", None)
    os.environ["RESILIMES_STUDY_HORIZON_H"] = str(int(HORIZON_H))
    from resilimes.smt.fab import load_fab
    from resilimes.smt.qtime_study import _setup
    from resilimes.smt.simulate import run_policy

    fab = load_fab()
    plant, kwargs = _setup(fab, "published", seed, "resilimes")
    result = run_policy(plant, hard_qtime=True, **kwargs)
    miss = dict(result.qtime_miss_class or {})
    return {
        "seed": seed,
        "completed_routes": int(result.completed_routes),
        "on_time_pct": float(result.on_time_pct),
        "due_in_horizon": int(result.due_in_horizon),
        "avoidable": int(miss.get("avoidable", 0)),
        "plan_used": bool(result.plan_used),
        "hard_qtime": bool(result.hard_qtime),
    }


@pytest.mark.kpi_baseline
def test_plan_hard_published_kpi_matches_hard_qtime_doc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambient product default (unset RESILIMES_SCHED_MODE) must stay plan+hard."""
    monkeypatch.delenv("RESILIMES_SCHED_MODE", raising=False)
    monkeypatch.delenv("RESILIMES_HARD_QTIME", raising=False)

    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(_one_seed, seed): seed for seed in SEEDS}
        for fut in as_completed(futs):
            rows.append(fut.result())
    rows.sort(key=lambda row: int(row["seed"]))

    assert [row["seed"] for row in rows] == list(SEEDS)
    for row in rows:
        assert row["plan_used"] is True
        assert row["hard_qtime"] is True
        assert row["avoidable"] == EXPECTED_AVOIDABLE[int(row["seed"])]

    avoidable_total = sum(int(row["avoidable"]) for row in rows)
    completed_mean = round(sum(int(row["completed_routes"]) for row in rows) / len(rows), 1)
    due = sum(int(row["due_in_horizon"]) for row in rows)
    on_time_lots = sum(
        round(float(row["on_time_pct"]) * int(row["due_in_horizon"]) / 100.0) for row in rows
    )
    on_time_pct = round(100.0 * on_time_lots / due, 2) if due else 0.0

    assert avoidable_total == EXPECTED_AVOIDABLE_TOTAL
    assert completed_mean == EXPECTED_COMPLETED_MEAN
    assert on_time_pct == EXPECTED_ON_TIME_PCT
