"""Digital twin for the shift lead: fork the running simulator, try plans ahead.

At an escalated exception the shift lead stops the world at ``t`` (inside the
scheduling tick), copies the simulator and plays each candidate plan, plus the
rule default, ``horizon_sec`` ahead over ``futures`` sampled futures.

No oracle. The copy keeps everything the floor knows at ``t``: WIP, queues,
running pieces, PM calendar, the lot's Q-time clocks, the active shift-lead
levers and the repair ETA of tools that are down now (the breakdown exception
already reports that ETA). Every breakdown that has not started yet is
removed from the copy, both from ``downs`` and from the event heap, and
replaced by a fresh draw from the same MTTF/MTTR distributions with a seed of
its own (``seed``, ``t``, ``k``). Future ``k`` is the same draw for every plan
(common random numbers), so plans are compared on the same futures. The true
future never enters a fork; ``tests/test_twin.py`` checks that.

Forks run in a ``spawn`` process pool (Windows-safe; the plant is sent once per
worker by the initializer) or serially when ``workers == 0``. Every function a
worker runs is module level.
"""

from __future__ import annotations

import hashlib
import heapq
import math
import multiprocessing
import pickle
import random
import time
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from resilimes.agents.shift_lead import RuleDefault, ShiftLead
from resilimes.smt.exceptions import Lever, Option
from resilimes.smt.simulate import _DOWN_START, _MISSED

# Attributes left out of a snapshot: live hooks, the plant (shared, read-only),
# and logs a fork does not need.
_DETACH = ("lead", "progress", "fab", "events", "samples", "busy_samples")


@dataclass(frozen=True)
class TwinConfig:
    horizon_sec: float = 8 * 3600.0
    futures: int = 3
    workers: int = 0  # 0 = serial in this process


@dataclass
class ForkKpis:
    """Outcome of one fork over [t, t + horizon]; lower is better except on_time."""

    wt_min: float  # value-weighted tardiness accrued inside the window
    late_lots: int  # lots due inside the window that missed the due date
    on_time: int  # lots due inside the window that finished on time
    due: int
    qviol: int  # Q-time violations inside the window
    qmissed: int  # Q-time windows closed missed (late/held/recleaned/expired)
    hot_late: int  # hot/VIP lots due inside the window that missed
    moves: int  # steps completed inside the window
    sim_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanScore:
    """A plan's forks, one per future, and their means."""

    plan_id: str
    runs: list[ForkKpis] = field(default_factory=list)

    def mean(self, key: str) -> float:
        values = [float(getattr(run, key)) for run in self.runs]
        return sum(values) / len(values) if values else math.inf

    def summary(self) -> dict[str, float]:
        keys = ("wt_min", "late_lots", "on_time", "qviol", "qmissed", "hot_late", "moves")
        return {key: round(self.mean(key), 2) for key in keys}


class ForkLead(ShiftLead):
    """Lever state only: keeps the levers active at ``t``, detects nothing."""

    def __init__(self) -> None:
        super().__init__(RuleDefault("en"))

    def on_tick(self, sim: Any, moment: float) -> None:
        self.sim = sim
        self._prio = {key: row for key, row in self._prio.items() if moment < row[1]}
        self._pins = {lot: until for lot, until in self._pins.items() if moment < until}
        self._batch = {key: until for key, until in self._batch.items() if moment < until}


def lever_state(lead: Any) -> dict[str, Any]:
    if lead is None:
        return {"prio": {}, "pins": {}, "batch": {}}
    return {"prio": dict(lead._prio), "pins": dict(lead._pins), "batch": dict(lead._batch)}


def snapshot(sim: Any) -> bytes:
    """Pickle the simulator without its hooks, plant and logs; ``sim`` is unchanged."""
    saved = {name: getattr(sim, name) for name in _DETACH}
    try:
        sim.lead = None
        sim.progress = None
        sim.fab = None
        sim.events = []
        sim.samples = []
        sim.busy_samples = []
        blob = pickle.dumps((sim, lever_state(saved["lead"])), protocol=pickle.HIGHEST_PROTOCOL)
    finally:
        for name, value in saved.items():
            setattr(sim, name, value)
    return blob


def future_seed(seed: int, moment: float, k: int) -> int:
    text = f"twin:{seed}:{round(moment)}:{k}"
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def resample_downs(sim: Any, moment: float, k: int) -> None:
    """Replace every breakdown that starts after ``moment`` with a fresh draw.

    Spans that started at or before ``moment`` stay (a tool down now keeps its
    reported repair ETA). From ``moment`` (or the end of the current repair)
    each tool gets a new exponential MTTF/MTTR clock, so the fork cannot know
    when the real fab breaks next.
    """
    fab = sim.fab
    rng = random.Random(future_seed(int(sim.seed), moment, k))
    horizon = float(sim.horizon)
    new_downs: list[list[tuple[float, float]]] = []
    for tool, spans in enumerate(sim.downs):
        kept = [span for span in spans if span[0] <= moment]
        group = fab.families[fab.tool_family[tool]].group
        mttf = fab.down_mttf.get(group)
        mttr = fab.down_mttr.get(group)
        if mttf and mttr and mttf > 0 and mttr > 0:
            clock = max([moment, *(end for _start, end in kept)])
            clock += rng.expovariate(1.0 / mttf)
            while clock < horizon:
                repair = rng.expovariate(1.0 / mttr)
                kept.append((clock, clock + repair))
                clock += repair + rng.expovariate(1.0 / mttf)
        kept.sort()
        new_downs.append(kept)
    sim.downs = new_downs
    sim.heap = [entry for entry in sim.heap if entry[2] != _DOWN_START]
    heapq.heapify(sim.heap)
    for tool, spans in enumerate(new_downs):
        for start_at, _end_at in spans:
            if start_at > moment:
                sim.push(start_at, _DOWN_START, tool)


def apply_levers(lead: ShiftLead, sim: Any, levers: list[Lever], moment: float) -> None:
    for index, lever in enumerate(levers):
        if lever.kind != "none":
            lead.apply(sim, None, Option(f"L{index}", "", lever), moment)  # type: ignore[arg-type]


def fork_kpis(sim: Any, start: dict[str, Any], t0: float, end: float) -> ForkKpis:
    wt = 0.0
    late = on_time = due_n = hot_late = 0
    for lot in range(sim.n):
        due = sim.due[lot]
        done = sim.finished_at[lot]
        finish = done if done >= 0 else end
        lo = max(due, t0)
        hi = min(finish, end)
        if hi > lo:
            wt += sim.value[lot] * (hi - lo) / 60.0
        if t0 < due <= end:
            due_n += 1
            if 0 <= done <= due:
                on_time += 1
            else:
                late += 1
                if sim.tier(lot) < 2:
                    hot_late += 1
    missed = sum(sim.qout[key] for key in _MISSED)
    return ForkKpis(
        wt_min=round(wt, 1),
        late_lots=late,
        on_time=on_time,
        due=due_n,
        qviol=sim.violations - start["violations"],
        qmissed=missed - start["missed"],
        hot_late=hot_late,
        moves=sim.steps_done - start["moves"],
    )


def run_fork(
    blob: bytes, fab: Any, levers: list[Lever], moment: float, k: int, horizon_sec: float
) -> ForkKpis:
    """Restore a snapshot, apply ``levers``, finish the tick, run ahead."""
    started = time.perf_counter()
    sim, levers_now = pickle.loads(blob)
    sim.fab = fab
    sim.record = False
    lead = ForkLead()
    lead._prio = levers_now["prio"]
    lead._pins = levers_now["pins"]
    lead._batch = levers_now["batch"]
    lead.sim = sim
    sim.lead = lead
    resample_downs(sim, moment, k)
    apply_levers(lead, sim, levers, moment)
    start = {
        "violations": sim.violations,
        "missed": sum(sim.qout[key] for key in _MISSED),
        "moves": sim.steps_done,
    }
    sim.tick_rest(moment, time.perf_counter())
    end = min(moment + horizon_sec, float(sim.horizon))
    sim.run_until(end)
    kpis = fork_kpis(sim, start, moment, end)
    kpis.sim_s = round(time.perf_counter() - started, 3)
    return kpis


# ------------------------------------------------------------------ pool

_WORKER_FAB: list[Any] = []


def _init_worker(fab: Any) -> None:
    _WORKER_FAB.clear()
    _WORKER_FAB.append(fab)


def _pool_fork(args: tuple[bytes, list[Lever], float, int, float]) -> ForkKpis:
    blob, levers, moment, k, horizon_sec = args
    return run_fork(blob, _WORKER_FAB[0], levers, moment, k, horizon_sec)


class Twin:
    """Evaluates plans at an exception. One per run; ``close()`` ends the pool."""

    def __init__(self, fab: Any, config: TwinConfig | None = None) -> None:
        self.fab = fab
        self.config = config or TwinConfig()
        self._pool: Executor | None = None
        self.forks = 0
        self.wall_s = 0.0

    def _executor(self) -> Executor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=self.config.workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_init_worker,
                initargs=(self.fab,),
            )
        return self._pool

    def evaluate(
        self, sim: Any, plans: dict[str, list[Lever]], moment: float
    ) -> dict[str, PlanScore]:
        started = time.perf_counter()
        blob = snapshot(sim)
        cfg = self.config
        jobs = [
            (plan_id, k, (blob, levers, moment, k, cfg.horizon_sec))
            for plan_id, levers in plans.items()
            for k in range(cfg.futures)
        ]
        scores = {plan_id: PlanScore(plan_id) for plan_id in plans}
        if cfg.workers > 0:
            results = list(self._executor().map(_pool_fork, [job[2] for job in jobs]))
        else:
            results = [run_fork(blob, self.fab, *job[2][1:]) for job in jobs]
        for (plan_id, _k, _args), kpis in zip(jobs, results, strict=True):
            scores[plan_id].runs.append(kpis)
        self.forks += len(jobs)
        self.wall_s += time.perf_counter() - started
        return scores

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None
