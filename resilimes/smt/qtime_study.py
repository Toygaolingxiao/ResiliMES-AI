"""Q-time r2 before/after study: every book, every policy, three arms.

``python -m resilimes.smt.qtime_study ARM OUT.json`` with ARM one of

* ``before``: run from a checkout of main 641d988 (``PYTHONPATH`` to it).
  The script only imports what main has.
* ``mech``: this branch with ``r2_policy=False``: the shared mechanics
  (full-queue batching, the timed deadline, reporting, the scanner-pin fix)
  without the ResiliMES policy fixes 1-3. Only ResiliMES differs from
  ``after``, so only ResiliMES runs.
* ``after``: this branch as shipped (dynamic risk weight, 300 s scheduling
  tick for every policy).
* ``plan``: ``after`` plus the planning layer (``book_plan``): step-due
  risk and plan band/rank tie-break for ResiliMES, the per-tool schedule and
  the deviation log for every policy.
* ``plan_famwait``: ``plan`` with ``plan_wait="family"`` (the risk's
  expected wait is the family average, planning-r1 before the
  position-in-queue fix); for the old-vs-new A/B.
* ``ablate_plan``: ``ablate`` with the plan.
* ``ablate``: ResiliMES only, published and X-factor books, each subset of
  fixes 1-3 on its own (``r2_fixes``); the row's ``variant`` names it.

Q-time buckets and batch fill are recomputed from the recorded events with
one replay for every arm, so the arms are scored the same way: a window
opens at the ``end`` of a dataset CQT step and closes at the ``start`` of
its target (met or started late), at a ``reclean``, at a ``qhold`` (fix 5),
or at a ``skip`` of the target (not scored). A window still open at the
horizon whose deadline has passed is open-expired. Windows inherited from
the t=0 snapshot are counted apart. ``RESILIMES_STUDY_WORKERS`` (default 5)
sets the pool.
"""

from __future__ import annotations

import heapq
import json
import os
import sys
from collections.abc import Iterator
from multiprocessing import get_context
from typing import Any

from resilimes.smt import simulate as sim_mod
from resilimes.smt.fab import LITHO_MTTR_MIN, Fab, load_fab
from resilimes.smt.progress import Progress, follow, progress_path
from resilimes.smt.scenarios import SEEDS, STUDY_HORIZON_SEC
from resilimes.smt.simulate import pm_shift_to_open, pm_windows, run_policy, sample_downs
from resilimes.smt.tight import TIGHT_HORIZON_SEC, apply_tight, apply_xfactor

POLICIES = ("resilimes", "edd", "fifo", "cr", "smt_rule")
HELDOUT_SEEDS = (9, 10, 11, 12, 13)
BOOKS = (
    "published",
    "xfactor_eta600",
    "tight_vip",
    "pm_enforced",
    "litho",
    "hot",
    "heldout_published",
    "heldout_xfactor",
    "litho_family_2h",
)
_ETA_SEC = 600.0 * 60.0
_STRESS_HOURS = 2.0
_WAFERS = int(getattr(sim_mod, "_WAFERS", 25))
_BUCKETS = ("met", "late", "held", "recleaned", "expired")
ABLATE_BOOKS = ("published", "xfactor_eta600")
ABLATE_VARIANTS = ("1", "2", "3", "1+2", "2+3", "1+3")


def _seeds(book: str) -> tuple[int, ...]:
    return HELDOUT_SEEDS if book.startswith("heldout") else tuple(SEEDS)


def _releases() -> bool:
    return os.environ.get("RESILIMES_STUDY_RELEASES", "0") == "1"


def _horizon() -> float:
    hours = os.environ.get("RESILIMES_STUDY_HORIZON_H")
    return float(hours) * 3600.0 if hours else STUDY_HORIZON_SEC


def _setup(
    fab: Fab, book: str, seed: int, policy: str, releases: bool | None = None
) -> tuple[Fab, dict[str, Any]]:
    """The plant and run_policy kwargs of one run (mirrors ``benchmark.py``).

    ``releases`` (default: env ``RESILIMES_STUDY_RELEASES=1``, else off) adds
    the ``order.txt`` lots released inside the horizon, at step 0.
    """
    horizon = _horizon()
    kwargs: dict[str, Any] = {"policy": policy, "seed": seed, "trace": False, "record": True}
    plant = fab
    if book in ("published", "heldout_published"):
        downs = sample_downs(fab, seed, horizon)
        pm = pm_windows(fab, horizon)
    elif book in ("xfactor_eta600", "heldout_xfactor"):
        plant = apply_xfactor(fab)
        downs = sample_downs(
            plant, seed, horizon, forced_tool=plant.focus_tool, forced_until=_ETA_SEC
        )
        pm = pm_windows(plant, horizon)
        kwargs["focus_down_until"] = _ETA_SEC
    elif book == "tight_vip":
        tight = apply_tight(fab, horizon=TIGHT_HORIZON_SEC)
        plant = tight.fab
        horizon = TIGHT_HORIZON_SEC
        downs = sample_downs(plant, seed, horizon)
        downs[tight.down_tool].append((0.0, min(tight.down_until, horizon)))
        pm = pm_windows(plant, horizon)
        kwargs["watch"] = tight.watch
    elif book == "pm_enforced":
        downs = sample_downs(fab, seed, horizon)
        shift = pm_shift_to_open(fab, fab.pm_calendar, 2 * 3600.0)
        pm = pm_windows(fab, horizon, shift_sec=shift)
    elif book == "litho":
        until = LITHO_MTTR_MIN * 60.0
        downs = sample_downs(fab, seed, horizon, forced_tool=fab.focus_tool, forced_until=until)
        pm = pm_windows(fab, horizon)
        kwargs["focus_down_until"] = until
    elif book == "hot":
        downs = sample_downs(fab, seed, horizon)
        pm = pm_windows(fab, horizon)
        kwargs["hot_lot"] = fab.hot_lot
        if policy == "resilimes":
            kwargs["hot_due"] = 12 * 3600.0
            kwargs["promote_hot"] = True
    elif book == "litho_family_2h":
        # Same outage as ``resilimes.smt.stress`` (busy window 0-2 h), inlined
        # so the script runs on main.
        downs = sample_downs(fab, seed, horizon)
        family = fab.families[fab.focus_family]
        for tool in range(family.tool0, family.tool0 + family.tools):
            downs[tool].append((0.0, _STRESS_HOURS * 3600.0))
        pm = pm_windows(fab, horizon)
    elif book.startswith("stress_"):
        # Pre-registered stress book (resilimes.smt.stress_book).
        from resilimes.smt import stress_book

        if not stress_book.is_stress(book):
            raise KeyError(book)
        downs = sample_downs(fab, seed, horizon)
        pm = pm_windows(fab, horizon)
        kwargs["horizon"] = horizon
        stress_book.apply(fab, book, policy, downs, pm, kwargs)
    else:
        raise KeyError(book)
    if _releases() if releases is None else releases:
        from resilimes.smt.planning import with_releases

        plant = with_releases(plant, until=horizon)
    kwargs.update(horizon=horizon, downs=downs, pm=pm)
    return plant, kwargs


# Planning scenario of each study book (``resilimes.smt.scenarios``).
# ``litho_family_2h`` has no headline scenario; its plan takes the same
# 2-hour outage of every focus-family tool.
BOOK_SCENARIO = {
    "published": "published",
    "heldout_published": "published",
    "xfactor_eta600": "xfactor",
    "heldout_xfactor": "xfactor",
    "tight_vip": "tight_p1",
    "pm_enforced": "pm_avoid",
    "litho": "litho_down",
    "hot": "hot_lot",
    "litho_family_2h": "published",
    "stress_furnace_down": "published",
    "stress_hot_cqt": "published",
    "stress_release_burst": "published",
    "stress_pm_peak": "published",
    "stress_batch_cap": "published",
}
_PLANS: dict[str, Any] = {}


def book_plan(fab: Fab, book: str, releases: bool | None = None) -> Any:
    """The planning layer's output for one book, computed once (t=0).

    The plan holds the lots the sim runs: the WIP, plus (``releases``, default
    env ``RESILIMES_STUDY_RELEASES=1``) the ``order.txt`` lots released inside
    the run's horizon, the same set ``_setup`` adds. Seeds share the plan: it
    uses the expected availability (MTTF/(MTTF+MTTR)), not the sampled downs.
    """
    released = _releases() if releases is None else releases
    until = (TIGHT_HORIZON_SEC if book == "tight_vip" else _horizon()) if released else None
    key = f"{book}:{until}"
    if key not in _PLANS:
        from resilimes.smt.planning import build_plan, scenario_input

        inp = scenario_input(fab, BOOK_SCENARIO[book], releases=released, release_until=until)
        if book == "litho_family_2h":
            family = fab.families[fab.focus_family]
            for tool in range(family.tool0, family.tool0 + family.tools):
                inp.down_until[tool] = _STRESS_HOURS * 3600.0
        _PLANS[key] = build_plan(fab, inp)
    return _PLANS[key]


def _inherited(fab: Fab) -> Iterator[tuple[int, int, int, float]]:
    """Snapshot lots already inside a CQT span at t=0 (window taken to open at 0)."""
    for lot, (route_i, step) in enumerate(zip(fab.lot_route, fab.lot_step, strict=True)):
        route = fab.routes[route_i]
        for origin in range(step - 1, -1, -1):
            target = route.cqt_target[origin]
            if route.cqt_limit[origin] > 0 and target >= step:
                yield lot, origin, target, route.cqt_limit[origin]
                break


def replay(fab: Fab, events: list[tuple[Any, ...]], horizon: float) -> dict[str, Any]:
    """Q-time buckets and batch fill from a recorded run (same for every arm)."""
    own = dict.fromkeys(_BUCKETS, 0)
    inh = dict.fromkeys(_BUCKETS, 0)
    skipped = 0
    window: dict[int, tuple[int, float, bool]] = {}
    for lot, _origin, target, limit in _inherited(fab):
        window[lot] = (target, limit, True)
    batch_lots = batch_cap = batch_starts = 0

    def close(lot: int, outcome: str) -> None:
        _target, _deadline, inherited = window.pop(lot)
        (inh if inherited else own)[outcome] += 1

    for event in events:
        kind = event[0]
        if kind == "end":
            _kind, moment, lot, index = event[:4]
            route = fab.routes[fab.lot_route[lot]]
            if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
                window[lot] = (route.cqt_target[index], moment + route.cqt_limit[index], False)
        elif kind == "start":
            moment, lots, steps = event[1], event[3], event[4]
            for lot, index in zip(lots, steps, strict=True):
                if lot in window and window[lot][0] == index:
                    close(lot, "late" if moment > window[lot][1] + 1e-6 else "met")
            route = fab.routes[fab.lot_route[lots[0]]]
            if route.batch_max[steps[0]] > 0:
                batch_starts += 1
                batch_lots += len(lots)
                batch_cap += max(1, route.batch_max[steps[0]] // _WAFERS)
        elif kind == "reclean":
            lot = event[2]
            if lot in window:
                close(lot, "recleaned")
        elif kind == "qhold":
            lot = event[2]
            if lot in window:
                close(lot, "held")
        elif kind == "skip":
            lot, nxt = event[2], event[3]
            if lot in window and window[lot][0] == nxt:
                window.pop(lot)
                skipped += 1
    live = 0
    for lot in list(window):
        if window[lot][1] <= horizon:
            close(lot, "expired")
        else:
            window.pop(lot)
            live += 1
    scored = sum(own.values())
    return {"q_" + key: value for key, value in own.items()} | {
        "q_scored": scored,
        "q_rate_pct": round(100.0 * own["met"] / scored, 2) if scored else None,
        "q_inherited": sum(inh.values()),
        "q_inherited_missed": sum(inh.values()) - inh["met"],
        "q_skipped": skipped,
        "q_live": live,
        "batch_starts_replay": batch_starts,
        "batch_lots_replay": batch_lots,
        "batch_cap_replay": batch_cap,
    }


# ------------------------------------------------------------- balance KPIs
#
# Measured only; nothing here feeds the dispatcher. Every KPI is recomputed
# from the recorded events (plus the run's downs, PM windows and horizon), so
# main, the fixed branch and every plan arm are scored the same way.

BOTTLENECKS = ("Litho_BE_110", "Litho_FE_92")
_SAMPLE_SEC = 3600.0


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for lo, hi in sorted(spans):
        if hi <= lo:
            continue
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _clip(spans: list[tuple[float, float]], end: float) -> list[tuple[float, float]]:
    return [(max(0.0, lo), min(hi, end)) for lo, hi in spans if hi > 0.0 and lo < end]


def _complement(spans: list[tuple[float, float]], end: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    cursor = 0.0
    for lo, hi in spans:
        if lo > cursor:
            out.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < end:
        out.append((cursor, end))
    return out


def _overlap(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    total = 0.0
    i = j = 0
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if hi > lo:
            total += hi - lo
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def _spread(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"max_min": None, "cv": None}
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    cv = (var**0.5) / mean if mean > 1e-12 else None
    return {
        "max_min": round(max(values) - min(values), 4),
        "cv": None if cv is None else round(cv, 4),
    }


def balance_kpis(
    fab: Fab,
    events: list[tuple[Any, ...]],
    horizon: float,
    downs: list[list[tuple[float, float]]],
    pm: list[list[tuple[float, float]]],
) -> dict[str, Any]:
    """Product fairness, load levelling, WIP balance and throughput of one run.

    Queue membership is rebuilt from the events: a lot joins the queue of its
    next step's family one fixed transport after its ``end`` (or at its entry:
    t=0 for WIP, the release for a released lot), after a ``reclean`` at its
    origin step, after a ``rework`` at once, and leaves it at its ``start``.
    Starvation of a bottleneck family is tool time that is up (no down, no
    PM), not processing, while that family's queue is empty: no WIP there at
    all. Idle-up time with WIP queued (pins, reticles, setups, holds) is
    reported apart as ``blocked``; eligibility is not re-derived here.
    """
    from resilimes.smt.fab import lot_number, measured, transport_seconds

    n = len(fab.lot_id)
    release = list(getattr(fab, "lot_release", None) or [0.0] * n)
    routes = fab.routes
    nfam = len(fab.families)
    ntool = len(fab.tool_family)
    number = [lot_number(name, lot) for lot, name in enumerate(fab.lot_id)]
    step = list(fab.lot_step)
    entered = [release[lot] <= 0.0 for lot in range(n)]
    finished = [-1.0] * n
    in_queue = [-1] * n
    qlen = [0] * nfam
    route_len = [len(routes[fab.lot_route[lot]].family) for lot in range(n)]
    remain0 = [routes[fab.lot_route[lot]].remain[fab.lot_step[lot]] for lot in range(n)]
    busy: list[list[tuple[float, float]]] = [[] for _ in range(ntool)]
    open_busy: dict[int, int] = {}
    steps_done = [0] * n
    watch = [fab.family_index[name] for name in BOTTLENECKS if name in fab.family_index]
    # (time, queue length) change log of the bottleneck families.
    qlog: dict[int, list[tuple[float, int]]] = {fam: [(0.0, 0)] for fam in watch}
    arrivals: list[tuple[float, int, int, int]] = []  # (time, seq, lot, family)
    seq = 0

    def join(lot: int, fam: int, moment: float) -> None:
        nonlocal seq
        heapq.heappush(arrivals, (moment, seq, lot, fam))
        seq += 1

    def set_q(fam: int, delta: int, moment: float) -> None:
        qlen[fam] += delta
        if fam in qlog:
            qlog[fam].append((moment, qlen[fam]))

    for lot in range(n):
        route = routes[fab.lot_route[lot]]
        join(lot, route.family[step[lot]], max(0.0, release[lot]))

    samples_q: list[list[int]] = []
    samples_pos: list[list[int]] = []
    next_sample = 0.0

    def take_sample() -> None:
        samples_q.append(list(qlen))
        pos = [0] * 5
        for lot in range(n):
            if entered[lot] and finished[lot] < 0:
                pos[min(4, 5 * step[lot] // route_len[lot])] += 1
        samples_pos.append(pos)

    def drain(until: float) -> None:
        nonlocal next_sample
        while True:
            when = arrivals[0][0] if arrivals else float("inf")
            if next_sample <= until and next_sample <= horizon and next_sample <= when:
                take_sample()
                next_sample += _SAMPLE_SEC
                continue
            if when <= until:
                moment, _s, lot, fam = heapq.heappop(arrivals)
                entered[lot] = True
                if finished[lot] < 0 and in_queue[lot] < 0:
                    in_queue[lot] = fam
                    set_q(fam, 1, moment)
                continue
            break

    def leave(lot: int, moment: float) -> None:
        fam = in_queue[lot]
        if fam >= 0:
            in_queue[lot] = -1
            set_q(fam, -1, moment)

    def advance(lot: int, index: int, moment: float) -> None:
        route = routes[fab.lot_route[lot]]
        nxt = index + 1
        while nxt < len(route.family) and not measured(route, nxt, number[lot]):
            nxt += 1
        if nxt >= len(route.family):
            finished[lot] = moment
            return
        step[lot] = nxt
        move = transport_seconds(fab, route.family[index], route.family[nxt])
        join(lot, route.family[nxt], moment + move)

    for event in events:
        kind = event[0]
        if kind not in ("start", "end", "reclean", "rework", "interrupt"):
            continue
        moment = float(event[1])
        drain(moment)
        if kind == "start":
            tool, lots, finish = event[2], event[3], float(event[5])
            for lot in lots:
                leave(lot, moment)
            busy[tool].append((moment, finish))
            open_busy[tool] = len(busy[tool]) - 1
        elif kind == "end":
            lot, index = event[2], event[3]
            steps_done[lot] += 1
            advance(lot, index, moment)
        elif kind == "interrupt":
            tool = event[2]
            slot = open_busy.get(tool)
            if slot is not None:
                lo, hi = busy[tool][slot]
                if moment < hi:
                    busy[tool][slot] = (lo, moment)
        elif kind == "reclean":
            lot, origin = event[2], event[4]
            leave(lot, moment)
            route = routes[fab.lot_route[lot]]
            here = route.family[step[lot]]
            step[lot] = origin
            join(
                lot,
                route.family[origin],
                moment + transport_seconds(fab, here, route.family[origin]),
            )
        elif kind == "rework":
            lot, index = event[3], event[4]
            route = routes[fab.lot_route[lot]]
            step[lot] = index
            join(lot, route.family[index], moment)
    drain(horizon)

    # Utilisation and starvation.
    days = horizon / 86400.0
    fam_util: list[float] = []
    fam_names: list[str] = []
    tool_util: dict[int, list[float]] = {fam: [] for fam in watch}
    starve = {fam: 0.0 for fam in watch}
    blocked = {fam: 0.0 for fam in watch}
    up_total = {fam: 0.0 for fam in watch}
    zero_spans: dict[int, list[tuple[float, float]]] = {}
    for fam in watch:
        log = qlog[fam]
        spans: list[tuple[float, float]] = []
        for (t0, q0), (t1, _q1) in zip(log, [*log[1:], (horizon, 0)], strict=True):
            if q0 == 0 and t1 > t0:
                spans.append((t0, min(t1, horizon)))
        zero_spans[fam] = _merge_spans(_clip(spans, horizon))
    for fam, item in enumerate(fab.families):
        up_sum = busy_sum = 0.0
        for tool in range(item.tool0, item.tool0 + item.tools):
            off = _merge_spans(_clip([*downs[tool], *pm[tool]], horizon))
            up_spans = _complement(off, horizon)
            up = sum(hi - lo for lo, hi in up_spans)
            mine = _merge_spans(_clip(busy[tool], horizon))
            work = _overlap(mine, up_spans)
            up_sum += up
            busy_sum += work
            if fam in tool_util:
                tool_util[fam].append(work / up if up > 0 else 0.0)
                idle_up = _complement(_merge_spans([*mine, *off]), horizon)
                gone = _overlap(idle_up, zero_spans[fam])
                starve[fam] += gone
                blocked[fam] += sum(hi - lo for lo, hi in idle_up) - gone
                up_total[fam] += up
        if up_sum > 0:
            fam_util.append(busy_sum / up_sum)
            fam_names.append(item.name)
    util = dict(zip(fam_names, fam_util, strict=True))
    out: dict[str, Any] = {
        "steps_per_day": round(sum(steps_done) / days, 1) if days > 0 else None,
        "completed_kpi": sum(1 for lot in range(n) if 0 <= finished[lot] <= horizon),
        "util_mean": round(sum(fam_util) / len(fam_util), 4) if fam_util else None,
        "util_spread": _spread(fam_util),
    }
    for fam in watch:
        name = fab.families[fam].name
        out[f"util_{name}"] = round(util.get(name, 0.0), 4)
        out[f"util_tools_{name}"] = _spread(tool_util[fam])
        out[f"starve_h_{name}"] = round(starve[fam] / 3600.0, 2)
        out[f"starve_pct_{name}"] = (
            round(100.0 * starve[fam] / up_total[fam], 2) if up_total[fam] > 0 else None
        )
        out[f"blocked_h_{name}"] = round(blocked[fam] / 3600.0, 2)

    # WIP balance: route-position quintiles and family queues over time.
    if samples_pos:
        mean_pos = [sum(row[q] for row in samples_pos) / len(samples_pos) for q in range(5)]
        total = sum(mean_pos) or 1.0
        out["wip_quintile_mean"] = [round(100.0 * v / total, 2) for v in mean_pos]
        last = samples_pos[-1]
        out["wip_quintile_end"] = [round(100.0 * v / (sum(last) or 1), 2) for v in last]
        out["wip_quintile_end_lots"] = last
    tools = [max(1, item.tools) for item in fab.families]
    cvs: list[float] = []
    for snap in samples_q:
        load = [snap[fam] / tools[fam] for fam in range(nfam)]
        cv = _spread(load)["cv"]
        if cv is not None:
            cvs.append(cv)
    out["queue_cv_families"] = round(sum(cvs) / len(cvs), 4) if cvs else None
    if samples_q:
        variances = []
        for fam in range(nfam):
            col = [snap[fam] for snap in samples_q]
            mean = sum(col) / len(col)
            variances.append(sum((v - mean) ** 2 for v in col) / len(col))
        out["queue_var_mean"] = round(sum(variances) / len(variances), 2)

    # Product fairness per route.
    per: dict[str, dict[str, Any]] = {}
    for lot in range(n):
        if not entered[lot] and release[lot] > horizon:
            continue
        rid = routes[fab.lot_route[lot]].route_id
        acc = per.setdefault(
            rid, {"lots": 0, "due": 0, "on_time": 0, "done": 0, "steps": 0, "ct": [], "xf": []}
        )
        acc["lots"] += 1
        acc["steps"] += steps_done[lot]
        end = finished[lot]
        if end >= 0:
            acc["done"] += 1
            cycle = end - max(0.0, release[lot])
            acc["ct"].append(cycle)
            if remain0[lot] > 1e-6:
                acc["xf"].append(cycle / remain0[lot])
        if fab.lot_due[lot] <= horizon:
            acc["due"] += 1
            if 0 <= end <= fab.lot_due[lot]:
                acc["on_time"] += 1
    routes_out: dict[str, Any] = {}
    for rid in sorted(per, key=lambda key: (len(key), key)):
        acc = per[rid]
        routes_out[rid] = {
            "lots": acc["lots"],
            "on_time_pct": round(100.0 * acc["on_time"] / acc["due"], 2) if acc["due"] else None,
            "due": acc["due"],
            "completed": acc["done"],
            "completed_pct": round(100.0 * acc["done"] / acc["lots"], 2),
            "steps_per_lot": round(acc["steps"] / acc["lots"], 2),
            "mean_ct_h": round(sum(acc["ct"]) / len(acc["ct"]) / 3600.0, 2) if acc["ct"] else None,
            "mean_xf": round(sum(acc["xf"]) / len(acc["xf"]), 3) if acc["xf"] else None,
        }
    out["route"] = routes_out
    for key in ("on_time_pct", "completed_pct", "steps_per_lot", "mean_xf", "mean_ct_h"):
        values = [r[key] for r in routes_out.values() if r[key] is not None]
        out[f"fair_{key}"] = _spread(values)
    return out


_FAB: list[Fab] = []
_ARM: list[str] = []


def _one(item: tuple[str, int, str] | tuple[str, int, str, str]) -> dict[str, Any]:
    book, seed, policy = item[:3]
    fab = _FAB[0]
    plant, kwargs = _setup(fab, book, seed, policy)
    if _ARM[0] == "mech":
        kwargs["r2_policy"] = False
    if _ARM[0] in ("plan", "ablate_plan", "plan_famwait"):
        kwargs["plan"] = book_plan(fab, book)
    else:
        # Non-plan arms are the qtime-r2 path (strict Q-time), not the default plan.
        kwargs["sched_mode"] = "strict_qtime"
    if _ARM[0] == "plan_famwait":
        # planning-r1 before the position-in-queue wait (A/B study arm).
        kwargs["plan_wait"] = "family"
    row: dict[str, Any] = {"book": book, "seed": seed, "policy": policy}
    row["lots"] = len(plant.lot_id)
    row["released_lots"] = len(plant.lot_id) - len(fab.lot_id)
    if len(item) == 4:
        variant = str(item[3])
        kwargs["r2_fixes"] = tuple(int(part) for part in variant.split("+"))
        row["variant"] = variant
    else:
        # Full r2 arm stays fixes 1-3 explicitly so study results reproduce
        # regardless of the run_policy default / RESILIMES_QTIME_FIX1.
        kwargs.setdefault("r2_fixes", (1, 2, 3))
    result = run_policy(plant, **kwargs)
    for key in (
        "on_time_pct",
        "due_in_horizon",
        "completed_routes",
        "mean_x_factor",
        "weighted_tardiness_min",
        "qtime_violations",
        "qtime_gates",
        "recleans",
        "reworks",
        "batch_starts",
        "batch_lots",
        "dispatch_p50_ms",
        "dispatch_p95_ms",
        "dispatch_busy_p95_ms",
        "sim_s",
        "tool_reservations",
        "reserved_min",
        "reserve_used",
        "reserve_elsewhere",
        "reserve_expired",
        "reserve_cancelled",
        "qtime_holds",
        "qtime_hold_lot_min",
        "qtime_shortlist_added",
        "repins",
        "reserve_replanned",
        "replan_ticks",
        "replan_stalls",
        "replan_stalls_batch",
        "replan_tick_p50_ms",
        "replan_tick_p95_ms",
        "replan_tick_total_s",
        "flow_wait_ratio",
        "plan_due_fallbacks",
        "sched_starts",
        "sched_follow",
        "deviations",
        "sched_stale_detail",
        "sched_build_p95_ms",
        "sched_build_total_s",
    ):
        row[key] = getattr(result, key, None)
    row["on_time"] = round(result.on_time_pct * result.due_in_horizon / 100.0)
    row.update(replay(plant, result.events, kwargs["horizon"]))
    if os.environ.get("RESILIMES_STUDY_KPI", "1") == "1":
        row["kpi"] = balance_kpis(
            plant, result.events, kwargs["horizon"], kwargs["downs"], kwargs["pm"]
        )
    return row


def main() -> None:
    if sys.argv[1:2] == ["shift_lead"]:
        from resilimes.smt.shift_lead_study import main as shift_lead_main

        shift_lead_main(sys.argv[2:])
        return
    arm, out = sys.argv[1], sys.argv[2]
    _ARM.append(arm)
    _FAB.append(load_fab())
    policies = ("resilimes",) if arm == "mech" else POLICIES
    items: list[Any] = [
        (book, seed, policy) for book in BOOKS for seed in _seeds(book) for policy in policies
    ]
    if arm in ("ablate", "ablate_plan"):
        items = [
            (book, seed, "resilimes", variant)
            for variant in ABLATE_VARIANTS
            for book in ABLATE_BOOKS
            for seed in _seeds(book)
        ]
    workers = max(1, int(os.environ.get("RESILIMES_STUDY_WORKERS", "5")))
    # Progress: a line on stderr per finished run (every 10 s in a log) and
    # <out>.progress.json; RESILIMES_STUDY_PROGRESS=0 turns both off.
    shown = os.environ.get("RESILIMES_STUDY_PROGRESS", "1") != "0"
    progress = Progress(
        study=f"qtime_study:{arm}",
        plan=[str(item[2]) for item in items],
        path=progress_path(out) if shown else None,
        console=shown,
        background=False,  # the pool may fork a fresh worker at any time
    )
    with get_context("fork").Pool(workers, maxtasksperchild=10) as pool, progress:
        rows = list(follow(pool.imap(_one, items, chunksize=1), progress))
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"arm": arm, "rows": rows}, handle, indent=1)
    print(f"{arm}: {len(rows)} runs -> {out}", flush=True)


if __name__ == "__main__":
    main()
