"""Scheduling exceptions for the AI shift lead (detection, options, impact).

The shift lead (``resilimes.agents.shift_lead``) is asked only at an
exception: a point where a human shift lead would step in because the rules'
default visibly costs something. At each scheduling tick ``detect`` looks for
five kinds:

* ``breakdown``: a scanner is down and lots pinned to it (litho dedication)
  are waiting. The rule re-routes them to a sibling scanner at once.
* ``qtime_competition``: two or more lots inside an open Q-time window
  compete for one family and the rule order is projected to lose at least one.
* ``pm_conflict``: a tool's PM starts inside the lookahead and Q-time lots
  at its family are projected to miss with the PM as scheduled.
* ``batch_underfill``: a furnace (batch) family has an idle tool and an
  under-filled batch waiting for more lots, within ``NEAR_CAP_SEC`` of its
  wait cap.
* ``hot_insertion``: a hot or VIP lot waits at a family together with Q-time
  lots, and the rule order (hot first) is projected to make a Q-time lot miss.

For each exception the engine (never the model) builds 2-4 legal options; the
first is always the rule default and is a no-op: the dispatcher behaves as if
no shift lead existed. Each option gets an ``Impact`` from ``project``, a
short list-scheduling projection of the family from live state (no future
breakdowns are known to it). Options act through four levers that
``simulate._Sim`` reads only when a shift lead is attached: a priority boost
inside the urgency band, keeping a pin through a repair, starting an
under-filled batch now, and deferring one PM window by a bounded amount.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from resilimes.smt.fab import BATCH_MAX_WAIT_SEC, HOT_BATCH_WAIT_SEC, measured

Sim = Any  # resilimes.smt.simulate._Sim; typed loosely to keep the hook one-way.

KINDS = ("breakdown", "qtime_competition", "pm_conflict", "batch_underfill", "hot_insertion")
LOOKAHEAD_SEC = 2 * 3600.0
PROJECT_LOTS = 60
NEAR_CAP_SEC = 30 * 60.0
PM_DEFER_STEPS_SEC = (30 * 60.0, 60 * 60.0, 120 * 60.0)
PM_DEFER_MAX_SEC = 120 * 60.0
BOOST_SEC = 3600.0
_WAFERS = 25
_BOOST = -1.0


def _covering(windows: list[tuple[float, float]], moment: float) -> tuple[float, float] | None:
    for start_at, end_at in windows:
        if start_at <= moment < end_at:
            return start_at, end_at
    return None


@dataclass(frozen=True)
class Impact:
    """Projected cost of an option over the lookahead, for one family."""

    qtime_violations: int
    late_lots: int
    hot_late: int
    idle_min: float
    queue_growth: int

    def key(self) -> tuple[float, ...]:
        """Lexicographic order of the heuristic stand-in: Q-time, hot, late, idle."""
        return (
            float(self.qtime_violations),
            float(self.hot_late),
            float(self.late_lots),
            round(self.idle_min, 1),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "qtime_violations": self.qtime_violations,
            "late_lots": self.late_lots,
            "hot_late": self.hot_late,
            "idle_min": round(self.idle_min, 1),
            "queue_growth": self.queue_growth,
        }


@dataclass
class Lever:
    """What an option changes. ``kind == "none"`` is the rule default."""

    kind: str = "none"
    # (lot, step) -> priority inside the urgency band; lower runs first.
    prio: dict[tuple[int, int], float] = field(default_factory=dict)
    # Lots that wait for their pinned scanner instead of re-routing.
    keep_pin: frozenset[int] = frozenset()
    # (family, recipe) that may start under-filled now.
    batch: tuple[int, int] | None = None
    # (tool, window index, shift seconds) of a deferred PM window.
    pm: tuple[int, int, float] | None = None
    until: float = 0.0


@dataclass
class Option:
    id: str
    action: str
    lever: Lever
    default: bool = False
    impact: Impact | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "rule_default": self.default,
            "impact": None if self.impact is None else self.impact.as_dict(),
        }


@dataclass
class FabException:
    id: str
    kind: str
    t: float
    family: int
    tool: int
    lots: list[int]
    situation: str
    facts: dict[str, Any]
    options: list[Option]
    key: tuple[Any, ...] = ()

    @property
    def default(self) -> Option:
        return next(option for option in self.options if option.default)

    def option(self, option_id: str) -> Option | None:
        return next((option for option in self.options if option.id == option_id), None)


# ---------------------------------------------------------------- projection


@dataclass
class _Row:
    lot: int
    index: int
    ready: float
    proc: float
    size: int
    floor: int
    recipe: int
    latest: float | None
    base: float  # latest start that still meets the due date
    tier: int
    key: tuple[float, ...]
    pinned: int
    waiting: bool


def waiting_lots(sim: Sim, fam: int) -> list[int]:
    """The family's live queue, read without touching the simulator's lists."""
    seen: set[int] = set()
    rows: list[int] = []
    for lot in sim.queues[fam]:
        if lot in seen or not sim.waiting[lot] or sim.step_family(lot) != fam:
            continue
        seen.add(lot)
        rows.append(lot)
    return rows


def _next_step(sim: Sim, lot: int, index: int) -> int:
    route = sim.fab.routes[sim.fab.lot_route[lot]]
    number = sim.lot_no[lot]
    nxt = index + 1
    while nxt < len(route.family) and not measured(route, nxt, number):
        nxt += 1
    return nxt


def inbound_lots(sim: Sim, moment: float, until: float) -> dict[int, list[tuple[int, int, float]]]:
    """Lots in process now, per family of their next step: (lot, step, eta)."""
    out: dict[int, list[tuple[int, int, float]]] = {}
    for tool, lots in enumerate(sim.on_tool):
        if not lots:
            continue
        finish = max(moment, sim.busy_until[tool])
        for lot in lots:
            index = sim.step[lot]
            route = sim.fab.routes[sim.fab.lot_route[lot]]
            nxt = _next_step(sim, lot, index)
            if nxt >= len(route.family):
                continue
            fam = route.family[nxt]
            eta = finish + sim.move_seconds(route.family[index], fam)
            if eta <= until:
                out.setdefault(fam, []).append((lot, nxt, eta))
    return out


def _latest_waiting(sim: Sim, lot: int) -> float | None:
    if not sim.in_window(lot):
        return None
    return float(sim.deadline[lot] - sim.qtime_need(lot))


def _due_base(sim: Sim, lot: int, index: int) -> float:
    """Latest start here that still meets the due date at the observed flow.

    Due minus the raw process still due, minus the fab-wide queue/process
    ratio (``flow_wait``, refreshed each tick) times the raw process after
    this step: the same expected wait the dispatcher's due risk uses.
    """
    route = sim.fab.routes[sim.fab.lot_route[lot]]
    after = max(0.0, route.remain[index] - route.cycle[index])
    return float(sim.due[lot] - route.remain[index] - sim.flow_wait * after)


def _rows(
    sim: Sim,
    fam: int,
    moment: float,
    inbound: list[tuple[int, int, float]],
    prio: dict[tuple[int, int], float],
) -> list[_Row]:
    rows: list[_Row] = []
    plan = sim.plan is not None

    def make(lot: int, index: int, ready: float, latest: float | None, waiting: bool) -> _Row:
        route = sim.fab.routes[sim.fab.lot_route[lot]]
        cap = route.batch_max[index]
        size = max(1, cap // _WAFERS)
        floor = max(1, -(-(route.batch_min[index] or cap) // _WAFERS)) if cap else 1
        band = float(sim.urgency_band(lot, moment)) if waiting else 2.0
        tier = int(sim.tier(lot))
        order = sim.plan_rank[lot] if plan else sim.due[lot]
        key = (band, prio.get((lot, index), 0.0), float(tier), float(order), float(lot))
        return _Row(
            lot=lot,
            index=index,
            ready=ready,
            proc=float(route.cycle[index]),
            size=size if cap else 1,
            floor=floor,
            recipe=int(route.recipe[index]),
            latest=latest,
            base=_due_base(sim, lot, index),
            tier=tier,
            key=key,
            pinned=int(sim.pin_for(lot, index)),
            waiting=waiting,
        )

    for lot in waiting_lots(sim, fam):
        ready = max(moment, float(sim.ready[lot]))
        rows.append(make(lot, sim.step[lot], ready, _latest_waiting(sim, lot), True))
    q_inbound = sim.inbound[fam]
    for lot, nxt, eta in inbound:
        row = q_inbound.get(lot)
        latest = row[1] if row is not None and row[2] == nxt else None
        rows.append(make(lot, nxt, eta, latest, False))
    rows.sort(key=lambda row: row.key)
    if len(rows) > PROJECT_LOTS:
        head = rows[:PROJECT_LOTS]
        head += [row for row in rows[PROJECT_LOTS:] if row.latest is not None]
        rows = head
    return rows


def project(
    sim: Sim,
    fam: int,
    moment: float,
    *,
    inbound: list[tuple[int, int, float]] | None = None,
    prio: dict[tuple[int, int], float] | None = None,
    keep_pin: frozenset[int] = frozenset(),
    batch_now: tuple[int, int] | None = None,
    pm_shift: tuple[int, int, float] | None = None,
    lookahead: float = LOOKAHEAD_SEC,
) -> Impact:
    """Greedy list schedule of one family over ``lookahead`` seconds.

    Tools come free at the end of their running piece, current breakdown or
    current PM; PM windows ahead block a start that would cross them (as in
    ``choose``). Lots (queue plus lots finishing upstream inside the window)
    go in the dispatcher's order (urgency band, shift-lead priority, class
    tier, plan rank), each on the tool that can start it first; a pinned lot
    only on its scanner unless that scanner is down and the lot is not kept
    on its pin. A batch step starts when ``floor`` lots are there or at the
    wait cap, or now with ``batch_now``. Future breakdowns are not known.
    """
    end = moment + lookahead
    lead = getattr(sim, "lead", None)
    merged: dict[tuple[int, int], float] = {} if lead is None else lead.prio_map()
    if prio:
        merged.update(prio)
    held = set(keep_pin)
    if lead is not None:
        held |= lead.kept_pins(moment)
    rows = _rows(sim, fam, moment, inbound or [], merged)
    family = sim.fab.families[fam]
    tools = list(range(family.tool0, family.tool0 + family.tools))
    free: dict[int, float] = {}
    blocks: dict[int, list[tuple[float, float]]] = {}
    lost: dict[int, float] = {}
    for tool in tools:
        pms = list(sim.pm[tool])
        if pm_shift is not None and pm_shift[0] == tool:
            start_at, end_at = pms[pm_shift[1]]
            pms[pm_shift[1]] = (start_at + pm_shift[2], end_at + pm_shift[2])
        gone = _covering(sim.downs[tool], moment) or _covering(pms, moment)
        if gone is not None:
            free[tool] = gone[1]
        elif sim.running[tool] >= 0:
            free[tool] = max(moment, float(sim.busy_until[tool]))
        else:
            free[tool] = moment
        lost[tool] = min(end, free[tool]) - moment if gone is not None else 0.0
        blocks[tool] = sorted((a, b) for a, b in pms if b > moment and a < end)
    busy = dict.fromkeys(tools, 0.0)
    for tool in tools:
        if sim.running[tool] >= 0 and _covering(sim.downs[tool], moment) is None:
            busy[tool] = min(end, free[tool]) - moment

    def earliest(tool: int, t0: float, proc: float) -> float:
        start = max(free[tool], t0)
        for a, b in blocks[tool]:
            if start < b and start + proc > a:
                start = max(start, b)
        return start

    def allowed(row: _Row) -> list[int]:
        pinned = row.pinned
        if pinned < 0 or pinned not in free:
            return tools
        if _covering(sim.downs[pinned], moment) is not None and row.lot not in held:
            return tools
        return [pinned]

    placed: dict[int, float] = {}
    for row in rows:
        if row.lot in placed:
            continue
        members = [row]
        go_at = row.ready
        if row.size > 1:
            group = [
                other
                for other in rows
                if other.lot not in placed and other.recipe == row.recipe and other.size > 1
            ]
            group.sort(key=lambda other: other.ready)
            if len(group) >= row.floor:
                go_at = group[row.floor - 1].ready
            elif batch_now == (fam, row.recipe):
                go_at = max(moment, row.ready)
            else:
                cap_at = min(other.ready for other in group) + BATCH_MAX_WAIT_SEC
                hot = [other.ready for other in group if other.tier < 2]
                if hot:
                    cap_at = min(cap_at, min(hot) + HOT_BATCH_WAIT_SEC)
                urgent = [other.latest for other in group if other.latest is not None]
                go_at = max(row.ready, min([cap_at, *urgent]))
        options = [(earliest(tool, go_at, row.proc), tool) for tool in allowed(row)]
        start, tool = min(options)
        if start >= end:
            continue
        if row.size > 1:
            members = [
                other
                for other in rows
                if other.lot not in placed
                and other.recipe == row.recipe
                and other.size > 1
                and other.ready <= start + 1e-6
            ][: row.size]
            if row not in members:
                members = [row, *members[: row.size - 1]]
        for member in members:
            placed[member.lot] = start
        free[tool] = start + row.proc
        busy[tool] += min(end, start + row.proc) - start

    q_viol = late = hot_late = 0
    for row in rows:
        at = placed.get(row.lot)
        if row.latest is not None and (
            (at is not None and at > row.latest + 1e-6) or (at is None and row.latest < end)
        ):
            q_viol += 1
        if row.ready <= row.base and (
            (at is not None and at > row.base) or (at is None and row.base < end)
        ):
            late += 1
            if row.tier < 2:
                hot_late += 1
    idle = 0.0
    for tool in tools:
        down = sum(max(0.0, min(b, end) - max(a, moment)) for a, b in blocks[tool] if a >= moment)
        idle += max(0.0, lookahead - lost[tool] - busy[tool] - down)
    waiting_now = sum(1 for row in rows if row.waiting)
    unplaced = sum(1 for row in rows if row.lot not in placed)
    return Impact(
        qtime_violations=q_viol,
        late_lots=late,
        hot_late=hot_late,
        idle_min=idle / 60.0,
        queue_growth=unplaced - waiting_now,
    )


# ---------------------------------------------------------------- detection


class Detector:
    """Finds exceptions at a tick and builds their options with impacts."""

    def __init__(self, sim: Sim, max_per_tick: int = 8) -> None:
        self.sim = sim
        self.max_per_tick = max_per_tick
        self.seen: dict[tuple[Any, ...], float] = {}
        self.count = 0
        self.pm_deferred: set[tuple[int, float]] = set()

    def _new_id(self) -> str:
        self.count += 1
        return f"X{self.count:05d}"

    def _fresh(self, key: tuple[Any, ...], moment: float, ttl: float = 3600.0) -> bool:
        until = self.seen.get(key)
        if until is not None and moment < until:
            return False
        self.seen[key] = moment + ttl
        return True

    def detect(self, moment: float) -> list[FabException]:
        sim = self.sim
        inbound = inbound_lots(sim, moment, moment + LOOKAHEAD_SEC)
        found: list[FabException] = []
        used_fams: set[int] = set()
        for finder in (self._breakdowns, self._pm, self._qtime, self._batches):
            for exc in finder(moment, inbound, used_fams):
                found.append(exc)
                used_fams.add(exc.family)
                if len(found) >= self.max_per_tick:
                    return found
        return found

    # (a) breakdown with pinned lots ------------------------------------
    def _breakdowns(
        self, moment: float, inbound: dict[int, list[tuple[int, int, float]]], used: set[int]
    ) -> list[FabException]:
        sim = self.sim
        out: list[FabException] = []
        for tool, spans in enumerate(sim.downs):
            window = _covering(spans, moment)
            if window is None:
                continue
            fam = sim.fab.tool_family[tool]
            if fam in used or sim.fab.families[fam].tools < 2:
                continue
            rows = inbound.get(fam, [])
            pinned = [
                lot for lot in waiting_lots(sim, fam) if sim.pin_for(lot, sim.step[lot]) == tool
            ]
            pinned += [lot for lot, nxt, _eta in rows if sim.pin_for(lot, nxt) == tool]
            if not pinned:
                continue
            if not self._fresh(("breakdown", tool, window[0]), moment, ttl=math.inf):
                continue
            repair = window[1]
            critical = [
                lot
                for lot in pinned
                if sim.in_window(lot) or lot in sim.inbound[fam] or sim.tier(lot) < 2
            ]
            options = [
                Option("A", "re-route every pinned lot to a sibling scanner now", Lever(), True),
                Option(
                    "B",
                    f"wait for the repair (ETA {repair / 3600.0:.1f} h) for every pinned lot",
                    Lever("keep_pin", keep_pin=frozenset(pinned), until=repair),
                ),
            ]
            rest = frozenset(lot for lot in pinned if lot not in critical)
            if critical and rest:
                options.insert(
                    1,
                    Option(
                        "C",
                        "re-route only Q-time and hot/VIP lots; the rest wait for the repair",
                        Lever("keep_pin", keep_pin=rest, until=repair),
                    ),
                )
            for option in options:
                option.impact = project(
                    sim, fam, moment, inbound=rows, keep_pin=option.lever.keep_pin
                )
            name = sim.fab.tool_name[tool]
            out.append(
                FabException(
                    id=self._new_id(),
                    kind="breakdown",
                    t=moment,
                    family=fam,
                    tool=tool,
                    lots=pinned,
                    situation=(
                        f"{name} is down until {repair / 3600.0:.1f} h; "
                        f"{len(pinned)} lots pinned to it (litho layer dedication), "
                        f"{len(critical)} of them Q-time or hot/VIP"
                    ),
                    facts={
                        "tool": name,
                        "repair_eta_h": round(repair / 3600.0, 2),
                        "pinned_lots": len(pinned),
                        "critical_lots": len(critical),
                        "sibling_tools": sim.fab.families[fam].tools - 1,
                    },
                    options=options,
                    key=("breakdown", tool, window[0]),
                )
            )
        return out

    # (c) PM conflict -----------------------------------------------------
    def _pm(
        self, moment: float, inbound: dict[int, list[tuple[int, int, float]]], used: set[int]
    ) -> list[FabException]:
        sim = self.sim
        out: list[FabException] = []
        for tool, spans in enumerate(sim.pm):
            for index, (start_at, end_at) in enumerate(spans):
                if not moment < start_at <= moment + LOOKAHEAD_SEC:
                    continue
                if (tool, start_at) in self.pm_deferred:
                    continue
                fam = sim.fab.tool_family[tool]
                if fam in used:
                    continue
                rows = inbound.get(fam, [])
                window_lots = [lot for lot in waiting_lots(sim, fam) if sim.in_window(lot)]
                window_lots += [lot for lot, _n, _e in rows if lot in sim.inbound[fam]]
                if not window_lots:
                    continue
                base = project(sim, fam, moment, inbound=rows)
                if base.qtime_violations == 0:
                    continue
                if not self._fresh(("pm", tool, start_at), moment, ttl=900.0):
                    continue
                options = [Option("A", "keep the PM as scheduled", Lever(), True, base)]
                for shift in PM_DEFER_STEPS_SEC:
                    if not pm_shift_ok(sim, tool, index, shift):
                        continue
                    lever = Lever("pm_defer", pm=(tool, index, shift), until=start_at + shift)
                    label = chr(ord("A") + len(options))
                    impact = project(sim, fam, moment, inbound=rows, pm_shift=lever.pm)
                    options.append(
                        Option(
                            label, f"defer the PM by {int(shift // 60)} min", lever, False, impact
                        )
                    )
                if len(options) < 2:
                    continue
                name = sim.fab.tool_name[tool]
                out.append(
                    FabException(
                        id=self._new_id(),
                        kind="pm_conflict",
                        t=moment,
                        family=fam,
                        tool=tool,
                        lots=window_lots,
                        situation=(
                            f"PM on {name} starts at {start_at / 3600.0:.2f} h "
                            f"({(start_at - moment) / 60.0:.0f} min from now, "
                            f"{(end_at - start_at) / 60.0:.0f} min long); "
                            f"{len(window_lots)} Q-time lots due at "
                            f"{sim.fab.families[fam].name}, "
                            f"{base.qtime_violations} projected to miss"
                        ),
                        facts={
                            "tool": name,
                            "pm_start_in_min": round((start_at - moment) / 60.0, 1),
                            "pm_len_min": round((end_at - start_at) / 60.0, 1),
                            "qtime_lots": len(window_lots),
                            "max_defer_min": PM_DEFER_MAX_SEC / 60.0,
                        },
                        options=options,
                        key=("pm", tool, start_at),
                    )
                )
                used.add(fam)
                break
        return out

    # (b) Q-time competition and (e) hot-lot insertion --------------------
    def _qtime(
        self, moment: float, inbound: dict[int, list[tuple[int, int, float]]], used: set[int]
    ) -> list[FabException]:
        sim = self.sim
        out: list[FabException] = []
        for fam in range(len(sim.fab.families)):
            if fam in used or not sim.queues[fam]:
                continue
            queue = waiting_lots(sim, fam)
            rows = inbound.get(fam, [])
            latest: dict[tuple[int, int], float] = {}
            for lot in queue:
                value = _latest_waiting(sim, lot)
                if value is not None:
                    latest[(lot, sim.step[lot])] = value
            for lot, nxt, _eta in rows:
                row = sim.inbound[fam].get(lot)
                if row is not None and row[2] == nxt:
                    latest[(lot, nxt)] = row[1]
            hot = [lot for lot in queue if sim.tier(lot) < 2 and not sim.in_window(lot)]
            if not latest or (len(latest) < 2 and not hot):
                continue
            base = project(sim, fam, moment, inbound=rows)
            if base.qtime_violations == 0:
                continue
            kind = "hot_insertion" if hot else "qtime_competition"
            lots = sorted({lot for lot, _ in latest})
            if not self._fresh((kind, fam), moment, ttl=1800.0):
                continue
            edf = {key: _BOOST + (value - moment) / 1e9 for key, value in latest.items()}
            options = [
                Option(
                    "A",
                    "keep the rule order (hot/VIP first)" if hot else "keep the rule order",
                    Lever(),
                    True,
                    base,
                )
            ]
            label = "run Q-time lots first, tightest latest start first"
            options.append(Option("B", label, Lever("prio", prio=edf, until=moment + BOOST_SEC)))
            options[1].impact = project(sim, fam, moment, inbound=rows, prio=edf)
            if options[1].impact.qtime_violations > 0:
                # Triage: demote the windows that still miss under EDF so the
                # rest are not delayed by lots that cannot make it anyway.
                saved = self._triage(fam, moment, rows, edf)
                if saved is not None and saved != edf:
                    options.append(
                        Option(
                            "C",
                            "Q-time triage: boost only the windows that can still be met",
                            Lever("prio", prio=saved, until=moment + BOOST_SEC),
                            False,
                            project(sim, fam, moment, inbound=rows, prio=saved),
                        )
                    )
            due_keys: dict[tuple[int, int], float] = {}
            for lot in queue:
                key = (lot, sim.step[lot])
                if key in latest:
                    continue
                start_by = _due_base(sim, lot, key[1])
                if moment <= start_by <= moment + LOOKAHEAD_SEC:
                    due_keys[key] = _BOOST + (start_by - moment) / 1e9
            if due_keys:
                # Q-time first must not quietly make a due-critical lot late:
                # the same boost, with due-critical lots ordered in by their
                # latest start for the due date.
                mixed = {**options[-1].lever.prio, **due_keys}
                options.append(
                    Option(
                        chr(ord("A") + len(options)),
                        "Q-time first, but due-critical lots keep their place "
                        "(earliest latest-start first)",
                        Lever("prio", prio=mixed, until=moment + BOOST_SEC),
                        False,
                        project(sim, fam, moment, inbound=rows, prio=mixed),
                    )
                )
                lots = sorted(set(lots) | {lot for lot, _ in due_keys})
            if hot:
                # Respect hot/VIP: offer Q-time-first only where the hot lots
                # stay on time in the projection.
                options = [
                    option
                    for option in options
                    if option.default
                    or (option.impact is not None and option.impact.hot_late <= base.hot_late)
                ]
            if len(options) < 2:
                continue
            situation = (
                f"{len(latest)} Q-time lots compete for {sim.fab.families[fam].name} "
                f"({sim.fab.families[fam].tools} tools, {len(queue)} queued); "
                f"rule order projects {base.qtime_violations} Q-time misses"
            )
            if hot:
                situation += f"; {len(hot)} hot/VIP lots ahead of them by class"
            out.append(
                FabException(
                    id=self._new_id(),
                    kind=kind,
                    t=moment,
                    family=fam,
                    tool=-1,
                    lots=lots,
                    situation=situation,
                    facts={
                        "family": sim.fab.families[fam].name,
                        "tools": sim.fab.families[fam].tools,
                        "queue": len(queue),
                        "qtime_lots": len(latest),
                        "hot_vip_lots": len(hot),
                        "tightest_slack_min": round((min(latest.values()) - moment) / 60.0, 1),
                    },
                    options=options,
                    key=(kind, fam),
                )
            )
            used.add(fam)
        return out

    def _triage(
        self,
        fam: int,
        moment: float,
        rows: list[tuple[int, int, float]],
        edf: dict[tuple[int, int], float],
    ) -> dict[tuple[int, int], float] | None:
        """EDF without the windows that miss under EDF (one Moore-style pass)."""
        sim = self.sim
        kept = dict(edf)
        best = project(sim, fam, moment, inbound=rows, prio=kept)
        for key in sorted(edf, key=lambda item: edf[item]):
            trial = dict(kept)
            del trial[key]
            impact = project(sim, fam, moment, inbound=rows, prio=trial)
            if impact.qtime_violations < best.qtime_violations:
                kept, best = trial, impact
        return kept if kept else None

    # (d) under-filled furnace batch near its cap -------------------------
    def _batches(
        self, moment: float, inbound: dict[int, list[tuple[int, int, float]]], used: set[int]
    ) -> list[FabException]:
        sim = self.sim
        out: list[FabException] = []
        for fam, flag in enumerate(sim.batch_family):
            if not flag or fam in used or not sim.queues[fam]:
                continue
            family = sim.fab.families[fam]
            idle = [
                tool
                for tool in range(family.tool0, family.tool0 + family.tools)
                if sim.running[tool] < 0
                and sim.res_lot[tool] < 0
                and _covering(sim.downs[tool], moment) is None
                and _covering(sim.pm[tool], moment) is None
            ]
            if not idle:
                continue
            groups: dict[int, list[int]] = {}
            for lot in waiting_lots(sim, fam):
                route = sim.fab.routes[sim.fab.lot_route[lot]]
                index = sim.step[lot]
                if route.batch_max[index] > 0 and sim.ready[lot] <= moment + 1e-6:
                    groups.setdefault(int(route.recipe[index]), []).append(lot)
            for recipe, group in sorted(groups.items()):
                head = group[0]
                route = sim.fab.routes[sim.fab.lot_route[head]]
                index = sim.step[head]
                cap = route.batch_max[index]
                floor = route.batch_min[index] or cap
                taken = group[: max(1, cap // _WAFERS)]
                _reason, until = sim.batch_rule(
                    taken, group, fam, recipe, len(taken) * _WAFERS, floor, moment
                )
                if until is None or until - moment > NEAR_CAP_SEC:
                    continue
                if not self._fresh(("batch", fam, recipe, round(until)), moment, ttl=math.inf):
                    continue
                rows = inbound.get(fam, [])
                options = [
                    Option(
                        "A",
                        f"wait for more lots (rule cap in {(until - moment) / 60.0:.0f} min)",
                        Lever(),
                        True,
                        project(sim, fam, moment, inbound=rows),
                    ),
                    Option(
                        "B",
                        f"start the batch now with {len(taken)} of {max(1, cap // _WAFERS)} lots",
                        Lever("batch_start", batch=(fam, recipe), until=until),
                        False,
                        project(sim, fam, moment, inbound=rows, batch_now=(fam, recipe)),
                    ),
                ]
                out.append(
                    FabException(
                        id=self._new_id(),
                        kind="batch_underfill",
                        t=moment,
                        family=fam,
                        tool=idle[0],
                        lots=list(taken),
                        situation=(
                            f"{family.name}: {len(idle)} idle furnace(s); recipe {recipe} "
                            f"batch has {len(taken) * _WAFERS} of min {floor} wafers, "
                            f"rule waits up to {(until - moment) / 60.0:.0f} more min"
                        ),
                        facts={
                            "family": family.name,
                            "idle_tools": len(idle),
                            "wafers": len(taken) * _WAFERS,
                            "batch_min_wafers": floor,
                            "batch_max_wafers": cap,
                            "cap_in_min": round((until - moment) / 60.0, 1),
                            "qtime_lots": sum(1 for lot in taken if sim.in_window(lot)),
                        },
                        options=options,
                        key=("batch", fam, recipe, round(until)),
                    )
                )
                used.add(fam)
                break
        return out


def pm_shift_ok(sim: Sim, tool: int, index: int, shift: float) -> bool:
    """A PM may be deferred once, by at most PM_DEFER_MAX_SEC, into free time."""
    if shift <= 0 or shift > PM_DEFER_MAX_SEC:
        return False
    spans = sim.pm[tool]
    if index >= len(spans):
        return False
    start_at, end_at = spans[index]
    if start_at <= sim.clock:
        return False
    new = (start_at + shift, end_at + shift)
    for other, (a, b) in enumerate(spans):
        if other != index and new[0] < b and new[1] > a:
            return False
    # Breakdowns are not checked: they are not known in advance.
    return True
