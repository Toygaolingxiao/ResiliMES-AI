"""Hard Q-time: on by default with the planning layer; off is main, on gates and expedites."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest

from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.hard_qtime import CAUSES, MISS_CLASSES
from resilimes.smt.simulate import (
    RunResult,
    default_hard_qtime,
    make_sim,
    pm_windows,
    run_policy,
    sample_downs,
)

HOURS = 12.0
SKIP = {
    "sim_s",
    "dispatch_p50_ms",
    "dispatch_p95_ms",
    "dispatch_busy_p50_ms",
    "dispatch_busy_p95_ms",
    "replan_tick_p50_ms",
    "replan_tick_p95_ms",
    "replan_tick_total_s",
}


@pytest.fixture(scope="module")
def fab() -> Fab:
    return load_fab()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESILIMES_HARD_QTIME", raising=False)


def _run(fab: Fab, policy: str, **kwargs: object) -> RunResult:
    horizon = HOURS * 3600.0
    return run_policy(
        fab,
        policy=policy,
        seed=1,
        horizon=horizon,
        downs=sample_downs(fab, 1, horizon),
        pm=pm_windows(fab, horizon),
        trace=False,
        record=True,
        **kwargs,  # type: ignore[arg-type]
    )


def _digest(result: RunResult) -> str:
    data = {key: value for key, value in asdict(result).items() if key not in SKIP}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@pytest.mark.parametrize("policy", ["resilimes", "edd"])
def test_off_is_main(fab: Fab, policy: str, monkeypatch: pytest.MonkeyPatch) -> None:
    default = _run(fab, policy)
    off = _run(fab, policy, hard_qtime=False)
    monkeypatch.setenv("RESILIMES_HARD_QTIME", "0")
    env_off = _run(fab, policy)
    assert default.hard_qtime == {}
    assert _digest(default) == _digest(off) == _digest(env_off)
    # Causes are read-only bookkeeping: one per missed dispatcher window.
    missed = sum(default.qtime_windows[key] for key in ("late", "held", "recleaned", "expired"))
    assert set(default.qtime_causes) == set(CAUSES)
    assert sum(default.qtime_causes.values()) == missed
    assert set(default.qtime_miss_class) == set(MISS_CLASSES)
    assert sum(default.qtime_miss_class.values()) == missed


@pytest.mark.parametrize("policy", ["resilimes", "edd"])
def test_on_gates_and_expedites(fab: Fab, policy: str, monkeypatch: pytest.MonkeyPatch) -> None:
    off = _run(fab, policy)
    on = _run(fab, policy, hard_qtime=True)
    monkeypatch.setenv("RESILIMES_HARD_QTIME", "1")
    env_on = _run(fab, policy)
    assert _digest(on) == _digest(env_on)
    stats = on.hard_qtime
    assert stats["gate_checks"] > 0
    assert stats["gate_blocks"] > 0
    assert _digest(on) != _digest(off)
    # Every miss is split into admitted / exempt starts with a cause.
    missed = sum(on.qtime_windows[key] for key in ("late", "held", "recleaned", "expired"))
    assert sum(stats["miss_causes"].values()) == missed
    assert stats["recovered"] + stats["unrecovered_at_horizon"] <= stats["expedited_lots"]


def test_segment_gate_and_intermediate_expedite(fab: Fab) -> None:
    """The kanban commits every measured step of a segment, and a lot at an
    intermediate step of an open window ranks like one at the target."""
    horizon = 6 * 3600.0
    sim = make_sim(
        fab,
        policy="edd",
        seed=1,
        horizon=horizon,
        downs=sample_downs(fab, 1, horizon),
        pm=pm_windows(fab, horizon),
        hard_qtime=True,
    )
    sim.run_until(horizon)
    hq = sim.hq
    assert hq is not None
    entries = [
        (lot, step, target)
        for fam in hq.committed
        for (lot, step), (_work, target, _latest, _need) in fam.items()
    ]
    assert entries
    assert any(step < target for _lot, step, target in entries)
    for lot, step, target in entries:
        assert sim.step[lot] <= step <= target
    middle = [lot for lot, step, target in entries if sim.step[lot] < target and sim.in_window(lot)]
    assert middle
    for lot in middle:
        assert sim.expedite_key(lot, horizon)[1] in (0.0, 2.0)


def test_default_on_with_planning_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard Q-time is the default with the plan; RESILIMES_HARD_QTIME=0 turns it off."""
    assert default_hard_qtime("resilimes", "plan") is True
    assert default_hard_qtime("resilimes", "strict_qtime") is False
    assert default_hard_qtime("edd", "plan") is False
    monkeypatch.setenv("RESILIMES_HARD_QTIME", "0")
    assert default_hard_qtime("resilimes", "plan") is False
    monkeypatch.setenv("RESILIMES_HARD_QTIME", "1")
    assert default_hard_qtime("edd", "strict_qtime") is True


def test_plan_mode_sim_gates_by_default(fab: Fab, monkeypatch: pytest.MonkeyPatch) -> None:
    horizon = 3_600.0
    kwargs = dict(
        policy="resilimes",
        seed=1,
        horizon=horizon,
        downs=sample_downs(fab, 1, horizon),
        pm=pm_windows(fab, horizon),
        sched_mode="plan",
    )
    assert make_sim(fab, **kwargs).hq is not None  # type: ignore[arg-type]
    assert make_sim(fab, hard_qtime=False, **kwargs).hq is None  # type: ignore[arg-type]
    monkeypatch.setenv("RESILIMES_HARD_QTIME", "0")
    assert make_sim(fab, **kwargs).hq is None  # type: ignore[arg-type]
    edd = dict(kwargs, policy="edd")
    monkeypatch.delenv("RESILIMES_HARD_QTIME")
    assert make_sim(fab, **edd).hq is None  # type: ignore[arg-type]


def test_report_edd_is_infeasible_reference() -> None:
    """EDD shows only as an industry reference with its avoidable count."""
    from resilimes.smt.hard_qtime_study import report

    def row(policy: str, arm: str, avoid: int, hq: dict | None) -> dict:
        return {
            "policy": policy,
            "arm": arm,
            "due_in_horizon": 10,
            "on_time": 9,
            "completed_routes": 100,
            "q_met": 90,
            "q_scored": 100,
            "q_steady_met": 90,
            "q_steady_missed": 10,
            "weighted_tardiness_min": 1.0,
            "qtime_causes": {},
            "q_inherited_missed": 0,
            "hard_qtime": hq,
            "qtime_miss_class": {"avoidable": avoid},
        }

    hq = {
        "gate_blocks": 1,
        "expedited_lots": 0,
        "recovered": 0,
        "recover_mean_min": None,
        "recover_p90_min": None,
    }
    text = report([row("edd", "H0", 7, None), row("planning", "H1", 0, hq)])
    head = text.splitlines()[0]
    assert "edd (off): industry reference (infeasible: 7 avoidable Q-time violations)" in head
    assert head.index("planning + hard") < head.index("edd")
    assert "Among Q-time-feasible configurations, planning + hard" in text
