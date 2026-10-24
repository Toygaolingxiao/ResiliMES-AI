"""Event-driven dispatch on the full SMT2020 fab.

One decision looks only at the station family of the tool that just went idle,
and only at a bounded look-ahead inside that queue. Breakdown clocks are
exponential MTTF/MTTR from ``downcal.txt``, one clock per tool. Every policy
refuses a start that falls inside a PM or whose process would cross the next PM.

Transport is a fixed move between steps (same STNGRP bay 1 min, other bay
3 min, ``transport_seconds``), the same for every policy; the SMT2020
``fromto`` row (one Fab-to-Fab distribution) is not used. Operators, reticle copies, and
the published fractional rework probability are not in this loop. A litho
layer with ``SVESTN`` / ``FORSTEP`` stays on the scanner that ran the first
layer of that chain, once this run has chosen it. WIP does not name a tool,
so a lot that starts mid-chain is not pinned until then. A lot in process
when a tool breaks goes to rework: it waits ``REWORK_SEC`` (30 minutes), then
redoes the whole operation from the family queue on any qualified tool. No
start is ever made on a tool inside a down window. A litho lot whose
dedicated scanner is down may run on another scanner of the family and is
re-pinned there. A lot becomes ready for the next step one transport time
after the current step ends. Same-recipe lots batch together even when their step numbers differ.
"""

from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from resilimes.kernel.score import class_tier, dynamic_priority, ped_risk, tiered_key
from resilimes.smt.fab import (
    BATCH_MAX_WAIT_SEC,
    HOT_BATCH_WAIT_SEC,
    LOOKAHEAD,
    QTIME_URGENT_MARGIN_SEC,
    RESERVE_MAX_SEC,
    REWORK_SEC,
    WIP_FLOOR,
    WIP_PER_TOOL,
    Fab,
    inherited_windows,
    lot_number,
    measured,
    transport_seconds,
)

_DONE = 0
_DOWN_START = 1
_DOWN_END = 2
_WAKE = 3
# A lot reaches the next family's queue after its transport. The slot holds the lot.
_ARRIVE = 4
# The latest start of a lot's open Q-time window. The slot holds the lot and
# gen holds the window generation (qgen), so a closed window's event is stale.
_QDEADLINE = 5
# Scheduling tick (all policies): refresh the live wait estimates, set the
# reservation hold plan and release stale holds, count stalled idle tools,
# snapshot the plan. It never starts a lot: dispatch stays event-triggered.
_TICK = 6
REPLAN_SEC = 300.0
_BIN_SEC = 900.0
_BUCKETS = ("met", "late", "held", "recleaned", "expired", "live", "skipped")
_MISSED = ("late", "held", "recleaned", "expired")
_WAFERS = 25
# The deadline event fires just after the latest start, so a start exactly at
# the deadline still counts as met.
_DEADLINE_EPS = 1e-3
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
    # Batch starts, lots in them, and why each under-BATCHMN batch started.
    batch_starts: int = 0
    batch_lots: int = 0
    batch_reasons: dict[str, int] = field(default_factory=dict)
    # Lots chosen for a start that did not start. Must stay 0.
    batch_dropped: int = 0
    setup_min: float = 0.0
    # Lots sent to rework by a breakdown, and the lot-minutes of rework hold.
    reworks: int = 0
    rework_lot_min: float = 0.0
    # Litho lots moved off a down dedicated scanner.
    repins: int = 0
    # Mean queue wait per started step, by class tier (VIP, hot, normal).
    class_wait_min: dict[str, float] = field(default_factory=dict)
    # Sampled metrology steps a lot skipped (StepPercent < 100, lot-ID rule),
    # and Q-time windows that ended because their target step was skipped.
    skipped: int = 0
    qtime_skipped: int = 0
    # Q-time-urgent overrides (ResiliMES only): starts led by a lot that would
    # miss its open dataset CQT window, ahead of the lot the plain tiered key
    # picks. Counted by the class of the displaced lot.
    transport: bool = True
    qtime_overrides: int = 0
    qtime_override_displaced: dict[str, int] = field(default_factory=dict)
    # Q-time window outcomes. Windows opened in this run (a CQT origin step
    # ended): met (target started by the deadline), late (started after it),
    # held (the deadline passed un-started and the lot went to Q-time hold),
    # recleaned, expired (deadline at or before the horizon, still open), live
    # (deadline after the horizon), skipped (sampling skipped the target).
    # ``qtime_violations`` = late + held + recleaned + expired.
    qtime_windows: dict[str, int] = field(default_factory=dict)
    # The same buckets for windows inherited from the snapshot (a lot already
    # inside a CQT span at t=0, ``inherited_windows``). Not in qtime_violations.
    qtime_inherited: dict[str, int] = field(default_factory=dict)
    qtime_met: int = 0
    qtime_late: int = 0
    qtime_held: int = 0
    qtime_recleaned: int = 0
    qtime_expired: int = 0
    qtime_rate_pct: float | None = None
    qtime_inherited_windows: int = 0
    qtime_inherited_missed: int = 0
    # Lot-minutes of Q-time hold (deadline passed, not reworkable), apart from
    # the breakdown rework hold in rework_lot_min.
    qtime_hold_lot_min: float = 0.0
    qtime_holds: int = 0
    batch_cap_lots: int = 0
    batch_fill_pct: float | None = None
    batch_short_full: int = 0
    qtime_shortlist_added: int = 0
    tool_reservations: int = 0
    reserved_min: float = 0.0
    reserve_used: int = 0
    reserve_elsewhere: int = 0
    reserve_expired: int = 0
    reserve_cancelled: int = 0
    reserve_replanned: int = 0
    replan_ticks: int = 0
    replan_stalls: int = 0
    replan_stalls_batch: int = 0
    replan_tick_p50_ms: float = 0.0
    replan_tick_p95_ms: float = 0.0
    replan_tick_total_s: float = 0.0
    flow_wait_ratio: float = 0.0


def rework_ready(moment: float) -> float:
    """Earliest restart of a lot that was in process when its tool broke.

    The work in process is lost. The lot redoes the whole operation, with
    setup, on any qualified tool once the rework hold is over.
    """
    return moment + REWORK_SEC


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
    transport: bool = True,
    deadline_event: bool = True,
    r2_policy: bool = True,
    r2_fixes: tuple[int, ...] = (1, 2, 3),
    replan_sec: float = REPLAN_SEC,
) -> RunResult:
    """One run. ``deadline_event`` (all policies) sends an un-started lot to
    re-clean or Q-time hold at its latest start. ``r2_policy`` turns on the
    ResiliMES-only Q-time r2 dispatch rules (shortlist admission, graded
    urgency, bounded tool reservation); False is the ablation. ``r2_fixes``
    picks which of fixes 1-3 are on (per-fix ablation). ``replan_sec`` is the
    re-evaluation tick period for every policy (0 turns the tick off)."""
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
        transport=transport,
        deadline_event=deadline_event,
        r2_policy=r2_policy,
        r2_fixes=r2_fixes,
        replan_sec=replan_sec,
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


def _step_key(route_i: int, index: int) -> int:
    return route_i * 100_000 + index


def _feeds(fab: Fab) -> dict[tuple[int, int], list[int]]:
    """(family, recipe) of every batch step -> the route steps right before it."""
    found: dict[tuple[int, int], list[int]] = {}
    for route_i, route in enumerate(fab.routes):
        for index in range(len(route.family) - 1):
            nxt = index + 1
            if route.batch_max[nxt] > 0:
                key = (route.family[nxt], route.recipe[nxt])
                found.setdefault(key, []).append(_step_key(route_i, index))
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
        transport: bool = True,
        deadline_event: bool = True,
        r2_policy: bool = True,
        r2_fixes: tuple[int, ...] = (1, 2, 3),
        replan_sec: float = REPLAN_SEC,
    ) -> None:
        self.fab = fab
        self.r2 = r2_policy and policy == "resilimes"
        # Per-fix switches: 1 shortlist admission, 2 dynamic risk order,
        # 3 bounded tool reservation.
        self.fix1 = self.r2 and 1 in r2_fixes
        self.fix2 = self.r2 and 2 in r2_fixes
        self.fix3 = self.r2 and 3 in r2_fixes
        self.replan_sec = replan_sec
        self.record = record
        self.transport = transport
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
        self.lot_tool = [-1] * self.n
        # Lots in process per (route, step), and the steps that feed each
        # (family, recipe) batch step. Used to predict batch arrivals.
        self.inproc: dict[int, set[int]] = {}
        self.feeds = _feeds(fab)
        self.batch_starts = 0
        self.batch_lots = 0
        self.batch_reasons: dict[str, int] = {}
        self.batch_dropped = 0
        self.setup_sec = 0.0
        self.reworks = 0
        self.repins = 0
        self.class_wait: dict[str, float] = {}
        self.skipped = 0
        self.qtime_skipped = 0
        self.lot_no = [lot_number(name, lot) for lot, name in enumerate(fab.lot_id)]
        self.class_starts: dict[str, int] = {}
        self.overrides = 0
        self.override_displaced: dict[str, int] = {}
        # Set by choose(): (lead lot, displaced lot, remaining s, need s).
        self.pending_override: tuple[int, int, float, float] | None = None
        # Q-time window bookkeeping. qgen changes whenever a lot's window opens
        # or closes, so a stale deadline event can be told apart.
        self.inherited = [False] * self.n
        self.qgen = [0] * self.n
        self.qout: dict[str, int] = dict.fromkeys(_BUCKETS, 0)
        self.qinh: dict[str, int] = dict.fromkeys(_BUCKETS, 0)
        self.hold_sec = 0.0
        # Q-time lots added to a capped shortlist by the r2 admission rule.
        self.shortlist_added = 0
        # Batch fill: lots started over batch capacity in lots (BATCHMX / 25).
        self.batch_cap_lots = 0
        # Batches started under capacity while the whole ready queue held a
        # full batch of that recipe (eligible, PM and gate not checked).
        self.batch_short_full = 0
        self.last_recipe_ready: dict[int, int] = {}
        # Q-time r2 fix 3: bounded tool reservation (ResiliMES). Lots heading
        # to a family inside an open window: lot -> (eta, latest start, step).
        self.inbound: list[dict[int, tuple[float, float, int]]] = [{} for _ in fab.families]
        tools = len(fab.tool_family)
        self.res_lot = [-1] * tools
        self.res_since = [0.0] * tools
        self.res_until = [0.0] * tools
        # A tool must start a lot between two reservations (no chains).
        self.res_cool = [False] * tools
        self.res_fam = [-1] * len(fab.families)
        self.res_by_lot: dict[int, int] = {}
        self.res_count = 0
        self.res_sec = 0.0
        self.res_out = {"used": 0, "elsewhere": 0, "expired": 0, "cancelled": 0, "replan": 0}
        # Live estimates, refreshed at every tick: expected wait (s) before a
        # lot arriving now could start at each family, and the fab-wide ratio
        # of observed queue time to raw process time.
        self.fam_wait = [0.0] * len(fab.families)
        self.flow_wait = 0.0
        self.wait_sum = 0.0
        self.proc_sum = 0.0
        self.risk_at = -1.0
        self.risk_memo: dict[int, tuple[int, int, float, float]] = {}
        self.wakes = [0] * tools
        self.ticks = 0
        self.tick_stalls = 0
        self.tick_stalls_batch = 0
        # Scheduling layer, fix 3: inbound Q-time lots that warrant a held
        # tool, per family, set at each tick. Dispatch honours it at events.
        self.hold_plan: list[list[int]] = [[] for _ in fab.families]
        self.tick_samples: list[float] = []
        self.last_replan: tuple[float, dict[int, tuple[int, ...]], dict[int, int]] | None = None
        self.batch_family = [False] * len(fab.families)
        for route in fab.routes:
            for index, cap in enumerate(route.batch_max):
                if cap > 0:
                    self.batch_family[route.family[index]] = True
        self.held = 0
        self.q_pending = [False] * self.n
        self.deadline_event = deadline_event

    def push(self, moment: float, kind: int, tool: int, gen: int = 0) -> None:
        if moment > self.horizon:
            return
        self.seq += 1
        if kind == _WAKE:
            self.wakes[tool] += 1
        heapq.heappush(self.heap, (moment, self.seq, kind, tool, gen))

    def run(self) -> RunResult:
        started = time.perf_counter()
        for lot, origin, target, limit in inherited_windows(self.fab):
            self.open_window(lot, origin, target, limit, 0.0, inherited=True)
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
        if self.replan_sec > 0:
            self.refresh_estimates(0.0)
            self.push(self.replan_sec, _TICK, -1)
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
            elif kind == _ARRIVE:
                self.enqueue(tool, moment)
            elif kind == _QDEADLINE:
                self.q_deadline(tool, moment, gen)
            elif kind == _TICK:
                self.tick(moment)
            elif kind in (_DOWN_END, _WAKE):
                if kind == _WAKE:
                    self.wakes[tool] -= 1
                self.release_idle(tool)
                self.try_start(tool, moment)
            steps += 1
            if steps > 2_000_000:
                raise RuntimeError("SMT simulation exceeded 2e6 events")
        return self.finish(time.perf_counter() - started)

    def open_window(
        self,
        lot: int,
        origin: int,
        target: int,
        limit: float,
        moment: float,
        *,
        inherited: bool = False,
    ) -> None:
        """A dataset CQT window opens: ``target`` must start by moment + limit."""
        self.deadline[lot] = moment + limit
        self.cqt_limit[lot] = limit
        self.cqt_at[lot] = target
        self.cqt_from[lot] = origin
        self.inherited[lot] = inherited
        self.qgen[lot] += 1
        self.q_pending[lot] = False
        if self.deadline_event:
            self.push(moment + limit + _DEADLINE_EPS, _QDEADLINE, lot, self.qgen[lot])

    def close_window(self, lot: int, outcome: str) -> None:
        """Count the window's outcome once and close it."""
        bucket = self.qinh if self.inherited[lot] else self.qout
        bucket[outcome] += 1
        if lot in self.res_by_lot:
            self.release(self.res_by_lot[lot], self.clock, "cancelled")
        if outcome in _MISSED and not self.inherited[lot]:
            self.violations += 1
        self.cqt_at[lot] = -1
        self.inherited[lot] = False
        self.qgen[lot] += 1
        self.q_pending[lot] = False

    def q_deadline(self, lot: int, moment: float, gen: int) -> None:
        """The latest start passed with the target step not started.

        A lot waiting in a queue (at the target or an earlier step of the span)
        is handled now. A lot in process, in transit or in breakdown rework is
        handled when it next reaches a queue.
        """
        if gen != self.qgen[lot] or self.cqt_at[lot] < 0:
            return
        if self.waiting[lot]:
            self.expire(lot, moment, queued=True)
        else:
            self.q_pending[lot] = True

    def expire(self, lot: int, moment: float, *, queued: bool) -> None:
        """Re-clean (Wet_Etch origin, first miss) or Q-time hold, then requeue."""
        fam = self.step_family(lot)
        if self._can_reclean(lot, moment):
            self._reclean(lot, fam, moment, queued=queued)
            return
        index = self.step[lot]
        target = self.cqt_at[lot]
        self.close_window(lot, "held")
        if queued:
            self.waiting[lot] = False
            self.depth[fam] = max(0, self.depth[fam] - 1)
            if lot in self.queues[fam]:
                self.queues[fam].remove(lot)
        self.held += 1
        self.hold_sec += max(0.0, min(REWORK_SEC, self.horizon - moment))
        if self.record:
            self.events.append(("qhold", moment, lot, index, target))
        self.push(moment + REWORK_SEC, _ARRIVE, lot)

    def enqueue(self, lot: int, moment: float) -> None:
        if self.q_pending[lot] and self.cqt_at[lot] >= 0:
            self.expire(lot, moment, queued=False)
            return
        self.q_pending[lot] = False
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

    def send(self, lot: int, moment: float, origin: int, target: int) -> None:
        """Queue the lot at ``target`` once it has been moved there from ``origin``."""
        move = self.move_seconds(origin, target)
        if move <= 0:
            self.enqueue(lot, moment)
        else:
            self.push(moment + move, _ARRIVE, lot)

    def move_seconds(self, origin: int, target: int) -> float:
        """Transport from one family to the next. 0 only for the no-transport ablation."""
        if not self.transport:
            return 0.0
        return transport_seconds(self.fab, origin, target)

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

    def step_family(self, lot: int) -> int:
        return self.fab.routes[self.fab.lot_route[lot]].family[self.step[lot]]

    def live(self, fam: int) -> list[int]:
        """Lots waiting for a step of this family.

        ``try_start`` drops a started lot from its queue. The family check
        keeps a lot whose step has moved on out of a queue it no longer
        belongs to, so a tool never starts a step of another family.
        """
        rows = [
            lot for lot in self.queues[fam] if self.waiting[lot] and self.step_family(lot) == fam
        ]
        self.queues[fam] = rows
        return rows

    def _sample(self, t0: float, nonempty: bool) -> None:
        elapsed = time.perf_counter() - t0
        self.samples.append(elapsed)
        if nonempty:
            self.busy_samples.append(elapsed)

    def choose(self, tool: int, moment: float) -> tuple[list[int], float | None, str]:
        t0 = time.perf_counter()
        fam = self.fab.tool_family[tool]
        pool = [lot for lot in self.live(fam) if self.eligible(lot, tool, moment)]
        if not pool:
            self._sample(t0, False)
            return [], None, ""
        ready_pool = [lot for lot in pool if self.ready[lot] <= moment + 1e-6]
        if not ready_pool:
            wake = min(self.ready[lot] for lot in pool)
            self._sample(t0, False)
            return [], wake, ""
        pool = ready_pool
        whole = pool
        over_cap = self.policy == "resilimes" and self.depth[fam] > self.threshold[fam]
        limit = 8 if over_cap else LOOKAHEAD
        if self.policy == "smt_rule":
            # The dataset cascade ranks the whole queue. The candidate cap is ResiliMES.
            limit = len(pool)
        if len(pool) > limit:
            if self.policy == "fifo":
                pool = pool[:limit]
            else:

                def _cheap(lot: int) -> tuple[float, ...]:
                    return self.cheap(lot, moment)

                ranked = heapq.nsmallest(limit, pool, key=_cheap)
                if over_cap:
                    kept = set(ranked)
                    for lot in pool:
                        if lot not in kept and self._slack(lot, moment) <= SLACK_CANDIDATE_SEC:
                            ranked.append(lot)
                pool = ranked
            if self.fix1:
                # Q-time r2 shortlist (ResiliMES): every lot inside an open
                # dataset CQT window is a candidate, highest live risk first.
                kept = set(pool)
                windowed = [lot for lot in whole if lot not in kept and self.in_window(lot)]
                windowed.sort(key=lambda lot: -self.risk(lot, moment)[0])
                self.shortlist_added += len(windowed)
                pool = pool + windowed
        # Furnace batching sees the whole same-recipe family queue, not only
        # the shortlist: a lot cut by the candidate cap can still fill a batch.
        # Singles still come from the shortlist. Shared by every policy.
        candidates = pool
        self.last_recipe_ready = {}
        if self.batch_family[fam]:
            for lot in whole:
                route = self.fab.routes[self.fab.lot_route[lot]]
                index = self.step[lot]
                if route.batch_max[index] > 0:
                    recipe = route.recipe[index]
                    self.last_recipe_ready[recipe] = self.last_recipe_ready.get(recipe, 0) + 1
            if len(whole) > len(pool):
                kept = set(pool)
                extra = [
                    lot
                    for lot in whole
                    if lot not in kept
                    and self.fab.routes[self.fab.lot_route[lot]].batch_max[self.step[lot]] > 0
                ]
                candidates = pool + extra
        pm_start = self.next_pm_start(tool, moment)
        feasible: list[int] = []
        skipped = False
        gated = False
        gate_wake: float | None = None
        for lot in candidates:
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
            return [], gate_wake if gate_wake is not None else pm_start, ""
        singles: list[int] = []
        batches: list[int] = []
        for lot in feasible:
            route = self.fab.routes[self.fab.lot_route[lot]]
            if route.batch_max[self.step[lot]] > 0:
                batches.append(lot)
            else:
                singles.append(lot)
        chosen: list[int] = []
        reason = ""
        batch_wake: float | None = None
        if batches:
            chosen, reason, batch_wake = self.pick_batch(batches, tool, moment)
        if singles:
            single = min(singles, key=lambda lot: self.rank(lot, tool, moment))
            if not chosen or self.rank(single, tool, moment) < self.rank(chosen[0], tool, moment):
                chosen = [single]
                reason = ""
        wake_at = batch_wake if not chosen else None
        self.pending_override = None
        if chosen and self.policy == "resilimes":
            urgent = self.qtime_urgent(chosen[0], moment)
            if urgent is not None:
                plain = min(feasible, key=lambda lot: self.plain_rank(lot, tool, moment))
                if plain not in chosen:
                    self.pending_override = (chosen[0], plain, urgent[0], urgent[1])
        self._sample(t0, True)
        return chosen, wake_at, reason

    def in_window(self, lot: int) -> bool:
        """The lot is inside an open dataset CQT window (target not started)."""
        return self.cqt_at[lot] >= self.step[lot] and self.deadline[lot] > 0

    def _slack(self, lot: int, moment: float) -> float:
        route = self.fab.routes[self.fab.lot_route[lot]]
        return self.due[lot] - moment - route.remain[self.step[lot]]

    def pin_for(self, lot: int, index: int) -> int:
        """The scanner this step is pinned to, or -1.

        A pin binds only the later steps of the layer that set it: the step
        has a dedication root before it, and the pinned scanner is in this
        step's family. The root step of a new layer chooses freely. Before
        Q-time r2 the pin from an earlier layer also bound the root of the
        next layer, even in another litho family, and no tool there could
        ever start the lot unless the old scanner was down (found by the
        2-hour litho stress; ``docs/QTIME_R2.md``).
        """
        route = self.fab.routes[self.fab.lot_route[lot]]
        root = route.dedicate_root[index]
        pinned = self.dedicate_tool[lot]
        if root < 0 or root >= index or pinned < 0:
            return -1
        if self.fab.tool_family[pinned] != route.family[index]:
            return -1
        return pinned

    def eligible(self, lot: int, tool: int, moment: float) -> bool:
        """The dedicated scanner after layer 1, unless that scanner is down."""
        pinned = self.pin_for(lot, self.step[lot])
        if pinned < 0 or pinned == tool:
            return True
        return _covering(self.downs[pinned], moment) is not None

    def piece_seconds(self, lot: int, tool: int) -> float:
        """Full process plus setup from the recipe the tool holds now."""
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
        move = self.move_seconds(route.family[index], target)
        return self._earliest_tool(target, moment + proc + move)

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

    def pick_batch(
        self, lots: list[int], tool: int, moment: float
    ) -> tuple[list[int], str, float | None]:
        """Same-recipe lots batch together, whatever their route or step number.

        Each recipe group is ordered by this policy's own rank, so the highest
        priority lot leads and fills first. Returns the best startable group,
        the reason it may start (``min_met`` or, under BATCHMN, ``hot_cap``,
        ``max_wait``, ``no_arrivals``), and the earliest wake of a group that
        is still waiting for expected arrivals.
        """
        fam = self.fab.tool_family[tool]
        grouped: dict[int, list[int]] = {}
        for lot in lots:
            route = self.fab.routes[self.fab.lot_route[lot]]
            grouped.setdefault(route.recipe[self.step[lot]], []).append(lot)
        best: list[int] = []
        best_reason = ""
        best_key: tuple[float, ...] | None = None
        wake: float | None = None
        for recipe, group in grouped.items():
            ordered = sorted(group, key=lambda lot: self.rank(lot, tool, moment))
            head = ordered[0]
            route = self.fab.routes[self.fab.lot_route[head]]
            index = self.step[head]
            cap = route.batch_max[index]
            floor = route.batch_min[index] or cap
            taken = ordered[: max(1, cap // _WAFERS)] if cap else ordered
            wafers = len(taken) * _WAFERS
            reason, until = self.batch_rule(taken, group, fam, recipe, wafers, floor, moment)
            if until is not None:
                wake = until if wake is None else min(wake, until)
                continue
            key = self.rank(head, tool, moment)
            if best_key is None or key < best_key:
                best = taken
                best_reason = reason
                best_key = key
        return best, best_reason, wake

    def batch_rule(
        self,
        taken: list[int],
        group: list[int],
        fam: int,
        recipe: int,
        wafers: int,
        floor: int,
        moment: float,
    ) -> tuple[str, float | None]:
        """Start now (reason, None) or wait until a time ("", t).

        At or above BATCHMN the batch starts. Under it, the batch waits only
        while enough same-recipe lots are in process at the step right before
        this one and will finish before the wait cap. The cap is
        BATCH_MAX_WAIT_SEC after the oldest ready lot, or HOT_BATCH_WAIT_SEC
        after the first ready hot or VIP member, whichever is earlier.
        """
        if wafers >= floor:
            return "min_met", None
        if self.policy == "resilimes" and any(
            self.qtime_urgent(lot, moment) is not None for lot in taken
        ):
            return "qtime_urgent", None
        cap_at = min(self.ready[lot] for lot in group) + BATCH_MAX_WAIT_SEC
        hot = [self.ready[lot] for lot in taken if self.tier(lot) < 2]
        if hot and min(hot) + HOT_BATCH_WAIT_SEC < cap_at:
            cap_at = min(hot) + HOT_BATCH_WAIT_SEC
            if moment >= cap_at - 1e-6:
                return "hot_cap", None
        if moment >= cap_at - 1e-6:
            return "max_wait", None
        need = -(-(floor - wafers) // _WAFERS)
        if self.expected_arrivals(fam, recipe, cap_at) < need:
            return "no_arrivals", None
        return "", cap_at

    def expected_arrivals(self, fam: int, recipe: int, until: float) -> int:
        count = 0
        for key in self.feeds.get((fam, recipe), ()):
            for lot in self.inproc.get(key, ()):
                if self.busy_until[self.lot_tool[lot]] <= until:
                    count += 1
        return count

    def lot_kind(self, lot: int) -> str:
        if self.promote_hot and lot == self.hot_lot:
            return "VIP"
        return self.fab.lot_class[lot]

    def tier(self, lot: int) -> int:
        """0 VIP, 1 hot, 2 normal, from SMT2020 PRIOR (or the promoted hot lot)."""
        return class_tier(self.lot_kind(lot))

    def cheap(self, lot: int, moment: float) -> tuple[float, ...]:
        if self.policy == "edd":
            return (self.due[lot], self.ready[lot], lot)
        if self.policy == "cr":
            return (self.cr(lot, moment), self.due[lot], lot)
        if self.policy == "resilimes":
            band = float(self.urgency_band(lot, moment))
            if self.fix2:
                risk, least = self.risk(lot, moment)
                return (band, float(self.tier(lot)), -risk, least, self.ready[lot], lot)
            slack = self._slack(lot, moment)
            late = 0.0 if slack <= 0.0 else 1.0
            return (band, float(self.tier(lot)), late, slack, self.ready[lot], lot)
        return (self.ready[lot], self.due[lot], lot)

    def rank(self, lot: int, tool: int, moment: float) -> tuple[float, ...]:
        if self.policy == "resilimes":
            return (float(self.urgency_band(lot, moment)), *self.plain_rank(lot, tool, moment))
        return self.plain_rank(lot, tool, moment)

    def qtime_need(self, lot: int, here: int = -1, target: int = -1) -> float:
        """Seconds the lot still needs before its CQT target can start.

        Dataset process time of the current step and of each later measured
        step before the target, plus the fixed transport legs between them and
        into the target. No setup.
        """
        route = self.fab.routes[self.fab.lot_route[lot]]
        here = self.step[lot] if here < 0 else here
        target = self.cqt_at[lot] if target < 0 else target
        number = self.lot_no[lot]
        need = 0.0
        last = here
        for index in range(here, target):
            if index == here or measured(route, index, number):
                if index != here:
                    need += self.move_seconds(route.family[last], route.family[index])
                need += route.cycle[index]
                last = index
        if last != target:
            need += self.move_seconds(route.family[last], route.family[target])
        return need

    def qtime_urgent(self, lot: int, moment: float) -> tuple[float, float] | None:
        """(remaining, need) when the open dataset CQT window is lost unless started now.

        Only a lot inside an open window (opened at the end of a step whose
        SMT2020 CQT column is set) can be urgent. Urgent means
        ``need <= remaining <= need + QTIME_URGENT_MARGIN_SEC``.
        """
        target = self.cqt_at[lot]
        if target < 0 or self.deadline[lot] <= 0 or self.step[lot] > target:
            return None
        remaining = self.deadline[lot] - moment
        if remaining < 0:
            return None
        need = self.qtime_need(lot)
        if remaining < need or remaining > need + QTIME_URGENT_MARGIN_SEC:
            return None
        return remaining, need

    def urgency_band(self, lot: int, moment: float) -> int:
        """0 VIP/hot that is late or Q-time-urgent, 1 other Q-time-urgent, 2 the rest."""
        urgent = self.qtime_urgent(lot, moment) is not None
        if self.tier(lot) < 2 and (urgent or self._slack(lot, moment) <= 0.0):
            return 0
        return 1 if urgent else 2

    def plain_rank(self, lot: int, tool: int, moment: float) -> tuple[float, ...]:
        if self.policy == "fifo":
            return (self.ready[lot], self.due[lot], lot)
        if self.policy == "edd":
            return (self.due[lot], self.ready[lot], lot)
        if self.policy == "cr":
            return (self.cr(lot, moment), self.due[lot], lot)
        if self.policy == "smt_rule":
            return self.smt_rule_key(lot, tool, moment)
        # Tiered: class tier, late band, Q-time risk, setup, slack. No weights.
        fam = self.fab.tool_family[tool]
        route = self.fab.routes[self.fab.lot_route[lot]]
        setup = setup_seconds(self.fab, fam, self.tool_recipe[tool], route.recipe[self.step[lot]])
        if self.fix2:
            # Q-time r2 dynamic weight: one live risk for Q-time and due date.
            # A lot expected to miss (risk >= 1) goes first, most at risk
            # first. Below 1 setup avoidance comes first, then risk.
            risk, least = self.risk(lot, moment)
            tier = float(self.tier(lot))
            if risk >= 1.0:
                return (tier, 0.0, -risk, setup, least, self.ready[lot], float(lot))
            return (tier, 1.0, setup, -risk, least, self.ready[lot], float(lot))
        key = tiered_key(
            order_class=self.lot_kind(lot),
            slack_sec=self._slack(lot, moment),
            setup_sec=setup,
            ped=self.ped(lot, moment),
        )
        return (*key, self.ready[lot], float(lot))

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
        kind = self.lot_kind(lot)
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

    def risk(self, lot: int, moment: float) -> tuple[float, float]:
        """Q-time r2 dynamic weight (ResiliMES): (risk, least slack).

        risk = expected wait / remaining slack, per constraint, and the max of
        the two. No tuned constant: every term is live fab state.

        * Q-time (lot inside an open window): slack = deadline - now - need,
          need = process and transport still due before the target
          (``qtime_need``). Expected wait = live wait estimate here plus at
          every later measured step up to and including the target.
        * Due date: slack = due - now - remaining raw process. Expected wait =
          live wait estimate here plus the observed fab-wide queue/process
          ratio times the raw process still due after this step.

        Slack <= 0 is infinite risk. Wait estimates come from the last tick
        (``refresh_estimates``), so they are at most ``replan_sec`` old.
        """
        if moment != self.risk_at:
            self.risk_at = moment
            self.risk_memo = {}
        memo = self.risk_memo.get(lot)
        if memo is not None and memo[0] == self.step[lot] and memo[1] == self.qgen[lot]:
            return memo[2], memo[3]
        route = self.fab.routes[self.fab.lot_route[lot]]
        index = self.step[lot]
        here = self.fam_wait[route.family[index]]
        slack = self._slack(lot, moment)
        after = max(0.0, route.remain[index] - route.cycle[index])
        wait = here + self.flow_wait * after
        risk = math.inf if slack <= 0.0 else wait / slack
        least = slack
        if self.in_window(lot):
            q_slack = self.deadline[lot] - moment - self.qtime_need(lot)
            number = self.lot_no[lot]
            q_wait = here
            for nxt in range(index + 1, self.cqt_at[lot] + 1):
                if measured(route, nxt, number):
                    q_wait += self.fam_wait[route.family[nxt]]
            q_risk = math.inf if q_slack <= 0.0 else q_wait / q_slack
            risk = max(risk, q_risk)
            least = min(least, q_slack)
        self.risk_memo[lot] = (self.step[lot], self.qgen[lot], risk, least)
        return risk, least

    def refresh_estimates(self, moment: float) -> None:
        """Live expected wait per family and the fab-wide queue/process ratio.

        Wait at a family = (raw work queued there, a batch step counted per
        lot as its time over the batch size in lots, plus the residual time of
        its busy up tools) / tools up now. With no tool up: time until the
        first one is back plus the queued work over all tools.
        """
        self.risk_at = -1.0
        self.flow_wait = self.wait_sum / self.proc_sum if self.proc_sum > 0 else 0.0
        for fam, family in enumerate(self.fab.families):
            work = 0.0
            for lot in self.live(fam):
                route = self.fab.routes[self.fab.lot_route[lot]]
                index = self.step[lot]
                size = route.batch_max[index] // _WAFERS
                work += route.cycle[index] / max(1, size)
            up = 0
            back = math.inf
            for tool in range(family.tool0, family.tool0 + family.tools):
                gone = _covering(self.downs[tool], moment) or _covering(self.pm[tool], moment)
                if gone is not None:
                    back = min(back, gone[1])
                    continue
                up += 1
                if self.running[tool] >= 0:
                    work += max(0.0, self.busy_until[tool] - moment)
            if up:
                self.fam_wait[fam] = work / up
            elif family.tools:
                back = min(back, self.horizon)
                self.fam_wait[fam] = max(0.0, back - moment) + work / family.tools

    def tick(self, moment: float) -> None:
        """Scheduling tick, every ``replan_sec`` of sim time, all policies.

        Scheduling layer only; it never starts a lot (dispatch stays
        event-triggered and reads what the tick left behind):
        (a) refresh the live wait estimates; (b) ResiliMES fix 3: release a
        hold no longer needed and set the hold plan (which inbound Q-time
        lots warrant a held tool); (c) count an idle, up tool with an
        eligible ready lot and no pending wake (stall detector, count only);
        (d) with ``record``, snapshot each family's queue order and the next
        planned lot per tool.
        """
        t0 = time.perf_counter()
        self.ticks += 1
        self.refresh_estimates(moment)
        if self.fix3:
            self.plan_holds(moment)
        for tool in range(len(self.running)):
            if self.running[tool] >= 0 or self.wakes[tool] > 0 or self.res_lot[tool] >= 0:
                continue
            fam = self.fab.tool_family[tool]
            if not self.queues[fam]:
                continue
            if _covering(self.downs[tool], moment) or _covering(self.pm[tool], moment):
                continue
            ready = [
                lot
                for lot in self.live(fam)
                if self.ready[lot] <= moment + 1e-6 and self.eligible(lot, tool, moment)
            ]
            if not ready:
                continue
            self.tick_stalls += 1
            batch = all(
                self.fab.routes[self.fab.lot_route[lot]].batch_max[self.step[lot]] > 0
                for lot in ready
            )
            if batch:
                self.tick_stalls_batch += 1
            if self.record:
                self.events.append(("tick_stall", moment, tool, len(ready), batch))
        if self.record:
            self.snapshot(moment)
        self.tick_samples.append(time.perf_counter() - t0)
        self.push(moment + self.replan_sec, _TICK, -1)

    def plan_holds(self, moment: float) -> None:
        """Fix 3, scheduling side: review holds and set the hold plan.

        A held tool is released ("replan") when its lot is gone or no longer
        needs it: the live wait at the family is below the lot's Q-time slack
        on arrival. The plan lists, per family, the inbound lots that arrive
        before their latest start and within RESERVE_MAX_SEC of the next tick,
        whose Q-time risk on arrival is at least 1 (live wait at the family >=
        latest start - arrival), tightest first.
        """
        for tool in range(len(self.res_lot)):
            lot = self.res_lot[tool]
            if lot < 0:
                continue
            fam = self.fab.tool_family[tool]
            row = self.inbound[fam].get(lot)
            if (
                row is None
                or not self._inbound_live(lot, row[0], row[2], moment)
                or self.fam_wait[fam] < row[1] - max(moment, row[0])
            ):
                self.release(tool, moment, "replan")
        horizon = moment + self.replan_sec + RESERVE_MAX_SEC
        for fam, rows in enumerate(self.inbound):
            plan: list[tuple[float, int]] = []
            for lot in list(rows):
                eta, latest, nxt = rows[lot]
                if not self._inbound_live(lot, eta, nxt, moment):
                    del rows[lot]
                    continue
                if eta > latest or eta > horizon:
                    continue
                if self.fam_wait[fam] >= latest - eta:
                    plan.append((latest, lot))
            plan.sort()
            self.hold_plan[fam] = [lot for _latest, lot in plan]

    def snapshot(self, moment: float) -> None:
        """'replan' record: queue order per family, next planned lot per tool.

        Order is the policy's own shortlist key (``cheap``; FIFO by ready
        time). Tools take the head of the order in the order they come free
        (now, end of the running piece, end of a down or PM), each the first
        lot it is eligible for. A plan, not a promise: the event chain decides.
        """
        orders: dict[int, tuple[int, ...]] = {}
        plan: dict[int, int] = {}
        for fam, family in enumerate(self.fab.families):
            if not self.queues[fam]:
                continue
            rows = self.live(fam)
            if not rows:
                continue
            order = sorted(rows, key=lambda lot: self.cheap(lot, moment))
            orders[fam] = tuple(order)
            free: list[tuple[float, int]] = []
            for tool in range(family.tool0, family.tool0 + family.tools):
                gone = _covering(self.downs[tool], moment) or _covering(self.pm[tool], moment)
                if gone is not None:
                    at = gone[1]
                elif self.running[tool] >= 0:
                    at = self.busy_until[tool]
                else:
                    at = moment
                free.append((at, tool))
            free.sort()
            taken: set[int] = set()
            for _at, tool in free:
                for lot in order[:64]:
                    if lot not in taken and self.eligible(lot, tool, moment):
                        plan[tool] = lot
                        taken.add(lot)
                        break
        self.last_replan = (moment, orders, plan)
        self.events.append(("replan", moment, orders, plan))

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
            if self.res_lot[tool] >= 0:
                self.release(tool, moment, "cancelled")
            self.push(in_pm[1], _WAKE, tool)
            return
        fam = self.fab.tool_family[tool]
        if self.res_lot[tool] >= 0:
            held = self.res_lot[tool]
            if moment >= self.res_until[tool] - 1e-9:
                self.release(tool, moment, "expired")
            elif self.waiting[held] and self.step_family(held) == fam:
                self._start(tool, fam, moment, [held], "reserved")
                return
            else:
                if tool not in self.idle[fam]:
                    self.idle[fam].append(tool)
                return
        chosen, wake_at, reason = self.choose(tool, moment)
        # A chosen lot that missed its Q-time window goes back to re-clean
        # before the start, and the tool chooses again. Every lot of the final
        # choice starts.
        for _round in range(len(chosen) + 1):
            missed = [lot for lot in chosen if self._can_reclean(lot, moment)]
            if not missed:
                break
            for lot in missed:
                self._reclean(lot, fam, moment)
            if self.running[tool] >= 0:
                return
            chosen, wake_at, reason = self.choose(tool, moment)
        if not chosen:
            if wake_at is not None and wake_at > moment:
                self.push(wake_at, _WAKE, tool)
            if tool not in self.idle[fam]:
                self.idle[fam].append(tool)
            return
        if self.fix3 and self.maybe_reserve(tool, fam, chosen, moment):
            return
        self._start(tool, fam, moment, chosen, reason)

    def _start(self, tool: int, fam: int, moment: float, chosen: list[int], reason: str) -> None:
        started: list[int] = []
        steps: list[int] = []
        for lot in chosen:
            if not self.waiting[lot] or self.step_family(lot) != fam:
                self.batch_dropped += 1
                continue
            if lot in self.res_by_lot:
                holder = self.res_by_lot[lot]
                self.release(holder, moment, "used" if holder == tool else "elsewhere")
            index = self.step[lot]
            if self.cqt_at[lot] == index:
                late = self.deadline[lot] > 0 and moment > self.deadline[lot]
                self.close_window(lot, "late" if late else "met")
            self.waiting[lot] = False
            self.depth[fam] -= 1
            started.append(lot)
            steps.append(index)
        if not started:
            if tool not in self.idle[fam]:
                self.idle[fam].append(tool)
            return
        self.res_cool[tool] = False
        # A started lot leaves this queue now. Left in place, it is still
        # listed here when it waits again for its next step in another family.
        gone = set(started)
        self.queues[fam] = [lot for lot in self.queues[fam] if lot not in gone]
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
        # Batch time is the longest member. Setup is paid from the recipe the
        # tool holds now, before it switches.
        piece = max(self.piece_seconds(lot, tool) for lot in started)
        head_route = self.fab.routes[self.fab.lot_route[started[0]]]
        recipe = head_route.recipe[steps[0]]
        self.setup_sec += setup_seconds(self.fab, fam, self.tool_recipe[tool], recipe)
        self.tool_gen[tool] += 1
        self.running[tool] = started[0]
        self.on_tool[tool] = started
        self.tool_recipe[tool] = recipe
        for lot, index in zip(started, steps, strict=True):
            route = self.fab.routes[self.fab.lot_route[lot]]
            if route.dedicate_root[index] >= 0 and self.dedicate_tool[lot] != tool:
                if self.pin_for(lot, index) >= 0:
                    self.repins += 1
                self.dedicate_tool[lot] = tool
            self.lot_tool[lot] = tool
            kind = ("VIP", "hot", "normal")[self.tier(lot)]
            self.class_wait[kind] = self.class_wait.get(kind, 0.0) + moment - self.ready[lot]
            self.wait_sum += max(0.0, moment - self.ready[lot])
            self.proc_sum += route.cycle[index]
            self.class_starts[kind] = self.class_starts.get(kind, 0) + 1
            self.inproc.setdefault(_step_key(self.fab.lot_route[lot], index), set()).add(lot)
        if head_route.batch_max[steps[0]] > 0:
            self.batch_starts += 1
            self.batch_lots += len(started)
            cap_lots = max(1, head_route.batch_max[steps[0]] // _WAFERS)
            self.batch_cap_lots += cap_lots
            if len(started) < cap_lots and self.last_recipe_ready.get(recipe, 0) >= cap_lots:
                self.batch_short_full += 1
            if reason != "min_met":
                self.batch_reasons[reason] = self.batch_reasons.get(reason, 0) + 1
        finish = moment + piece
        self.piece_started[tool] = moment
        self.piece_proc[tool] = piece
        if self.overlaps_pm(tool, moment, piece):
            self.pm_overlaps += 1
        override = self.pending_override
        self.pending_override = None
        if override is not None and override[0] == started[0]:
            lead, plain, remaining, need = override
            displaced = ("VIP", "hot", "normal")[self.tier(plain)]
            self.overrides += 1
            self.override_displaced[displaced] = self.override_displaced.get(displaced, 0) + 1
            if self.record:
                self.events.append(
                    ("override", moment, tool, lead, steps[0], plain, remaining, need, displaced)
                )
        if self.record:
            self.events.append(
                ("start", moment, tool, tuple(started), tuple(steps), finish, reason, tuple(chosen))
            )
        self.push(finish, _DONE, tool, self.tool_gen[tool])
        self.busy_until[tool] = finish
        if self.fix3:
            for lot, index in zip(started, steps, strict=True):
                self.note_inbound(lot, fam, index, finish)
        self.busy_litho[tool] = self.fab.families[fam].litho
        self.busy_scanner[tool] = self.fab.families[fam].scanner
        self.account(tool, fam, moment, finish, started)

    def note_inbound(self, lot: int, fam: int, index: int, finish: float) -> None:
        """Remember a started lot that reaches its next step inside an open window."""
        route = self.fab.routes[self.fab.lot_route[lot]]
        number = self.lot_no[lot]
        nxt = index + 1
        while nxt < len(route.family) and not measured(route, nxt, number):
            nxt += 1
        if nxt >= len(route.family):
            return
        if route.cqt_limit[index] > 0 and route.cqt_target[index] >= nxt:
            deadline = finish + route.cqt_limit[index]
            target = route.cqt_target[index]
        elif self.cqt_at[lot] >= nxt and self.deadline[lot] > 0:
            deadline = self.deadline[lot]
            target = self.cqt_at[lot]
        else:
            return
        fam2 = route.family[nxt]
        eta = finish + self.move_seconds(fam, fam2)
        latest = deadline - self.qtime_need(lot, nxt, target)
        self.inbound[fam2][lot] = (eta, latest, nxt)

    def _inbound_live(self, lot: int, eta: float, nxt: int, moment: float) -> bool:
        if self.waiting[lot] or self.finished_at[lot] >= 0 or eta < moment - 1e-6:
            return False
        if self.lot_tool[lot] >= 0:
            return self.step[lot] < nxt
        return self.step[lot] == nxt and self.in_window(lot)

    def maybe_reserve(self, tool: int, fam: int, chosen: list[int], moment: float) -> bool:
        """Q-time r2 fix 3, dispatch side: honour the tick's hold plan.

        The lot must be on the family's hold plan (set by the scheduling tick,
        ``plan_holds``: Q-time risk on arrival >= 1). Then only when the chosen lead is an ordinary lot (normal class, band 2,
        not in a window, not a batch step), the inbound lot arrives within
        RESERVE_MAX_SEC and before its latest start, starting the lead here
        would run past that latest start, no other tool of the family is
        free by then, and the tool has no PM before the inbound piece ends.
        At most one tool per family, at most RESERVE_MAX_SEC, and a tool must
        start a lot between two reservations.
        """
        if self.res_fam[fam] >= 0 or self.res_cool[tool] or not self.hold_plan[fam]:
            return False
        lead = chosen[0]
        route = self.fab.routes[self.fab.lot_route[lead]]
        if route.batch_max[self.step[lead]] > 0 or len(chosen) > 1:
            return False
        if self.tier(lead) < 2 or self.in_window(lead) or self.urgency_band(lead, moment) < 2:
            return False
        if _covering(self.downs[tool], moment) is not None:
            return False
        done_at = moment + self.piece_seconds(lead, tool)
        family = self.fab.families[fam]
        best: tuple[float, int, float] | None = None
        rows = self.inbound[fam]
        for lot in self.hold_plan[fam]:
            if lot not in rows:
                continue
            eta, latest, nxt = rows[lot]
            if not self._inbound_live(lot, eta, nxt, moment):
                continue
            if lot in self.res_by_lot or eta > moment + RESERVE_MAX_SEC or eta > latest:
                continue
            if done_at <= latest:
                continue
            lot_route = self.fab.routes[self.fab.lot_route[lot]]
            pinned = self.pin_for(lot, nxt)
            pinned_up = pinned >= 0 and _covering(self.downs[pinned], moment) is None
            if pinned != tool and pinned_up:
                continue
            setup = setup_seconds(self.fab, fam, self.tool_recipe[tool], lot_route.recipe[nxt])
            if self.overlaps_pm(
                tool, moment, max(0.0, eta - moment) + lot_route.cycle[nxt] + setup
            ):
                continue
            free = False
            for other in range(family.tool0, family.tool0 + family.tools):
                if other == tool or self.res_lot[other] >= 0:
                    continue
                if _covering(self.downs[other], moment) is not None:
                    continue
                if _covering(self.pm[other], moment) is not None:
                    continue
                free_at = self.busy_until[other] if self.running[other] >= 0 else moment
                if free_at <= latest:
                    free = True
                    break
            if free:
                continue
            if best is None or latest < best[0]:
                best = (latest, lot, eta)
        if best is None:
            return False
        latest, lot, eta = best
        until = min(moment + RESERVE_MAX_SEC, latest)
        self.res_lot[tool] = lot
        self.res_since[tool] = moment
        self.res_until[tool] = until
        self.res_fam[fam] = tool
        self.res_by_lot[lot] = tool
        self.res_count += 1
        if self.record:
            self.events.append(("reserve", moment, tool, lot, until, eta))
        self.push(until, _WAKE, tool)
        if tool not in self.idle[fam]:
            self.idle[fam].append(tool)
        return True

    def release(self, tool: int, moment: float, outcome: str) -> None:
        """End a reservation: used, used elsewhere, expired or cancelled."""
        lot = self.res_lot[tool]
        if lot < 0:
            return
        fam = self.fab.tool_family[tool]
        self.res_sec += max(0.0, min(moment, self.horizon) - self.res_since[tool])
        self.res_out[outcome] += 1
        self.res_lot[tool] = -1
        self.res_fam[fam] = -1
        self.res_by_lot.pop(lot, None)
        self.res_cool[tool] = True
        if self.record:
            self.events.append(("release", moment, tool, lot, outcome))
        if outcome in ("cancelled", "elsewhere", "replan") and self.running[tool] < 0:
            self.push(moment, _WAKE, tool)

    def _can_reclean(self, lot: int, moment: float) -> bool:
        # Any step of the span, origin excluded: with the deadline event a lot
        # can miss its window while still upstream of the target.
        index = self.step[lot]
        origin = self.cqt_from[lot]
        if not origin < index <= self.cqt_at[lot]:
            return False
        if self.deadline[lot] <= 0 or moment <= self.deadline[lot]:
            return False
        if origin < 0 or self.rework[lot] >= 1:
            return False
        route = self.fab.routes[self.fab.lot_route[lot]]
        return self.fab.families[route.family[origin]].group == "Wet_Etch"

    def _reclean(self, lot: int, fam: int, moment: float, *, queued: bool = True) -> bool:
        """One re-clean. The lot is not held. A second miss goes to Q-time hold."""
        if not self._can_reclean(lot, moment):
            return False
        index = self.step[lot]
        origin = self.cqt_from[lot]
        self.recleans += 1
        self.rework[lot] += 1
        self.close_window(lot, "recleaned")
        self.deadline[lot] = 0.0
        if queued:
            self.waiting[lot] = False
            self.depth[fam] = max(0, self.depth[fam] - 1)
            if lot in self.queues[fam]:
                self.queues[fam].remove(lot)
        if self.record:
            self.events.append(("reclean", moment, lot, index, origin))
        self.step[lot] = origin
        route = self.fab.routes[self.fab.lot_route[lot]]
        self.send(lot, moment, fam, route.family[origin])
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
        self._leave_tool(lot, index)
        if lot == self.hot_lot:
            self.hot_steps += 1
        if self.record:
            self.events.append(("end", moment, lot, index))
        if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
            limit = route.cqt_limit[index]
            self.open_window(lot, index, route.cqt_target[index], limit, moment)
        nxt = index + 1
        # Sampled metrology: a lot not picked by the lot-ID rule moves past
        # the step with no queue and no process time.
        while nxt < len(route.family) and not measured(route, nxt, self.lot_no[lot]):
            self.skipped += 1
            if self.record:
                self.events.append(("skip", moment, lot, nxt))
            if self.cqt_at[lot] == nxt:
                # The Q-time window ends at its target step; an unmeasured lot
                # never visits it, so the window is closed without a check.
                self.close_window(lot, "skipped")
                self.qtime_skipped += 1
            nxt += 1
        if nxt >= len(route.family):
            self.step[lot] = len(route.family) - 1
            self.finished_at[lot] = moment
            return
        self.step[lot] = nxt
        self.send(lot, moment, route.family[index], route.family[nxt])

    def _leave_tool(self, lot: int, index: int) -> None:
        self.lot_tool[lot] = -1
        rows = self.inproc.get(_step_key(self.fab.lot_route[lot], index))
        if rows is not None:
            rows.discard(lot)

    def down_start(self, tool: int, moment: float) -> None:
        self.release_idle(tool)
        if self.res_lot[tool] >= 0:
            self.release(tool, moment, "cancelled")
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
            done = self.piece_started[tool] + self.piece_proc[tool] <= moment + 1e-6
            if self.record:
                self.events.append(("interrupt", moment, tool, tuple(lots)))
            for lot in lots:
                if done:
                    self.finish_lot(lot, moment)
                    continue
                # Rework: the lot leaves the broken tool now and redoes the
                # same operation from the family queue after the hold.
                self._leave_tool(lot, self.step[lot])
                self.reworks += 1
                if self.record:
                    self.events.append(("rework", moment, tool, lot, self.step[lot]))
                self.enqueue(lot, rework_ready(moment))
        self._queue_down_ends(tool, moment)
        # Lots pinned to this scanner may now run on an idle sibling.
        self.wake_family(self.fab.tool_family[tool])

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
        for tool, lot in enumerate(self.res_lot):
            if lot >= 0:
                self.release(tool, min(self.horizon, self.res_until[tool]), "expired")
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
            if self.cqt_at[lot] >= 0:
                expired = 0 < self.deadline[lot] <= self.horizon
                self.close_window(lot, "expired" if expired else "live")
        qout, qinh = self.qout, self.qinh
        scored = qout["met"] + sum(qout[key] for key in _MISSED)
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
            batch_starts=self.batch_starts,
            batch_lots=self.batch_lots,
            batch_reasons=dict(sorted(self.batch_reasons.items())),
            batch_dropped=self.batch_dropped,
            setup_min=round(self.setup_sec / 60.0, 1),
            reworks=self.reworks,
            rework_lot_min=round(self.reworks * REWORK_SEC / 60.0, 1),
            repins=self.repins,
            skipped=self.skipped,
            qtime_skipped=self.qtime_skipped,
            transport=self.transport,
            qtime_overrides=self.overrides,
            qtime_override_displaced=dict(sorted(self.override_displaced.items())),
            qtime_windows=dict(qout),
            qtime_inherited=dict(qinh),
            qtime_met=qout["met"],
            qtime_late=qout["late"],
            qtime_held=qout["held"],
            qtime_recleaned=qout["recleaned"],
            qtime_expired=qout["expired"],
            qtime_rate_pct=round(100.0 * qout["met"] / scored, 2) if scored else None,
            qtime_inherited_windows=sum(qinh.values()),
            qtime_inherited_missed=sum(qinh[key] for key in _MISSED),
            qtime_hold_lot_min=round(self.hold_sec / 60.0, 1),
            qtime_holds=self.held,
            batch_cap_lots=self.batch_cap_lots,
            batch_fill_pct=(
                round(100.0 * self.batch_lots / self.batch_cap_lots, 1)
                if self.batch_cap_lots
                else None
            ),
            batch_short_full=self.batch_short_full,
            qtime_shortlist_added=self.shortlist_added,
            tool_reservations=self.res_count,
            reserved_min=round(self.res_sec / 60.0, 1),
            reserve_used=self.res_out["used"],
            reserve_elsewhere=self.res_out["elsewhere"],
            reserve_expired=self.res_out["expired"],
            reserve_cancelled=self.res_out["cancelled"],
            reserve_replanned=self.res_out["replan"],
            replan_ticks=self.ticks,
            replan_stalls=self.tick_stalls,
            replan_stalls_batch=self.tick_stalls_batch,
            replan_tick_p50_ms=round(_percentile(self.tick_samples, 50) * 1000.0, 4),
            replan_tick_p95_ms=round(_percentile(self.tick_samples, 95) * 1000.0, 4),
            replan_tick_total_s=round(sum(self.tick_samples), 4),
            flow_wait_ratio=round(self.wait_sum / self.proc_sum, 4) if self.proc_sum else 0.0,
            class_wait_min={
                kind: round(self.class_wait[kind] / self.class_starts[kind] / 60.0, 2)
                for kind in sorted(self.class_wait)
            },
        )
