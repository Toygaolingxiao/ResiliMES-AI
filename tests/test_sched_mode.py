"""Default scheduling mode: the planning layer with hard Q-time; strict Q-time is the switch."""

from __future__ import annotations

from typing import Any

import pytest

from resilimes.smt.fab import load_fab
from resilimes.smt.simulate import (
    DEFAULT_SCHED_MODE,
    auto_plan,
    default_sched_mode,
    make_sim,
    pm_windows,
    run_policy,
    sample_downs,
)

HORIZON = 3.0 * 3600.0


def _kwargs(policy: str) -> dict[str, Any]:
    fab = load_fab()
    return {
        "policy": policy,
        "seed": 1,
        "horizon": HORIZON,
        "downs": sample_downs(fab, 1, HORIZON),
        "pm": pm_windows(fab, HORIZON),
        "trace": False,
    }


def test_default_mode_is_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESILIMES_SCHED_MODE", raising=False)
    assert DEFAULT_SCHED_MODE == "plan"
    assert default_sched_mode() == "plan"
    monkeypatch.setenv("RESILIMES_SCHED_MODE", "strict_qtime")
    assert default_sched_mode() == "strict_qtime"
    monkeypatch.setenv("RESILIMES_SCHED_MODE", "nope")
    with pytest.raises(ValueError):
        default_sched_mode()


def test_default_resilimes_run_uses_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESILIMES_SCHED_MODE", raising=False)
    fab = load_fab()
    sim = make_sim(fab, **_kwargs("resilimes"))
    assert sim.plan is not None
    assert sim.position_wait
    assert sim.fix2 and sim.fix3 and not sim.fix1
    assert sim.plan is auto_plan(fab)
    assert sim.hq is not None  # hard Q-time comes with the plan


def test_strict_qtime_and_baselines_run_without_a_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESILIMES_SCHED_MODE", raising=False)
    fab = load_fab()
    strict = make_sim(fab, sched_mode="strict_qtime", **_kwargs("resilimes"))
    assert strict.plan is None and strict.fix2 and strict.hq is None
    assert make_sim(fab, **_kwargs("edd")).plan is None
    with pytest.raises(ValueError):
        make_sim(fab, sched_mode="nope", **_kwargs("resilimes"))


def test_default_equals_explicit_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESILIMES_SCHED_MODE", raising=False)
    fab = load_fab()
    default = run_policy(fab, **_kwargs("resilimes"))
    explicit = run_policy(
        fab,
        plan=auto_plan(fab),
        sched_mode="strict_qtime",
        hard_qtime=True,
        **_kwargs("resilimes"),
    )
    assert default.plan_used and explicit.plan_used
    assert default.hard_qtime and default.hard_qtime == explicit.hard_qtime
    assert default.completed_routes == explicit.completed_routes
    assert default.on_time_pct == explicit.on_time_pct
    assert default.qtime_violations == explicit.qtime_violations
    assert default.deviations == explicit.deviations
