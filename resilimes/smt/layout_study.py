"""Multi-building layout study: layout off vs on, and freeze off vs on with it.

``python -m resilimes.smt.layout_study OUT.json`` runs the published book,
published seeds 1-3, 168 h horizon (``RESILIMES_STUDY_HORIZON_H``), ResiliMES
and EDD, three arms:

* ``L0F0``: one building (main transport), freeze off;
* ``L1F0``: example two-building layout (``resilimes.smt.layout``), freeze off;
* ``L1F1``: example layout, frozen zone on at its defaults (2 loads / 30 min).

Freeze tracking is on in every arm (dispatch unchanged with the freeze off), so
second transports are counted the same way everywhere; with the freeze off they
are the shadow count, as in ``freeze_study``. Settings otherwise as
``freeze_study`` (``qtime_study._setup``, Q-time r2 fixes 1-3). No weights, due
dates or seeds are tuned. ``RESILIMES_STUDY_WORKERS`` (default 2) sets the pool.
``python -m resilimes.smt.layout_study --report OUT.json`` prints the table of
docs/FAB_LAYOUT.md.
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

BOOK = "published"
SEEDS = (1, 2, 3)
POLICIES = ("resilimes", "edd")
# (arm, layout on, freeze on)
ARMS = (("L0F0", False, False), ("L1F0", True, False), ("L1F1", True, True))
ARM_LABEL = {
    "L0F0": "1 building, freeze off",
    "L1F0": "2 buildings, freeze off",
    "L1F1": "2 buildings, freeze on",
}
_FAB: list[Fab] = []


def _one(item: tuple[int, str, str]) -> dict[str, Any]:
    seed, policy, arm = item
    _name, layout, freeze = next(row for row in ARMS if row[0] == arm)
    plant, kwargs = qtime_study._setup(_FAB[0], BOOK, seed, policy)
    kwargs.setdefault("r2_fixes", (1, 2, 3))
    cfg = FreezeConfig(enabled=freeze, track=True)
    result = run_policy(plant, freeze=cfg, layout=layout, **kwargs)
    horizon = kwargs["horizon"]
    row: dict[str, Any] = {"book": BOOK, "seed": seed, "policy": policy, "arm": arm}
    row["horizon_h"] = horizon / 3600.0
    for key in (
        "on_time_pct",
        "due_in_horizon",
        "completed_routes",
        "weighted_tardiness_min",
        "qtime_violations",
        "sim_s",
    ):
        row[key] = getattr(result, key)
    row["on_time"] = round(result.on_time_pct * result.due_in_horizon / 100.0)
    row.update(qtime_study.replay(plant, result.events, horizon))
    row["layout"] = result.layout
    row["second_transports"] = result.sched_freeze["second_transports"]
    return row


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 2) if den else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pooled KPIs of one policy and arm over its seeds."""
    due = sum(row["due_in_horizon"] for row in rows)
    return {
        "runs": len(rows),
        "on_time_pct": _pct(sum(row["on_time"] for row in rows), due),
        "on_time": f"{sum(row['on_time'] for row in rows)}/{due}",
        "completed": sum(row["completed_routes"] for row in rows),
        "q_true_pct": _pct(sum(row["q_met"] for row in rows), sum(row["q_scored"] for row in rows)),
        "weighted_tardiness_min": round(sum(row["weighted_tardiness_min"] for row in rows), 1),
        "transport_min": round(sum(row["layout"]["transport_min"] for row in rows), 1),
        "transport_moves": sum(row["layout"]["transport_moves"] for row in rows),
        "cross_building_moves": sum(row["layout"]["cross_building_moves"] for row in rows),
        "second_transports": sum(row["second_transports"] for row in rows),
        "second_transport_min": round(
            sum(row["layout"]["second_transport_min"] for row in rows), 1
        ),
    }


KEYS = (
    ("on_time_pct", "on-time %"),
    ("on_time", "on-time lots"),
    ("completed", "completed"),
    ("q_true_pct", "true Q-time %"),
    ("weighted_tardiness_min", "weighted tardiness (min)"),
    ("transport_min", "transport (min)"),
    ("transport_moves", "transport moves"),
    ("cross_building_moves", "cross-building moves"),
    ("second_transports", "second transports"),
    ("second_transport_min", "second-transport (min)"),
)


def report(rows: list[dict[str, Any]]) -> str:
    """Pooled table (seeds summed) per policy and arm, then per-seed on-time."""
    lines = ["| KPI | " + " | ".join(f"{p} {a}" for p in POLICIES for a, *_ in ARMS) + " |"]
    lines.append("|---|" + "---:|" * (len(POLICIES) * len(ARMS)))
    pooled = {
        (p, a): aggregate([r for r in rows if r["policy"] == p and r["arm"] == a])
        for p in POLICIES
        for a, *_ in ARMS
    }
    for key, label in KEYS:
        cells = [str(pooled[(p, a)][key]) for p in POLICIES for a, *_ in ARMS]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["", "Per seed, on-time lots / due (completed):", ""]
    lines.append("| policy | arm | " + " | ".join(f"seed {s}" for s in SEEDS) + " |")
    lines.append("|---|---|" + "---:|" * len(SEEDS))
    for p in POLICIES:
        for a, *_ in ARMS:
            cells = []
            for s in SEEDS:
                hit = [r for r in rows if r["policy"] == p and r["arm"] == a and r["seed"] == s]
                cells.append(
                    f"{hit[0]['on_time']}/{hit[0]['due_in_horizon']} ({hit[0]['completed_routes']})"
                    if hit
                    else "-"
                )
            lines.append(f"| {p} | {a} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    if sys.argv[1] == "--report":
        with open(sys.argv[2], encoding="utf-8") as handle:
            data = json.load(handle)
        print(report(data["rows"] if isinstance(data, dict) else data))
        return
    out = sys.argv[1]
    hours = float(os.environ.get("RESILIMES_STUDY_HORIZON_H", "168"))
    qtime_study.STUDY_HORIZON_SEC = hours * 3600.0
    _FAB.append(load_fab())
    items = [(seed, policy, arm) for seed in SEEDS for policy in POLICIES for arm, *_ in ARMS]
    workers = max(1, int(os.environ.get("RESILIMES_STUDY_WORKERS", "2")))
    rows: list[dict[str, Any]] = []
    with (
        get_context("fork").Pool(workers, maxtasksperchild=3) as pool,
        open(f"{out}.partial.jsonl", "w", encoding="utf-8") as partial,
    ):
        for row in pool.imap_unordered(_one, items, chunksize=1):
            rows.append(row)
            partial.write(json.dumps(row) + "\n")
            partial.flush()
            print(
                f"{len(rows)}/{len(items)} s{row['seed']} {row['policy']} {row['arm']} "
                f"{row['sim_s']:.0f}s",
                flush=True,
            )
    rows.sort(key=lambda row: (row["seed"], row["policy"], row["arm"]))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"horizon_h": hours, "rows": rows}, handle, indent=1)
    print(f"layout study: {len(rows)} runs -> {out}")


if __name__ == "__main__":
    main()
