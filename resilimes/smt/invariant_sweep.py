"""Run the trace invariant checker on the full fab, seeds 1-5, every policy.

Books: published dues (steady), X-factor dues with ``Litho_FE_92-1`` down
600 minutes, the PM calendar shifted so ``Litho_FE_92_WK`` opens at 2 hours,
the tight VIP book, and the litho stress book (every ``Litho_FE_92`` scanner
down 2 hours in the busy window, see ``resilimes.smt.stress``), which also
runs the stall audit: ``stall`` counts samples where an idle, up tool had a
start ready and no pending event would ever start it, ``wip_frozen`` counts
5-minute samples (after the first hour) with no step finished, ``stranded``
is the most waiting lots no tool of their family may ever start. Prints one line per run and a total per book and
policy. Exits non-zero when any check fails. ``make smt-invariants``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from multiprocessing import get_context
from typing import Any

from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.invariants import CHECKS, check_trace
from resilimes.smt.scenarios import SEEDS, STUDY_HORIZON_SEC
from resilimes.smt.simulate import pm_shift_to_open, pm_windows, run_policy, sample_downs
from resilimes.smt.stress import audited_run, stress_downs
from resilimes.smt.tight import TIGHT_HORIZON_SEC, apply_tight, apply_xfactor

POLICIES = ("resilimes", "edd", "fifo", "cr", "smt_rule")
_ETA_SEC = 600.0 * 60.0
BOOKS = ("published", "xfactor_eta600", "pm_enforced", "tight_vip", "litho_family_2h")
SWEEP_CHECKS = (*CHECKS, "stall", "wip_frozen", "stranded")


def _books(fab: Fab, seed: int) -> Iterator[tuple[str, Fab, float, Any, Any, float]]:
    horizon = STUDY_HORIZON_SEC
    yield "published", fab, horizon, sample_downs(fab, seed, horizon), pm_windows(fab, horizon), 0.0
    plant = apply_xfactor(fab)
    yield (
        "xfactor_eta600",
        plant,
        horizon,
        sample_downs(plant, seed, horizon, forced_tool=plant.focus_tool, forced_until=_ETA_SEC),
        pm_windows(plant, horizon),
        _ETA_SEC,
    )
    shift = pm_shift_to_open(fab, fab.pm_calendar, 2 * 3600.0)
    yield (
        "pm_enforced",
        fab,
        horizon,
        sample_downs(fab, seed, horizon),
        pm_windows(fab, horizon, shift_sec=shift),
        0.0,
    )
    book = apply_tight(fab, horizon=TIGHT_HORIZON_SEC)
    downs = sample_downs(book.fab, seed, TIGHT_HORIZON_SEC)
    downs[book.down_tool].append((0.0, min(book.down_until, TIGHT_HORIZON_SEC)))
    yield (
        "tight_vip",
        book.fab,
        TIGHT_HORIZON_SEC,
        downs,
        pm_windows(book.fab, TIGHT_HORIZON_SEC),
        0.0,
    )
    yield (
        "litho_family_2h",
        fab,
        horizon,
        stress_downs(fab, seed, horizon),
        pm_windows(fab, horizon),
        0.0,
    )


_FAB: list[Fab] = []


def _one(item: tuple[int, str, str]) -> tuple[int, str, str, dict[str, Any]]:
    seed, want, policy = item
    fab = _FAB[0]
    for name, plant, horizon, downs, pm, focus in _books(fab, seed):
        if name != want:
            continue
        kwargs: dict[str, Any] = {
            "policy": policy,
            "seed": seed,
            "horizon": horizon,
            "downs": downs,
            "pm": pm,
            "trace": False,
            "focus_down_until": focus,
            "record": True,
        }
        audit = None
        if name == "litho_family_2h":
            result, audit = audited_run(plant, **kwargs)
        else:
            result = run_policy(plant, **kwargs)
        report = check_trace(plant, result, downs=downs, pm=pm)
        report.pop("examples", None)
        report["counts"]["stall"] = audit.stall_samples if audit else 0
        report["counts"]["wip_frozen"] = audit.wip_frozen if audit else 0
        report["counts"]["stranded"] = audit.stranded_max if audit else 0
        return seed, name, policy, report
    raise KeyError(want)


def sweep(
    seeds: tuple[int, ...] = tuple(SEEDS), workers: int | None = None
) -> dict[str, dict[str, dict[str, int]]]:
    """Every (seed, book, policy) run is independent; ``workers`` processes run them.

    A recorded full-scale run keeps its event list, so the default pool is
    smaller than the benchmark's. ``RESILIMES_SWEEP_WORKERS=1`` runs serially.
    """
    if not _FAB:
        _FAB.append(load_fab())
    count = workers or max(1, int(os.environ.get("RESILIMES_SWEEP_WORKERS", "4")))
    items = [(seed, name, policy) for seed in seeds for name in BOOKS for policy in POLICIES]
    if count <= 1:
        done = [_one(item) for item in items]
    else:
        with get_context("fork").Pool(count) as pool:
            done = pool.map(_one, items, chunksize=1)
    totals: dict[str, dict[str, dict[str, int]]] = {}
    for seed, name, policy, report in done:
        row = totals.setdefault(name, {}).setdefault(
            policy, {"starts": 0, **{key: 0 for key in SWEEP_CHECKS}}
        )
        row["starts"] += int(report["starts"])
        for key, value in report["counts"].items():
            row[key] += int(value)
        failed = {key: value for key, value in report["counts"].items() if value}
        print(
            f"{name} {policy} seed {seed}: {report['starts']} starts, "
            f"Q-time {report['qtime_recount']}/{report['qtime_reported']}, "
            f"failures {failed or 0}",
            flush=True,
        )
    return totals


def main() -> None:
    totals = sweep()
    bad = 0
    print("| Book | Policy | Starts | " + " | ".join(SWEEP_CHECKS) + " |")
    print("| --- | --- | ---: | " + " | ".join("---:" for _ in SWEEP_CHECKS) + " |")
    for name, rows in totals.items():
        for policy, row in rows.items():
            bad += sum(row[key] for key in SWEEP_CHECKS)
            cells = " | ".join(str(row[key]) for key in SWEEP_CHECKS)
            print(f"| {name} | {policy} | {row['starts']} | {cells} |")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
