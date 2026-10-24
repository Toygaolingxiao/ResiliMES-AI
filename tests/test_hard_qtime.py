"""Hard Q-time (default off): off is main, on gates origin starts and expedites misses."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest

from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.hard_qtime import CAUSES
from resilimes.smt.simulate import RunResult, pm_windows, run_policy, sample_downs

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
