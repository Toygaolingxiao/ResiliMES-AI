"""Read-only replay of one recorded full-fab run, for the operator screens.

One ``run_policy(..., record=True)`` trace on the public SMT2020 benchmark is
indexed once per book. Every screen reads that index at a chosen moment ``t``:
tool states, family queues, lot positions, batches, breakdowns, and Q-time
windows. Nothing here dispatches. The order of lots on a tool is the order the
simulator chose; the reasons are read from the same lot attributes the tiered
key ranks on (class, late band, Q-time, setup, slack).
"""

from __future__ import annotations

import bisect
import hashlib
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from resilimes.kernel.score import ped_risk, tiered_key
from resilimes.smt.fab import (
    BATCH_MAX_WAIT_SEC,
    HOT_BATCH_WAIT_SEC,
    LITHO_MTTR_MIN,
    REWORK_SEC,
    WIP_FLOOR,
    WIP_PER_TOOL,
    Fab,
    load_fab,
)
from resilimes.smt.scenarios import HOT_DUE_SEC, PM_OPEN_SEC, STUDY_HORIZON_SEC
from resilimes.smt.simulate import (
    RunResult,
    pm_shift_to_open,
    pm_windows,
    run_policy,
    sample_downs,
    setup_seconds,
)

WAFERS_PER_LOT = 25
BIN_SEC = 900.0
UTIL_WINDOW_SEC = 4 * 3600.0
RISK_SEC = 8 * 3600.0
SEED = 1

WAIT = 0
RUN = 1
HOLD = 2
DONE = 3
STATUS = ("wait", "run", "hold", "done")


@dataclass(frozen=True)
class BookSpec:
    """One recorded run: the baseline or one change to it."""

    key: str
    kind: str = "base"
    forced_tool: int | None = None
    forced_until: float = 0.0
    promote_lot: int | None = None
    pm_shift: float = 0.0
    seed: int = SEED
    horizon: float = STUDY_HORIZON_SEC


@dataclass
class Piece:
    tool: int
    family: int
    start: float
    end: float
    planned: float
    lots: tuple[int, ...]
    steps: tuple[int, ...]
    setup: float
    recipe: int
    reason: str
    batch: bool
    interrupted: bool = False


@dataclass
class QWindow:
    lot: int
    origin: int
    target: int
    opened: float
    deadline: float
    limit: float
    closed: float | None = None
    outcome: str = "open"


@dataclass
class Replay:
    fab: Fab
    spec: BookSpec
    result: RunResult
    downs: list[list[tuple[float, float]]]
    pm: list[list[tuple[float, float]]]
    due: list[float]
    kind: list[str]
    pieces: list[Piece] = field(default_factory=list)
    tool_pieces: list[list[int]] = field(default_factory=list)
    tool_starts: list[list[float]] = field(default_factory=list)
    trans: list[list[tuple[float, int, int]]] = field(default_factory=list)
    trans_t: list[list[float]] = field(default_factory=list)
    ops: list[list[tuple[int, int, float]]] = field(default_factory=list)
    skips: list[list[tuple[float, int]]] = field(default_factory=list)
    recleans: list[tuple[float, int, int, int]] = field(default_factory=list)
    reworks: list[tuple[float, int, int, int]] = field(default_factory=list)
    interrupts: list[tuple[float, int, tuple[int, ...]]] = field(default_factory=list)
    qwins: list[QWindow] = field(default_factory=list)
    lot_qwins: list[list[int]] = field(default_factory=list)
    waits: list[list[tuple[float, float, int, int]]] = field(default_factory=list)
    finished: list[float] = field(default_factory=list)
    occupancy: list[list[float]] = field(default_factory=list)
    batch_families: set[int] = field(default_factory=set)
    threshold: list[int] = field(default_factory=list)
    lot_index: dict[str, int] = field(default_factory=dict)
    tool_index: dict[str, int] = field(default_factory=dict)

    @property
    def horizon(self) -> float:
        return self.spec.horizon


# --------------------------------------------------------------------------- books


def base_spec() -> BookSpec:
    return BookSpec(key="base")


def scenario_spec(fab: Fab, name: str) -> BookSpec:
    if name == "base":
        return base_spec()
    if name == "litho_down":
        return BookSpec(
            key=name,
            kind="litho_down",
            forced_tool=fab.focus_tool,
            forced_until=LITHO_MTTR_MIN * 60.0,
        )
    if name == "hot_lot":
        return BookSpec(key=name, kind="hot_lot", promote_lot=fab.hot_lot)
    if name == "pm_avoid":
        return BookSpec(
            key=name,
            kind="pm_avoid",
            pm_shift=pm_shift_to_open(fab, fab.pm_calendar, PM_OPEN_SEC),
        )
    raise KeyError(name)


SCENARIO_BOOKS = ("base", "litho_down", "hot_lot", "pm_avoid")


def whatif_spec(
    *, forced_tool: int | None = None, forced_min: float = 0.0, promote_lot: int | None = None
) -> BookSpec:
    raw = f"{forced_tool}:{round(forced_min, 1)}:{promote_lot}"
    digest = hashlib.sha1(raw.encode()).hexdigest()[:10]
    return BookSpec(
        key=f"whatif-{digest}",
        kind="whatif",
        forced_tool=forced_tool,
        forced_until=max(0.0, forced_min) * 60.0,
        promote_lot=promote_lot,
    )


_LOCK = threading.Lock()
_BUILDING: dict[str, threading.Event] = {}
_CACHE: OrderedDict[str, Replay] = OrderedDict()
_CACHE_MAX = 8
_SPECS: dict[str, BookSpec] = {}


def register(spec: BookSpec) -> None:
    with _LOCK:
        _SPECS[spec.key] = spec


def known_spec(fab: Fab, key: str) -> BookSpec:
    with _LOCK:
        found = _SPECS.get(key)
    if found is not None:
        return found
    return scenario_spec(fab, key)


def get_replay(spec: BookSpec) -> Replay:
    """Build once per book. Concurrent callers wait for the same build."""
    while True:
        with _LOCK:
            hit = _CACHE.get(spec.key)
            if hit is not None:
                _CACHE.move_to_end(spec.key)
                return hit
            pending = _BUILDING.get(spec.key)
            if pending is None:
                pending = threading.Event()
                _BUILDING[spec.key] = pending
                owner = True
            else:
                owner = False
        if not owner:
            pending.wait(timeout=120)
            continue
        try:
            built = build_replay(load_fab(), spec)
            with _LOCK:
                _CACHE[spec.key] = built
                _SPECS[spec.key] = spec
                while len(_CACHE) > _CACHE_MAX:
                    oldest = next(iter(_CACHE))
                    if oldest == "base":
                        _CACHE.move_to_end(oldest)
                        oldest = next(iter(_CACHE))
                    _CACHE.pop(oldest)
            return built
        finally:
            with _LOCK:
                _BUILDING.pop(spec.key, None)
            pending.set()


def cached(key: str) -> bool:
    with _LOCK:
        return key in _CACHE


def warm(spec: BookSpec | None = None) -> threading.Thread:
    worker = threading.Thread(target=get_replay, args=(spec or base_spec(),), daemon=True)
    worker.start()
    return worker


# --------------------------------------------------------------------------- build


def build_replay(fab: Fab, spec: BookSpec) -> Replay:
    horizon = spec.horizon
    downs = sample_downs(
        fab,
        spec.seed,
        horizon,
        forced_tool=spec.forced_tool,
        forced_until=spec.forced_until,
    )
    pm = pm_windows(fab, horizon, shift_sec=spec.pm_shift)
    promote = spec.promote_lot
    result = run_policy(
        fab,
        policy="resilimes",
        seed=spec.seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        hot_lot=promote,
        hot_due=HOT_DUE_SEC if promote is not None else None,
        promote_hot=promote is not None,
        focus_down_until=spec.forced_until,
        record=True,
    )
    due = list(fab.lot_due)
    kind = list(fab.lot_class)
    if promote is not None:
        due[promote] = HOT_DUE_SEC
        kind[promote] = "VIP"
    replay = Replay(fab=fab, spec=spec, result=result, downs=downs, pm=pm, due=due, kind=kind)
    _index(replay)
    return replay


def _index(rp: Replay) -> None:
    fab = rp.fab
    n_lots = len(fab.lot_id)
    n_tools = len(fab.tool_name)
    rp.tool_pieces = [[] for _ in range(n_tools)]
    rp.tool_starts = [[] for _ in range(n_tools)]
    rp.trans = [[(0.0, fab.lot_step[lot], WAIT)] for lot in range(n_lots)]
    rp.ops = [[] for _ in range(n_lots)]
    rp.skips = [[] for _ in range(n_lots)]
    rp.lot_qwins = [[] for _ in range(n_lots)]
    rp.lot_index = {name: index for index, name in enumerate(fab.lot_id)}
    rp.tool_index = {name: index for index, name in enumerate(fab.tool_name)}
    rp.threshold = [max(WIP_FLOOR, WIP_PER_TOOL * item.tools) for item in fab.families]
    for route in fab.routes:
        for index, cap in enumerate(route.batch_max):
            if cap > 0:
                rp.batch_families.add(route.family[index])
    tool_recipe = [0] * n_tools
    active: list[int] = [-1] * n_tools
    open_win: list[int] = [-1] * n_lots
    for event in rp.result.events:
        if not event:
            continue
        name = event[0]
        moment = float(event[1])
        if name == "start":
            tool = int(event[2])
            lots = tuple(int(x) for x in event[3])
            steps = tuple(int(x) for x in event[4])
            finish = float(event[5])
            reason = str(event[6]) if len(event) > 6 else ""
            fam = fab.tool_family[tool]
            route = fab.routes[fab.lot_route[lots[0]]]
            recipe = route.recipe[steps[0]]
            setup = setup_seconds(fab, fam, tool_recipe[tool], recipe)
            tool_recipe[tool] = recipe
            piece = Piece(
                tool=tool,
                family=fam,
                start=moment,
                end=finish,
                planned=finish,
                lots=lots,
                steps=steps,
                setup=setup,
                recipe=recipe,
                reason=reason,
                batch=route.batch_max[steps[0]] > 0,
            )
            index = len(rp.pieces)
            rp.pieces.append(piece)
            rp.tool_pieces[tool].append(index)
            rp.tool_starts[tool].append(moment)
            active[tool] = index
            for lot, step in zip(lots, steps, strict=False):
                ready = _last_wait(rp.trans[lot])
                rp.trans[lot].append((moment, step, RUN))
                rp.ops[lot].append((index, step, ready))
                win = open_win[lot]
                if win >= 0 and rp.qwins[win].target == step:
                    window = rp.qwins[win]
                    window.closed = moment
                    window.outcome = "violated" if moment > window.deadline else "met"
                    open_win[lot] = -1
        elif name == "end":
            lot = int(event[2])
            index = int(event[3])
            rp.trans[lot].append((moment, index + 1, WAIT))
            route = fab.routes[fab.lot_route[lot]]
            if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
                prev = open_win[lot]
                if prev >= 0:
                    rp.qwins[prev].closed = moment
                    rp.qwins[prev].outcome = "superseded"
                window = QWindow(
                    lot=lot,
                    origin=index,
                    target=route.cqt_target[index],
                    opened=moment,
                    deadline=moment + route.cqt_limit[index],
                    limit=route.cqt_limit[index],
                )
                open_win[lot] = len(rp.qwins)
                rp.lot_qwins[lot].append(len(rp.qwins))
                rp.qwins.append(window)
        elif name == "skip":
            lot = int(event[2])
            nxt = int(event[3])
            last = rp.trans[lot][-1]
            rp.trans[lot][-1] = (last[0], nxt + 1, last[2])
            rp.skips[lot].append((moment, nxt))
            win = open_win[lot]
            if win >= 0 and rp.qwins[win].target == nxt:
                rp.qwins[win].closed = moment
                rp.qwins[win].outcome = "skipped"
                open_win[lot] = -1
        elif name == "interrupt":
            tool = int(event[2])
            lots = tuple(int(x) for x in event[3])
            rp.interrupts.append((moment, tool, lots))
            index = active[tool]
            if index >= 0:
                piece = rp.pieces[index]
                if piece.end > moment + 1e-6:
                    piece.end = moment
                    piece.interrupted = True
        elif name == "rework":
            tool = int(event[2])
            lot = int(event[3])
            step = int(event[4])
            rp.reworks.append((moment, tool, lot, step))
            rp.trans[lot].append((moment, step, HOLD))
            rp.trans[lot].append((moment + REWORK_SEC, step, WAIT))
        elif name == "reclean":
            lot = int(event[2])
            index = int(event[3])
            origin = int(event[4])
            rp.recleans.append((moment, lot, index, origin))
            win = open_win[lot]
            if win >= 0:
                rp.qwins[win].closed = moment
                rp.qwins[win].outcome = "recleaned"
                open_win[lot] = -1
            last = rp.trans[lot][-1]
            if last[0] == moment and last[2] == WAIT:
                rp.trans[lot][-1] = (moment, origin, WAIT)
            else:
                rp.trans[lot].append((moment, origin, WAIT))
    rp.finished = [-1.0] * n_lots
    rp.waits = [[] for _ in fab.families]
    for lot in range(n_lots):
        route = fab.routes[fab.lot_route[lot]]
        last_step = len(route.family) - 1
        rows = rp.trans[lot]
        fixed: list[tuple[float, int, int]] = []
        for moment, step, status in rows:
            if step > last_step:
                fixed.append((moment, last_step, DONE))
                if rp.finished[lot] < 0:
                    rp.finished[lot] = moment
            else:
                fixed.append((moment, step, status))
        rp.trans[lot] = fixed
        for position, (moment, step, status) in enumerate(fixed):
            if status != WAIT:
                continue
            until = fixed[position + 1][0] if position + 1 < len(fixed) else math.inf
            rp.waits[route.family[step]].append((moment, until, lot, step))
    rp.trans_t = [[row[0] for row in rows] for rows in rp.trans]
    for wait_rows in rp.waits:
        wait_rows.sort()
    bins = int(rp.horizon // BIN_SEC) + 1
    rp.occupancy = [[0.0] * bins for _ in fab.families]
    for piece in rp.pieces:
        _add_bins(rp.occupancy[piece.family], piece.start, min(piece.end, rp.horizon))


def _last_wait(rows: list[tuple[float, int, int]]) -> float:
    for moment, _step, status in reversed(rows):
        if status == WAIT:
            return moment
    return rows[0][0]


def _add_bins(row: list[float], start: float, end: float) -> None:
    if end <= start:
        return
    first = int(start // BIN_SEC)
    last = min(int(end // BIN_SEC), len(row) - 1)
    for index in range(first, last + 1):
        left = max(start, index * BIN_SEC)
        right = min(end, (index + 1) * BIN_SEC)
        if right > left:
            row[index] += right - left


# --------------------------------------------------------------------------- reads


def clamp_t(rp: Replay, t: float | None) -> float:
    if t is None or not math.isfinite(t):
        return 0.0
    return max(0.0, min(float(t), rp.horizon))


def lot_state(rp: Replay, lot: int, t: float) -> tuple[int, int]:
    rows = rp.trans[lot]
    index = bisect.bisect_right(rp.trans_t[lot], t) - 1
    index = max(index, 0)
    _moment, step, status = rows[index]
    return step, status


def slack_sec(rp: Replay, lot: int, step: int, t: float) -> float:
    route = rp.fab.routes[rp.fab.lot_route[lot]]
    return rp.due[lot] - t - route.remain[step]


def tool_recipe_at(rp: Replay, tool: int, t: float) -> int:
    index = bisect.bisect_right(rp.tool_starts[tool], t) - 1
    if index < 0:
        return 0
    return rp.pieces[rp.tool_pieces[tool][index]].recipe


def covering(windows: list[tuple[float, float]], t: float) -> tuple[float, float] | None:
    for start, end in windows:
        if start <= t < end:
            return (start, end)
    return None


def next_window(windows: list[tuple[float, float]], t: float) -> tuple[float, float] | None:
    found: tuple[float, float] | None = None
    for start, end in windows:
        if start > t and (found is None or start < found[0]):
            found = (start, end)
    return found


def open_qwindow(rp: Replay, lot: int, t: float) -> QWindow | None:
    for index in rp.lot_qwins[lot]:
        window = rp.qwins[index]
        if window.opened <= t and (window.closed is None or t < window.closed):
            return window
    return None


def family_queue(rp: Replay, fam: int, t: float) -> list[tuple[float, int, int]]:
    """(ready, lot, step) of lots waiting at ``t`` for this family."""
    rows: list[tuple[float, int, int]] = []
    for ready, until, lot, step in rp.waits[fam]:
        if ready > t:
            break
        if t < until:
            rows.append((ready, lot, step))
    return rows


def queue_counts(rp: Replay, t: float) -> list[int]:
    counts = [0] * len(rp.fab.families)
    for fam, rows in enumerate(rp.waits):
        total = 0
        for ready, until, _lot, _step in rows:
            if ready > t:
                break
            if t < until:
                total += 1
        counts[fam] = total
    return counts


def family_util(rp: Replay, fam: int, t: float, window: float = UTIL_WINDOW_SEC) -> float:
    start = max(0.0, t - window)
    end = t
    if end - start < BIN_SEC:
        end = min(rp.horizon, start + max(window, BIN_SEC))
    first = int(start // BIN_SEC)
    last = max(first, math.ceil(end / BIN_SEC) - 1)
    row = rp.occupancy[fam]
    busy = sum(row[first : min(last + 1, len(row))])
    span = (last - first + 1) * BIN_SEC
    tools = max(1, rp.fab.families[fam].tools)
    return max(0.0, min(1.0, busy / (span * tools)))


def tool_util(rp: Replay, tool: int, t0: float, t1: float) -> float:
    if t1 <= t0:
        return 0.0
    busy = 0.0
    starts = rp.tool_starts[tool]
    first = max(0, bisect.bisect_left(starts, t0) - 1)
    for index in rp.tool_pieces[tool][first:]:
        piece = rp.pieces[index]
        if piece.start >= t1:
            break
        busy += max(0.0, min(piece.end, t1) - max(piece.start, t0))
    return busy / (t1 - t0)


def proc_seconds(rp: Replay, lot: int, step: int, tool: int, recipe_now: int) -> float:
    route = rp.fab.routes[rp.fab.lot_route[lot]]
    fam = rp.fab.tool_family[tool]
    return route.cycle[step] + setup_seconds(rp.fab, fam, recipe_now, route.recipe[step])


def reasons(
    rp: Replay,
    lot: int,
    step: int,
    moment: float,
    *,
    tool: int | None = None,
    recipe_now: int | None = None,
    piece: Piece | None = None,
    rework: bool = False,
) -> list[dict[str, Any]]:
    """Why this lot sits where it does, in the tiered key's own order."""
    fab = rp.fab
    route = fab.routes[fab.lot_route[lot]]
    out: list[dict[str, Any]] = []
    kind = rp.kind[lot]
    if kind == "VIP":
        out.append({"code": "vip"})
    elif kind == "hot":
        out.append({"code": "hot"})
    slack = slack_sec(rp, lot, step, moment)
    if slack <= 0:
        out.append({"code": "late", "h": round(-slack / 3600.0, 1)})
    window = open_qwindow(rp, lot, moment)
    if window is not None and window.target == step:
        left = (window.deadline - moment) / 60.0
        out.append({"code": "qtime", "min": round(left)})
    if rework:
        out.append({"code": "rework"})
    if piece is not None and piece.batch:
        cap = route.batch_max[step]
        floor = route.batch_min[step] or cap
        out.append(
            {
                "code": "batch",
                "lots": len(piece.lots),
                "wafers": len(piece.lots) * WAFERS_PER_LOT,
                "min": floor,
                "max": cap,
                "why": piece.reason or "min_met",
            }
        )
    if tool is not None and recipe_now is not None:
        fam = fab.tool_family[tool]
        setup = setup_seconds(fab, fam, recipe_now, route.recipe[step])
        if setup <= 0:
            out.append({"code": "same_recipe"})
        else:
            out.append({"code": "setup", "min": round(setup / 60.0)})
    if slack > 0:
        out.append({"code": "slack", "h": round(slack / 3600.0, 1)})
    return out


def _lot_brief(rp: Replay, lot: int) -> dict[str, Any]:
    fab = rp.fab
    return {
        "lot": fab.lot_id[lot],
        "kind": rp.kind[lot],
        "product": fab.lot_product[lot],
    }


def _risk(slack: float) -> str:
    if slack <= 0:
        return "late"
    if slack <= RISK_SEC:
        return "risk"
    return "ok"


def tool_state(rp: Replay, tool: int, t: float, waiting_batch: bool) -> dict[str, Any]:
    down = covering(rp.downs[tool], t)
    pm = covering(rp.pm[tool], t)
    starts = rp.tool_starts[tool]
    index = bisect.bisect_right(starts, t) - 1
    piece = rp.pieces[rp.tool_pieces[tool][index]] if index >= 0 else None
    body: dict[str, Any] = {"state": "idle"}
    if piece is not None and piece.end > t:
        span = max(1.0, piece.end - piece.start)
        body = {
            "state": "setup" if t < piece.start + piece.setup else "run",
            "progress": round((t - piece.start) / span, 3),
            "start": piece.start,
            "end": piece.end,
            "setup_min": round(piece.setup / 60.0, 1),
            "recipe": rp.fab.recipe_name[piece.recipe]
            if piece.recipe < len(rp.fab.recipe_name)
            else "",
            "lots": [
                {**_lot_brief(rp, lot), "step": step}
                for lot, step in zip(piece.lots, piece.steps, strict=False)
            ],
            "batch": piece.batch,
        }
    if down is not None:
        body["state"] = "down"
        body["until"] = down[1]
    elif pm is not None:
        body["state"] = "pm"
        body["until"] = pm[1]
    elif body["state"] == "idle" and waiting_batch:
        body["state"] = "batch_wait"
    return body


def next_on_tool(rp: Replay, tool: int, t: float, limit: int = 3) -> list[dict[str, Any]]:
    """The next pieces this tool really started after ``t``, with reasons."""
    starts = rp.tool_starts[tool]
    index = bisect.bisect_right(starts, t)
    pieces = rp.tool_pieces[tool]
    out: list[dict[str, Any]] = []
    pm_next = next_window(rp.pm[tool], t)
    pm_placed = False
    rework_keys = {(lot, step) for _m, _tool, lot, step in rp.reworks}
    while index < len(pieces) and len(out) < limit:
        piece = rp.pieces[pieces[index]]
        if pm_next is not None and not pm_placed and pm_next[0] <= piece.start:
            out.append({"type": "pm", "start": pm_next[0], "end": pm_next[1]})
            pm_placed = True
            continue
        recipe_before = rp.pieces[pieces[index - 1]].recipe if index > 0 else 0
        lot = piece.lots[0]
        step = piece.steps[0]
        out.append(
            {
                "type": "batch" if piece.batch else "lot",
                "start": piece.start,
                "lots": [_lot_brief(rp, item) for item in piece.lots],
                "step": step,
                "reasons": reasons(
                    rp,
                    lot,
                    step,
                    piece.start,
                    tool=tool,
                    recipe_now=recipe_before,
                    piece=piece,
                    rework=(lot, step) in rework_keys,
                ),
            }
        )
        index += 1
    if pm_next is not None and not pm_placed and len(out) < limit:
        out.append({"type": "pm", "start": pm_next[0], "end": pm_next[1]})
    return out


def ranked_queue(
    rp: Replay, fam: int, t: float, limit: int = 12
) -> tuple[int, list[dict[str, Any]]]:
    """The family queue at ``t`` in tiered-key order, with PM skips marked."""
    fab = rp.fab
    family = fab.families[fam]
    rows = family_queue(rp, fam, t)
    tools = range(family.tool0, family.tool0 + family.tools)
    recipe0 = tool_recipe_at(rp, family.tool0, t)
    pm_next = {tool: next_window(rp.pm[tool], t) for tool in tools}

    def key(row: tuple[float, int, int]) -> tuple[float, ...]:
        ready, lot, step = row
        route = fab.routes[fab.lot_route[lot]]
        window = open_qwindow(rp, lot, t)
        ped = 0.0
        if window is not None:
            ped = ped_risk(window.deadline - t, window.limit, 6.0)
        tiered = tiered_key(
            order_class=rp.kind[lot],
            slack_sec=slack_sec(rp, lot, step, t),
            setup_sec=setup_seconds(fab, fam, recipe0, route.recipe[step]),
            ped=ped,
        )
        return (*tiered, ready, float(lot))

    ordered = sorted(rows, key=key)
    out: list[dict[str, Any]] = []
    for ready, lot, step in ordered[:limit]:
        item = {
            **_lot_brief(rp, lot),
            "step": step,
            "ready": ready,
            "wait_min": round((t - ready) / 60.0),
            "risk": _risk(slack_sec(rp, lot, step, t)),
            "reasons": reasons(rp, lot, step, t, tool=family.tool0, recipe_now=recipe0),
        }
        blocked = []
        for tool in tools:
            window = pm_next[tool]
            if window is None:
                continue
            proc = proc_seconds(rp, lot, step, tool, tool_recipe_at(rp, tool, t))
            if t + proc > window[0]:
                blocked.append(tool)
        if blocked and len(blocked) == family.tools:
            first = min(pm_next[tool][0] for tool in blocked if pm_next[tool] is not None)  # type: ignore[index]
            item["reasons"].insert(0, {"code": "pm_skip", "at": first})
        elif blocked:
            item["pm_blocked"] = [fab.tool_name[tool] for tool in blocked]
        out.append(item)
    return len(rows), out


def bottlenecks(rp: Replay, t: float, counts: list[int] | None = None) -> list[dict[str, Any]]:
    fab = rp.fab
    counts = counts if counts is not None else queue_counts(rp, t)
    earlier = queue_counts(rp, max(0.0, t - 2 * 3600.0))
    rows: list[dict[str, Any]] = []
    for fam, family in enumerate(fab.families):
        util = family_util(rp, fam, t)
        queue = counts[fam]
        limit = rp.threshold[fam]
        load = queue / max(1, limit)
        rows.append(
            {
                "family": family.name,
                "group": family.group,
                "tools": family.tools,
                "util": round(util, 3),
                "queue": queue,
                "threshold": limit,
                "trend": queue - earlier[fam],
                "pileup": queue > limit,
                "score": round(util * (1.0 + load), 3),
                "bottleneck": util >= 0.85 and queue > limit,
            }
        )
    rows.sort(key=lambda row: (not row["bottleneck"], -row["score"]))
    return rows


def families_with_batch_waiting(rp: Replay, t: float) -> set[int]:
    found: set[int] = set()
    for fam in rp.batch_families:
        for _ready, lot, step in family_queue(rp, fam, t):
            route = rp.fab.routes[rp.fab.lot_route[lot]]
            if route.batch_max[step] > 0:
                found.add(fam)
                break
    return found


def tool_counts(rp: Replay, t: float) -> dict[str, int]:
    waiting = families_with_batch_waiting(rp, t)
    totals: dict[str, int] = {}
    for tool in range(len(rp.fab.tool_name)):
        fam = rp.fab.tool_family[tool]
        state = tool_state(rp, tool, t, fam in waiting)["state"]
        totals[state] = totals.get(state, 0) + 1
    return totals


def counters(rp: Replay) -> dict[str, Any]:
    result = rp.result
    return {
        "on_time_pct": result.on_time_pct,
        "due_in_horizon": result.due_in_horizon,
        "completed_routes": result.completed_routes,
        "weighted_tardiness_min": result.weighted_tardiness_min,
        "qtime_violations": result.qtime_violations,
        "qtime_gates": result.qtime_gates,
        "recleans": result.recleans,
        "reworks": result.reworks,
        "rework_lot_min": result.rework_lot_min,
        "skipped": result.skipped,
        "qtime_skipped": result.qtime_skipped,
        "pm_avoided": result.pm_avoided,
        "pm_overlaps": result.pm_overlaps,
        "wip_replans": result.wip_replans,
        "batch_starts": result.batch_starts,
        "batch_lots": result.batch_lots,
        "batch_reasons": dict(result.batch_reasons),
        "batch_dropped": result.batch_dropped,
        "setup_min": result.setup_min,
        "repins": result.repins,
        "litho_util_pct": result.litho_util_pct,
        "scanner_util_pct": result.scanner_util_pct,
        "mean_step_cycle_min": result.mean_step_cycle_min,
        "class_wait_min": dict(result.class_wait_min),
        "dispatch_p50_ms": result.dispatch_p50_ms,
        "dispatch_p95_ms": result.dispatch_p95_ms,
        "dispatch_decisions": result.dispatch_decisions,
        "down_starts": len(result.down_starts),
        "sim_s": result.sim_s,
        "events": len(result.events),
    }


def redo_of(rp: Replay, lot: int, step: int, after: float) -> tuple[int, float] | None:
    for index, op_step, _ready in rp.ops[lot]:
        piece = rp.pieces[index]
        if op_step == step and piece.start >= after:
            return piece.tool, piece.start
    return None


def breakdowns(rp: Replay, t0: float, t1: float) -> list[dict[str, Any]]:
    fab = rp.fab
    cards: list[dict[str, Any]] = []
    hit: dict[tuple[int, float], list[int]] = {}
    for moment, tool, lots in rp.interrupts:
        hit[(tool, moment)] = list(lots)
    for tool, windows in enumerate(rp.downs):
        for start, end in windows:
            if not (t0 <= start <= t1):
                continue
            hit_lots: list[dict[str, Any]] = []
            for lot in hit.get((tool, start), []):
                step = next(
                    (s for m, tl, lt, s in rp.reworks if lt == lot and tl == tool and m == start),
                    None,
                )
                if step is None:
                    continue
                redo = redo_of(rp, lot, step, start)
                hit_lots.append(
                    {
                        **_lot_brief(rp, lot),
                        "step": step,
                        "hold_until": start + REWORK_SEC,
                        "redo_tool": fab.tool_name[redo[0]] if redo else None,
                        "redo_at": redo[1] if redo else None,
                    }
                )
            fam = fab.tool_family[tool]
            cards.append(
                {
                    "tool": fab.tool_name[tool],
                    "family": fab.families[fam].name,
                    "group": fab.families[fam].group,
                    "start": start,
                    "end": min(end, rp.horizon),
                    "open_end": end > rp.horizon,
                    "forced": rp.spec.forced_tool == tool and start == 0.0,
                    "lots": hit_lots,
                }
            )
    cards.sort(key=lambda card: card["start"])
    return cards


# --------------------------------------------------------------------------- views


def _route_len(rp: Replay, lot: int) -> int:
    return len(rp.fab.routes[rp.fab.lot_route[lot]].family)


def _on_time(rp: Replay, lot: int) -> bool | None:
    done = rp.finished[lot]
    if done < 0:
        return None
    return done <= rp.due[lot]


def lot_row(rp: Replay, lot: int, t: float) -> dict[str, Any]:
    step, status = lot_state(rp, lot, t)
    length = _route_len(rp, lot)
    slack = slack_sec(rp, lot, step, t) if status != DONE else rp.due[lot] - rp.finished[lot]
    fam = rp.fab.routes[rp.fab.lot_route[lot]].family[step]
    row = {
        **_lot_brief(rp, lot),
        "step": step,
        "steps": length,
        "status": STATUS[status],
        "family": rp.fab.families[fam].name,
        "group": rp.fab.families[fam].group,
        "slack_h": round(slack / 3600.0, 1),
        "risk": _risk(slack),
        "due": rp.due[lot],
        "done_at": rp.finished[lot] if 0 <= rp.finished[lot] <= t else None,
    }
    window = open_qwindow(rp, lot, t)
    if window is not None and status != DONE:
        row["qtime_min"] = round((window.deadline - t) / 60.0)
    return row


def recent_events(rp: Replay) -> list[tuple[float, str, dict[str, Any]]]:
    cache = getattr(rp, "_events", None)
    if cache is not None:
        return cache
    fab = rp.fab
    rows: list[tuple[float, str, dict[str, Any]]] = []
    for card in breakdowns(rp, 0.0, rp.horizon):
        rows.append(
            (
                card["start"],
                "down",
                {
                    "tool": card["tool"],
                    "family": card["family"],
                    "until": card["end"],
                    "lots": [item["lot"] for item in card["lots"]],
                    "forced": card["forced"],
                },
            )
        )
    for tool, windows in enumerate(rp.pm):
        for start, end in windows:
            if start < rp.horizon:
                rows.append(
                    (
                        start,
                        "pm",
                        {
                            "tool": fab.tool_name[tool],
                            "family": fab.families[fab.tool_family[tool]].name,
                            "until": end,
                        },
                    )
                )
    for piece in rp.pieces:
        tool_label = fab.tool_name[piece.tool]
        family = fab.families[piece.family].name
        if piece.batch:
            rows.append(
                (
                    piece.start,
                    "batch",
                    {
                        "tool": tool_label,
                        "family": family,
                        "lots": [fab.lot_id[lot] for lot in piece.lots],
                        "wafers": len(piece.lots) * WAFERS_PER_LOT,
                        "why": piece.reason or "min_met",
                    },
                )
            )
        for lot, step in zip(piece.lots, piece.steps, strict=False):
            if rp.kind[lot] in {"VIP", "hot"}:
                rows.append(
                    (
                        piece.start,
                        "priority",
                        {
                            "lot": fab.lot_id[lot],
                            "class": rp.kind[lot],
                            "tool": tool_label,
                            "family": family,
                            "step": step,
                        },
                    )
                )
    for moment, tool_index, lot, step in rp.reworks:
        redo = redo_of(rp, lot, step, moment)
        rows.append(
            (
                moment,
                "rework",
                {
                    "lot": fab.lot_id[lot],
                    "tool": fab.tool_name[tool_index],
                    "step": step,
                    "redo_tool": fab.tool_name[redo[0]] if redo else None,
                    "redo_at": redo[1] if redo else None,
                },
            )
        )
    for moment, lot, index, origin in rp.recleans:
        rows.append(
            (
                moment,
                "reclean",
                {"lot": fab.lot_id[lot], "step": index, "origin": origin},
            )
        )
    for window in rp.qwins:
        if window.outcome == "violated" and window.closed is not None:
            rows.append(
                (
                    window.closed,
                    "qtime_miss",
                    {
                        "lot": fab.lot_id[window.lot],
                        "step": window.target,
                        "over_min": round((window.closed - window.deadline) / 60.0),
                    },
                )
            )
    for lot, done in enumerate(rp.finished):
        if done >= 0:
            rows.append(
                (
                    done,
                    "done",
                    {
                        "lot": fab.lot_id[lot],
                        "class": rp.kind[lot],
                        "on_time": done <= rp.due[lot],
                        "late_h": round(max(0.0, done - rp.due[lot]) / 3600.0, 1),
                    },
                )
            )
    for lot, skips in enumerate(rp.skips):
        for moment, step in skips:
            rows.append((moment, "skip", {"lot": fab.lot_id[lot], "step": step}))
    rows.sort(key=lambda row: row[0])
    object.__setattr__(rp, "_events", rows)
    return rows


EVENT_KINDS = ("down", "pm", "batch", "priority", "rework", "reclean", "qtime_miss", "done", "skip")
DEFAULT_KINDS = ("down", "pm", "batch", "priority", "rework", "reclean", "qtime_miss", "done")


def events_view(
    rp: Replay,
    t0: float,
    t1: float,
    kinds: tuple[str, ...] = DEFAULT_KINDS,
    query: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    rows = recent_events(rp)
    times = [row[0] for row in rows]
    lo = bisect.bisect_left(times, t0)
    hi = bisect.bisect_right(times, t1)
    needle = query.strip().lower()
    picked: list[dict[str, Any]] = []
    total = 0
    by_kind: dict[str, int] = {}
    for moment, kind, body in reversed(rows[lo:hi]):
        if kind not in kinds:
            continue
        if needle and needle not in " ".join(str(v) for v in body.values()).lower():
            continue
        total += 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if len(picked) < limit:
            picked.append({**body, "t": moment, "kind": kind})
    return {"t0": t0, "t1": t1, "total": total, "by_kind": by_kind, "events": picked}


def overview(rp: Replay, t: float) -> dict[str, Any]:
    fab = rp.fab
    counts = queue_counts(rp, t)
    statuses = [0, 0, 0, 0]
    rows = []
    for lot in range(len(fab.lot_id)):
        step, status = lot_state(rp, lot, t)
        statuses[status] += 1
        rows.append((lot, step, status))
    priority = []
    risky = []
    for lot, step, status in rows:
        if rp.kind[lot] in {"VIP", "hot"}:
            priority.append(lot_row(rp, lot, t))
        elif status != DONE and rp.due[lot] <= rp.horizon * 2:
            slack = slack_sec(rp, lot, step, t)
            if slack <= RISK_SEC:
                risky.append((slack, lot))
    priority.sort(key=lambda row: (row["kind"] != "VIP", row["slack_h"]))
    risky.sort()
    due_lots = [lot for lot in range(len(fab.lot_id)) if fab.lot_due[lot] <= t]
    due_on_time = sum(1 for lot in due_lots if 0 <= rp.finished[lot] <= rp.due[lot])
    prio_due = [row for row in priority if row["due"] <= rp.horizon]
    prio_ok = sum(1 for row in prio_due if row["done_at"] is not None and row["slack_h"] >= 0)
    bns = bottlenecks(rp, t, counts)
    alerts = sorted(
        (row for row in bns if row["pileup"]),
        key=lambda row: -row["queue"] / max(1, row["threshold"]),
    )
    return {
        "t": t,
        "lots": {
            "total": len(fab.lot_id),
            "wait": statuses[WAIT],
            "run": statuses[RUN],
            "hold": statuses[HOLD],
            "done": statuses[DONE],
        },
        "tools": tool_counts(rp, t),
        "due_so_far": {"due": len(due_lots), "on_time": due_on_time},
        "priority_due": {"due": len(prio_due), "on_time": prio_ok},
        "priority": priority,
        "at_risk": [lot_row(rp, lot, t) for _slack, lot in risky[:12]],
        "at_risk_total": len(risky),
        "bottlenecks": [row for row in bns if row["bottleneck"]][:8] or bns[:5],
        "alerts": alerts[:10],
        "alerts_total": len(alerts),
        "recent": events_view(rp, max(0.0, t - 3 * 3600.0), t, limit=8)["events"],
        "counters": counters(rp),
    }


def tools_view(rp: Replay, t: float, group: str | None, family: str | None) -> dict[str, Any]:
    fab = rp.fab
    counts = queue_counts(rp, t)
    waiting = families_with_batch_waiting(rp, t)
    fams = [
        index
        for index, item in enumerate(fab.families)
        if (family is None or item.name == family)
        and (group is None or item.group == group or family is not None)
    ]
    groups: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(fab.families):
        entry = groups.setdefault(
            item.group, {"group": item.group, "families": 0, "tools": 0, "queue": 0, "pileups": 0}
        )
        entry["families"] += 1
        entry["tools"] += item.tools
        entry["queue"] += counts[index]
        entry["pileups"] += int(counts[index] > rp.threshold[index])
    window0 = max(0.0, t - 3 * 3600.0)
    window1 = min(rp.horizon, t + 3 * 3600.0)
    out: list[dict[str, Any]] = []
    for fam in fams:
        item = fab.families[fam]
        queue_total, queue = ranked_queue(rp, fam, t, limit=8)
        tools = []
        for tool in range(item.tool0, item.tool0 + item.tools):
            body = tool_state(rp, tool, t, fam in waiting)
            body["tool"] = fab.tool_name[tool]
            body["next"] = next_on_tool(rp, tool, t)
            body["util"] = round(tool_util(rp, tool, max(0.0, t - UTIL_WINDOW_SEC), t), 3)
            pm_next = next_window(rp.pm[tool], t)
            body["pm_next"] = pm_next[0] if pm_next else None
            body["timeline"] = _timeline(rp, tool, window0, window1)
            tools.append(body)
        out.append(
            {
                "family": item.name,
                "group": item.group,
                "batch": fam in rp.batch_families,
                "util": round(family_util(rp, fam, t), 3),
                "queue": queue_total,
                "threshold": rp.threshold[fam],
                "pileup": queue_total > rp.threshold[fam],
                "queue_top": queue,
                "tools": tools,
            }
        )
    out.sort(key=lambda row: (-(row["queue"] / max(1, row["threshold"])), row["family"]))
    return {
        "t": t,
        "window": [window0, window1],
        "groups": sorted(groups.values(), key=lambda row: row["group"]),
        "families": out,
    }


def _timeline(rp: Replay, tool: int, t0: float, t1: float) -> list[list[Any]]:
    bars: list[list[Any]] = []
    for start, end in rp.downs[tool]:
        if end > t0 and start < t1:
            bars.append(["down", max(start, t0), min(end, t1), ""])
    for start, end in rp.pm[tool]:
        if end > t0 and start < t1:
            bars.append(["pm", max(start, t0), min(end, t1), ""])
    starts = rp.tool_starts[tool]
    first = max(0, bisect.bisect_left(starts, t0) - 1)
    for index in rp.tool_pieces[tool][first:]:
        piece = rp.pieces[index]
        if piece.start >= t1:
            break
        if piece.end <= t0:
            continue
        label = rp.fab.lot_id[piece.lots[0]]
        kind = rp.kind[piece.lots[0]]
        if piece.setup > 0:
            bars.append(["setup", piece.start, min(piece.start + piece.setup, piece.end), label])
        bars.append(
            [
                "batch" if piece.batch else "run",
                piece.start + min(piece.setup, piece.end - piece.start),
                piece.end,
                label if len(piece.lots) == 1 else f"{label} +{len(piece.lots) - 1}",
                kind,
            ]
        )
    return bars


def flow_view(rp: Replay, t: float) -> dict[str, Any]:
    fab = rp.fab
    products: dict[int, dict[str, Any]] = {}
    groups: dict[str, list[int]] = {}
    for lot in range(len(fab.lot_id)):
        step, status = lot_state(rp, lot, t)
        route_index = fab.lot_route[lot]
        route = fab.routes[route_index]
        done = status == DONE
        slack = rp.due[lot] - rp.finished[lot] if done else slack_sec(rp, lot, step, t)
        entry = products.setdefault(
            route_index,
            {
                "route": route_index,
                "product": fab.lot_product[lot],
                "steps": len(route.family),
                "lots": [],
                "counts": {"late": 0, "risk": 0, "ok": 0, "done": 0},
            },
        )
        risk = _risk(slack)
        entry["lots"].append([lot, step, status, round(slack / 60.0)])
        if status == DONE:
            entry["counts"]["done"] += 1
        else:
            entry["counts"][risk] += 1
            group = fab.families[route.family[step]].group
            cell = groups.setdefault(group, [0, 0, 0])
            cell[0 if status == WAIT else 1 if status == RUN else 2] += 1
    for entry in products.values():
        route = fab.routes[entry["route"]]
        marks = []
        last = ""
        for index, fam in enumerate(route.family):
            group = fab.families[fam].group
            if group != last:
                marks.append([index, group])
                last = group
        entry["areas"] = marks
    return {
        "t": t,
        "products": sorted(products.values(), key=lambda row: row["product"]),
        "wip_by_group": [
            {"group": name, "wait": cell[0], "run": cell[1], "hold": cell[2]}
            for name, cell in sorted(groups.items(), key=lambda item: -sum(item[1]))
        ],
    }


def lot_view(rp: Replay, lot: int, t: float) -> dict[str, Any]:
    fab = rp.fab
    route = fab.routes[fab.lot_route[lot]]
    ops = []
    reworked = {(lot_, step): moment for moment, _tool, lot_, step in rp.reworks}
    for position, (index, step, ready) in enumerate(rp.ops[lot]):
        piece = rp.pieces[index]
        before = rp.tool_pieces[piece.tool]
        order = bisect.bisect_left(rp.tool_starts[piece.tool], piece.start)
        recipe_before = rp.pieces[before[order - 1]].recipe if order > 0 else 0
        ops.append(
            {
                "n": position,
                "step": step,
                "family": fab.families[piece.family].name,
                "group": fab.families[piece.family].group,
                "tool": fab.tool_name[piece.tool],
                "ready": ready,
                "start": piece.start,
                "setup_min": round(piece.setup / 60.0, 1),
                "end": piece.end,
                "interrupted": piece.interrupted,
                "batch_lots": len(piece.lots) if piece.batch else 0,
                "reasons": reasons(
                    rp,
                    lot,
                    step,
                    piece.start,
                    tool=piece.tool,
                    recipe_now=recipe_before,
                    piece=piece,
                    rework=(lot, step) in reworked and reworked[(lot, step)] < piece.start,
                ),
            }
        )
    step, status = lot_state(rp, lot, t)
    upcoming = [
        {"step": index, "family": fab.families[route.family[index]].name}
        for index in range(step + (0 if status != RUN else 1), min(len(route.family), step + 7))
    ]
    windows = [
        {
            "origin": window.origin,
            "target": window.target,
            "opened": window.opened,
            "deadline": window.deadline,
            "closed": window.closed,
            "outcome": window.outcome,
        }
        for window in (rp.qwins[index] for index in rp.lot_qwins[lot])
    ]
    return {
        **lot_row(rp, lot, t),
        "route": fab.lot_route[lot],
        "release_step": fab.lot_step[lot],
        "priority": fab.lot_priority[lot],
        "finished": rp.finished[lot] if rp.finished[lot] >= 0 else None,
        "on_time": _on_time(rp, lot),
        "ops": ops,
        "skips": [{"t": moment, "step": step_} for moment, step_ in rp.skips[lot]],
        "reworks": [
            {"t": moment, "tool": fab.tool_name[tool], "step": step_}
            for moment, tool, lot_, step_ in rp.reworks
            if lot_ == lot
        ],
        "recleans": [
            {"t": moment, "step": index, "origin": origin}
            for moment, lot_, index, origin in rp.recleans
            if lot_ == lot
        ],
        "qtime": windows,
        "upcoming": upcoming,
    }


def batches_view(rp: Replay, t: float) -> dict[str, Any]:
    fab = rp.fab
    running: list[dict[str, Any]] = []
    forming: list[dict[str, Any]] = []
    for fam in sorted(rp.batch_families):
        item = fab.families[fam]
        for tool in range(item.tool0, item.tool0 + item.tools):
            index = bisect.bisect_right(rp.tool_starts[tool], t) - 1
            if index < 0:
                continue
            piece = rp.pieces[rp.tool_pieces[tool][index]]
            if piece.end <= t or not piece.batch:
                continue
            route = fab.routes[fab.lot_route[piece.lots[0]]]
            step = piece.steps[0]
            running.append(
                {
                    "family": item.name,
                    "tool": fab.tool_name[tool],
                    "recipe": fab.recipe_name[piece.recipe],
                    "start": piece.start,
                    "end": piece.end,
                    "progress": round((t - piece.start) / max(1.0, piece.end - piece.start), 3),
                    "lots": [_lot_brief(rp, lot) for lot in piece.lots],
                    "wafers": len(piece.lots) * WAFERS_PER_LOT,
                    "min": route.batch_min[step] or route.batch_max[step],
                    "max": route.batch_max[step],
                    "why": piece.reason or "min_met",
                }
            )
        pools: dict[int, list[tuple[float, int, int]]] = {}
        for ready, lot, step in family_queue(rp, fam, t):
            route = fab.routes[fab.lot_route[lot]]
            if route.batch_max[step] > 0:
                pools.setdefault(route.recipe[step], []).append((ready, lot, step))
        for recipe, members in pools.items():
            members.sort()
            ready0, lot0, step0 = members[0]
            route = fab.routes[fab.lot_route[lot0]]
            cap = route.batch_max[step0]
            floor = route.batch_min[step0] or cap
            cap_at = ready0 + BATCH_MAX_WAIT_SEC
            hot = [ready for ready, lot, _step in members if rp.kind[lot] in {"VIP", "hot"}]
            if hot:
                cap_at = min(cap_at, min(hot) + HOT_BATCH_WAIT_SEC)
            started = None
            for index, op_step, _ready in rp.ops[lot0]:
                piece = rp.pieces[index]
                if op_step == step0 and piece.start >= t:
                    started = {
                        "t": piece.start,
                        "tool": fab.tool_name[piece.tool],
                        "lots": len(piece.lots),
                        "why": piece.reason or "min_met",
                    }
                    break
            wafers = len(members) * WAFERS_PER_LOT
            forming.append(
                {
                    "family": item.name,
                    "recipe": fab.recipe_name[recipe],
                    "lots": [
                        {**_lot_brief(rp, lot), "ready": ready, "step": step}
                        for ready, lot, step in members[: max(1, cap // WAFERS_PER_LOT)]
                    ],
                    "queued": len(members),
                    "wafers": min(wafers, cap),
                    "min": floor,
                    "max": cap,
                    "cap_at": cap_at,
                    "countdown_min": round((cap_at - t) / 60.0),
                    "waiting_for": "wafers" if wafers < floor else "tool",
                    "hot": bool(hot),
                    "started": started,
                }
            )
    forming.sort(key=lambda row: row["cap_at"])
    return {"t": t, "running": running, "forming": forming}


def meta(rp: Replay) -> dict[str, Any]:
    fab = rp.fab
    return {
        "source": "public industry benchmark (SMT2020)",
        "book": rp.spec.key,
        "kind": rp.spec.kind,
        "horizon": rp.horizon,
        "seed": rp.spec.seed,
        "lots": len(fab.lot_id),
        "tools": len(fab.tool_name),
        "families": [
            {"name": item.name, "group": item.group, "tools": item.tools} for item in fab.families
        ],
        "groups": sorted({item.group for item in fab.families}),
        "lot_id": fab.lot_id,
        "lot_kind": rp.kind,
        "lot_product": fab.lot_product,
        "lot_route": fab.lot_route,
        "routes": [len(route.family) for route in fab.routes],
        "forced_tool": fab.tool_name[rp.spec.forced_tool]
        if rp.spec.forced_tool is not None
        else None,
        "forced_until": rp.spec.forced_until,
        "promoted": fab.lot_id[rp.spec.promote_lot] if rp.spec.promote_lot is not None else None,
        "pm_tools": sum(1 for windows in rp.pm if windows),
    }


def resolve_lot(rp: Replay, name: str) -> int | None:
    found = rp.lot_index.get(name)
    if found is not None:
        return found
    lowered = name.lower()
    for key, index in rp.lot_index.items():
        if key.lower() == lowered:
            return index
    return None
