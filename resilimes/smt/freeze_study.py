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
tick log next to OUT. ``python -m resilimes.smt.freeze_study --report OUT.json``
prints the markdown tables of docs/SCHED_FREEZE.md.
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


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 2) if den else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pooled KPIs of a set of runs (one policy, one arm)."""
    due = sum(row["due_in_horizon"] for row in rows)
    stats = [row["sched_freeze"] for row in rows]
    reasons: dict[str, int] = {}
    for stat in stats:
        for reason, count in stat["unfreezes"].items():
            reasons[reason] = reasons.get(reason, 0) + count
    runs = len(rows) or 1
    return {
        "runs": len(rows),
        "on_time_pct": _pct(sum(row["on_time"] for row in rows), due),
        "completed": sum(row["completed_routes"] for row in rows),
        "q_true_pct": _pct(sum(row["q_met"] for row in rows), sum(row["q_scored"] for row in rows)),
        "q_held": sum(row["q_held"] for row in rows),
        "weighted_tardiness_min": round(sum(row["weighted_tardiness_min"] for row in rows), 1),
        "fab_util_pct": round(sum(row["fab_util_pct"] for row in rows) / runs, 2),
        "litho_util_pct": round(sum(row["litho_util_pct"] for row in rows) / runs, 2),
        "staged_tool_change_rate": round(
            sum(stat["staged_tool_change_rate"] for stat in stats) / runs, 4
        ),
        "plan_tool_change_rate": round(
            sum(stat["plan_tool_change_rate"] for stat in stats) / runs, 4
        ),
        "kendall_tau_distance": round(
            sum(stat["kendall_tau_distance"] for stat in stats) / runs, 5
        ),
        "second_transports": sum(stat["second_transports"] for stat in stats),
        "unfreezes": reasons,
        "unfreeze_total": sum(reasons.values()),
        "hot_inserts": sum(stat["hot_inserts"] for stat in stats),
        "qtime_inserts": sum(stat["qtime_inserts"] for stat in stats),
        "frozen_waits": sum(stat["frozen_waits"] for stat in stats),
    }


def report(rows: list[dict[str, Any]]) -> str:
    """Markdown tables: pooled off vs on per policy, then on - off per book.

    Only complete off/on pairs (same book, seed, policy) are counted.
    """
    arms: dict[tuple[str, int, str], set[str]] = {}
    for row in rows:
        arms.setdefault((row["book"], row["seed"], row["policy"]), set()).add(row["arm"])
    rows = [r for r in rows if len(arms[(r["book"], r["seed"], r["policy"])]) == len(ARMS)]
    lines: list[str] = []
    keys = (
        ("on_time_pct", "on-time %"),
        ("completed", "completed"),
        ("q_true_pct", "true Q-time %"),
        ("q_held", "Q-time holds"),
        ("weighted_tardiness_min", "weighted tardiness (min)"),
        ("fab_util_pct", "fab util % (mean)"),
        ("litho_util_pct", "litho util % (mean)"),
        ("staged_tool_change_rate", "plan stability: staged tool-change rate"),
        ("plan_tool_change_rate", "plan stability: planned tool-change rate"),
        ("kendall_tau_distance", "plan stability: Kendall-tau distance"),
        ("second_transports", "second transports"),
        ("unfreeze_total", "unfreezes (total)"),
        ("hot_inserts", "hot-lot insertions"),
        ("qtime_inserts", "Q-time insertions"),
    )
    for scope, keep in (
        ("all books, all seeds", lambda row: True),
        ("published seeds 1-5", lambda row: row["seed"] < 9),
        ("held-out seeds 9-13", lambda row: row["seed"] >= 9),
    ):
        lines += [f"### {scope}", ""]
        lines.append("| KPI | " + " | ".join(f"{p} off | {p} on" for p in POLICIES) + " |")
        lines.append("|---|" + "---|" * (2 * len(POLICIES)))
        pooled = {
            (policy, arm): aggregate(
                [r for r in rows if r["policy"] == policy and r["arm"] == arm and keep(r)]
            )
            for policy in POLICIES
            for arm in ARMS
        }
        for key, label in keys:
            cells = [str(pooled[(policy, arm)][key]) for policy in POLICIES for arm in ARMS]
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        for reason in pooled[(POLICIES[0], "on")]["unfreezes"]:
            cells = [
                str(pooled[(policy, arm)]["unfreezes"].get(reason, 0))
                for policy in POLICIES
                for arm in ARMS
            ]
            lines.append(f"| unfreeze: {reason} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += ["### on - off per book (pooled over seeds)", ""]
    lines.append(
        "| book | policy | on-time pp | completed | true Q pp | WT min | second transports |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    books = sorted({row["book"] for row in rows})
    for book in books:
        for policy in POLICIES:
            off = aggregate(
                [
                    r
                    for r in rows
                    if r["book"] == book and r["policy"] == policy and r["arm"] == "off"
                ]
            )
            on = aggregate(
                [
                    r
                    for r in rows
                    if r["book"] == book and r["policy"] == policy and r["arm"] == "on"
                ]
            )
            if not off["runs"] or not on["runs"]:
                continue

            def delta(key: str, on: dict[str, Any] = on, off: dict[str, Any] = off) -> str:
                if on[key] is None or off[key] is None:
                    return "n/a"
                return f"{on[key] - off[key]:+.2f}".rstrip("0").rstrip(".")

            lines.append(
                f"| {book} | {policy} | {delta('on_time_pct')} | {delta('completed')} | "
                f"{delta('q_true_pct')} | {delta('weighted_tardiness_min')} | "
                f"{off['second_transports']} -> {on['second_transports']} |"
            )
    lines.append("")
    lines += ["### runs where on is worse than off (same book, seed, policy)", ""]
    pairs: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        pairs.setdefault((row["book"], row["seed"], row["policy"]), {})[row["arm"]] = row
    for policy in POLICIES:
        both = [p for k, p in pairs.items() if k[2] == policy and len(p) == 2]
        worse_ot = sum(p["on"]["on_time"] < p["off"]["on_time"] for p in both)
        worse_q = sum((p["on"]["q_rate_pct"] or 0) < (p["off"]["q_rate_pct"] or 0) for p in both)
        worse_wt = sum(
            p["on"]["weighted_tardiness_min"] > p["off"]["weighted_tardiness_min"] for p in both
        )
        worse_done = sum(p["on"]["completed_routes"] < p["off"]["completed_routes"] for p in both)
        lines.append(
            f"- {policy}: {len(both)} pairs; on worse in on-time {worse_ot}, "
            f"true Q {worse_q}, weighted tardiness {worse_wt}, completed {worse_done}"
        )
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
