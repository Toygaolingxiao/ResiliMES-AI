"""Frozen dispatch zone ("FIX") and the scheduling-tick log.

The user's fab rule (not SMT2020 data): at every scheduling tick each tool
keeps the lot it is processing plus its next lots, up to ``max_lots`` loads or
``max_sec`` of planned start time, whichever comes first, FIXED to that tool.
A fixed lot is moved to the tool's port once and is not re-targeted by a later
tick, so it is not transported a second time. Lots outside the frozen zone are
re-planned at every tick and dispatched as before. The defaults (2 loads, 30
min) were chosen before any run and are not tuned; a batch counts as one load.

Dispatch honours the zone: a tool takes its frozen head when it can start
(eligibility, PM, Q-time gate and the batch rule as for any lot), and a lot
frozen to one tool is not taken by another. A lot leaves the zone only on a
logged exception:

* ``tool_down``: its tool breaks down (every lot frozen there).
* ``pm``: it can no longer finish before the tool's next scheduled PM (PMs are
  fixed in this simulator; a start that crosses the next PM is refused).
* ``qtime_emergency``: it is inside an open dataset CQT window, its frozen tool
  would start it after its latest start, and an idle sibling can start it now.
* ``hot_lot``: a VIP/hot lot (SMT2020 PRIOR class) whose frozen tool cannot
  start it now while an idle sibling can.
* ``hold``: Q-time hold or re-clean (the lot leaves the queue).
* ``eligibility``: the tool is no longer eligible (scanner dedication).
* ``other``: safety net, a frozen lot started on another tool by another path.

Insertion (the frozen zone is kept, nothing is unfrozen or re-transported):
a lot that is not frozen anywhere may run ahead of a tool's frozen head when
the policy's own choice at that tool puts it first and it is either a VIP/hot
lot (``hot_inserts``) or a Q-time emergency, i.e. inside an open CQT window
whose latest feasible start falls before the tool would be through its frozen
lots (``qtime_inserts``). The frozen lots simply slip by one piece.

Deadlock rule: when the frozen head cannot start yet (not ready, batch still
waiting, Q-time gate), the tool may run another ready lot only if that lot
finishes before the head can start, or if it is one of the tool's own frozen
lots; otherwise the tool waits for the head (``frozen_waits``).

With ``enabled=False`` and tracking on (``track`` or a tick log) the same plan
is computed as a shadow (frozen zone recomputed from scratch at every tick, not
enforced) so plan stability and second transports can be compared; dispatch is
unchanged. With everything off no hook does anything.
"""

from __future__ import annotations

import gzip
import heapq
import json
import os
import re
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Any

from resilimes.smt.fab import LOOKAHEAD

if TYPE_CHECKING:
    from resilimes.smt.simulate import _Sim

DEFAULT_FREEZE_LOTS = 2
DEFAULT_FREEZE_SEC = 30 * 60.0
# Lots planned per family beyond the frozen zone (as the 'replan' snapshot).
PLAN_DEPTH = 64
# Changed-lot rows kept per tick in the JSONL log (the count is always exact).
LOG_CHANGES_MAX = 500
REASONS = (
    "tool_down",
    "pm",
    "qtime_emergency",
    "hot_lot",
    "hold",
    "eligibility",
    "other",
)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class FreezeConfig:
    """Frozen-zone switch (default OFF) and tick tracking.

    ``enabled`` enforces the frozen zone. ``track`` computes the plan,
    stability and second-transport KPIs without enforcing anything.
    ``log_path`` writes one JSON line per scheduling tick (implies tracking).
    """

    enabled: bool = False
    max_lots: int = DEFAULT_FREEZE_LOTS
    max_sec: float = DEFAULT_FREEZE_SEC
    track: bool = False
    log_path: str | None = None

    @property
    def active(self) -> bool:
        return self.enabled or self.track or bool(self.log_path)

    @classmethod
    def from_env(cls) -> FreezeConfig:
        """RESILIMES_SCHED_FREEZE=1 turns it on; RESILIMES_FREEZE_LOTS,
        RESILIMES_FREEZE_MIN set the limits; RESILIMES_SCHED_TRACK=1 tracks
        without enforcing; RESILIMES_TICK_LOG=path writes the tick log."""
        lots = os.environ.get("RESILIMES_FREEZE_LOTS", "").strip()
        minutes = os.environ.get("RESILIMES_FREEZE_MIN", "").strip()
        path = os.environ.get("RESILIMES_TICK_LOG", "").strip()
        return cls(
            enabled=_env_flag("RESILIMES_SCHED_FREEZE"),
            max_lots=int(lots) if lots else DEFAULT_FREEZE_LOTS,
            max_sec=float(minutes) * 60.0 if minutes else DEFAULT_FREEZE_SEC,
            track=_env_flag("RESILIMES_SCHED_TRACK"),
            log_path=path or None,
        )


def inversions(seq: list[int]) -> int:
    """Discordant pairs (Kendall-tau distance) of a sequence of ranks."""
    if len(seq) < 2:
        return 0
    work = list(seq)
    buf = [0] * len(work)
    count = 0
    width = 1
    size = len(work)
    while width < size:
        for lo in range(0, size, 2 * width):
            mid = min(lo + width, size)
            hi = min(lo + 2 * width, size)
            i, j, k = lo, mid, lo
            while i < mid and j < hi:
                if work[i] <= work[j]:
                    buf[k] = work[i]
                    i += 1
                else:
                    buf[k] = work[j]
                    count += mid - i
                    j += 1
                k += 1
            buf[k : k + mid - i] = work[i:mid]
            k += mid - i
            buf[k : k + hi - j] = work[j:hi]
            work[lo:hi] = buf[lo:hi]
        width *= 2
    return count


def _covering(windows: list[tuple[float, float]], moment: float) -> tuple[float, float] | None:
    for start_at, end_at in windows:
        if start_at <= moment < end_at:
            return start_at, end_at
    return None


class Freezer:
    """Frozen zone, plan tracking and tick log of one run (see module doc)."""

    def __init__(self, sim: _Sim, cfg: FreezeConfig, *, wafers: int, wake_kind: int) -> None:
        self.sim = sim
        self.cfg = cfg
        self.enabled = cfg.enabled
        self.wafers = wafers
        self.wake_kind = wake_kind
        tools = len(sim.fab.tool_name)
        self.frozen: list[list[int]] = [[] for _ in range(tools)]
        self.frozen_at: dict[int, int] = {}
        self.fam_frozen: list[set[int]] = [set() for _ in sim.fab.families]
        # Where a lot was staged (frozen, or shadow frozen when off): lot -> (tool, step).
        self.staged: dict[int, tuple[int, int]] = {}
        self.last_cause: dict[int, str] = {}
        self.unfreezes: dict[str, int] = dict.fromkeys(REASONS, 0)
        self.second: dict[str, int] = {}
        # Second transports weighted by their move time (staged tool -> new tool).
        self.second_sec = 0.0
        self.frozen_starts = 0
        self.hot_inserts = 0
        self.qtime_inserts = 0
        self.fill_starts = 0
        self.frozen_waits = 0
        self.prev_plan: dict[int, int] = {}
        self.prev_orders: dict[int, list[int]] = {}
        self.ticks = 0
        self.compared_ticks = 0
        self.tool_changes = 0
        self.change_rates: list[float] = []
        self.staged_changes = 0
        self.staged_rates: list[float] = []
        self.planned_lots: set[int] = set()
        self.swaps = 0
        self.tau: list[float] = []
        self.frozen_sum = 0
        self.replanned_sum = 0
        self.tick_unfreezes: list[list[Any]] = []
        self.lead_seen = 0
        self.log: IO[str] | None = None
        if cfg.log_path:
            folder = os.path.dirname(cfg.log_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            if cfg.log_path.endswith(".gz"):
                self.log = gzip.open(cfg.log_path, "wt", encoding="utf-8")  # noqa: SIM115
            else:
                self.log = open(cfg.log_path, "w", encoding="utf-8")  # noqa: SIM115

    # ---- dispatch side ------------------------------------------------

    def free_for(self, lot: int, tool: int) -> bool:
        """Not frozen to another tool."""
        held = self.frozen_at.get(lot)
        return held is None or held == tool

    def unfreeze(self, lot: int, reason: str, moment: float, *, poke: bool = True) -> None:
        tool = self.frozen_at.pop(lot, None)
        if tool is None:
            return
        sim = self.sim
        fam = sim.fab.tool_family[tool]
        if lot in self.frozen[tool]:
            self.frozen[tool].remove(lot)
        self.fam_frozen[fam].discard(lot)
        self.unfreezes[reason] = self.unfreezes.get(reason, 0) + 1
        self.last_cause[lot] = reason
        if len(self.tick_unfreezes) < LOG_CHANGES_MAX:
            self.tick_unfreezes.append([round(moment, 1), lot, tool, reason])
        if sim.record:
            sim.events.append(("unfreeze", moment, lot, tool, reason))
        if poke:
            for other in sim.idle[fam]:
                sim.push(moment, self.wake_kind, other)

    def _drop(self, lot: int) -> None:
        """A frozen lot that is no longer waiting here (no count)."""
        tool = self.frozen_at.pop(lot, None)
        if tool is None:
            return
        if lot in self.frozen[tool]:
            self.frozen[tool].remove(lot)
        self.fam_frozen[self.sim.fab.tool_family[tool]].discard(lot)

    def _startable(self, lot: int, tool: int, moment: float) -> bool:
        sim = self.sim
        if not sim.waiting[lot] or sim.ready[lot] > moment + 1e-6:
            return False
        if not sim.eligible(lot, tool, moment):
            return False
        pm_start = sim.next_pm_start(tool, moment)
        return pm_start is None or moment + sim.piece_seconds(lot, tool) <= pm_start

    def _head(
        self, tool: int, fam: int, moment: float
    ) -> tuple[list[int], float | None, str] | None:
        """The frozen head's start: (lots, None, reason) now, ([], t, "") not
        before t, or None when the tool has no frozen lot."""
        sim = self.sim
        mine = self.frozen[tool]
        while mine:
            head = mine[0]
            if not sim.waiting[head] or sim.step_family(head) != fam:
                self._drop(head)
                continue
            if not sim.eligible(head, tool, moment):
                self.unfreeze(head, "eligibility", moment)
                continue
            pm_start = sim.next_pm_start(tool, moment)
            ready_at = max(moment, sim.ready[head])
            if pm_start is not None and ready_at + sim.piece_seconds(head, tool) > pm_start:
                self.unfreeze(head, "pm", moment)
                continue
            break
        if not mine:
            return None
        head = mine[0]
        if sim.ready[head] > moment + 1e-6:
            return [], sim.ready[head], ""
        proc = sim.piece_seconds(head, tool)
        if sim.policy == "resilimes":
            opened = sim.downstream_ready(head, moment, proc)
            limit = sim._open_limit(head)
            if opened is not None and opened > moment + proc + limit:
                return [], max(moment + 60.0, opened - proc - limit), ""
        route = sim.fab.routes[sim.fab.lot_route[head]]
        index = sim.step[head]
        if route.batch_max[index] <= 0:
            return [head], None, ""
        recipe = route.recipe[index]
        same: list[int] = []
        for lot in sim.live(fam):
            lot_route = sim.fab.routes[sim.fab.lot_route[lot]]
            step = sim.step[lot]
            if lot_route.batch_max[step] <= 0 or lot_route.recipe[step] != recipe:
                continue
            if self.free_for(lot, tool) and self._startable(lot, tool, moment):
                same.append(lot)
        own = [lot for lot in mine if lot in same]
        if head not in own:
            own.insert(0, head)
        kept = set(own)
        others = sorted(
            (lot for lot in same if lot not in kept), key=lambda lot: sim.rank(lot, tool, moment)
        )
        ordered = own + others
        cap = route.batch_max[index]
        floor = route.batch_min[index] or cap
        taken = ordered[: max(1, cap // self.wafers)] if cap else ordered
        sim.last_recipe_ready = {recipe: len(ordered)}
        reason, until = sim.batch_rule(
            taken, ordered, fam, recipe, len(taken) * self.wafers, floor, moment
        )
        if until is not None:
            return [], until, ""
        return taken, None, reason

    def _est_start(self, holder: int, lot: int, moment: float) -> float:
        """When ``holder`` would start ``lot`` working through its frozen list."""
        sim = self.sim
        at = sim.busy_until[holder] if sim.running[holder] >= 0 else moment
        gone = _covering(sim.pm[holder], moment) or _covering(sim.downs[holder], moment)
        if gone is not None:
            at = max(at, gone[1])
        if sim.res_lot[holder] >= 0:
            at = max(at, sim.res_until[holder])
        for other in self.frozen[holder]:
            at = max(at, sim.ready[other])
            if other == lot:
                return at
            at += sim.piece_seconds(other, holder)
        return max(at, sim.ready[lot])

    def _rescue(self, tool: int, fam: int, moment: float) -> list[int]:
        """Q-time emergency / hot lot: frozen elsewhere, startable here now."""
        sim = self.sim
        found: list[int] = []
        for lot in sorted(self.fam_frozen[fam]):
            holder = self.frozen_at.get(lot, tool)
            if holder == tool or not self._startable(lot, tool, moment):
                continue
            est = self._est_start(holder, lot, moment)
            if sim.in_window(lot):
                latest = sim.deadline[lot] - sim.qtime_need(lot)
                if est > latest + 1e-6 and moment <= latest:
                    self.unfreeze(lot, "qtime_emergency", moment, poke=False)
                    found.append(lot)
                    continue
            if est > moment + 1e-6 and sim.tier(lot) < 2:
                self.unfreeze(lot, "hot_lot", moment, poke=False)
                found.append(lot)
        return found

    def _frozen_end(self, tool: int, moment: float) -> float:
        """When ``tool`` would be through its whole frozen list."""
        sim = self.sim
        at = sim.busy_until[tool] if sim.running[tool] >= 0 else moment
        for other in self.frozen[tool]:
            at = max(at, sim.ready[other]) + sim.piece_seconds(other, tool)
        return at

    def _exception(self, lot: int, moment: float, end: float) -> str:
        """Why a lot not frozen here may go ahead of the frozen zone, or ""."""
        sim = self.sim
        if sim.tier(lot) < 2:
            return "hot"
        if sim.in_window(lot):
            latest = sim.deadline[lot] - sim.qtime_need(lot)
            if moment <= latest < end:
                return "qtime"
        return ""

    def _insert_waiting(self, tool: int, fam: int, moment: float) -> float | None:
        """End of the frozen work when a hot / Q-time-emergency lot waits, else None."""
        sim = self.sim
        mine = set(self.frozen[tool])
        end = self._frozen_end(tool, moment)
        for lot in sim.live(fam):
            if lot in mine or not self.free_for(lot, tool):
                continue
            if sim.ready[lot] <= moment + 1e-6 and self._exception(lot, moment, end):
                return end
        return None

    def choose(self, tool: int, moment: float) -> tuple[list[int], float | None, str]:
        """Dispatch with the frozen zone (replaces ``_Sim.choose`` when enabled)."""
        sim = self.sim
        fam = sim.fab.tool_family[tool]
        head = self._head(tool, fam, moment)
        if head is not None and head[1] is None:
            end = self._insert_waiting(tool, fam, moment)
            if end is not None:
                alt = sim.choose(tool, moment)
                lead = alt[0][0] if alt[0] else -1
                kind = (
                    ""
                    if lead < 0 or lead in self.frozen[tool]
                    else self._exception(lead, moment, end)
                )
                if kind == "hot":
                    self.hot_inserts += 1
                    return alt
                if kind == "qtime":
                    self.qtime_inserts += 1
                    return alt
            sim.pending_override = None
            self.frozen_starts += 1
            return head
        rescued = self._rescue(tool, fam, moment)
        for lot in rescued:
            route = sim.fab.routes[sim.fab.lot_route[lot]]
            if route.batch_max[sim.step[lot]] <= 0:
                # A rescued batch lot competes in the ordinary choice below.
                sim.pending_override = None
                return [lot], None, ""
        alt = sim.choose(tool, moment)
        if head is None:
            return alt
        until = head[1]
        assert until is not None
        if alt[0]:
            mine = set(self.frozen[tool])
            end = moment + max(sim.piece_seconds(lot, tool) for lot in alt[0])
            if all(lot in mine for lot in alt[0]) or end <= until + 1e-6:
                if not all(lot in mine for lot in alt[0]):
                    self.fill_starts += 1
                return alt
        self.frozen_waits += 1
        sim.pending_override = None
        wake = until if alt[1] is None else min(until, alt[1])
        return [], wake, ""

    def _move(self, old_tool: int, new_tool: int) -> float:
        """Transport time of a second transport, staged tool -> new tool."""
        fam = self.sim.fab.tool_family
        return float(self.sim.move_seconds(fam[old_tool], fam[new_tool]))

    # ---- event hooks --------------------------------------------------

    def on_start(self, tool: int, started: list[int], moment: float) -> None:
        sim = self.sim
        for lot in started:
            staged = self.staged.pop(lot, None)
            if staged is not None and staged[0] != tool and staged[1] == sim.step[lot]:
                cause = self.last_cause.get(lot, "dispatch")
                self.second[cause] = self.second.get(cause, 0) + 1
                self.second_sec += self._move(staged[0], tool)
            self.last_cause.pop(lot, None)
            held = self.frozen_at.get(lot)
            if held is not None and held != tool:
                self.unfreeze(lot, "other", moment, poke=False)
            self._drop(lot)

    def on_down(self, tool: int, moment: float) -> None:
        for lot, (where, _step) in self.staged.items():
            if where == tool:
                self.last_cause[lot] = "tool_down"
        for lot in list(self.frozen[tool]):
            self.unfreeze(lot, "tool_down", moment, poke=False)

    def on_hold(self, lot: int, moment: float) -> None:
        """Q-time hold or re-clean: the lot leaves the queue."""
        self.unfreeze(lot, "hold", moment, poke=False)
        self.staged.pop(lot, None)
        self.last_cause.pop(lot, None)

    # ---- scheduling tick ----------------------------------------------

    def _validate(self, moment: float) -> None:
        sim = self.sim
        for tool, mine in enumerate(self.frozen):
            if not mine:
                continue
            fam = sim.fab.tool_family[tool]
            down = _covering(sim.downs[tool], moment) is not None
            in_pm = _covering(sim.pm[tool], moment) is not None
            for lot in list(mine):
                if not sim.waiting[lot] or sim.step_family(lot) != fam:
                    self._drop(lot)
                elif down:
                    self.unfreeze(lot, "tool_down", moment)
                elif in_pm:
                    self.unfreeze(lot, "pm", moment)
                elif lot in sim.res_by_lot:
                    self.unfreeze(lot, "hold", moment)
                elif not sim.eligible(lot, tool, moment):
                    self.unfreeze(lot, "eligibility", moment)

    def _plan_family(
        self, fam: int, order: list[int], moment: float
    ) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
        """List scheduling of the family order: (zone per tool, planned per tool).

        Tools come free in order (now, end of the running piece, end of a PM;
        a down or reserved tool takes nothing). A zone slot takes, among the
        first LOOKAHEAD feasible lots ready by then, the one the policy's own
        per-tool rank puts first (setup-aware, with the tool's planned recipe);
        later slots take the first feasible lot of the order. Feasible means
        eligible and able to finish before the tool's next PM. The first
        loads within ``max_lots`` and ``max_sec`` form the zone (frozen when
        enabled, carried over between ticks; a shadow when off).
        """
        sim = self.sim
        family = sim.fab.families[fam]
        horizon = moment + self.cfg.max_sec
        zone: dict[int, list[int]] = {}
        planned: dict[int, list[int]] = {}
        taken: set[int] = set(self.fam_frozen[fam]) if self.enabled else set()
        free: list[tuple[float, int]] = []
        loads: dict[int, int] = {}
        recipe_at: dict[int, int] = {}
        for tool in range(family.tool0, family.tool0 + family.tools):
            if _covering(sim.downs[tool], moment) is not None or sim.res_lot[tool] >= 0:
                continue
            at = sim.busy_until[tool] if sim.running[tool] >= 0 else moment
            gone = _covering(sim.pm[tool], moment)
            if gone is not None:
                at = max(at, gone[1])
            count = 0
            recipe_at[tool] = sim.tool_recipe[tool]
            if self.enabled and self.frozen[tool]:
                zone[tool] = list(self.frozen[tool])
                for lot in self.frozen[tool]:
                    at = max(at, sim.ready[lot]) + sim.piece_seconds(lot, tool)
                    count += 1
                    recipe_at[tool] = self._recipe(lot)
            loads[tool] = count
            free.append((at, tool))
        heapq.heapify(free)
        spare = PLAN_DEPTH
        rest = [lot for lot in order if lot not in taken]
        # Open batch per tool: (recipe, lots, start, end, in zone).
        open_batch: dict[int, tuple[int, int, float, float, bool]] = {}
        while free and rest and spare > 0:
            at, tool = heapq.heappop(free)
            zone_slot = not planned.get(tool) and loads[tool] < self.cfg.max_lots and at <= horizon
            pick = self._pick(tool, at, rest, moment, recipe_at[tool], zone_slot)
            if pick < 0:
                continue
            rest.remove(pick)
            recipe_at[tool] = self._recipe(pick)
            route = sim.fab.routes[sim.fab.lot_route[pick]]
            index = sim.step[pick]
            proc = sim.piece_seconds(pick, tool)
            batch = open_batch.get(tool)
            cap = max(1, route.batch_max[index] // self.wafers)
            if (
                route.batch_max[index] > 0
                and batch is not None
                and batch[0] == route.recipe[index]
                and batch[1] < cap
                and sim.ready[pick] <= batch[2]
            ):
                # Joins the tool's open batch: same load, same start.
                end = max(batch[3], batch[2] + proc)
                in_zone = batch[4]
                open_batch[tool] = (batch[0], batch[1] + 1, batch[2], end, in_zone)
            else:
                start = max(at, sim.ready[pick])
                end = start + proc
                in_zone = (
                    not planned.get(tool) and loads[tool] < self.cfg.max_lots and start <= horizon
                )
                if in_zone:
                    loads[tool] += 1
                if route.batch_max[index] > 0:
                    open_batch[tool] = (route.recipe[index], 1, start, end, in_zone)
                else:
                    open_batch.pop(tool, None)
            if in_zone:
                zone.setdefault(tool, []).append(pick)
            else:
                planned.setdefault(tool, []).append(pick)
                spare -= 1
            heapq.heappush(free, (end, tool))
        return zone, planned

    def _recipe(self, lot: int) -> int:
        route = self.sim.fab.routes[self.sim.fab.lot_route[lot]]
        return route.recipe[self.sim.step[lot]]

    def _pick(
        self, tool: int, at: float, rest: list[int], moment: float, recipe: int, zone_slot: bool
    ) -> int:
        """The lot the tool takes when it comes free at ``at`` in the plan.

        Beyond the zone: the first feasible lot of the family order. For a
        zone slot: the policy's own per-tool choice, i.e. the best
        ``rank`` (setup from the recipe the tool will hold then) among the
        first ``LOOKAHEAD`` feasible lots ready by ``at`` -- the same
        candidate cap the dispatcher uses.
        """
        sim = self.sim
        first = -1
        candidates: list[int] = []
        for lot in rest:
            if not sim.eligible(lot, tool, moment):
                continue
            if sim.overlaps_pm(tool, max(at, sim.ready[lot]), sim.piece_seconds(lot, tool)):
                continue
            if first < 0:
                first = lot
                if not zone_slot:
                    return first
            if sim.ready[lot] <= at + 1e-6:
                candidates.append(lot)
                if len(candidates) >= LOOKAHEAD:
                    break
        if not candidates:
            return first
        held = sim.tool_recipe[tool]
        sim.tool_recipe[tool] = recipe
        try:
            return min(candidates, key=lambda lot: sim.rank(lot, tool, moment))
        finally:
            sim.tool_recipe[tool] = held

    def on_tick(self, moment: float) -> None:
        sim = self.sim
        self.ticks += 1
        if self.enabled:
            self._validate(moment)
        orders: dict[int, list[int]] = {}
        zones: dict[int, list[int]] = {}
        plans: dict[int, list[int]] = {}
        for fam in range(len(sim.fab.families)):
            rows = sim.live(fam) if sim.queues[fam] else []
            if not rows:
                continue
            order = sorted(rows, key=lambda lot: sim.cheap(lot, moment))
            orders[fam] = order
            zone, planned = self._plan_family(fam, order, moment)
            zones.update(zone)
            plans.update(planned)
        new_frozen = 0
        if self.enabled:
            for tool, lots in zones.items():
                fam = sim.fab.tool_family[tool]
                fresh = [lot for lot in lots if lot not in self.frozen_at]
                for lot in fresh:
                    self.frozen[tool].append(lot)
                    self.frozen_at[lot] = tool
                    self.fam_frozen[fam].add(lot)
                new_frozen += len(fresh)
                if fresh and sim.running[tool] < 0 and tool in sim.idle[fam]:
                    sim.push(moment, self.wake_kind, tool)
        # Staging and second transports (a staged lot re-targeted elsewhere).
        retargeted: list[list[Any]] = []
        for tool, lots in zones.items():
            for lot in lots:
                step = sim.step[lot]
                old = self.staged.get(lot)
                if old is not None and old[1] == step and old[0] != tool:
                    cause = self.last_cause.get(lot, "replan")
                    self.second[cause] = self.second.get(cause, 0) + 1
                    self.second_sec += self._move(old[0], tool)
                    if len(retargeted) < LOG_CHANGES_MAX:
                        retargeted.append([lot, old[0], tool, cause])
                self.last_cause.pop(lot, None)
                self.staged[lot] = (tool, step)
        # Plan diff against the previous tick.
        plan: dict[int, int] = {}
        for tool, lots in zones.items():
            for lot in lots:
                plan[lot] = tool
        staged_now = dict(plan)
        for tool, lots in plans.items():
            for lot in lots:
                plan[lot] = tool
        common = 0
        changed: list[list[int]] = []
        for lot, tool in plan.items():
            old_tool = self.prev_plan.get(lot)
            if old_tool is None:
                continue
            common += 1
            if old_tool != tool:
                changed.append([lot, old_tool, tool])
        staged_common = 0
        staged_changed = 0
        for lot, tool in staged_now.items():
            old_tool = self.prev_plan.get(lot)
            if old_tool is None:
                continue
            staged_common += 1
            if old_tool != tool:
                staged_changed += 1
        swaps = 0
        pairs = 0
        for fam, order in orders.items():
            before = self.prev_orders.get(fam)
            if not before:
                continue
            pos = {lot: i for i, lot in enumerate(before)}
            seq = [pos[lot] for lot in order if lot in pos]
            swaps += inversions(seq)
            pairs += len(seq) * (len(seq) - 1) // 2
        if self.prev_plan:
            self.compared_ticks += 1
            self.tool_changes += len(changed)
            self.change_rates.append(len(changed) / common if common else 0.0)
            self.staged_changes += staged_changed
            self.staged_rates.append(staged_changed / staged_common if staged_common else 0.0)
            self.swaps += swaps
            self.tau.append(swaps / pairs if pairs else 0.0)
        self.planned_lots.update(plan)
        n_frozen = sum(len(lots) for lots in zones.values())
        n_planned = sum(len(lots) for lots in plans.values())
        self.frozen_sum += n_frozen
        self.replanned_sum += n_planned
        diff = {
            "tool_changes": len(changed),
            "compared": common,
            "staged_tool_changes": staged_changed,
            "order_swaps": swaps,
            "order_pairs": pairs,
            "kendall_tau_distance": round(swaps / pairs, 6) if pairs else 0.0,
            "frozen": n_frozen,
            "new_frozen": new_frozen,
            "replanned": n_planned,
            "unfreezes": len(self.tick_unfreezes),
            "second_transports": len(retargeted),
        }
        lead = getattr(sim, "lead", None)
        decisions: list[Any] = []
        lead_log = getattr(lead, "log", None)
        if isinstance(lead_log, list):
            decisions = lead_log[self.lead_seen :]
            self.lead_seen = len(lead_log)
        if sim.record:
            sim.events.append(
                (
                    "sched_tick",
                    moment,
                    {tool: tuple(lots) for tool, lots in zones.items()},
                    diff,
                )
            )
        if self.log is not None:
            self._write(moment, orders, zones, plans, changed, retargeted, diff, decisions)
        self.tick_unfreezes = []
        self.prev_plan = plan
        self.prev_orders = orders

    def _write(
        self,
        moment: float,
        orders: dict[int, list[int]],
        zones: dict[int, list[int]],
        plans: dict[int, list[int]],
        changed: list[list[int]],
        retargeted: list[list[Any]],
        diff: dict[str, Any],
        decisions: list[Any],
    ) -> None:
        sim = self.sim
        fab = sim.fab
        lot_id = fab.lot_id
        tool_name = fab.tool_name
        tools: dict[str, dict[str, Any]] = {}
        for tool in sorted(
            set(zones) | set(plans) | {t for t, r in enumerate(sim.running) if r >= 0}
        ):
            row: dict[str, Any] = {
                "running": [lot_id[lot] for lot in sim.on_tool[tool]],
                "frozen": [lot_id[lot] for lot in zones.get(tool, [])],
                "planned": [lot_id[lot] for lot in plans.get(tool, [])],
            }
            if not (row["frozen"] or row["planned"]):
                continue
            tools[tool_name[tool]] = row
        holds = {tool_name[tool]: lot_id[lot] for tool, lot in enumerate(sim.res_lot) if lot >= 0}
        hold_plan = {
            fab.families[fam].name: [lot_id[lot] for lot in rows]
            for fam, rows in enumerate(sim.hold_plan)
            if rows
        }
        record = {
            "t": round(moment, 1),
            "t_h": round(moment / 3600.0, 4),
            "policy": sim.policy,
            "freeze": self.enabled,
            "queues": {
                fab.families[fam].name: [lot_id[lot] for lot in order]
                for fam, order in orders.items()
            },
            "tools": tools,
            "holds": {"reserved": holds, "hold_plan": hold_plan},
            "ai_decisions": decisions,
            "diff": diff,
            "tool_changes": [
                [lot_id[lot], tool_name[old], tool_name[new]]
                for lot, old, new in changed[:LOG_CHANGES_MAX]
            ],
            "second_transports": [
                [lot_id[lot], tool_name[old], tool_name[new], cause]
                for lot, old, new, cause in retargeted
            ],
            "unfreezes": [
                [at, lot_id[lot], tool_name[tool], reason]
                for at, lot, tool, reason in self.tick_unfreezes
            ],
        }
        assert self.log is not None
        self.log.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")

    # ---- result -------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        if self.log is not None:
            self.log.close()
            self.log = None

        def mean(rows: list[float]) -> float:
            return round(sum(rows) / len(rows), 6) if rows else 0.0

        ticks = max(1, self.compared_ticks)
        return {
            "enabled": self.enabled,
            "max_lots": self.cfg.max_lots,
            "max_min": round(self.cfg.max_sec / 60.0, 3),
            "ticks": self.ticks,
            "plan_tool_change_rate": mean(self.change_rates),
            "plan_tool_changes_per_tick": round(self.tool_changes / ticks, 3),
            "plan_tool_changes_per_lot": round(self.tool_changes / len(self.planned_lots), 4)
            if self.planned_lots
            else 0.0,
            "staged_tool_change_rate": mean(self.staged_rates),
            "staged_tool_changes": self.staged_changes,
            "order_swaps_per_tick": round(self.swaps / ticks, 2),
            "kendall_tau_distance": mean(self.tau),
            "frozen_per_tick": round(self.frozen_sum / max(1, self.ticks), 2),
            "replanned_per_tick": round(self.replanned_sum / max(1, self.ticks), 2),
            "second_transports": sum(self.second.values()),
            "second_transport_causes": dict(sorted(self.second.items())),
            "second_transport_min": round(self.second_sec / 60.0, 1),
            "unfreezes": dict(self.unfreezes),
            "unfreeze_total": sum(self.unfreezes.values()),
            "frozen_starts": self.frozen_starts,
            "hot_inserts": self.hot_inserts,
            "qtime_inserts": self.qtime_inserts,
            "fill_starts": self.fill_starts,
            "frozen_waits": self.frozen_waits,
        }


# ---- reading tick logs (API) -------------------------------------------

TICK_LOG_DIR_ENV = "RESILIMES_TICK_LOG_DIR"
_RUN_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def tick_log_dir() -> str:
    """Folder the API reads tick logs from (``RESILIMES_TICK_LOG_DIR``)."""
    return os.environ.get(TICK_LOG_DIR_ENV, os.path.join("out", "sched_ticks"))


def list_tick_logs(folder: str) -> list[str]:
    """Run names with a ``.jsonl`` or ``.jsonl.gz`` tick log in ``folder``."""
    if not os.path.isdir(folder):
        return []
    names = []
    for name in os.listdir(folder):
        for ext in (".jsonl.gz", ".jsonl"):
            if name.endswith(ext):
                names.append(name[: -len(ext)])
                break
    return sorted(names)


def read_tick_log(folder: str, run: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """Ticks ``offset .. offset+limit`` of one run's log. KeyError if absent."""
    if not _RUN_NAME.match(run) or run.startswith("."):
        raise KeyError(run)
    path = os.path.join(folder, run + ".jsonl")
    if not os.path.isfile(path):
        path += ".gz"
        if not os.path.isfile(path):
            raise KeyError(run)
    ticks: list[dict[str, Any]] = []
    more = False
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < offset:
                continue
            if len(ticks) >= limit:
                more = True
                break
            ticks.append(json.loads(line))
    return {"run": run, "offset": offset, "count": len(ticks), "more": more, "ticks": ticks}
