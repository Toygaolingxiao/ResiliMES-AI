"""Frozen dispatch zone study: freeze off vs on, ResiliMES and EDD, 7 days.

``python -m resilimes.smt.freeze_study OUT.json`` runs every book and seed of
``qtime_study`` (published seeds 1-5, held-out 9-13; tight_vip stays at its
fixed 48 h) at a 168 h horizon, both policies, two arms:

* ``off``: main dispatch, with tick tracking on (shadow frozen zone, not
  enforced) so plan stability and second transports are measured the same way;
* ``on``: frozen zone enforced at the a-priori defaults (2 loads / 30 min).

Settings otherwise as the existing studies (``qtime_study._setup``, Q-time r2
fixes 1-3 set explicitly). True Q-time % is recomputed from the recorded
events with ``qtime_study.replay``. ``RESILIMES_STUDY_WORKERS`` (default 3)
sets the pool; ``RESILIMES_STUDY_HORIZON_H`` overrides the 168 h; with
``RESILIMES_STUDY_TICKLOG=1`` the published seed-1 runs also write their JSONL
tick log next to OUT.
"""

from __future__ import annotations

import json
import os
import sys
from multiprocessing import get_context
from typing import Any

from resilimes.smt import qtime_study
from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.freeze import FreezeConfig
from resilimes.smt.simulate import run_policy

POLICIES = ("resilimes", "edd")
ARMS = ("off", "on")
_FAB: list[Fab] = []
_OUT: list[str] = []


def fab_util_pct(tools: int, events: list[tuple[Any, ...]], horizon: float) -> float:
    """Busy share of every tool over the horizon, from 'start'/'interrupt' events."""
    piece: dict[int, tuple[float, float]] = {}
    busy = 0.0
    for event in events:
        kind = event[0]
        if kind == "start":
            _kind, moment, tool, _lots, _steps, finish = event[:6]
            piece[tool] = (moment, finish)
            busy += max(0.0, min(finish, horizon) - moment)
        elif kind == "interrupt":
            _kind, moment, tool = event[:3]
            row = piece.pop(tool, None)
            if row is not None and row[1] > moment:
                busy -= min(row[1], horizon) - moment
    return round(100.0 * busy / (tools * horizon), 3) if tools and horizon > 0 else 0.0


def _one(item: tuple[str, int, str, str]) -> dict[str, Any]:
    book, seed, policy, arm = item
    fab = _FAB[0]
    plant, kwargs = qtime_study._setup(fab, book, seed, policy)
    kwargs.setdefault("r2_fixes", (1, 2, 3))
    log_path = None
    if os.environ.get("RESILIMES_STUDY_TICKLOG") == "1" and book == "published" and seed == 1:
        log_path = f"{_OUT[0]}.ticks/{book}_s{seed}_{policy}_{arm}.jsonl.gz"
    cfg = FreezeConfig(enabled=arm == "on", track=True, log_path=log_path)
    result = run_policy(plant, freeze=cfg, **kwargs)
    horizon = kwargs["horizon"]
    row: dict[str, Any] = {"book": book, "seed": seed, "policy": policy, "arm": arm}
    row["horizon_h"] = horizon / 3600.0
    for key in (
        "on_time_pct",
        "due_in_horizon",
        "completed_routes",
        "weighted_tardiness_min",
        "mean_x_factor",
        "litho_util_pct",
        "scanner_util_pct",
        "qtime_violations",
        "recleans",
        "reworks",
        "batch_starts",
        "batch_lots",
        "setup_min",
        "pm_avoided",
        "replan_stalls",
        "sim_s",
    ):
        row[key] = getattr(result, key, None)
    row["on_time"] = round(result.on_time_pct * result.due_in_horizon / 100.0)
    row["fab_util_pct"] = fab_util_pct(len(plant.tool_name), result.events, horizon)
    replayed = qtime_study.replay(plant, result.events, horizon)
    row.update(replayed)
    row["sched_freeze"] = result.sched_freeze
    return row


def main() -> None:
    out = sys.argv[1]
    hours = float(os.environ.get("RESILIMES_STUDY_HORIZON_H", "168"))
    qtime_study.STUDY_HORIZON_SEC = hours * 3600.0
    _OUT.append(out)
    _FAB.append(load_fab())
    items = [
        (book, seed, policy, arm)
        for book in qtime_study.BOOKS
        for seed in qtime_study._seeds(book)
        for policy in POLICIES
        for arm in ARMS
    ]
    workers = max(1, int(os.environ.get("RESILIMES_STUDY_WORKERS", "3")))
    rows: list[dict[str, Any]] = []
    with (
        get_context("fork").Pool(workers, maxtasksperchild=4) as pool,
        open(f"{out}.partial.jsonl", "w", encoding="utf-8") as partial,
    ):
        for row in pool.imap_unordered(_one, items, chunksize=1):
            rows.append(row)
            partial.write(json.dumps(row) + "\n")
            partial.flush()
            print(
                f"{len(rows)}/{len(items)} {row['book']} s{row['seed']} {row['policy']} {row['arm']}",
                flush=True,
            )
    rows.sort(key=lambda row: (row["book"], row["seed"], row["policy"], row["arm"]))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"horizon_h": hours, "rows": rows}, handle, indent=1)
    print(f"freeze study: {len(rows)} runs -> {out}")


if __name__ == "__main__":
    main()
