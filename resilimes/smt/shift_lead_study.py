"""Study: rules only vs rules plus a shift lead at exceptions.

    python -m resilimes.smt.qtime_study shift_lead --provider heuristic \\
        --out study_shift_lead.json

``--provider heuristic`` (default) is the deterministic stand-in that picks
the lowest projected impact. It is NOT an LLM. ``mock`` goes through the LLM
path with the offline mock provider; ``nightshift`` calls the live provider
and needs ``RESILIMES_MODE=live`` plus the Nightshift settings in ``.env``
(run it on a machine that has them; use ``--books published --seeds 1``
and ``--budget`` to keep the call count small).

Books ``published``, ``litho``, ``hot`` (plus ``pm_enforced``, the only
book whose PM calendar falls inside a 2-day horizon, so PM conflicts occur),
seeds 1-3, 2-day horizon (``RESILIMES_STUDY_HORIZON_H``, default 48), at most
2 worker processes (``--workers``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import get_context
from typing import Any

BOOKS = ("published", "litho", "hot", "pm_enforced")
SEEDS = (1, 2, 3)
MAX_WORKERS = 2
KPIS = (
    "on_time_pct",
    "on_time",
    "due_in_horizon",
    "completed_routes",
    "weighted_tardiness_min",
    "mean_x_factor",
    "qtime_violations",
    "q_rate_pct",
    "q_late",
    "q_expired",
    "batch_starts",
    "recleans",
    "reworks",
)
BALANCE = ("queue_var_mean", "queue_cv_families", "wip_quintile_mean")
BALANCE_PREFIX = ("util_", "starve_h_")

_ARGS: dict[str, Any] = {}


def _run(item: tuple[str, int, str]) -> dict[str, Any]:
    from resilimes.agents.shift_lead import ShiftLead, build_decider
    from resilimes.smt.fab import load_fab
    from resilimes.smt.qtime_study import _setup, balance_kpis, replay
    from resilimes.smt.simulate import run_policy

    book, seed, arm = item
    fab = load_fab()
    plant, kwargs = _setup(fab, book, seed, "resilimes")
    lead = None
    if arm != "rules":
        decider = build_decider(arm, lang=_ARGS["lang"], timeout_s=_ARGS["timeout"])
        lead = ShiftLead(decider, budget=_ARGS["budget"])
    started = time.perf_counter()
    result = run_policy(plant, shift_lead=lead, **kwargs)
    row: dict[str, Any] = {"book": book, "seed": seed, "arm": arm}
    row["wall_s"] = round(time.perf_counter() - started, 1)
    for key in KPIS:
        if hasattr(result, key):
            row[key] = getattr(result, key)
    row["on_time"] = round(result.on_time_pct * result.due_in_horizon / 100.0)
    replayed = replay(plant, result.events, kwargs["horizon"])
    for key in KPIS:
        if key in replayed:
            row[key] = replayed[key]
    if os.environ.get("RESILIMES_STUDY_KPI", "1") == "1":
        kpi = balance_kpis(plant, result.events, kwargs["horizon"], kwargs["downs"], kwargs["pm"])
        row["balance"] = {
            key: value for key, value in kpi.items() if isinstance(value, int | float)
        }
    if lead is not None:
        row["shift_lead"] = lead.summary()
        row["decisions"] = lead.log
    return row


def _delta(a: Any, b: Any) -> float | None:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return round(float(b) - float(a), 3)
    return None


def compare(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    """Per (book, seed): exceptions, overrides and KPI deltas (arm - rules)."""
    base = {(r["book"], r["seed"]): r for r in rows if r["arm"] == "rules"}
    pairs: list[dict[str, Any]] = []
    totals: dict[str, Any] = {"exceptions": {}, "differs": {}, "fallbacks": 0, "delta": {}}
    for row in rows:
        if row["arm"] != arm or (row["book"], row["seed"]) not in base:
            continue
        ref = base[(row["book"], row["seed"])]
        summary = row["shift_lead"]
        delta = {key: _delta(ref.get(key), row.get(key)) for key in KPIS if key in row}
        for key, value in (ref.get("balance") or {}).items():
            other = (row.get("balance") or {}).get(key)
            if key in BALANCE or key.startswith(BALANCE_PREFIX):
                delta[f"balance.{key}"] = _delta(value, other)
        pairs.append(
            {
                "book": row["book"],
                "seed": row["seed"],
                "exceptions": summary["by_type"],
                "differs": summary["differs_by_type"],
                "fallbacks": summary["fallbacks"],
                "rules": {key: ref.get(key) for key in KPIS},
                "arm": {key: row.get(key) for key in KPIS},
                "delta": delta,
            }
        )
        for kind, count in summary["by_type"].items():
            totals["exceptions"][kind] = totals["exceptions"].get(kind, 0) + count
            totals["differs"][kind] = (
                totals["differs"].get(kind, 0) + summary["differs_by_type"][kind]
            )
        totals["fallbacks"] += summary["fallbacks"]
        for key, value in delta.items():
            if value is not None:
                totals["delta"].setdefault(key, []).append(value)
    totals["delta_mean"] = {
        key: round(sum(values) / len(values), 3) for key, values in totals.pop("delta").items()
    }
    return {"arm": arm, "pairs": pairs, "totals": totals}


def table(report: dict[str, Any]) -> str:
    """Markdown summary of ``compare``."""
    keys = ("on_time_pct", "qtime_violations", "q_rate_pct", "completed_routes")
    lines = [
        "| book | seed | exceptions | differs | "
        + " | ".join(f"{key} rules -> arm" for key in keys)
        + " |",
        "|" + "---|" * (4 + len(keys)),
    ]
    for pair in report["pairs"]:
        cells = [
            f"{pair['rules'].get(key)} -> {pair['arm'].get(key)} ({pair['delta'].get(key):+g})"
            if pair["delta"].get(key) is not None
            else "-"
            for key in keys
        ]
        lines.append(
            f"| {pair['book']} | {pair['seed']} | {sum(pair['exceptions'].values())} | "
            f"{sum(pair['differs'].values())} | " + " | ".join(cells) + " |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qtime_study shift_lead")
    parser.add_argument(
        "--provider", default="heuristic", choices=("heuristic", "mock", "nightshift", "rules")
    )
    parser.add_argument("--out", default="study_shift_lead.json")
    parser.add_argument("--books", default=",".join(BOOKS))
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in SEEDS))
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--lang", default="zh", choices=("zh", "ja", "en"))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--budget", type=int, default=None, help="max decider calls per run")
    args = parser.parse_args(argv)
    os.environ.setdefault("RESILIMES_STUDY_HORIZON_H", "48")
    _ARGS.update(lang=args.lang, timeout=args.timeout, budget=args.budget)
    books = [book for book in args.books.split(",") if book]
    seeds = [int(seed) for seed in args.seeds.split(",") if seed]
    items = [(b, s, arm) for b in books for s in seeds for arm in ("rules", args.provider)]
    workers = max(1, min(MAX_WORKERS, args.workers))
    if args.provider == "nightshift":
        workers = 1
    with get_context("fork").Pool(workers, maxtasksperchild=4) as pool:
        rows = pool.map(_run, items, chunksize=1)
    report = compare(rows, args.provider)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(
            {"provider": args.provider, "report": report, "rows": rows},
            handle,
            indent=1,
            ensure_ascii=False,
        )
    print(table(report))
    print(json.dumps(report["totals"], indent=1, ensure_ascii=False))
    print(f"shift_lead/{args.provider}: {len(rows)} runs -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
