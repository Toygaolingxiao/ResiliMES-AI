"""Digital twin forks: deterministic, common futures, and no peeking at the true future."""

from __future__ import annotations

import pickle
from typing import Any

from resilimes.agents.shift_lead import RuleDefault, ShiftLead
from resilimes.smt.exceptions import Lever
from resilimes.smt.fab import load_fab
from resilimes.smt.qtime_study import _setup
from resilimes.smt.simulate import _DOWN_START, make_sim
from resilimes.smt.twin import Twin, TwinConfig, resample_downs, run_fork, snapshot

FORK_AT = 2 * 3600.0
AHEAD = 2 * 3600.0
_CACHE: dict[str, Any] = {}


class _Capture(ShiftLead):
    """Takes one snapshot inside the first tick at or after FORK_AT."""

    def __init__(self) -> None:
        super().__init__(RuleDefault("en"))
        self.blob: bytes | None = None
        self.at = -1.0

    def on_tick(self, sim: Any, moment: float) -> None:
        super().on_tick(sim, moment)
        if self.blob is None and moment >= FORK_AT:
            self.blob = snapshot(sim)
            self.at = moment


def _captured() -> tuple[Any, bytes, float]:
    if "blob" not in _CACHE:
        import os

        os.environ["RESILIMES_STUDY_HORIZON_H"] = "6"
        fab = load_fab()
        plant, kw = _setup(fab, "published", 9, "resilimes")
        lead = _Capture()
        sim = make_sim(plant, shift_lead=lead, **kw)
        sim.run_until(FORK_AT + 1.0)
        assert lead.blob is not None
        _CACHE.update(plant=plant, blob=lead.blob, at=lead.at)
        del os.environ["RESILIMES_STUDY_HORIZON_H"]
    return _CACHE["plant"], _CACHE["blob"], _CACHE["at"]


def _with_fake_future(blob: bytes, plant: Any, at: float) -> bytes:
    """The same snapshot, but the TRUE future now has a long outage on every tool."""
    sim, levers = pickle.loads(blob)
    sim.fab = plant
    for tool in range(len(sim.downs)):
        span = (at + 600.0, at + 3 * 3600.0)
        sim.downs[tool] = sorted([*sim.downs[tool], span])
        sim.push(span[0], _DOWN_START, tool)
    sim.fab = None
    return pickle.dumps((sim, levers))


def test_snapshot_leaves_the_sim_running() -> None:
    _plant, blob, at = _captured()
    sim, levers = pickle.loads(blob)
    assert sim.fab is None and sim.lead is None
    assert set(levers) == {"prio", "pins", "batch"}
    assert at >= FORK_AT


def test_fork_is_deterministic() -> None:
    plant, blob, at = _captured()
    one = run_fork(blob, plant, [], at, 0, AHEAD)
    two = run_fork(blob, plant, [], at, 0, AHEAD)
    one.sim_s = two.sim_s = 0.0
    assert one == two
    assert one.moves > 0


def test_forks_do_not_see_the_true_future() -> None:
    plant, blob, at = _captured()
    poisoned = _with_fake_future(blob, plant, at)
    for k in range(2):
        clean = run_fork(blob, plant, [], at, k, AHEAD)
        dirty = run_fork(poisoned, plant, [], at, k, AHEAD)
        clean.sim_s = dirty.sim_s = 0.0
        assert clean == dirty, "a change to the true future leaked into a fork"


def test_resampled_downs_replace_the_future_only() -> None:
    plant, blob, at = _captured()
    truth, _ = pickle.loads(blob)
    truth.fab = plant
    past = [[span for span in spans if span[0] <= at] for spans in truth.downs]
    future_true = {
        (tool, span) for tool, spans in enumerate(truth.downs) for span in spans if span[0] > at
    }
    fork, _ = pickle.loads(blob)
    fork.fab = plant
    resample_downs(fork, at, 0)
    for tool, spans in enumerate(fork.downs):
        assert [span for span in spans if span[0] <= at] == past[tool]
    future_fork = {
        (tool, span) for tool, spans in enumerate(fork.downs) for span in spans if span[0] > at
    }
    assert future_fork and not (future_fork & future_true)
    heap_downs = sorted((e[3], e[0]) for e in fork.heap if e[2] == _DOWN_START)
    expected = sorted((tool, span[0]) for tool, span in future_fork if span[0] <= fork.horizon)
    assert heap_downs == expected
    other, _ = pickle.loads(blob)
    other.fab = plant
    resample_downs(other, at, 1)
    assert other.downs != fork.downs


def test_levers_change_the_fork() -> None:
    plant, blob, at = _captured()
    sim, _ = pickle.loads(blob)
    fam = max(range(len(sim.queues)), key=lambda f: len(sim.queues[f]))
    lots = list(dict.fromkeys(sim.queues[fam]))[::-1][:10]
    prio = {(lot, sim.step[lot]): -1.0 - i * 1e-3 for i, lot in enumerate(lots)}
    lever = Lever("prio", prio=prio, until=at + 3600.0)
    base = run_fork(blob, plant, [], at, 0, AHEAD)
    boosted = run_fork(blob, plant, [lever], at, 0, AHEAD)
    base.sim_s = boosted.sim_s = 0.0
    assert base != boosted


def test_spawn_pool_matches_serial() -> None:
    plant, blob, at = _captured()
    sim, _ = pickle.loads(blob)
    sim.fab = plant
    plans: dict[str, list[Lever]] = {"A": []}
    serial = Twin(plant, TwinConfig(horizon_sec=AHEAD, futures=2, workers=0))
    pooled = Twin(plant, TwinConfig(horizon_sec=AHEAD, futures=2, workers=2))
    try:
        sim.lead = None
        sim.progress = None
        sim.events = []
        sim.samples = []
        sim.busy_samples = []
        one = serial.evaluate(sim, plans, at)
        two = pooled.evaluate(sim, plans, at)
    finally:
        pooled.close()
    assert one["A"].summary() == two["A"].summary()
