"""Hard Q-time: origin-step gating by a per-target Q-time kanban, plus expedite.

Two parts, both read by ``simulate._Sim`` (see ``docs/HARD_QTIME.md``):

* ``classify`` (always on, read-only): why an open dataset CQT window was
  missed, decided at its deadline from the sim state. Causes: ``transport``,
  ``breakdown_rework`` (the lot was in a step that a tool breakdown aborted),
  ``upstream`` (still at an intermediate step of a multi-step span),
  ``tool_down_pm`` (at the target, and the target family lost at least one
  tool-equivalent of up time to breakdown or PM while the lot waited),
  ``batch_fill`` (at a batch target with an up, idle tool: waiting to fill),
  ``queueing`` (at the target, every up tool busy). It changes no decision.
* ``HardQtime`` (``hard_qtime=True``, default off): a lot may start a CQT
  origin step only if the work already committed to the target family (lots
  inside an open window or at a CQT origin heading there) plus its own fits
  the up tools of that family within the limit. Dataset process time, batch
  size, transport and the PM calendar only; future breakdowns are not used.
  A lot that missed (or is about to miss) its window is never gated and is
  expedited: first at its target within its class tier, and through re-clean
  and the re-opened window until its target step starts.
"""

from __future__ import annotations

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
_WAFERS = 25


def _overlap(spans: list[tuple[float, float]], left: float, right: float) -> float:
    total = 0.0
    for start_at, end_at in spans:
        lo = max(left, start_at)
        hi = min(right, end_at)
        if hi > lo:
            total += hi - lo
    return total


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


class HardQtime:
    """Q-time kanban gate and expedite bookkeeping for one run."""

    def __init__(self, sim: _Sim) -> None:
        self.sim = sim
        nfam = len(sim.fab.families)
        # Target family -> lot -> (work seconds at the target, target step,
        # latest target start estimated when the origin started).
        self.committed: list[dict[int, tuple[float, int, float]]] = [{} for _ in range(nfam)]
        self.where: dict[int, int] = {}
        # Expedite: the target step a missed lot must still start, and since when.
        self.x_target = [-1] * sim.n
        self.x_since = [0.0] * sim.n
        self.gate_checks = 0
        self.gate_blocks = 0
        # Base feasibility per family, valid for one (moment, version) pair.
        self.version = 0
        self.base: dict[int, tuple[float, int, bool]] = {}
        self.exempt_starts = 0
        self.expedited_lots = 0
        self.recover_sec: list[float] = []
        # Misses of windows opened by an admitted origin start, by cause.
        self.admitted = [False] * sim.n

    # -- kanban -----------------------------------------------------------
    def _work(self, route: Any, target: int) -> float:
        # A batch tool shares its run over at least batch_min lots (conservative).
        lots = max(1, route.batch_min[target] // _WAFERS) if route.batch_max[target] > 0 else 1
        return float(route.cycle[target]) / lots

    def commit(self, lot: int, target: int, latest: float) -> None:
        sim = self.sim
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        if not measured(route, target, sim.lot_no[lot]):
            return
        self.drop(lot)
        self.version += 1
        fam = route.family[target]
        self.committed[fam][lot] = (self._work(route, target), target, latest)
        self.where[lot] = fam

    def drop(self, lot: int) -> None:
        fam = self.where.pop(lot, -1)
        if fam >= 0:
            self.version += 1
            self.committed[fam].pop(lot, None)

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
        extra: tuple[float, float] | None = None,
    ) -> bool:
        """Fluid EDF test: can every committed lot start its target in time?

        Up tools (current state and the PM calendar only, never future
        breakdowns) are free from their current job's end; committed lots, by
        latest start, must fit in the cumulative free tool time. Missed lots
        (expedited) take capacity first with no deadline of their own.
        ``extra`` adds a candidate (work, latest start).
        """
        sim = self.sim
        family = sim.fab.families[fam]
        free: list[tuple[int, float]] = []
        for tool in range(family.tool0, family.tool0 + family.tools):
            if _off_now(sim, tool, moment):
                continue
            start = sim.busy_until[tool] if sim.running[tool] >= 0 else moment
            free.append((tool, max(moment, start)))
        missed = 0.0
        items: list[tuple[float, float]] = []
        for lot, (work, target, latest) in self.committed[fam].items():
            if self.x_target[lot] >= 0:
                missed += work
                continue
            if sim.cqt_at[lot] == target and sim.deadline[lot] > 0:
                latest = sim.deadline[lot]
            items.append((latest, work))
        if extra is not None:
            items.append((extra[1], extra[0]))
        items.sort()
        cum = missed
        for latest, work in items:
            cum += work
            cap = 0.0
            for tool, start in free:
                if latest > start:
                    cap += latest - start - _overlap(sim.pm[tool], start, latest)
            if cum > cap + 1e-6:
                return False
        return True

    def base_ok(self, fam: int, moment: float) -> bool:
        hit = self.base.get(fam)
        if hit is not None and hit[0] == moment and hit[1] == self.version:
            return hit[2]
        ok = self.feasible(fam, moment)
        self.base[fam] = (moment, self.version, ok)
        return ok

    def admit(self, lot: int, moment: float, proc: float) -> bool:
        """May ``lot`` start its current step now (only CQT origins are gated)."""
        sim = self.sim
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        index = sim.step[lot]
        limit = route.cqt_limit[index]
        target = route.cqt_target[index]
        if limit <= 0 or target < 0:
            return True
        # Never gate a lot already inside or past a window, or one being expedited.
        if sim.in_window(lot) or self.x_target[lot] >= 0 or sim.rework[lot] > 0:
            return True
        if not measured(route, target, sim.lot_no[lot]):
            return True
        self.gate_checks += 1
        post = sim.qtime_need(lot, index, target) - route.cycle[index]
        latest = moment + proc + limit
        fam = route.family[target]
        ok = (
            post < limit
            and self.base_ok(fam, moment)
            and self.feasible(fam, moment, extra=(self._work(route, target), latest))
        )
        if not ok:
            self.gate_blocks += 1
        return ok

    # -- hooks ------------------------------------------------------------
    def on_start(self, lot: int, index: int, moment: float) -> None:
        sim = self.sim
        self.version += 1  # a tool just turned busy
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        held = self.where.get(lot, -1)
        if held >= 0 and self.committed[held].get(lot, (0.0, -1, 0.0))[1] == index:
            self.drop(lot)
        if self.x_target[lot] == index:
            self.recover_sec.append(moment - self.x_since[lot])
            self.x_target[lot] = -1
        if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
            exempt = sim.in_window(lot) or self.x_target[lot] >= 0 or sim.rework[lot] > 0
            if exempt:
                self.exempt_starts += 1
            self.admitted[lot] = not exempt
            latest = moment + route.cycle[index] + route.cqt_limit[index]
            self.commit(lot, route.cqt_target[index], latest)

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
