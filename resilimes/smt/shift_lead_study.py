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

Progress (on by default, ``--no-progress`` to turn off): a line on stderr,
rewritten in place on a terminal and printed every 10 s when redirected, and
``<out>.progress.json`` (``--progress-file``) rewritten every 2 s with status
running / done / failed; see ``resilimes.smt.progress``. With one worker
(always for ``nightshift``) it shows the simulated time and every AI call;
with a worker pool it counts finished runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import get_all_start_methods, get_context
from typing import Any

from resilimes.smt.progress import Progress, follow, progress_path

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
# The live tracker, set only for in-process runs (never inherited by a pool).
_LIVE: list[Progress] = []


def _run(item: tuple[str, int, str]) -> dict[str, Any]:
    from resilimes.agents.shift_lead import ShiftLead, build_decider
    from resilimes.smt.fab import load_fab
    from resilimes.smt.qtime_study import _setup, balance_kpis, replay
    from resilimes.smt.simulate import run_policy

    book, seed, arm = item
    fab = load_fab()
    plant, kwargs = _setup(fab, book, seed, "resilimes")
    live = _LIVE[0] if _LIVE else None
    lead = None
    if arm != "rules":
        decider = build_decider(arm, lang=_ARGS["lang"], timeout_s=_ARGS["timeout"])
        lead = ShiftLead(decider, budget=_ARGS["budget"], progress=live)
    if live is not None:
        live.begin_run(book, seed, arm, kwargs["horizon"])
    started = time.perf_counter()
    result = run_policy(
        plant,
        shift_lead=lead,
        progress=live.sim_time if live is not None else None,
        **kwargs,
    )
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
    if live is not None:
        live.end_run(arm, row["wall_s"])
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


def _init_args(values: dict[str, object]) -> None:
    _ARGS.update(values)


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
    parser.add_argument("--no-progress", action="store_true", help="no progress line or file")
    parser.add_argument(
        "--progress-file", default=None, help="default <out>.progress.json; '' for none"
    )
    parser.add_argument(
        "--progress-every", type=float, default=10.0, help="seconds between lines in a log"
    )
    args = parser.parse_args(argv)
    os.environ.setdefault("RESILIMES_STUDY_HORIZON_H", "48")
    _ARGS.update(lang=args.lang, timeout=args.timeout, budget=args.budget)
    books = [book for book in args.books.split(",") if book]
    seeds = [int(seed) for seed in args.seeds.split(",") if seed]
    items = [(b, s, arm) for b in books for s in seeds for arm in ("rules", args.provider)]
    workers = max(1, min(MAX_WORKERS, args.workers))
    if args.provider == "nightshift":
        workers = 1
    path = args.progress_file if args.progress_file is not None else progress_path(args.out)
    progress = Progress(
        study="shift_lead",
        plan=[arm for _book, _seed, arm in items],
        provider=args.provider,
        budget=args.budget,
        path=None if args.no_progress or not path else path,
        console=not args.no_progress,
        log_every=args.progress_every,
        # A thread keeps the line moving while a model call blocks; none
        # beside a pool, which may fork a fresh worker at any time.
        background=workers == 1,
    )
    if not args.no_progress:
        print(
            f"shift_lead/{args.provider}: {len(items)} runs, books {','.join(books)}, "
            f"seeds {','.join(str(seed) for seed in seeds)}, budget {args.budget}, "
            f"timeout {args.timeout:g} s, lang {args.lang}, workers {workers}, "
            f"horizon {os.environ['RESILIMES_STUDY_HORIZON_H']} h -> {args.out}"
            + (f"; progress file {path}" if path else ""),
            file=sys.stderr,
            flush=True,
        )
    if workers == 1:
        # In-process: no fork needed (Windows has none), and live calls stay sequential.
        with progress:
            if not args.no_progress:
                _LIVE.append(progress)
            try:
                rows = [_run(item) for item in items]
            finally:
                _LIVE.clear()
            _write(args, rows)
        return
    method = "fork" if "fork" in get_all_start_methods() else "spawn"
    with (
        get_context(method).Pool(
            workers, maxtasksperchild=4, initializer=_init_args, initargs=(dict(_ARGS),)
        ) as pool,
        progress,
    ):
        rows = list(follow(pool.imap(_run, items, chunksize=1), progress))
        _write(args, rows)


def _write(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    report = compare(rows, args.provider)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(
            {"provider": args.provider, "report": report, "rows": rows},
            handle,
            indent=1,
            ensure_ascii=False,
        )
    print(table(report), flush=True)
    print(json.dumps(report["totals"], indent=1, ensure_ascii=False), flush=True)
    print(
        f"shift_lead/{args.provider}: {len(rows)} runs -> {args.out}", file=sys.stderr, flush=True
    )


if __name__ == "__main__":
    main()
