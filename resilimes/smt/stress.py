"""Litho stress: every ``Litho_FE_92`` scanner down for 2 hours in the busy window.

``python -m resilimes.smt.stress`` runs the stress book (published dues,
seeds 1-5, every policy) with a stall audit and prints one row per run.

The stall audit samples the live simulator every ``SAMPLE_SEC``. At each
sample, every tool that is up, not in PM, holds nothing and is not reserved
is asked what it would start now (``choose``, side effects undone). A tool
that has a start ready but sits idle is checked against the event heap. With
no pending event for that tool it is a hard stall: a lost wake-up, the
starvation the stress test looks for (nothing would ever start it). With a
pending wake-up it is a late start: a batch furnace waiting on an upstream
lot that will no longer come in time (the "no arrivals" rule turned true
after the wait was set); the delay is bounded by the pending wake and is
reported separately as ``late_*``. A waiting lot that no tool of its family
may ever start (``eligible`` false everywhere, and its pinned scanner is not
in the family) is stranded: starvation without an idle-tool symptom. Lots held by a rule (batch wait, PM
avoidance, the Q-time downstream gate) are not stalls because ``choose``
returns nothing for them. It also records WIP movement: steps finished per
hour and the queue of the stressed family; a 5-minute sample after the first
hour with no step finished anywhere in the fab counts as frozen WIP.

Works against any tree that has ``resilimes.smt.simulate._Sim`` (the audit
patches the module in the worker process), so the same audit runs on main.
"""

from __future__ import annotations

import heapq
import json
import os
import sys
from multiprocessing import get_context
from typing import Any

from resilimes.smt import simulate as sim_mod
from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.scenarios import SEEDS, STUDY_HORIZON_SEC
from resilimes.smt.simulate import pm_windows, run_policy, sample_downs

POLICIES = ("resilimes", "edd", "fifo", "cr", "smt_rule")
STRESS_HOURS = 2.0
# Busy window: the 2-hour window (hour aligned) with the deepest
# Litho_FE_92 queue in the EDD seed-1 published run on main 641d988, measured
# once with ``busy_window`` before any stress run: 0-2 h (the snapshot WIP;
# the same window also has the most Litho_FE_92 starts). Not chosen per
# policy. A second outage at 24-26 h checks a mid-run recovery.
STRESS_START_SEC = 0.0
STRESS_STARTS = (STRESS_START_SEC, 24 * 3600.0)
SAMPLE_SEC = 300.0
# Heap kinds whose 4th field is a tool (done, down start, down end, wake).
_TOOL_EVENTS = (sim_mod._DONE, sim_mod._DOWN_START, sim_mod._DOWN_END, sim_mod._WAKE)


def stress_downs(fab: Fab, seed: int, horizon: float, start: float = STRESS_START_SEC) -> Any:
    """Seeded MTTF/MTTR draws plus all tools of the focus litho family down 2 h."""
    downs = sample_downs(fab, seed, horizon)
    family = fab.families[fab.focus_family]
    for tool in range(family.tool0, family.tool0 + family.tools):
        downs[tool].append((start, start + STRESS_HOURS * 3600.0))
    return downs


class _Audit:
    """Samples one simulator; installed by ``audited_run``."""

    def __init__(self, horizon: float, family: int) -> None:
        self.sim: Any = None
        self.next_at = SAMPLE_SEC
        self.horizon = horizon
        self.family = family
        self.stall_samples = 0
        self.stall_tools: dict[int, int] = {}
        self.streak: dict[int, int] = {}
        self.max_streak = 0
        self.examples: list[str] = []
        self.steps: list[int] = []
        self.focus_queue: list[int] = []
        self.wip_frozen = 0
        self.frozen_at: list[float] = []
        self.late_samples = 0
        self.stranded_max = 0
        self.stranded_end = 0
        self.stranded_examples: list[str] = []
        self.late_max_min = 0.0

    def sample(self, moment: float) -> None:
        sim = self.sim
        fab = sim.fab
        reserved = getattr(sim, "res_lot", None)
        stalled_now: set[int] = set()
        for fam in range(len(fab.families)):
            if not sim.queues[fam]:
                continue
            family = fab.families[fam]
            for tool in range(family.tool0, family.tool0 + family.tools):
                if sim.running[tool] >= 0:
                    continue
                if reserved is not None and reserved[tool] >= 0:
                    continue
                if sim_mod._covering(sim.downs[tool], moment) is not None:
                    continue
                if sim_mod._covering(sim.pm[tool], moment) is not None:
                    continue
                if not sim.live(fam):
                    break
                if self._would_start(tool, moment):
                    pending = [e[0] for e in sim.heap if e[3] == tool and e[2] in _TOOL_EVENTS]
                    if pending:
                        self.late_samples += 1
                        wait = (min(pending) - moment) / 60.0
                        self.late_max_min = max(self.late_max_min, wait)
                    else:
                        stalled_now.add(tool)
        for tool in stalled_now:
            self.stall_samples += 1
            self.stall_tools[tool] = self.stall_tools.get(tool, 0) + 1
            self.streak[tool] = self.streak.get(tool, 0) + 1
            self.max_streak = max(self.max_streak, self.streak[tool])
            if len(self.examples) < 5:
                self.examples.append(f"{fab.tool_name[tool]} idle at {moment / 3600.0:.2f} h")
        for tool in list(self.streak):
            if tool not in stalled_now:
                del self.streak[tool]
        # The first hour is excluded: every snapshot lot starts at t=0, so no
        # step finishes for a while in every run, stressed or not.
        self._stranded(moment)
        if self.steps and sim.steps_done == self.steps[-1] and moment > 3600.0:
            self.wip_frozen += 1
            self.frozen_at.append(moment / 3600.0)
        self.steps.append(sim.steps_done)
        self.focus_queue.append(sim.depth[self.family])

    def _stranded(self, moment: float) -> None:
        """Waiting lots no tool of their family may ever start.

        ``eligible`` is false on every tool of the family, and the scanner the
        lot is pinned to is not in that family, so no event there frees it.
        """
        sim = self.sim
        fab = sim.fab
        found = 0
        for fam, family in enumerate(fab.families):
            for lot in sim.live(fam):
                tools = range(family.tool0, family.tool0 + family.tools)
                if any(sim.eligible(lot, tool, moment) for tool in tools):
                    continue
                pinned = sim.dedicate_tool[lot]
                if pinned >= 0 and fab.tool_family[pinned] == fam:
                    continue
                found += 1
                if len(self.stranded_examples) < 5:
                    self.stranded_examples.append(
                        f"{fab.lot_id[lot]} in {family.name} at {moment / 3600.0:.2f} h"
                    )
        self.stranded_max = max(self.stranded_max, found)
        self.stranded_end = found

    def _would_start(self, tool: int, moment: float) -> bool:
        sim = self.sim
        saved: dict[str, Any] = {
            key: value
            for key, value in vars(sim).items()
            if isinstance(value, (int, float, bool, tuple)) or value is None
        }
        saved_dicts: dict[str, Any] = {
            key: dict(value)
            for key, value in vars(sim).items()
            if isinstance(value, dict) and key in ("last_recipe_ready", "batch_reasons")
        }
        lengths = {key: len(value) for key, value in vars(sim).items() if isinstance(value, list)}
        try:
            chosen, _wake, _reason = sim.choose(tool, moment)
        finally:
            for key, value in saved.items():
                setattr(sim, key, value)
            for key, value in saved_dicts.items():
                setattr(sim, key, value)
            for key in ("samples", "busy_samples", "events"):
                rows = getattr(sim, key, None)
                if isinstance(rows, list) and len(rows) > lengths.get(key, 0):
                    del rows[lengths[key] :]
        return bool(chosen)


class _HeapShim:
    """``heapq`` stand-in for the simulator module: samples before each pop."""

    def __init__(self, audit: _Audit) -> None:
        self.audit = audit

    def __getattr__(self, name: str) -> Any:
        return getattr(heapq, name)

    def heappush(self, heap: list[Any], item: Any) -> None:
        heapq.heappush(heap, item)

    def heappop(self, heap: list[Any]) -> Any:
        audit = self.audit
        if audit.sim is not None and heap:
            while heap[0][0] > audit.next_at and audit.next_at <= audit.horizon:
                audit.sample(audit.next_at)
                audit.next_at += SAMPLE_SEC
        return heapq.heappop(heap)


def audited_run(fab: Fab, **kwargs: Any) -> tuple[Any, _Audit]:
    """``run_policy`` with the stall audit attached."""
    audit = _Audit(float(kwargs["horizon"]), fab.focus_family)
    base = sim_mod._Sim
    original_heapq = sim_mod.heapq

    class Audited(base):  # type: ignore[valid-type,misc]
        def run(self) -> Any:
            audit.sim = self
            return super().run()

    sim_mod._Sim = Audited  # type: ignore[misc]
    sim_mod.heapq = _HeapShim(audit)  # type: ignore[assignment]
    try:
        result = run_policy(fab, **kwargs)
    finally:
        sim_mod._Sim = base  # type: ignore[misc]
        sim_mod.heapq = original_heapq
    return result, audit


def busy_window(fab: Fab, seed: int = 1, policy: str = "edd") -> float:
    """Start of the 2-hour window with the deepest focus-family queue (mean)."""
    horizon = STUDY_HORIZON_SEC
    downs = sample_downs(fab, seed, horizon)
    _result, audit = audited_run(
        fab, policy=policy, seed=seed, horizon=horizon, downs=downs, pm=pm_windows(fab, horizon)
    )
    per_hour = int(3600 / SAMPLE_SEC)
    span = int(STRESS_HOURS * per_hour)
    best, best_at = -1.0, 0.0
    queue = audit.focus_queue
    for first in range(0, len(queue) - span + 1, per_hour):
        depth = sum(queue[first : first + span]) / span
        if depth > best:
            best, best_at = depth, first * SAMPLE_SEC
    return best_at


def stress_one(
    fab: Fab, policy: str, seed: int, start: float = STRESS_START_SEC, **extra: Any
) -> dict[str, Any]:
    """One stress run: KPIs, stall audit and WIP movement around the outage."""
    horizon = STUDY_HORIZON_SEC
    downs = stress_downs(fab, seed, horizon, start)
    pm = pm_windows(fab, horizon)
    result, audit = audited_run(
        fab,
        policy=policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        record=True,
        **extra,
    )
    report: dict[str, Any] = {}
    try:
        from resilimes.smt.invariants import check_trace

        report = check_trace(fab, result, downs=downs, pm=pm)
    except Exception as exc:  # pragma: no cover - main has an older checker
        report = {"total": -1, "error": repr(exc)}
    per_hour = int(3600 / SAMPLE_SEC)
    steps = audit.steps
    hourly = [
        steps[min(len(steps) - 1, (hour + 1) * per_hour - 1)]
        - (steps[hour * per_hour - 1] if hour else 0)
        for hour in range(len(steps) // per_hour)
    ]
    start_h = int(start / 3600)
    end_h = start_h + int(STRESS_HOURS)

    def queue_at(hours: float) -> int:
        index = int(hours * per_hour) - 1
        return audit.focus_queue[index] if 0 <= index < len(audit.focus_queue) else -1

    return {
        "policy": policy,
        "seed": seed,
        "outage_start_h": start / 3600.0,
        "on_time_pct": result.on_time_pct,
        "mean_x_factor": result.mean_x_factor,
        "qtime_violations": result.qtime_violations,
        "recleans": result.recleans,
        "completed_routes": result.completed_routes,
        "stall_samples": audit.stall_samples,
        "stall_tools": len(audit.stall_tools),
        "stall_max_streak_min": audit.max_streak * SAMPLE_SEC / 60.0,
        "stall_examples": audit.examples,
        "wip_frozen_samples": audit.wip_frozen,
        "wip_frozen_at_h": [round(h, 2) for h in audit.frozen_at],
        "stranded_max": audit.stranded_max,
        "stranded_end": audit.stranded_end,
        "stranded_examples": audit.stranded_examples,
        "late_samples": audit.late_samples,
        "late_max_wait_min": round(audit.late_max_min, 1),
        "min_steps_per_hour": min(hourly) if hourly else 0,
        "steps_per_hour_outage": hourly[start_h:end_h],
        "steps_per_hour_after": hourly[end_h : end_h + 4],
        "focus_queue": {
            "start": queue_at(start_h) if start_h else audit.focus_queue[0],
            "end": queue_at(end_h),
            "plus2h": queue_at(end_h + 2),
            "plus6h": queue_at(end_h + 6),
        },
        "reservations": getattr(result, "tool_reservations", 0),
        "reserved_min": getattr(result, "reserved_min", 0.0),
        "invariant_failures": report.get("total", -1),
        "invariant_counts": {k: v for k, v in report.get("counts", {}).items() if v},
    }


_FAB: list[Fab] = []


_PLAN: list[Any] = []


def _job(item: tuple[str, int, float]) -> dict[str, Any]:
    """One stress run. ``RESILIMES_STRESS_PLAN=1`` adds the published t=0 plan
    (WIP only); the outage is unplanned, as in a real fab."""
    policy, seed, start = item
    extra: dict[str, Any] = {}
    if os.environ.get("RESILIMES_STRESS_PLAN") == "1":
        if not _PLAN:
            from resilimes.smt.planning import build_plan, scenario_input

            fab = _FAB[0]
            _PLAN.append(build_plan(fab, scenario_input(fab, "published", releases=False)))
        extra["plan"] = _PLAN[0]
    row = stress_one(_FAB[0], policy, seed, start, **extra)
    if extra:
        row["plan"] = True
    return row


def main() -> None:
    _FAB.append(load_fab())
    workers = max(1, int(os.environ.get("RESILIMES_SWEEP_WORKERS", "4")))
    items = [
        (policy, seed, start) for start in STRESS_STARTS for seed in SEEDS for policy in POLICIES
    ]
    with get_context("fork").Pool(workers) as pool:
        rows = pool.map(_job, items, chunksize=1)
    bad = 0
    for row in rows:
        bad += row["stall_samples"] + max(0, row["invariant_failures"])
        bad += row["wip_frozen_samples"] + row["stranded_max"]
        print(row, flush=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=1)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
