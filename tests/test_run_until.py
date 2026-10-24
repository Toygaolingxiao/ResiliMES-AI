"""``_Sim.run_until``: stopping and resuming is the same run as ``run()``."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

import pytest

from resilimes.agents.shift_lead import ShiftLead, build_decider
from resilimes.smt.fab import load_fab
from resilimes.smt.qtime_study import _setup
from resilimes.smt.simulate import _Sim, make_sim

_FAB: list[Any] = []


def _fab() -> Any:
    if not _FAB:
        _FAB.append(load_fab())
    return _FAB[0]


def _scrub(value: Any) -> Any:
    """Drop wall-clock fields; everything else must match exactly."""
    if isinstance(value, dict):
        return {
            key: _scrub(item) for key, item in value.items() if not str(key).endswith(("_ms", "_s"))
        }
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def _sim(book: str, lead: str | None) -> _Sim:
    plant, kw = _setup(_fab(), book, 1, "resilimes")
    shift_lead = ShiftLead(build_decider(lead, lang="en")) if lead else None
    return make_sim(plant, shift_lead=shift_lead, **kw)


def _digest(sim: _Sim, elapsed: float) -> str:
    result = asdict(sim.finish(elapsed))
    return json.dumps(_scrub(result), sort_keys=True, default=str)


@pytest.mark.parametrize("lead", [None, "heuristic"])
def test_run_until_in_chunks_matches_run(monkeypatch: pytest.MonkeyPatch, lead: str | None) -> None:
    monkeypatch.setenv("RESILIMES_STUDY_HORIZON_H", "6")
    whole = _sim("published", lead)
    one = json.dumps(_scrub(asdict(whole.run())), sort_keys=True, default=str)
    chunked = _sim("published", lead)
    chunked.start()
    stops = [1234.5, 3600.0, 3600.0, 7777.0, 15_000.0]
    for stop in stops:
        chunked.run_until(stop)
        assert chunked.clock <= stop
        assert not chunked.heap or chunked.heap[0][0] > stop
    chunked.run_until(chunked.horizon + 10_000.0)
    assert _digest(chunked, time.perf_counter() - chunked._started_at) == one
    assert chunked.steps == whole.steps


def test_start_twice_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIMES_STUDY_HORIZON_H", "1")
    sim = _sim("published", None)
    sim.start()
    with pytest.raises(RuntimeError):
        sim.start()


def test_run_until_starts_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIMES_STUDY_HORIZON_H", "1")
    sim = _sim("published", None)
    sim.run_until(600.0)
    assert sim._started_at >= 0.0
    assert 0.0 < sim.clock <= 600.0
