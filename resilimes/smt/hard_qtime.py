"""Hard Q-time: origin-step gating by a whole-segment Q-time kanban, plus expedite.

Two parts, both read by ``simulate._Sim`` (see ``docs/HARD_QTIME.md``):

* ``classify`` (always on, read-only): why an open dataset CQT window was
  missed, decided at its deadline from the sim state. Causes: ``transport``,
  ``breakdown_rework`` (the lot was in a step that a tool breakdown aborted),
  ``upstream`` (still at an intermediate step of a multi-step span),
  ``tool_down_pm`` (at the target, and the target family lost at least one
  tool-equivalent of up time to breakdown or PM while the lot waited),
  ``batch_fill`` (at a batch target with an up, idle tool: waiting to fill),
  ``queueing`` (at the target, every up tool busy). It changes no decision.
* ``HardQtime`` (on by default with the planning layer, ResiliMES in ``plan``
  mode; ``RESILIMES_HARD_QTIME=0`` turns it off for experiments): a lot may
  start a CQT origin step only if, for every family of the CQT segment (each
  measured intermediate step and the target), the work already committed
  there (the remaining segment steps of lots inside an open window or at a
  CQT origin) plus its own fits the up tools before each step's latest start,
  both as fluid work and as whole runs (a batch run shared only by
  same-recipe lots). The members of one batch start are admitted jointly.
  Dataset process time, batch size, transport and the PM calendar only;
  future breakdowns are not used. Only a lot already inside a window is
  never gated; a missed or re-cleaned lot back at an origin is gated like
  any other. Missed lots are expedited until their target step starts:
  inside the class tier they rank behind every lot inside an open window
  (urgent first, then by slack) and ahead of everyone else, so they never
  take capacity an admitted window was counted against.
* ``miss_class`` (read-only): each missed window is ``avoidable`` (a Q-time
  violation the scheduler caused), ``unavoidable_breakdown`` (a breakdown
  started on the current or target family after the origin start) or
  ``unavoidable_disruption`` (transport, breakdown rework or PM loss).
"""

from __future__ import annotations

import heapq
import math
from typing import TYPE_CHECKING, Any

from resilimes.smt.fab import QTIME_URGENT_MARGIN_SEC, measured

if TYPE_CHECKING:
    from resilimes.smt.simulate import _Sim

CAUSES = (
    "transport",
    "breakdown_rework",
    "upstream",
    "tool_down_pm",
    "batch_fill",
    "queueing",
    "unclassified",
)
# Causes the scheduler could have prevented by not starting the origin step,
# versus disruptions after the start.
AVOIDABLE = ("upstream", "batch_fill", "queueing")
DISRUPTION = ("transport", "breakdown_rework", "tool_down_pm")
# Missed windows split by what the scheduler could still have done about them
# (``miss_class``): ``avoidable`` misses are Q-time violations the scheduler
# caused; the other two are exceptions it can only expedite.
MISS_CLASSES = ("avoidable", "unavoidable_breakdown", "unavoidable_disruption")
_WAFERS = 25


def _overlap(spans: list[tuple[float, float]], left: float, right: float) -> float:
    total = 0.0
    for start_at, end_at in spans:
        lo = max(left, start_at)
        hi = min(right, end_at)
        if hi > lo:
            total += hi - lo
    return total


def _after_pm(spans: list[tuple[float, float]], moment: float) -> float:
    """``moment``, or the end of the PM it falls in (repeated for back-to-back PMs)."""
    moved = True
    while moved:
        moved = False
        for start_at, end_at in spans:
            if start_at <= moment < end_at:
                moment = end_at
                moved = True
    return moment


def _off_now(sim: _Sim, tool: int, moment: float) -> bool:
    for spans in (sim.downs[tool], sim.pm[tool]):
        for start_at, end_at in spans:
            if start_at <= moment < end_at:
                return True
    return False


def classify(sim: _Sim, lot: int, moment: float) -> str:
    """Cause of a window still open at its deadline ``moment``."""
    target = sim.cqt_at[lot]
    if target < 0:
        return "unclassified"
    if not sim.waiting[lot]:
        if sim.lot_tool[lot] >= 0:
            return "upstream"
        return "transport"
    if sim.ready[lot] > moment + 1e-6:
        return "breakdown_rework"
    if sim.step[lot] < target:
        return "upstream"
    route = sim.fab.routes[sim.fab.lot_route[lot]]
    family = sim.fab.families[route.family[target]]
    tools = range(family.tool0, family.tool0 + family.tools)
    since = min(sim.ready[lot], moment)
    lost = sum(
        _overlap(sim.downs[tool], since, moment) + _overlap(sim.pm[tool], since, moment)
        for tool in tools
    )
    if moment > since and lost >= moment - since:
        return "tool_down_pm"
    if route.batch_max[target] > 0 and any(
        sim.running[tool] < 0 and not _off_now(sim, tool, moment) for tool in tools
    ):
        return "batch_fill"
    return "queueing"


def miss_class(sim: _Sim, lot: int, cause: str) -> str:
    """Avoidable or unavoidable, for a window missed with ``cause``.

    Unavoidable: a disruption cause (transport, breakdown rework, target down
    or in PM), or a breakdown that began on the family the lot waited at or on
    the target family after the origin step started (the origin start is the
    admission; a tool already down then is known to the gate). Avoidable: a
    plannable miss (queueing, upstream, batch fill) with no such breakdown.
    """
    if cause in DISRUPTION:
        return "unavoidable_disruption"
    route = sim.fab.routes[sim.fab.lot_route[lot]]
    target = sim.cqt_at[lot]
    origin = sim.cqt_from[lot]
    if target < 0 or origin < 0:
        return "avoidable"
    deadline = sim.deadline[lot]
    admitted = deadline - sim.cqt_limit[lot] - route.cycle[origin]
    here = min(max(sim.step[lot], origin + 1), target)
    for fam in {route.family[here], route.family[target]}:
        family = sim.fab.families[fam]
        for tool in range(family.tool0, family.tool0 + family.tools):
            if any(admitted <= start_at < deadline for start_at, _end in sim.downs[tool]):
                return "unavoidable_breakdown"
    return "avoidable"


class HardQtime:
    """Q-time kanban gate and expedite bookkeeping for one run."""

    def __init__(self, sim: _Sim) -> None:
        self.sim = sim
        nfam = len(sim.fab.families)
        # Family -> (lot, step) -> (work seconds at that step, target step,
        # latest target start estimated when the origin started, seconds the
        # lot still needs from that step's start to the target start). One
        # entry per step of the CQT segment after the origin, target included.
        self.committed: list[dict[tuple[int, int], tuple[float, int, float, float]]] = [
            {} for _ in range(nfam)
        ]
        self.where: dict[int, list[tuple[int, int]]] = {}
        # Expedite: the target step a missed lot must still start, and since when.
        self.x_target = [-1] * sim.n
        self.x_since = [0.0] * sim.n
        self.gate_checks = 0
        self.gate_blocks = 0
        # Base feasibility per family, valid for one (moment, version) pair.
        self.version = 0
        self.waiters: dict[int, set[int]] = {}
        self.blocked_fam = -1
        self.fallback_at: dict[int, float] = {}
        self.base: dict[int, tuple[float, int, bool]] = {}
        self.exempt_starts = 0
        self.expedited_lots = 0
        self.recover_sec: list[float] = []
        # Misses of windows opened by an admitted origin start, by cause.
        self.admitted = [False] * sim.n

    # -- kanban -----------------------------------------------------------
    @staticmethod
    def _lots(route: Any, step: int) -> int:
        # A batch tool shares its run over batch_min lots (BATCHMN; it may start
        # with fewer, never waits for more once the minimum is met).
        return max(1, route.batch_min[step] // _WAFERS) if route.batch_max[step] > 0 else 1

    @staticmethod
    def _run(route: Any, step: int) -> tuple[int, int]:
        """(lots per run, recipe): only same-recipe lots share a batch run."""
        lots = HardQtime._lots(route, step)
        return lots, (int(route.recipe[step]) if lots > 1 else -1)

    def _work(self, route: Any, target: int) -> float:
        return float(route.cycle[target]) / self._lots(route, target)

    def segment(self, lot: int, origin: int, target: int) -> list[tuple[int, int, float, float]]:
        """(family, step, work, need to target) for each step after the origin.

        The measured intermediate steps of the CQT segment and the target.
        """
        sim = self.sim
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        number = sim.lot_no[lot]
        out = []
        for step in range(origin + 1, target + 1):
            if step == target or measured(route, step, number):
                need = sim.qtime_need(lot, step, target) if step < target else 0.0
                out.append((route.family[step], step, self._work(route, step), need))
        return out

    def commit(self, lot: int, origin: int, target: int, latest: float) -> None:
        sim = self.sim
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        if not measured(route, target, sim.lot_no[lot]):
            return
        self.drop(lot)
        self.version += 1
        keys = []
        for fam, step, work, need in self.segment(lot, origin, target):
            self.committed[fam][(lot, step)] = (work, target, latest, need)
            keys.append((fam, step))
        self.where[lot] = keys

    def drop(self, lot: int, upto: int | None = None) -> None:
        """Release the lot's segment load (only steps <= ``upto`` if given)."""
        keys = self.where.get(lot)
        if not keys:
            return
        self.version += 1
        keep = []
        for fam, step in keys:
            if upto is None or step <= upto:
                self.committed[fam].pop((lot, step), None)
            else:
                keep.append((fam, step))
        if keep:
            self.where[lot] = keep
        else:
            del self.where[lot]

    def expedited(self, lot: int, moment: float) -> bool:
        """Missed its window, or inside one with no more than the urgent margin left."""
        sim = self.sim
        if self.x_target[lot] >= 0:
            return True
        if not sim.in_window(lot):
            return False
        left = sim.deadline[lot] - moment
        return left <= sim.qtime_need(lot) + QTIME_URGENT_MARGIN_SEC

    def feasible(
        self,
        fam: int,
        moment: float,
        extra: list[tuple[float, float, int, int]] | None = None,
    ) -> bool:
        """EDF test: can every committed lot start its step here in time?

        Up tools (current state and the PM calendar only, never future
        breakdowns) are free from their current job's end. Missed lots
        (expedited) go first with no deadline of their own, then committed
        lots by latest start. Two checks, both must pass: the fluid one (the
        cumulative work up to each lot fits the free tool time before its
        latest start) and the whole-run one (each lot takes the earliest free
        tool for a full run, a batch run shared by ``batch_min`` consecutive
        same-recipe lots, no run starting inside a PM, and must start by its latest start;
        the fluid check alone lets a 7 h batch run "share" tool time that is
        never free before the deadline). A committed step's
        latest start is the target's latest start minus what the lot still
        needs from that step. ``extra`` adds a candidate's (work, latest
        start, lots per run, recipe) tuples.
        """
        sim = self.sim
        family = sim.fab.families[fam]
        free: list[tuple[float, int]] = []
        for tool in range(family.tool0, family.tool0 + family.tools):
            if _off_now(sim, tool, moment):
                continue
            start = sim.busy_until[tool] if sim.running[tool] >= 0 else moment
            free.append((max(moment, start), tool))
        items: list[tuple[float, float, int, int]] = []
        for (lot, step), (work, target, latest, need) in self.committed[fam].items():
            lots, recipe = self._run(sim.fab.routes[sim.fab.lot_route[lot]], step)
            if self.x_target[lot] >= 0:
                items.append((-math.inf, work, lots, recipe))
                continue
            if sim.cqt_at[lot] == target and sim.deadline[lot] > 0:
                latest = sim.deadline[lot]
            items.append((latest - need, work, lots, recipe))
        for work, latest, lots, recipe in extra or ():
            items.append((latest, work, lots, recipe))
        if not items:
            return True
        if not free:
            return False
        items.sort()
        # Fluid: the work of every lot up to and including each one fits the
        # free tool time before its latest start (missed lots first).
        cum = 0.0
        for latest, work, _lots, _recipe in items:
            cum += work
            if latest == -math.inf:
                continue
            cap = 0.0
            for start, tool in free:
                if latest > start:
                    cap += latest - start - _overlap(sim.pm[tool], start, latest)
            if cum > cap + 1e-6:
                return False
        # Whole runs: a tool is held for a full run (a batch run is shared by
        # batch_min consecutive lots), and each run starts by its latest start.
        heapq.heapify(free)
        # Recipe -> (start, places left) of its last open batch run.
        runs: dict[int, tuple[float, int]] = {}
        for latest, work, lots, recipe in items:
            start, left = runs.get(recipe, (0.0, 0))
            if lots > 1 and left > 0:
                begin = start
                runs[recipe] = (start, left - 1)
            else:
                begin, tool = heapq.heappop(free)
                begin = _after_pm(sim.pm[tool], begin)
                heapq.heappush(free, (begin + work * lots, tool))
                if lots > 1:
                    runs[recipe] = (begin, lots - 1)
            if latest > -math.inf and begin > latest + 1e-6:
                return False
        return True

    def base_ok(self, fam: int, moment: float) -> bool:
        hit = self.base.get(fam)
        if hit is not None and hit[0] == moment and hit[1] == self.version:
            return hit[2]
        ok = self.feasible(fam, moment)
        self.base[fam] = (moment, self.version, ok)
        return ok

    def admit(
        self,
        lot: int,
        moment: float,
        proc: float,
        pending: dict[int, list[tuple[float, float, int, int]]] | None = None,
    ) -> bool:
        """May ``lot`` start its current step now (only CQT origins are gated).

        ``pending`` holds the segment load of lots admitted into the same
        start (a batch): it is tested together with this lot's, and this lot's
        is added to it when admitted.
        """
        sim = self.sim
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        index = sim.step[lot]
        limit = route.cqt_limit[index]
        target = route.cqt_target[index]
        if limit <= 0 or target < 0:
            return True
        # Never gate a lot already inside a window (a nested origin). A missed
        # or re-cleaned lot back at an origin is gated like any other: it stays
        # expedited, so it goes first as soon as its segment is feasible.
        if sim.in_window(lot):
            return True
        if not measured(route, target, sim.lot_no[lot]):
            return True
        self.gate_checks += 1
        post = sim.qtime_need(lot, index, target) - route.cycle[index]
        latest = moment + proc + limit
        if post >= limit:
            self.gate_blocks += 1
            self.blocked_fam = route.family[target]
            return False
        # Every family of the segment (intermediate steps and the target).
        extra: dict[int, list[tuple[float, float, int, int]]] = {}
        for fam, step, work, need in self.segment(lot, index, target):
            extra.setdefault(fam, []).append((work, latest - need, *self._run(route, step)))
        for fam, pairs in extra.items():
            joint = pairs + (pending or {}).get(fam, [])
            if not (self.base_ok(fam, moment) and self.feasible(fam, moment, extra=joint)):
                self.gate_blocks += 1
                self.blocked_fam = fam
                return False
        if pending is not None:
            for fam, pairs in extra.items():
                pending.setdefault(fam, []).extend(pairs)
        return True

    def admit_batch(self, lots: list[int], moment: float, procs: dict[int, float]) -> list[int]:
        """The members of one batch start that are admissible together.

        Each member passed ``admit`` alone; a batch origin starts them at
        once, so their segment loads are tested jointly, in rank order.
        """
        pending: dict[int, list[tuple[float, float, int, int]]] = {}
        return [lot for lot in lots if self.admit(lot, moment, procs[lot], pending)]

    def wait_on(self, tool: int) -> None:
        """``tool`` was just gated on ``blocked_fam``; wake it when that family frees up."""
        self.waiters.setdefault(self.blocked_fam, set()).add(tool)

    def woken(self, fam: int) -> list[int]:
        """Tools gated on ``fam``, to wake now (a tool of ``fam`` finished or came up)."""
        return sorted(self.waiters.pop(fam, ()))

    # -- hooks ------------------------------------------------------------
    def on_start(self, lot: int, index: int, moment: float) -> None:
        sim = self.sim
        self.version += 1  # a tool just turned busy
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        if lot in self.where:
            self.drop(lot, upto=index)
        if self.x_target[lot] == index:
            self.recover_sec.append(moment - self.x_since[lot])
            self.x_target[lot] = -1
        if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
            exempt = sim.in_window(lot)
            if exempt:
                self.exempt_starts += 1
            self.admitted[lot] = not exempt
            latest = moment + route.cycle[index] + route.cqt_limit[index]
            self.commit(lot, index, route.cqt_target[index], latest)

    def on_miss(self, lot: int, target: int, moment: float, outcome: str) -> None:
        if self.x_target[lot] < 0:
            self.x_target[lot] = target
            self.x_since[lot] = moment
            self.expedited_lots += 1
        if outcome == "recleaned":
            # Back to the origin; it commits again when the origin restarts.
            self.drop(lot)

    def summary(self) -> dict[str, Any]:
        rec = sorted(self.recover_sec)
        open_x = sum(1 for target in self.x_target if target >= 0)
        return {
            "gate_checks": self.gate_checks,
            "gate_blocks": self.gate_blocks,
            "exempt_origin_starts": self.exempt_starts,
            "expedited_lots": self.expedited_lots,
            "recovered": len(rec),
            "unrecovered_at_horizon": open_x,
            "recover_mean_min": round(sum(rec) / len(rec) / 60.0, 1) if rec else None,
            "recover_p90_min": round(rec[int(0.9 * (len(rec) - 1))] / 60.0, 1) if rec else None,
        }
