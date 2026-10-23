"""Event-driven dispatch on the full SMT2020 fab.

One decision looks only at the station family of the tool that just went idle,
and only at a bounded look-ahead inside that queue. Breakdown clocks are
exponential MTTF/MTTR from ``downcal.txt``, one clock per tool. ResiliMES
refuses a start that would run across the next PM. EDD, FIFO, and CR do not.

Transport (``fromto``), operators, and fractional rework are not in this loop.
A lot becomes ready for the next step when the current step ends.
"""

from __future__ import annotations

import heapq
import random
import time
from dataclasses import dataclass, field

from resilimes.kernel.score import dynamic_priority, ped_risk
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
) -> RunResult:
    if policy not in {"resilimes", "edd", "fifo", "cr"}:
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
    ) -> None:
        self.fab = fab
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
        if self.policy == "resilimes" and self.depth[fam] > self.threshold[fam]:
            if not self.seen_over[fam]:
                self.seen_over[fam] = True
                self.wip_replans += 1
        elif self.depth[fam] <= self.threshold[fam]:
            self.seen_over[fam] = False
        if self.idle[fam]:
            tool = self.idle[fam].pop()
            self.try_start(tool, moment)

    def note_depth(self, fam: int) -> None:
        if fam == self.focus_fam and self.depth[fam] > self.focus_queue_max:
            self.focus_queue_max = self.depth[fam]
        if fam in self.downstream and self.depth[fam] > self.downstream_max:
            self.downstream_max = self.depth[fam]

    def live(self, fam: int) -> list[int]:
        rows = [lot for lot in self.queues[fam] if self.waiting[lot]]
        self.queues[fam] = rows
        return rows

    def choose(self, tool: int, moment: float) -> tuple[list[int], float | None]:
        t0 = time.perf_counter()
        fam = self.fab.tool_family[tool]
        pool = self.live(fam)
        if not pool:
            self.samples.append(time.perf_counter() - t0)
            return [], None
        limit = (
            8 if self.policy == "resilimes" and self.depth[fam] > self.threshold[fam] else LOOKAHEAD
        )
        if len(pool) > limit:
            pool = (
                pool[:limit]
                if self.policy == "fifo"
                else heapq.nsmallest(limit, pool, key=lambda lot: self.cheap(lot, moment))
            )
        pm_start = self.next_pm_start(tool, moment) if self.policy == "resilimes" else None
        feasible: list[int] = []
        skipped = False
        for lot in pool:
            route = self.fab.routes[self.fab.lot_route[lot]]
            index = self.step[lot]
            proc = route.cycle[index] + setup_seconds(
                self.fab, fam, self.tool_recipe[tool], route.recipe[index]
            )
            if self.policy == "resilimes" and pm_start is not None and moment + proc > pm_start:
                skipped = True
                continue
            feasible.append(lot)
        if skipped:
            # One refused start per decision. The same lot can be seen again later.
            self.pm_avoided += 1
        if not feasible:
            self.samples.append(time.perf_counter() - t0)
            return [], pm_start
        singles: list[int] = []
        batches: list[int] = []
        for lot in feasible:
            route = self.fab.routes[self.fab.lot_route[lot]]
            if route.batch_max[self.step[lot]] > 0:
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
        self.samples.append(time.perf_counter() - t0)
        return chosen, wake_at

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

    def rank(self, lot: int, tool: int, moment: float) -> tuple[float, float, int]:
        if self.policy == "fifo":
            return (self.ready[lot], self.due[lot], lot)
        if self.policy == "edd":
            return (self.due[lot], self.ready[lot], lot)
        if self.policy == "cr":
            return (self.cr(lot, moment), self.due[lot], lot)
        fam = self.fab.tool_family[tool]
        route = self.fab.routes[self.fab.lot_route[lot]]
        setup = setup_seconds(self.fab, fam, self.tool_recipe[tool], route.recipe[self.step[lot]])
        score = self.dpi(lot, moment) - (setup / 60.0) + self.ped(lot, moment)
        return (-score, self.ready[lot], lot)

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
        covered = _covering(self.downs[tool], moment)
        if covered is not None:
            return
        if self.policy == "resilimes":
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
        setup = setup_seconds(self.fab, fam, self.tool_recipe[tool], route.recipe[index])
        proc = route.cycle[index]
        started: list[int] = []
        for lot in chosen:
            if not self.waiting[lot] or self.step[lot] != index:
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
        self.tool_gen[tool] += 1
        self.running[tool] = started[0]
        self.on_tool[tool] = started
        self.tool_recipe[tool] = route.recipe[index]
        finish = moment + setup + proc
        if self.policy != "resilimes" and self.overlaps_pm(tool, moment, setup + proc):
            self.pm_overlaps += 1
        self.push(finish, _DONE, tool, self.tool_gen[tool])
        self.busy_until[tool] = finish
        self.busy_litho[tool] = self.fab.families[fam].litho
        self.busy_scanner[tool] = self.fab.families[fam].scanner
        self.account(tool, fam, moment, finish, started)

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
        if fam == self.focus_fam and moment < 12 * 3600 and len(self.focus_bars) < 400:
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
        if lot == self.hot_lot:
            self.hot_steps += 1
        if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
            self.deadline[lot] = moment + route.cqt_limit[index]
            self.cqt_limit[lot] = route.cqt_limit[index]
            self.cqt_at[lot] = route.cqt_target[index]
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
            for lot in lots:
                self.enqueue(lot, moment)
        end_at = None
        for start_at, stop in self.downs[tool]:
            if start_at <= moment < stop:
                end_at = stop
                break
        if end_at is not None:
            self.push(end_at, _DOWN_END, tool)

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
        )
