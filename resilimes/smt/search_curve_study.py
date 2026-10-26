"""K curve of the non-AI lever search (arm ``sim_search``), plus arm D.

    python -m resilimes.smt.search_curve_study [--out-dir study_search_curve]

For K in 1, 3, 5, 10, 15 (the curve) and K = 50 (arm D, the large-budget
extrapolation point), the ``sim_search`` arm runs on the normal
held-out book with three sampler seeds, and the per-run rows are
aggregated into ``k_curve.json`` / ``k_curve.md``: avoidable Q-time
violations, hot-late, completed routes, and simulation calls (gate
forks + twin forks, the twin's own counter). Pure simulation — no LLM
is involved in any run of this study.

Escalation defaults to the legacy ``always`` filter for this study
only: under the shipped gate a normal book may never escalate (see the
zero-call table), which would starve the K measurement entirely. The
gate itself is not changed; ``--escalation exception`` measures under
the shipped gate instead.

Runs are resumable: one JSON per (K, search seed, book seed) under
``<out-dir>/runs/``; finished runs are skipped. Twin forks default to
serial (workers=0) — process pools were killed on the shared dev box.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KS = (1, 3, 5, 10, 15)
# D arm: the same lever space with a much larger candidate budget — the
# curve's extrapolation point. It answers "does the AI reach the same
# effect with fewer simulations?" by pricing the non-AI effect at K=50.
D_KS = (50,)
SEARCH_SEEDS = (101, 202, 303)
BOOK = "heldout_published"
BOOK_SEED = 9
METRICS = (
    "qtime_avoidable",
    "hot_late",
    "weighted_tardiness_min",
    "completed_routes",
    "sim_calls",
    "propose_calls",
    "escalated",
)


def _say(message: str) -> None:
    print(message, flush=True)


def _manifest() -> dict[str, Any]:
    return {
        "environment": f"{platform.platform()} / python {platform.python_version()}",
        "ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "note": "",
    }


def run_one(book: str, book_seed: int, search_seed: int, k: int, args: argparse.Namespace) -> dict:
    from resilimes.smt import sim_select_study

    previous = os.environ.get("RESILIMES_SEARCH_SEED")
    os.environ["RESILIMES_SEARCH_SEED"] = str(search_seed)
    previous_mode = os.environ.get("SHIFT_LEAD_ESCALATE")
    os.environ["SHIFT_LEAD_ESCALATE"] = args.escalation
    study_args = argparse.Namespace(
        fork_h=args.fork_h,
        futures=args.futures,
        workers=args.workers,
        llm_timeout=30.0,
        budget=None,
        progress_s=3600.0,
        max_plans=k,
    )
    try:
        row = sim_select_study.run_one("sim_search", book, book_seed, study_args)
    finally:
        if previous is None:
            os.environ.pop("RESILIMES_SEARCH_SEED", None)
        else:
            os.environ["RESILIMES_SEARCH_SEED"] = previous
        if previous_mode is None:
            os.environ.pop("SHIFT_LEAD_ESCALATE", None)
        else:
            os.environ["SHIFT_LEAD_ESCALATE"] = previous_mode
    lead = row.get("shift_lead") or {}
    return {
        "k": k,
        "search_seed": search_seed,
        "book_seed": book_seed,
        "book": book,
        "config": row.get("config"),
        "wall_s": row.get("wall_s"),
        "qtime_avoidable": row.get("qtime_avoidable"),
        "hot_late": row.get("hot_late"),
        "weighted_tardiness_min": row.get("weighted_tardiness_min"),
        "completed_routes": row.get("completed_routes"),
        "escalated": lead.get("escalated"),
        "propose_calls": lead.get("llm_calls"),
        "sim_calls": (lead.get("gate_forks") or 0) + (lead.get("twin_forks") or 0),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-K mean/min/max of every metric over the runs that are in."""
    out: dict[str, Any] = {}
    for k in sorted({int(row["k"]) for row in rows}):
        group = [row for row in rows if int(row["k"]) == k]
        entry: dict[str, Any] = {"runs": len(group)}
        for key in METRICS:
            values = [float(row[key]) for row in group if row.get(key) is not None]
            if values:
                entry[key] = {
                    "mean": round(statistics.fmean(values), 3),
                    "min": round(min(values), 3),
                    "max": round(max(values), 3),
                }
        out[str(k)] = entry
    return out


def table(result: dict[str, Any]) -> str:
    cfg, man = result["config"], result["manifest"]
    lines = [
        "# K curve — lever search (sim_search arm, non-LLM, seeded)",
        "",
        f"- 运行环境 (environment): {man['environment']}",
        f"- 运行时间 (ran_at): {man['ran_at']}",
        f"- 代码版本 (git_commit): {man['git_commit']}",
        f"- 注记 (note): {man['note']}",
        f"- book {cfg['book']}, book seeds {cfg['book_seeds']}, search seeds "
        f"{cfg['search_seeds']}, horizon {cfg['horizon_h']} h, fork {cfg['fork_h']} h, "
        f"futures {cfg['futures']}, escalation {cfg['escalation']} "
        "(always = legacy kind filter, experiment only; the shipped gate is exception)",
        f"- runs in: {result['runs_done']}/{result['runs_planned']} "
        "(means over search seeds x book seeds; min-max in brackets)",
        "",
        "| K | runs | avoidable Q-time (mean) | hot late (mean) | completed (mean) "
        "| wt min (mean) | sim calls (mean) | propose calls (mean) | escalated (mean) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def cell(entry: dict[str, Any], key: str) -> str:
        stat = entry.get(key)
        if not stat:
            return "-"
        return f"{stat['mean']} [{stat['min']}-{stat['max']}]"

    for k, entry in result["by_k"].items():
        label = f"{k} (D)" if int(k) in cfg.get("d_ks", []) else f"{k}"
        lines.append(
            f"| {label} | {entry['runs']} | {cell(entry, 'qtime_avoidable')} | "
            f"{cell(entry, 'hot_late')} | {cell(entry, 'completed_routes')} | "
            f"{cell(entry, 'weighted_tardiness_min')} | {cell(entry, 'sim_calls')} | "
            f"{cell(entry, 'propose_calls')} | {cell(entry, 'escalated')} |"
        )
    lines += [
        "",
        "sim calls = gate forks + twin forks (the twin's fork counter). "
        "propose calls = escalations that asked the sampler for plans. "
        "Pure simulation: no LLM is involved in any run of this curve.",
        "",
        "D arm: rows marked (D) are the same lever-space search at a much "
        "larger candidate budget (the extrapolation point). To answer "
        "'does the AI reach the same effect with fewer simulations?', "
        "compare the sim calls of the row whose avoidable / hot-late "
        "matches the C arm's (see the stress live report, same "
        "lexicographic metrics) against the C arm's own fork counts.",
        "",
    ]
    return "\n".join(lines)


def _planned(args: argparse.Namespace) -> list[tuple[int, int, int]]:
    ks = [*args.ks, *getattr(args, "d_ks", [])]
    return [
        (k, search_seed, book_seed)
        for k in ks
        for search_seed in args.search_seeds
        for book_seed in args.book_seeds
    ]


def write_report(
    args: argparse.Namespace, manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    out = Path(args.out_dir)
    rows = []
    for path in sorted((out / "runs").glob("k*_ss*_s*.json")):
        rows.append(json.loads(path.read_text("utf-8")))
    result = {
        "manifest": manifest or _manifest(),
        "config": {
            "book": args.book,
            "book_seeds": args.book_seeds,
            "search_seeds": args.search_seeds,
            "ks": args.ks,
            "d_ks": getattr(args, "d_ks", []),
            "horizon_h": args.horizon_h,
            "fork_h": args.fork_h,
            "futures": args.futures,
            "escalation": args.escalation,
        },
        "runs_planned": len(_planned(args)),
        "runs_done": len(rows),
        "by_k": aggregate(rows),
        "rows": rows,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "k_curve.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (out / "k_curve.md").write_text(table(result), encoding="utf-8")
    return result


def run_curve(args: argparse.Namespace) -> None:
    out = Path(args.out_dir)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    for k, search_seed, book_seed in _planned(args):
        target = out / "runs" / f"k{k}_ss{search_seed}_s{book_seed}.json"
        if target.exists():
            _say(f"[skip] K={k} search_seed={search_seed} book_seed={book_seed}")
            continue
        _say(f"[run] K={k} search_seed={search_seed} book_seed={book_seed} ...")
        row = run_one(args.book, book_seed, search_seed, k, args)
        target.write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding="utf-8")
        _say(
            f"[done] avoidable={row['qtime_avoidable']} sim_calls={row['sim_calls']} "
            f"wall={row['wall_s']}s"
        )
    result = write_report(args)
    _say(f"runs {result['runs_done']}/{result['runs_planned']} -> {out}/k_curve.md")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--book", default=BOOK)
    p.add_argument("--book-seeds", default=str(BOOK_SEED))
    p.add_argument("--search-seeds", default=",".join(str(s) for s in SEARCH_SEEDS))
    p.add_argument("--ks", default=",".join(str(k) for k in KS))
    p.add_argument("--horizon-h", type=float, default=5.0)
    p.add_argument("--escalation", default="always", choices=("always", "exception"))
    p.add_argument("--fork-h", type=float, default=1.0)
    p.add_argument("--futures", type=int, default=2)
    p.add_argument(
        "--workers",
        type=int,
        default=0,
        help="twin fork processes; 0 (default) = serial in-process, the "
        "Twin's own default — process pools were killed on the shared "
        "dev box (BrokenProcessPool under memory/tmp pressure); raise "
        "it on a dedicated machine",
    )
    p.add_argument("--out-dir", default="study_search_curve")
    p.add_argument(
        "--d-ks",
        default="50",
        help="D-arm budgets (large-budget extrapolation points), comma separated",
    )
    args = p.parse_args(argv)
    args.book_seeds = [int(s) for s in str(args.book_seeds).split(",") if s]
    args.search_seeds = [int(s) for s in str(args.search_seeds).split(",") if s]
    args.ks = [int(s) for s in str(args.ks).split(",") if s]
    args.d_ks = [int(s) for s in str(args.d_ks).split(",") if s]
    # The horizon is read from the env by qtime_study._setup.
    os.environ["RESILIMES_STUDY_HORIZON_H"] = f"{args.horizon_h:g}"
    return args


def main(argv: list[str] | None = None) -> int:
    run_curve(parse(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
