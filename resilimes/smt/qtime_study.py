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

import json
import os
import sys
from collections.abc import Iterator
from multiprocessing import get_context
from typing import Any

from resilimes.smt import simulate as sim_mod
from resilimes.smt.fab import LITHO_MTTR_MIN, Fab, load_fab
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


def _setup(fab: Fab, book: str, seed: int, policy: str) -> tuple[Fab, dict[str, Any]]:
    """The plant and run_policy kwargs of one run (mirrors ``benchmark.py``)."""
    horizon = STUDY_HORIZON_SEC
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
    else:
        raise KeyError(book)
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
}
_PLANS: dict[str, Any] = {}


def book_plan(fab: Fab, book: str) -> Any:
    """The planning layer's output for one book, computed once (t=0, WIP only).

    WIP only: the sim does not release ``order.txt`` lots yet, so the plan's
    litho load is the load the sim runs. Seeds share the plan: it uses the
    expected availability (MTTF/(MTTF+MTTR)), not the sampled downs.
    """
    if book not in _PLANS:
        from resilimes.smt.planning import build_plan, scenario_input

        inp = scenario_input(fab, BOOK_SCENARIO[book], releases=False)
        if book == "litho_family_2h":
            family = fab.families[fab.focus_family]
            for tool in range(family.tool0, family.tool0 + family.tools):
                inp.down_until[tool] = _STRESS_HOURS * 3600.0
        _PLANS[book] = build_plan(fab, inp)
    return _PLANS[book]


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


_FAB: list[Fab] = []
_ARM: list[str] = []


def _one(item: tuple[str, int, str] | tuple[str, int, str, str]) -> dict[str, Any]:
    book, seed, policy = item[:3]
    fab = _FAB[0]
    plant, kwargs = _setup(fab, book, seed, policy)
    if _ARM[0] == "mech":
        kwargs["r2_policy"] = False
    if _ARM[0] in ("plan", "ablate_plan"):
        kwargs["plan"] = book_plan(fab, book)
    row: dict[str, Any] = {"book": book, "seed": seed, "policy": policy}
    if len(item) == 4:
        variant = str(item[3])
        kwargs["r2_fixes"] = tuple(int(part) for part in variant.split("+"))
        row["variant"] = variant
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
    return row


def main() -> None:
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
    with get_context("fork").Pool(workers, maxtasksperchild=10) as pool:
        rows = pool.map(_one, items, chunksize=1)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"arm": arm, "rows": rows}, handle, indent=1)
    print(f"{arm}: {len(rows)} runs -> {out}")


if __name__ == "__main__":
    main()
