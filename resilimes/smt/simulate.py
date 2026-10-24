"""Event-driven dispatch on the full SMT2020 fab.

One decision looks only at the station family of the tool that just went idle,
and only at a bounded look-ahead inside that queue. Breakdown clocks are
exponential MTTF/MTTR from ``downcal.txt``, one clock per tool. Every policy
refuses a start that falls inside a PM or whose process would cross the next PM.

Transport (``fromto`` is one Fab-to-Fab row), operators, reticle copies, and
the published fractional rework probability are not in this loop. A litho
layer with ``SVESTN`` / ``FORSTEP`` stays on the scanner that ran the first
layer of that chain, once this run has chosen it. WIP does not name a tool,
so a lot that starts mid-chain is not pinned until then. A lot in process
when a tool breaks keeps the remaining process, waits 15 minutes, and
resumes on that same tool. A lot becomes ready for the next step when the
current step ends.
"""

from __future__ import annotations

import heapq
import random
import time
from dataclasses import dataclass, field
from typing import Any

from resilimes.kernel.score import dispatch_score, dynamic_priority, ped_risk
from resilimes.smt.fab import (
    BATCH_MAX_WAIT_SEC,
    LOOKAHEAD,
    WIP_FLOOR,
    WIP_PER_TOOL,
    Fab,
)

_DONE = 0
_DOWN_START = 1
_DOWN_END = 2
_WAKE = 3
_BIN_SEC = 900.0
_WAFERS = 25
# Not an SMT2020 column. Interrupted work waits this long, and only the
# process completed before the breakdown counts.
DISPOSITION_SEC = 15.0 * 60.0
# Due dates in the X-factor book. Middle of the 2.5-3 range.
X_FACTOR = 2.75
# Lots at least this tight stay in the candidate list when the family cap is on.
# Pre-registered at 7200 s before the seeds 9-13 run. Not changed after that run.
SLACK_CANDIDATE_SEC = 7200.0


@dataclass
class RunResult:
    policy: str
    seed: int
    horizon_sec: float
    on_time_pct: float
    weighted_tardiness_min: float
    due_in_horizon: int
    already_late: int
    completed_routes: int
    cycle_time_h: float | None
    mean_step_cycle_min: float
    litho_util_pct: float
    scanner_util_pct: float
    qtime_violations: int
    pm_avoided: int
    pm_overlaps: int
    wip_replans: int
    dispatch_p50_ms: float
    dispatch_p95_ms: float
    dispatch_decisions: int
    sim_s: float
    focus_queue_max: int
    sibling_starts: int
    downstream_queue_max: int
    hot_steps: int
    hot_scanner_start_min: float | None
    queue_end: dict[str, int] = field(default_factory=dict)
    down_tools: dict[str, int] = field(default_factory=dict)
    occupancy: list[list[float]] = field(default_factory=list)
    focus_bars: list[dict[str, float | str]] = field(default_factory=list)
    watched_late_h: dict[str, float] = field(default_factory=dict)
    mean_x_factor: float | None = None
    qtime_gates: int = 0
    recleans: int = 0
    # Decisions where at least one lot was ready. The headline p50/p95 also
    # counts empty wakes.
    dispatch_busy_p50_ms: float = 0.0
    dispatch_busy_p95_ms: float = 0.0
    dispatch_busy_decisions: int = 0
    # Starts committed while a down window covered the tool. Empty when the
    # loop refuses those starts before choose().
    down_starts: list[dict[str, Any]] = field(default_factory=list)
    # Filled only with ``record=True``. Read by ``resilimes.smt.invariants``.
    events: list[tuple[Any, ...]] = field(default_factory=list)


def interrupt_remaining(started: float, moment: float, proc: float) -> tuple[float, float]:
    """Process left after a breakdown, and the earliest restart.

    Elapsed time stops at the breakdown. It is not extended to the horizon.
    The second value is the breakdown time plus disposition.
    """
    elapsed = max(0.0, moment - started)
    remain = max(0.0, proc - elapsed)
    return remain, moment + DISPOSITION_SEC


def price_paid(
    before: RunResult,
    after: RunResult,
    lot_ids: list[str],
) -> dict[str, Any]:
    """Non-hot lots that finish later under the recovery than under the baseline."""
    worse: list[tuple[float, str]] = []
    for lot_id in lot_ids:
        delta = after.watched_late_h.get(lot_id, 0.0) - before.watched_late_h.get(lot_id, 0.0)
        if delta > 0.05:
            worse.append((delta, lot_id))
    worse.sort(reverse=True)
    return {
        "lots": len(worse),
        "extra_h": round(sum(item[0] for item in worse), 2),
        "worst": [{"lot_id": lot_id, "extra_h": round(delta, 2)} for delta, lot_id in worse[:5]],
    }


def setup_seconds(fab: Fab, family: int, current: int, recipe: int) -> float:
    if current == recipe:
        return 0.0
    exact = fab.setup.get((family, current, recipe))
    if exact is not None:
        return exact
    return fab.setup.get((family, 0, recipe), 0.0)


def sample_downs(
    fab: Fab,
    seed: int,
    horizon: float,
    *,
    forced_tool: int | None = None,
    forced_until: float = 0.0,
) -> list[list[tuple[float, float]]]:
    """Exponential MTTF/MTTR from downcal, one clock per tool."""
    rng = random.Random(seed)
    windows: list[list[tuple[float, float]]] = []
    for tool, fam_i in enumerate(fab.tool_family):
        group = fab.families[fam_i].group
        mttf = fab.down_mttf.get(group)
        mttr = fab.down_mttr.get(group)
        spans: list[tuple[float, float]] = []
        if mttf and mttr and mttf > 0 and mttr > 0:
            moment = rng.expovariate(1.0 / mttf)
            while moment < horizon:
                repair = rng.expovariate(1.0 / mttr)
                spans.append((moment, moment + repair))
                moment = moment + repair + rng.expovariate(1.0 / mttf)
        if forced_tool is not None and tool == forced_tool and forced_until > 0:
            spans.append((0.0, forced_until))
        spans.sort()
        windows.append(spans)
    return windows


def pm_windows(
    fab: Fab,
    horizon: float,
    *,
    shift_sec: float = 0.0,
) -> list[list[tuple[float, float]]]:
    """One published FOA per family, copied onto every tool in that family.

    The extract stores a single first-start, not a per-tool stagger.
    ``shift_sec`` subtracts the same offset from every calendar so a weekly PM
    can sit inside a multi-shift window. Durations and intervals stay published.
    """
    per_family: list[list[tuple[float, float]]] = [[] for _ in fab.families]
    for fam, first, interval, duration, _name in fab.pm:
        if interval <= 0 or duration <= 0:
            continue
        start = first - shift_sec
        guard = 0
        while start < horizon and guard < 10000:
            end = start + duration
            if end > 0 and start < horizon:
                per_family[fam].append((max(0.0, start), min(end, horizon + duration)))
            start += interval
            guard += 1
    return [list(per_family[fam]) for fam in fab.tool_family]


def pm_shift_to_open(fab: Fab, calendar: str, open_at: float) -> float:
    for _fam, first, _interval, _duration, name in fab.pm:
        if name == calendar:
            return first - open_at
    raise ValueError(f"Unknown PM calendar {calendar}")


def macro_aps_ms(fab: Fab) -> tuple[float, int]:
    """Backward dues plus earliest-free scanner placement.

    Same placement rule as ``schedule_bottleneck``: scanner steps go out in
    operation-due order onto the earliest free expose scanner. Non-scanner
    steps are pulled around those windows and discarded. No per-step rows.
    """
    started = time.perf_counter()
    scanners = max(1, fab.scanner_tools)
    jobs: list[tuple[float, float, int, int]] = []
    for lot_i, route_i in enumerate(fab.lot_route):
        route = fab.routes[route_i]
        step0 = fab.lot_step[lot_i]
        last = len(route.family) - 1
        cursor = fab.lot_due[lot_i]
        span = last - step0 + 1
        dues = [0.0] * span
        for offset, index in enumerate(range(last, step0 - 1, -1)):
            dues[span - 1 - offset] = cursor
            cursor -= route.cycle[index]
        for offset, index in enumerate(range(step0, last + 1)):
            if fab.families[route.family[index]].scanner:
                jobs.append((dues[offset], route.cycle[index], lot_i, index))
    jobs.sort()
    free = [0.0] * scanners
    placed: dict[tuple[int, int], float] = {}
    for _due, cycle, lot_i, index in jobs:
        tool = min(range(scanners), key=lambda item: free[item])
        placed[(lot_i, index)] = free[tool]
        free[tool] += cycle
    for lot_i, route_i in enumerate(fab.lot_route):
        route = fab.routes[route_i]
        step0 = fab.lot_step[lot_i]
        cursor = 0.0
        for index in range(step0, len(route.family)):
            start = placed.get((lot_i, index))
            if start is None:
                cursor += route.cycle[index]
                continue
            pull = start
            earlier = index - 1
            while earlier >= step0 and (lot_i, earlier) not in placed:
                pull -= route.cycle[earlier]
                placed[(lot_i, earlier)] = pull
                earlier -= 1
            cursor = start + route.cycle[index]
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return elapsed_ms, len(jobs)


def run_policy(
    fab: Fab,
    *,
    policy: str,
    seed: int,
    horizon: float,
    downs: list[list[tuple[float, float]]],
    pm: list[list[tuple[float, float]]],
    hot_lot: int | None = None,
    hot_due: float | None = None,
    promote_hot: bool = False,
    trace: bool = False,
    focus_down_until: float = 0.0,
    watch: tuple[int, ...] = (),
    bar_family: int | None = None,
    bar_until: float | None = None,
    record: bool = False,
) -> RunResult:
    if policy not in {"resilimes", "edd", "fifo", "cr", "smt_rule"}:
        raise ValueError(f"Unknown policy {policy}")
    sim = _Sim(
        fab,
        policy=policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        hot_lot=hot_lot,
        hot_due=hot_due,
        promote_hot=promote_hot,
        trace=trace,
        focus_down_until=focus_down_until,
        watch=watch,
        bar_family=bar_family,
        bar_until=bar_until,
        record=record,
    )
    return sim.run()


def _downstream(fab: Fab, focus: int) -> set[int]:
    found: set[int] = set()
    for route in fab.routes:
        families = route.family
        for index, fam in enumerate(families):
            if fam == focus and index + 1 < len(families):
                found.add(families[index + 1])
    return found


def _covering(windows: list[tuple[float, float]], moment: float) -> tuple[float, float] | None:
    for start_at, end_at in windows:
        if start_at <= moment < end_at:
            return start_at, end_at
    return None


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = round((pct / 100.0) * (len(ordered) - 1))
    return ordered[max(0, min(index, len(ordered) - 1))]


class _Sim:
    def __init__(
        self,
        fab: Fab,
        *,
        policy: str,
        seed: int,
        horizon: float,
        downs: list[list[tuple[float, float]]],
        pm: list[list[tuple[float, float]]],
        hot_lot: int | None,
        hot_due: float | None,
        promote_hot: bool,
        trace: bool,
        focus_down_until: float,
        watch: tuple[int, ...] = (),
        bar_family: int | None = None,
        bar_until: float | None = None,
        record: bool = False,
    ) -> None:
        self.fab = fab
        self.record = record
        self.events: list[tuple[Any, ...]] = []
        self.policy = policy
        self.seed = seed
        self.horizon = horizon
        self.downs = downs
        self.pm = pm
        self.hot_lot = hot_lot
        self.promote_hot = promote_hot
        self.trace = trace
        self.focus_down_until = focus_down_until
        self.watch = watch
        self.partial = [0.0] * len(fab.lot_id)
        self.bound_tool = [-1] * len(fab.lot_id)
        self.dedicate_tool = [-1] * len(fab.lot_id)
        self.rework = [0] * len(fab.lot_id)
        self.cqt_from = [-1] * len(fab.lot_id)
        self.piece_started = [0.0] * len(fab.tool_name)
        self.piece_proc = [0.0] * len(fab.tool_name)
        self.raw_remain = [
            fab.routes[route_i].remain[step]
            for route_i, step in zip(fab.lot_route, fab.lot_step, strict=True)
        ]
        self.gated = 0
        self.recleans = 0
        self.down_starts: list[dict[str, Any]] = []
        self.n = len(fab.lot_id)
        self.tools = len(fab.tool_name)
        self.step = list(fab.lot_step)
        self.due = list(fab.lot_due)
        self.value = list(fab.lot_value)
        if promote_hot and hot_lot is not None:
            self.value[hot_lot] = 3.0
            if hot_due is not None:
                self.due[hot_lot] = hot_due
        self.ready = [0.0] * self.n
        self.waiting = [False] * self.n
        self.deadline = [0.0] * self.n
        self.cqt_at = [-1] * self.n
        self.cqt_limit = [0.0] * self.n
        self.finished_at = [-1.0] * self.n
        self.queues: list[list[int]] = [[] for _ in fab.families]
        self.depth = [0] * len(fab.families)
        self.idle: list[list[int]] = [[] for _ in fab.families]
        self.running = [-1] * self.tools
        self.on_tool: list[list[int]] = [[] for _ in range(self.tools)]
        self.tool_gen = [0] * self.tools
        self.tool_recipe = [0] * self.tools
        self.samples: list[float] = []
        self.busy_samples: list[float] = []
        self.heap: list[tuple[float, int, int, int, int]] = []
        self.seq = 0
        self.violations = 0
        self.pm_avoided = 0
        self.pm_overlaps = 0
        self.wip_replans = 0
        self.seen_over = [False] * len(fab.families)
        self.litho_busy = 0.0
        self.scanner_busy = 0.0
        self.step_cycle = 0.0
        self.steps_done = 0
        self.sibling_starts = 0
        self.focus_queue_max = 0
        self.downstream_max = 0
        self.hot_steps = 0
        self.hot_scanner: float | None = None
        self.busy_until = [0.0] * self.tools
        self.busy_litho = [False] * self.tools
        self.busy_scanner = [False] * self.tools
        self.focus_fam = fab.focus_family
        self.bar_family = fab.focus_family if bar_family is None else bar_family
        self.bar_until = 12 * 3600.0 if bar_until is None else bar_until
        self.bar_cap = 2400 if self.bar_until > 12 * 3600.0 else 400
        self.downstream = _downstream(fab, fab.focus_family)
        self.threshold = [max(WIP_FLOOR, WIP_PER_TOOL * item.tools) for item in fab.families]
        self.bins = int(horizon // _BIN_SEC) + 1 if trace else 0
        self.occupancy = [[0.0] * self.bins for _ in fab.families] if trace else []
        self.focus_bars: list[dict[str, float | str]] = []
        self.clock = 0.0

    def push(self, moment: float, kind: int, tool: int, gen: int = 0) -> None:
        if moment > self.horizon:
            return
        self.seq += 1
        heapq.heappush(self.heap, (moment, self.seq, kind, tool, gen))

    def run(self) -> RunResult:
        started = time.perf_counter()
        for lot in range(self.n):
            self.enqueue(lot, 0.0)
        for tool, spans in enumerate(self.downs):
            opened = False
            for start_at, end_at in spans:
                if start_at <= 0 < end_at:
                    self.push(end_at, _DOWN_END, tool)
                    opened = True
                elif start_at > 0:
                    self.push(start_at, _DOWN_START, tool)
            if not opened:
                self.push(0.0, _WAKE, tool)
        steps = 0
        while self.heap:
            moment, _seq, kind, tool, gen = heapq.heappop(self.heap)
            if moment > self.horizon:
                break
            self.clock = moment
            if kind == _DONE:
                self.complete(tool, moment, gen)
            elif kind == _DOWN_START:
                self.down_start(tool, moment)
            elif kind in (_DOWN_END, _WAKE):
                self.release_idle(tool)
                self.try_start(tool, moment)
            steps += 1
            if steps > 2_000_000:
                raise RuntimeError("SMT simulation exceeded 2e6 events")
        return self.finish(time.perf_counter() - started)

    def enqueue(self, lot: int, moment: float) -> None:
        route = self.fab.routes[self.fab.lot_route[lot]]
        fam = route.family[self.step[lot]]
        self.ready[lot] = moment
        self.waiting[lot] = True
        self.queues[fam].append(lot)
        self.depth[fam] += 1
        self.note_depth(fam)
        # Counter only. choose() shortens the candidate list. It does not replan.
        if self.policy == "resilimes" and self.depth[fam] > self.threshold[fam]:
            if not self.seen_over[fam]:
                self.seen_over[fam] = True
                self.wip_replans += 1
        elif self.depth[fam] <= self.threshold[fam]:
            self.seen_over[fam] = False
        self.wake_family(fam)

    def wake_family(self, fam: int) -> None:
        """Every idle tool in the family gets one look.

        A lot pinned to one scanner has to be seen by that scanner. Trying
        only the first idle tool leaves it queued while its scanner sits idle.
        """
        pending = list(self.idle[fam])
        self.idle[fam].clear()
        for tool in pending:
            self.try_start(tool, self.clock)

    def note_depth(self, fam: int) -> None:
        if fam == self.focus_fam and self.depth[fam] > self.focus_queue_max:
            self.focus_queue_max = self.depth[fam]
        if fam in self.downstream and self.depth[fam] > self.downstream_max:
            self.downstream_max = self.depth[fam]

    def live(self, fam: int) -> list[int]:
        rows = [lot for lot in self.queues[fam] if self.waiting[lot]]
        self.queues[fam] = rows
        return rows

    def _sample(self, t0: float, nonempty: bool) -> None:
        elapsed = time.perf_counter() - t0
        self.samples.append(elapsed)
        if nonempty:
            self.busy_samples.append(elapsed)

    def choose(self, tool: int, moment: float) -> tuple[list[int], float | None]:
        t0 = time.perf_counter()
        fam = self.fab.tool_family[tool]
        pool = [lot for lot in self.live(fam) if self.eligible(lot, tool)]
        if not pool:
            self._sample(t0, False)
            return [], None
        ready_pool = [lot for lot in pool if self.ready[lot] <= moment + 1e-6]
        if not ready_pool:
            wake = min(self.ready[lot] for lot in pool)
            self._sample(t0, False)
            return [], wake
        pool = ready_pool
        over_cap = self.policy == "resilimes" and self.depth[fam] > self.threshold[fam]
        limit = 8 if over_cap else LOOKAHEAD
        if self.policy == "smt_rule":
            # The dataset cascade ranks the whole queue. The candidate cap is ResiliMES.
            limit = len(pool)
        if len(pool) > limit:
            if self.policy == "fifo":
                pool = pool[:limit]
            else:

                def _cheap(lot: int) -> tuple[float, float, int]:
                    return self.cheap(lot, moment)

                ranked = heapq.nsmallest(limit, pool, key=_cheap)
                if over_cap:
                    kept = set(ranked)
                    for lot in pool:
                        if lot not in kept and self._slack(lot, moment) <= SLACK_CANDIDATE_SEC:
                            ranked.append(lot)
                pool = ranked
        pm_start = self.next_pm_start(tool, moment)
        feasible: list[int] = []
        skipped = False
        gated = False
        gate_wake: float | None = None
        for lot in pool:
            proc = self.piece_seconds(lot, tool)
            if pm_start is not None and moment + proc > pm_start:
                skipped = True
                continue
            if self.policy == "resilimes":
                opened = self.downstream_ready(lot, moment, proc)
                if opened is not None and opened > moment + proc + self._open_limit(lot):
                    gated = True
                    when = max(moment + 60.0, opened - proc - self._open_limit(lot))
                    if gate_wake is None or when < gate_wake:
                        gate_wake = when
                    continue
            feasible.append(lot)
        if gated:
            self.gated += 1
        if skipped:
            # One refused start per decision. The same lot can be seen again later.
            self.pm_avoided += 1
        if not feasible:
            self._sample(t0, True)
            return [], gate_wake if gate_wake is not None else pm_start
        singles: list[int] = []
        batches: list[int] = []
        for lot in feasible:
            route = self.fab.routes[self.fab.lot_route[lot]]
            if self.partial[lot] > 0 or self.bound_tool[lot] >= 0:
                singles.append(lot)
            elif route.batch_max[self.step[lot]] > 0:
                batches.append(lot)
            else:
                singles.append(lot)
        chosen = self.pick_batch(batches, moment) if batches else []
        if singles:
            single = min(singles, key=lambda lot: self.rank(lot, tool, moment))
            if not chosen or self.rank(single, tool, moment) < self.rank(chosen[0], tool, moment):
                chosen = [single]
        wake_at = None
        if not chosen and batches:
            wake_at = min(self.ready[lot] for lot in batches) + BATCH_MAX_WAIT_SEC
        self._sample(t0, True)
        return chosen, wake_at

    def _slack(self, lot: int, moment: float) -> float:
        route = self.fab.routes[self.fab.lot_route[lot]]
        return self.due[lot] - moment - route.remain[self.step[lot]]

    def eligible(self, lot: int, tool: int) -> bool:
        """Same tool after a breakdown, and the dedicated scanner after layer 1."""
        bound = self.bound_tool[lot]
        route = self.fab.routes[self.fab.lot_route[lot]]
        root = route.dedicate_root[self.step[lot]]
        pinned = self.dedicate_tool[lot]
        on_bound = bound < 0 or bound == tool
        on_scanner = root < 0 or pinned < 0 or pinned == tool
        return on_bound and on_scanner

    def piece_seconds(self, lot: int, tool: int) -> float:
        """Remaining process. A resumed lot does not pay setup a second time."""
        if self.partial[lot] > 0:
            return self.partial[lot]
        route = self.fab.routes[self.fab.lot_route[lot]]
        index = self.step[lot]
        fam = self.fab.tool_family[tool]
        setup = setup_seconds(self.fab, fam, self.tool_recipe[tool], route.recipe[index])
        return route.cycle[index] + setup

    def _open_limit(self, lot: int) -> float:
        route = self.fab.routes[self.fab.lot_route[lot]]
        index = self.step[lot]
        if route.cqt_target[index] != index + 1:
            return 0.0
        return route.cqt_limit[index]

    def downstream_ready(self, lot: int, moment: float, proc: float) -> float | None:
        """Earliest downstream start for an adjacent Wet_Etch queue-time pair.

        Returns None when this step does not open that kind of window.
        On the measured books this gate fired 0 times. A Dry_Etch retarget
        was reverted after seeds 9-13.
        """
        limit = self._open_limit(lot)
        if limit <= 0:
            return None
        route = self.fab.routes[self.fab.lot_route[lot]]
        index = self.step[lot]
        if self.fab.families[route.family[index]].group != "Wet_Etch":
            return None
        target = route.family[index + 1]
        return self._earliest_tool(target, moment + proc)

    def _earliest_tool(self, target: int, arrival: float) -> float | None:
        family = self.fab.families[target]
        earliest: float | None = None
        for tool in range(family.tool0, family.tool0 + family.tools):
            free = max(arrival, self.busy_until[tool])
            covered = _covering(self.downs[tool], free)
            if covered is not None:
                free = covered[1]
            if earliest is None or free < earliest:
                earliest = free
        return earliest

    def pick_batch(self, lots: list[int], moment: float) -> list[int]:
        grouped: dict[int, list[int]] = {}
        for lot in lots:
            route = self.fab.routes[self.fab.lot_route[lot]]
            grouped.setdefault(route.recipe[self.step[lot]], []).append(lot)
        best: list[int] | None = None
        best_key: tuple[float, int] | None = None
        for group in grouped.values():
            ordered = sorted(group, key=lambda lot: (self.ready[lot], lot))
            route = self.fab.routes[self.fab.lot_route[ordered[0]]]
            index = self.step[ordered[0]]
            cap = route.batch_max[index]
            floor = route.batch_min[index] or cap
            taken: list[int] = []
            wafers = 0
            for lot in ordered:
                if cap and wafers >= cap:
                    break
                taken.append(lot)
                wafers += _WAFERS
            aged = moment - self.ready[ordered[0]] >= BATCH_MAX_WAIT_SEC
            if wafers < floor and not aged:
                continue
            key = (self.due[taken[0]], taken[0])
            if best is None or best_key is None or key < best_key:
                best = taken
                best_key = key
        return best or []

    def cheap(self, lot: int, moment: float) -> tuple[float, float, int]:
        if self.policy == "edd":
            return (self.due[lot], self.ready[lot], lot)
        if self.policy == "cr":
            return (self.cr(lot, moment), self.due[lot], lot)
        if self.policy == "resilimes":
            return (-self.dpi(lot, moment), self.ready[lot], lot)
        return (self.ready[lot], self.due[lot], lot)

    def rank(self, lot: int, tool: int, moment: float) -> tuple[float, ...]:
        if self.policy == "fifo":
            return (self.ready[lot], self.due[lot], lot)
        if self.policy == "edd":
            return (self.due[lot], self.ready[lot], lot)
        if self.policy == "cr":
            return (self.cr(lot, moment), self.due[lot], lot)
        if self.policy == "smt_rule":
            return self.smt_rule_key(lot, tool, moment)
        fam = self.fab.tool_family[tool]
        route = self.fab.routes[self.fab.lot_route[lot]]
        setup = setup_seconds(self.fab, fam, self.tool_recipe[tool], route.recipe[self.step[lot]])
        score = dispatch_score(
            dpi=self.dpi(lot, moment), setup_sec=setup, ped=self.ped(lot, moment)
        )
        return (-score, self.ready[lot], lot)

    def smt_rule_key(self, lot: int, tool: int, moment: float) -> tuple[float, ...]:
        """Dataset cascade from ``tool.txt.1l``. Not ``dispatch_score``.

        ``rule_HotLotFIRST`` with ``rank_HP;rank_RSETUP;rank_CR``: a lot whose
        PRIOR is at least 20 (hot, including VIP at 30) ranks before a normal
        lot, then higher PRIOR, then shorter setup, then lower CR. The 20 is
        the published band in ``order_class_from_priority``, not a tuned weight.
        ``rule_LSSU`` (Implant_128, Implant_132, Implant_91) puts setup first
        and then that same cascade. Tool choice stays the idle-tool loop.
        ``wake_LeastSetupTime`` is not implemented.
        """
        fam = self.fab.tool_family[tool]
        family = self.fab.families[fam]
        route = self.fab.routes[self.fab.lot_route[lot]]
        setup = setup_seconds(self.fab, fam, self.tool_recipe[tool], route.recipe[self.step[lot]])
        priority = self.fab.lot_priority[lot]
        hot = 0.0 if priority >= 20 else 1.0
        ratio = self.cr(lot, moment)
        cascade = (hot, -float(priority), setup, ratio, float(lot))
        if family.rule == "rule_LSSU":
            return (setup, hot, -float(priority), ratio, float(lot))
        return cascade

    def dpi(self, lot: int, moment: float) -> float:
        route = self.fab.routes[self.fab.lot_route[lot]]
        kind = "VIP" if self.promote_hot and lot == self.hot_lot else self.fab.lot_class[lot]
        return dynamic_priority(
            due_sec=self.due[lot],
            now_sec=moment,
            remaining_sec=route.remain[self.step[lot]],
            order_class=kind,
        ).index

    def cr(self, lot: int, moment: float) -> float:
        route = self.fab.routes[self.fab.lot_route[lot]]
        remaining = route.remain[self.step[lot]]
        if remaining <= 1e-9:
            remaining = 1e-9
        return (self.due[lot] - moment) / remaining

    def ped(self, lot: int, moment: float) -> float:
        if self.cqt_at[lot] < 0 or self.deadline[lot] <= 0:
            return 0.0
        return ped_risk(self.deadline[lot] - moment, self.cqt_limit[lot], 6.0)

    def next_pm_start(self, tool: int, moment: float) -> float | None:
        found: float | None = None
        for start_at, _end in self.pm[tool]:
            if start_at > moment and (found is None or start_at < found):
                found = start_at
        return found

    def overlaps_pm(self, tool: int, moment: float, proc: float) -> bool:
        end = moment + proc
        return any(moment < end_at and end > start_at for start_at, end_at in self.pm[tool])

    def release_idle(self, tool: int) -> None:
        fam = self.fab.tool_family[tool]
        if tool in self.idle[fam]:
            self.idle[fam].remove(tool)

    def try_start(self, tool: int, moment: float) -> None:
        if moment >= self.horizon or self.running[tool] >= 0:
            return
        if self._queue_down_ends(tool, moment):
            return
        in_pm = _covering(self.pm[tool], moment)
        if in_pm is not None:
            self.push(in_pm[1], _WAKE, tool)
            return
        chosen, wake_at = self.choose(tool, moment)
        fam = self.fab.tool_family[tool]
        if not chosen:
            if wake_at is not None and wake_at > moment:
                self.push(wake_at, _WAKE, tool)
            if tool not in self.idle[fam]:
                self.idle[fam].append(tool)
            return
        route = self.fab.routes[self.fab.lot_route[chosen[0]]]
        index = self.step[chosen[0]]
        started: list[int] = []
        for lot in chosen:
            if not self.waiting[lot] or self.step[lot] != index:
                continue
            if self._reclean(lot, fam, moment):
                continue
            if self.cqt_at[lot] == index and self.deadline[lot] > 0 and moment > self.deadline[lot]:
                self.violations += 1
            if self.cqt_at[lot] == index:
                self.cqt_at[lot] = -1
            self.waiting[lot] = False
            self.depth[fam] -= 1
            started.append(lot)
        if not started:
            if tool not in self.idle[fam]:
                self.idle[fam].append(tool)
            return
        covered = _covering(self.downs[tool], moment)
        if covered is not None:
            down_min = (covered[1] - covered[0]) / 60.0
            for lot in started:
                self.down_starts.append(
                    {
                        "lot_id": self.fab.lot_id[lot],
                        "tool": self.fab.tool_name[tool],
                        "t": moment,
                        "down_min": down_min,
                    }
                )
        self.tool_gen[tool] += 1
        self.running[tool] = started[0]
        self.on_tool[tool] = started
        self.tool_recipe[tool] = route.recipe[index]
        piece = self.piece_seconds(started[0], tool)
        for lot in started:
            self.partial[lot] = 0.0
            if route.dedicate_root[index] >= 0 and self.dedicate_tool[lot] < 0:
                self.dedicate_tool[lot] = tool
        finish = moment + piece
        self.piece_started[tool] = moment
        self.piece_proc[tool] = piece
        if self.overlaps_pm(tool, moment, piece):
            self.pm_overlaps += 1
        if self.record:
            self.events.append(("start", moment, tool, tuple(started), index, finish))
        self.push(finish, _DONE, tool, self.tool_gen[tool])
        self.busy_until[tool] = finish
        self.busy_litho[tool] = self.fab.families[fam].litho
        self.busy_scanner[tool] = self.fab.families[fam].scanner
        self.account(tool, fam, moment, finish, started)

    def _reclean(self, lot: int, fam: int, moment: float) -> bool:
        """One re-clean. The lot is not held. A second miss just counts."""
        index = self.step[lot]
        if self.cqt_at[lot] != index or self.deadline[lot] <= 0 or moment <= self.deadline[lot]:
            return False
        origin = self.cqt_from[lot]
        if origin < 0 or self.rework[lot] >= 1:
            return False
        route = self.fab.routes[self.fab.lot_route[lot]]
        if self.fab.families[route.family[origin]].group != "Wet_Etch":
            return False
        self.violations += 1
        self.recleans += 1
        self.rework[lot] += 1
        self.cqt_at[lot] = -1
        self.deadline[lot] = 0.0
        self.waiting[lot] = False
        self.depth[fam] = max(0, self.depth[fam] - 1)
        if lot in self.queues[fam]:
            self.queues[fam].remove(lot)
        if self.record:
            self.events.append(("reclean", moment, lot, index, origin))
        self.step[lot] = origin
        self.partial[lot] = 0.0
        self.enqueue(lot, moment)
        return True

    def account(
        self,
        tool: int,
        fam: int,
        moment: float,
        finish: float,
        lots: list[int],
    ) -> None:
        clipped = max(0.0, min(finish, self.horizon) - moment)
        family = self.fab.families[fam]
        if family.litho:
            self.litho_busy += clipped
        if family.scanner:
            self.scanner_busy += clipped
        if fam == self.focus_fam and tool != self.fab.focus_tool and moment < self.focus_down_until:
            self.sibling_starts += len(lots)
        if self.hot_lot in lots and family.scanner and self.hot_scanner is None:
            self.hot_scanner = moment / 60.0
        if not self.trace or not self.bins:
            return
        start_bin = int(max(0.0, moment) // _BIN_SEC)
        end_bin = int(min(finish, self.horizon) // _BIN_SEC)
        for bin_index in range(start_bin, min(end_bin + 1, self.bins)):
            left = max(moment, bin_index * _BIN_SEC)
            right = min(finish, self.horizon, (bin_index + 1) * _BIN_SEC)
            if right > left:
                self.occupancy[fam][bin_index] += right - left
        if (
            fam == self.bar_family
            and moment < self.bar_until
            and len(self.focus_bars) < self.bar_cap
        ):
            self.focus_bars.append(
                {
                    "tool": self.fab.tool_name[tool],
                    "s": round(moment / 60.0, 1),
                    "e": round(min(finish, self.horizon) / 60.0, 1),
                }
            )

    def complete(self, tool: int, moment: float, gen: int) -> None:
        if gen != self.tool_gen[tool]:
            return
        lots = self.on_tool[tool]
        self.on_tool[tool] = []
        self.running[tool] = -1
        for lot in lots:
            self.finish_lot(lot, moment)
        self.try_start(tool, moment)

    def finish_lot(self, lot: int, moment: float) -> None:
        route = self.fab.routes[self.fab.lot_route[lot]]
        index = self.step[lot]
        self.step_cycle += max(0.0, moment - self.ready[lot])
        self.steps_done += 1
        self.bound_tool[lot] = -1
        if lot == self.hot_lot:
            self.hot_steps += 1
        if self.record:
            self.events.append(("end", moment, lot, index))
        if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
            self.deadline[lot] = moment + route.cqt_limit[index]
            self.cqt_limit[lot] = route.cqt_limit[index]
            self.cqt_at[lot] = route.cqt_target[index]
            self.cqt_from[lot] = index
        nxt = index + 1
        if nxt >= len(route.family):
            self.step[lot] = max(index, 0)
            self.finished_at[lot] = moment
            return
        self.step[lot] = nxt
        self.enqueue(lot, moment)

    def down_start(self, tool: int, moment: float) -> None:
        self.release_idle(tool)
        lots = self.on_tool[tool]
        if lots:
            self.tool_gen[tool] += 1
            self.on_tool[tool] = []
            self.running[tool] = -1
            accounted_end = min(self.busy_until[tool], self.horizon)
            leftover = accounted_end - moment
            if leftover > 0:
                if self.busy_litho[tool]:
                    self.litho_busy -= leftover
                if self.busy_scanner[tool]:
                    self.scanner_busy -= leftover
                self.busy_until[tool] = moment
            remain, ready = interrupt_remaining(
                self.piece_started[tool], moment, self.piece_proc[tool]
            )
            if self.record:
                self.events.append(("interrupt", moment, tool, tuple(lots)))
            for lot in lots:
                if remain <= 1e-6:
                    self.finish_lot(lot, moment)
                    continue
                self.partial[lot] = remain
                self.bound_tool[lot] = tool
                self.enqueue(lot, ready)
        self._queue_down_ends(tool, moment)

    def _queue_down_ends(self, tool: int, moment: float) -> bool:
        """Queue a release at every down window that still covers ``moment``.

        A forced outage and an MTTF draw can overlap. Queuing only the first
        end leaves the tool down after that end, through the rest of the horizon.
        """
        covered = False
        for _start_at, end_at in self.downs[tool]:
            if _start_at <= moment < end_at:
                covered = True
                self.push(end_at, _DOWN_END, tool)
        return covered

    def finish(self, elapsed: float) -> RunResult:
        fab = self.fab
        due_lots = [lot for lot in range(self.n) if self.due[lot] <= self.horizon]
        already = sum(1 for lot in due_lots if self.due[lot] <= 0)
        on_time = 0
        tardiness = 0.0
        completed = 0
        cycle_sum = 0.0
        for lot in range(self.n):
            end = self.finished_at[lot]
            if end >= 0:
                completed += 1
                cycle_sum += end
            if self.due[lot] > self.horizon:
                continue
            finish = end if end >= 0 else self.horizon
            late = max(0.0, finish - self.due[lot])
            tardiness += self.value[lot] * (late / 60.0)
            if end >= 0 and end <= self.due[lot]:
                on_time += 1
        for lot in range(self.n):
            if self.cqt_at[lot] >= 0 and 0 < self.deadline[lot] <= self.horizon:
                self.violations += 1
        denom = len(due_lots)
        xs = [
            self.finished_at[lot] / self.raw_remain[lot]
            for lot in range(self.n)
            if self.finished_at[lot] >= 0 and self.raw_remain[lot] > 1e-6
        ]
        mean_x = round(sum(xs) / len(xs), 3) if xs else None
        watched: dict[str, float] = {}
        for lot in self.watch:
            end = self.finished_at[lot]
            finish = end if end >= 0 else self.horizon
            watched[fab.lot_id[lot]] = round(max(0.0, finish - self.due[lot]) / 3600.0, 2)
        self.litho_busy = max(0.0, self.litho_busy)
        self.scanner_busy = max(0.0, self.scanner_busy)
        litho_tools = max(1, fab.litho_tools)
        scanners = max(1, fab.scanner_tools)
        queue_end: dict[str, int] = {name: 0 for name in fab.group_names}
        for fam, depth in enumerate(self.depth):
            queue_end[fab.families[fam].group] += depth
        down_tools: dict[str, int] = {name: 0 for name in fab.group_names}
        for tool, spans in enumerate(self.downs):
            if any(start < self.horizon and stop > 0 for start, stop in spans):
                group = fab.families[fab.tool_family[tool]].group
                down_tools[group] += 1
        return RunResult(
            policy=self.policy,
            seed=self.seed,
            horizon_sec=self.horizon,
            on_time_pct=round(100.0 * on_time / denom, 2) if denom else 100.0,
            weighted_tardiness_min=round(tardiness, 1),
            due_in_horizon=denom,
            already_late=already,
            completed_routes=completed,
            cycle_time_h=round(cycle_sum / completed / 3600.0, 2) if completed else None,
            mean_step_cycle_min=round(self.step_cycle / self.steps_done / 60.0, 2)
            if self.steps_done
            else 0.0,
            litho_util_pct=round(100.0 * self.litho_busy / (litho_tools * self.horizon), 2),
            scanner_util_pct=round(100.0 * self.scanner_busy / (scanners * self.horizon), 2),
            qtime_violations=self.violations,
            pm_avoided=self.pm_avoided,
            pm_overlaps=self.pm_overlaps,
            wip_replans=self.wip_replans,
            dispatch_p50_ms=round(_percentile(self.samples, 50) * 1000.0, 4),
            dispatch_p95_ms=round(_percentile(self.samples, 95) * 1000.0, 4),
            dispatch_decisions=len(self.samples),
            dispatch_busy_p50_ms=round(_percentile(self.busy_samples, 50) * 1000.0, 4),
            dispatch_busy_p95_ms=round(_percentile(self.busy_samples, 95) * 1000.0, 4),
            dispatch_busy_decisions=len(self.busy_samples),
            sim_s=round(elapsed, 3),
            focus_queue_max=self.focus_queue_max,
            sibling_starts=self.sibling_starts,
            downstream_queue_max=self.downstream_max,
            hot_steps=self.hot_steps,
            hot_scanner_start_min=None if self.hot_scanner is None else round(self.hot_scanner, 1),
            queue_end=queue_end,
            down_tools=down_tools,
            occupancy=self.occupancy,
            focus_bars=self.focus_bars,
            watched_late_h=watched,
            mean_x_factor=mean_x,
            qtime_gates=self.gated,
            recleans=self.recleans,
            down_starts=self.down_starts,
            events=self.events,
        )
