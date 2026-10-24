"""Run the trace invariant checker on the full fab, seeds 1-5, every policy.

Books: published dues (steady), X-factor dues with ``Litho_FE_92-1`` down
600 minutes, the PM calendar shifted so ``Litho_FE_92_WK`` opens at 2 hours,
and the tight VIP book. Prints one line per run and a total per book and
policy. Exits non-zero when any check fails. ``make smt-invariants``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.invariants import CHECKS, check_trace
from resilimes.smt.scenarios import SEEDS, STUDY_HORIZON_SEC
from resilimes.smt.simulate import pm_shift_to_open, pm_windows, run_policy, sample_downs
from resilimes.smt.tight import TIGHT_HORIZON_SEC, apply_tight, apply_xfactor

POLICIES = ("resilimes", "edd", "fifo", "cr", "smt_rule")
_ETA_SEC = 600.0 * 60.0


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


def sweep(seeds: tuple[int, ...] = tuple(SEEDS)) -> dict[str, dict[str, dict[str, int]]]:
    fab = load_fab()
    totals: dict[str, dict[str, dict[str, int]]] = {}
    for seed in seeds:
        for name, plant, horizon, downs, pm, focus in _books(fab, seed):
            for policy in POLICIES:
                result = run_policy(
                    plant,
                    policy=policy,
                    seed=seed,
                    horizon=horizon,
                    downs=downs,
                    pm=pm,
                    trace=False,
                    focus_down_until=focus,
                    record=True,
                )
                report = check_trace(plant, result, downs=downs, pm=pm)
                row = totals.setdefault(name, {}).setdefault(
                    policy, {"starts": 0, **{key: 0 for key in CHECKS}}
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
    print("| Book | Policy | Starts | " + " | ".join(CHECKS) + " |")
    print("| --- | --- | ---: | " + " | ".join("---:" for _ in CHECKS) + " |")
    for name, rows in totals.items():
        for policy, row in rows.items():
            bad += sum(row[key] for key in CHECKS)
            cells = " | ".join(str(row[key]) for key in CHECKS)
            print(f"| {name} | {policy} | {row['starts']} | {cells} |")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
