"""Study: pure rules vs heuristic vs propose-fork-simulate-select (+ H-MEM).

    python -m resilimes.smt.sim_select_study --arms rules,heuristic,sim,sim_hmem \\
        --out-dir study_sim_select

Arms (all on the same held-out seeds, same book, same horizon):

* ``rules``      rules only, no shift lead.
* ``heuristic``  the existing shift lead with the deterministic stand-in.
* ``sim``        fork the twin at escalated exceptions, engine plans only,
                 do-no-harm Pareto pick (no model).
* ``sim_hmem``   ``sim`` plus H-MEM shift memory (warm-started on the dev
                 seeds; lets the twin be skipped on repeated cases).
* ``sim_mock``   ``sim`` with the offline mock in both LLM lanes (pipeline
                 check only; the mock is NOT a model).
* ``sim_llm``    ``sim`` with Nemotron via Nightshift proposing and selecting
                 (needs ``RESILIMES_MODE=live`` and the Nightshift settings).
* ``sim_llm_hmem`` ``sim_llm`` plus H-MEM cases in both prompts.
* ``sim_search`` ``sim`` with the non-LLM lever-search sampler proposing
                 (same ``MAX_PLANS`` budget, fixed seed — ``RESILIMES_SEARCH_SEED``
                 overrides it) and the Pareto rule selecting. The same-budget
                 baseline for the LLM proposers: not a model, never in
                 ``LLM_ARMS``.

Memory arms warm-start from ``<out-dir>/memory_<arm>.json``, built once on
the dev seeds (``--warm-seeds``, default 1-3, same book without the
``heldout_`` prefix). Every held-out run loads that same file and does not
write back, so held-out runs are independent and order-free.

Resumable: each run is ``<out-dir>/<arm>/<book>_s<seed>.json`` and is skipped
if it exists. ``report`` writes ``<out-dir>/report.json`` and a markdown table.
Pre-registered: the arms, seeds, horizon, fork horizon and futures are set
before any run; nothing is tuned on held-out seeds.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ARMS = (
    "rules",
    "heuristic",
    "sim",
    "sim_hmem",
    "sim_mock",
    "sim_llm",
    "sim_llm_hmem",
    "sim_search",
)
LLM_ARMS = ("sim_mock", "sim_llm", "sim_llm_hmem")
MEMORY_ARMS = ("sim_hmem", "sim_llm_hmem")
HEADLINE = (
    "weighted_tardiness_min",
    "on_time_pct",
    "qtime_violations",
    "q_late",
    "q_expired",
    "mean_x_factor",
    "qtime_avoidable",
    "hot_late",
)
BALANCE = ("queue_var_mean", "queue_cv_families", "wip_quintile_mean")
LEAD = (
    "exceptions",
    "escalated",
    "rule_handled",
    "gate_checks",
    "gate_forks",
    "gate_wall_s",
    "gate_ms_p50",
    "gate_ms_p95",
    "twin_forks",
    "twin_skips",
    "twin_wall_s",
    "llm_calls",
    "llm_ms_p50",
    "llm_ms_p95",
    "fallbacks",
    "chosen_llm_plan",
    "llm_plans",
    "llm_plans_invalid",
    "non_nemotron_replies",
)


def _say(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def _search_seed() -> int:
    from resilimes.llm.search import DEFAULT_SEED

    raw = os.environ.get("RESILIMES_SEARCH_SEED", "").strip()
    try:
        return int(raw) if raw else DEFAULT_SEED
    except ValueError:
        return DEFAULT_SEED


def _completer(arm: str) -> Any:
    if arm == "sim_search":
        from resilimes.llm.search import SearchCompleter

        return SearchCompleter(seed=_search_seed())
    if arm == "sim_mock":
        from resilimes.llm.mock import MockProvider

        return MockProvider()
    if arm in ("sim_llm", "sim_llm_hmem"):
        from resilimes.config import load_settings
        from resilimes.llm.factory import build_provider

        settings = load_settings()
        if not settings.use_nightshift:
            raise RuntimeError("sim_llm arms need RESILIMES_MODE=live and the Nightshift .env")
        return build_provider(settings)
    return None


def _selector(arm: str, completer: Any) -> str:
    """Who picks among the twin-scored plans. ``sim_search`` proposes by
    sampling and must be judged by the Pareto rule — letting it use the
    ``llm`` selector would ask the sampler to pick its own samples (it
    refuses; see ``resilimes.llm.search``)."""
    if arm == "sim_search":
        return "pareto"
    return "llm" if completer is not None else "pareto"


def run_one(
    arm: str,
    book: str,
    seed: int,
    args: argparse.Namespace,
    memory_path: Path | None = None,
    save_memory: Path | None = None,
) -> dict[str, Any]:
    from resilimes.agents.shift_lead import ShiftLead, build_decider
    from resilimes.smt.fab import load_fab
    from resilimes.smt.qtime_study import _setup, balance_kpis, replay
    from resilimes.smt.simulate import make_sim

    fab = load_fab()
    plant, kwargs = _setup(fab, book, seed, "resilimes")
    lead: Any = None
    twin: Any = None
    memory: Any = None
    if arm == "heuristic":
        lead = ShiftLead(build_decider("heuristic", lang="en"))
    elif arm != "rules":
        from resilimes.agents.sim_select import SimShiftLead
        from resilimes.engines.hmem import ShiftMemory
        from resilimes.smt.twin import Twin, TwinConfig

        twin = Twin(
            plant,
            TwinConfig(
                horizon_sec=args.fork_h * 3600.0, futures=args.futures, workers=args.workers
            ),
        )
        if arm in MEMORY_ARMS:
            memory = (
                ShiftMemory.load(memory_path, scope=f"{book}:s{seed}")
                if memory_path is not None
                else ShiftMemory(scope=f"{book}:s{seed}")
            )
        completer = _completer(arm)
        lead = SimShiftLead(
            twin,
            completer=completer,
            selector=_selector(arm, completer),
            memory=memory,
            timeout_s=args.llm_timeout,
            budget=args.budget,
            max_plans=getattr(args, "max_plans", 4),
        )
    started = time.perf_counter()
    last = [started]

    def progress(t: float) -> None:
        if time.perf_counter() - last[0] >= args.progress_s:
            last[0] = time.perf_counter()
            extra = ""
            if lead is not None and hasattr(lead, "escalations"):
                extra = (
                    f" escalated={lead.escalations} rule_handled={lead.rule_handled}"
                    f" llm_calls={lead.llm_calls}"
                )
            _say(f"  {arm} {book} s{seed}: sim {t / 3600:.1f} h{extra}")

    try:
        sim = make_sim(plant, shift_lead=lead, progress=progress, **kwargs)
        result = sim.run()
    finally:
        if twin is not None:
            twin.close()
    row: dict[str, Any] = {"arm": arm, "book": book, "seed": seed}
    row["wall_s"] = round(time.perf_counter() - started, 1)
    row["config"] = {
        "horizon_h": kwargs["horizon"] / 3600.0,
        "fork_h": args.fork_h,
        "futures": args.futures,
        "llm_timeout_s": args.llm_timeout,
        "budget": args.budget,
        "escalation_mode": getattr(lead, "escalation", None),
        "provider": getattr(getattr(lead, "completer", None), "name", None),
        "mocked": getattr(getattr(lead, "completer", None), "mocked", None),
        "selector": getattr(lead, "selector", None),
        "search_seed": getattr(getattr(lead, "completer", None), "seed", None),
    }
    for key in (*HEADLINE, "on_time", "due_in_horizon", "completed_routes"):
        if hasattr(result, key):
            row[key] = getattr(result, key)
    row.update(
        {k: v for k, v in replay(plant, result.events, kwargs["horizon"]).items() if k in HEADLINE}
    )
    row["qtime_miss_class"] = dict(getattr(result, "qtime_miss_class", None) or {})
    row["qtime_avoidable"] = int(row["qtime_miss_class"].get("avoidable", 0))
    row["hot_late"], row["hot_due"] = hot_late(sim, kwargs["horizon"])
    kpi = balance_kpis(plant, result.events, kwargs["horizon"], kwargs["downs"], kwargs["pm"])
    row["balance"] = {k: v for k, v in kpi.items() if isinstance(v, int | float)}
    if lead is not None:
        row["shift_lead"] = lead.summary()
        row["decisions"] = lead.log
    if memory is not None:
        row["memory"] = memory.stats()
        row["playbook_proposals"] = memory.propose_playbook()
        if save_memory is not None:
            memory.save(save_memory)
    return row


def hot_late(sim: Any, horizon: float) -> tuple[int, int]:
    """(late, due): hot/VIP lots (tier < 2) due inside (0, horizon] and
    whether they finished by their due (the twin's ``hot_late``, whole run)."""
    late = due_n = 0
    for lot in range(sim.n):
        due = sim.due[lot]
        if sim.tier(lot) >= 2 or not 0.0 < due <= horizon:
            continue
        due_n += 1
        done = sim.finished_at[lot]
        if not 0.0 <= done <= due:
            late += 1
    return late, due_n


def _write(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(row, default=str, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def warm_memory(arm: str, args: argparse.Namespace, book: str | None = None) -> Path | None:
    """Build the memory file once on the dev seeds (sequential, resumable).

    The stress book has no dev seeds: pre-registered, its memory arms start
    every run with empty memory (``None``) and learn within the run.
    """
    from resilimes.smt import stress_book

    book = book or args.book
    if stress_book.is_stress(book):
        return None
    out = Path(args.out_dir)
    mem_path = out / f"memory_{arm}.json"
    dev_book = book.removeprefix("heldout_")
    for seed in args.warm_seeds:
        done = out / arm / "warm" / f"{dev_book}_s{seed}.json"
        if done.exists():
            continue
        _say(f"warm {arm} on dev {dev_book} s{seed}")
        load = mem_path if mem_path.exists() else None
        row = run_one(arm, dev_book, seed, args, memory_path=load, save_memory=mem_path)
        _write(done, row)
    return mem_path


def pairs(args: argparse.Namespace) -> list[tuple[str, int]]:
    """(book, seed) runs of one arm. ``--book stress``: the pre-registered
    order (seed-major, then S1..S5), cut to the first ``--first`` pairs."""
    from resilimes.smt import stress_book

    if args.book in stress_book.BOOKS:
        out = stress_book.ordered_pairs(args.seeds, args.book)
    else:
        out = [(args.book, seed) for seed in args.seeds]
    return out[: args.first] if args.first else out


def run_arms(args: argparse.Namespace) -> None:
    out = Path(args.out_dir)
    plan = [(arm, book, seed) for arm in args.arms for book, seed in pairs(args)]
    _say(f"{len(plan)} runs: arms={','.join(args.arms)} seeds={args.seeds} book={args.book}")
    for index, (arm, book, seed) in enumerate(plan, 1):
        path = out / arm / f"{book}_s{seed}.json"
        if path.exists():
            _say(f"[{index}/{len(plan)}] {arm} {book} s{seed}: done, skipped")
            continue
        mem = warm_memory(arm, args, book) if arm in MEMORY_ARMS else None
        _say(f"[{index}/{len(plan)}] {arm} {book} s{seed}: start")
        row = run_one(arm, book, seed, args, memory_path=mem)
        _write(path, row)
        lead = row.get("shift_lead", {})
        _say(
            f"[{index}/{len(plan)}] {arm} {book} s{seed}: wt={row.get('weighted_tardiness_min')} "
            f"qviol={row.get('qtime_violations')} avoid={row.get('qtime_avoidable')} "
            f"hot_late={row.get('hot_late')} on_time={row.get('on_time_pct')} "
            f"exceptions={lead.get('exceptions')} escalated={lead.get('escalated')} "
            f"rule_handled={lead.get('rule_handled')} gate_wall={lead.get('gate_wall_s')} s "
            f"llm_calls={lead.get('llm_calls')} wall={row['wall_s']} s"
        )
    report(args)


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def report(args: argparse.Namespace) -> dict[str, Any]:
    if args.book in ("stress", "stress2"):
        return stress_report(args)
    return report_book(args, args.book)


def report_book(args: argparse.Namespace, book: str, name: str = "report") -> dict[str, Any]:
    out = Path(args.out_dir)
    rows: dict[str, dict[int, dict[str, Any]]] = {}
    for arm in ARMS:
        for path in sorted((out / arm).glob(f"{book}_s*.json")):
            row = json.loads(path.read_text("utf-8"))
            rows.setdefault(arm, {})[int(row["seed"])] = row
    arms: dict[str, Any] = {}
    base = rows.get("rules", {})
    for arm, by_seed in rows.items():
        seeds = sorted(by_seed)
        entry: dict[str, Any] = {"seeds": seeds}
        for key in HEADLINE:
            vals = [float(by_seed[s][key]) for s in seeds if by_seed[s].get(key) is not None]
            entry[key] = _mean(vals)
            paired = [
                float(by_seed[s][key]) - float(base[s][key])
                for s in seeds
                if s in base and by_seed[s].get(key) is not None and base[s].get(key) is not None
            ]
            entry[f"d_{key}_vs_rules"] = _mean(paired)
            if key == "weighted_tardiness_min" and paired:
                entry["wt_wins_ties_losses"] = [
                    sum(1 for d in paired if d < -0.5),
                    sum(1 for d in paired if abs(d) <= 0.5),
                    sum(1 for d in paired if d > 0.5),
                ]
        for key in BALANCE:
            vals = [
                float(by_seed[s]["balance"][key])
                for s in seeds
                if key in by_seed[s].get("balance", {})
            ]
            entry[key] = _mean(vals)
        for key in LEAD:
            vals = [
                float(by_seed[s]["shift_lead"][key])
                for s in seeds
                if isinstance(by_seed[s].get("shift_lead", {}).get(key), int | float)
            ]
            if vals:
                pooled = key.startswith(("llm_ms", "gate_ms"))
                entry[key] = _mean(vals) if pooled else round(sum(vals), 1)
        entry["wall_s"] = round(sum(float(by_seed[s]["wall_s"]) for s in seeds), 1)
        causes: dict[str, int] = {}
        for s in seeds:
            for d in by_seed[s].get("decisions", []):
                cause = d.get("fallback_cause")
                if d.get("escalated") and cause:
                    causes[cause] = causes.get(cause, 0) + 1
        if causes:
            entry["fallback_causes"] = causes
        reasons: dict[str, int] = {}
        for s in seeds:
            for d in by_seed[s].get("decisions", []):
                why = d.get("escalation_reason")
                if why:
                    reasons[why] = reasons.get(why, 0) + 1
        if reasons:
            entry["escalation_reasons"] = reasons
        arms[arm] = entry
    result = {"book": book, "arms": arms}
    (out / f"{name}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (out / f"{name}.md").write_text(table(result), encoding="utf-8")
    print(table(result), flush=True)
    return result


def lexi_key(row: dict[str, Any]) -> tuple[float, float, float]:
    """Pre-registered metric: avoidable Q-time, then hot late, then wt."""
    return (
        float(row.get("qtime_avoidable") or 0),
        float(row.get("hot_late") or 0),
        float(row.get("weighted_tardiness_min") or 0.0),
    )


def lexi_cmp(row: dict[str, Any], base: dict[str, Any], band: float = 0.5) -> int:
    """-1 win, 0 tie, +1 loss of ``row`` against ``base``."""
    a, b = lexi_key(row), lexi_key(base)
    for x, y in zip(a[:2], b[:2], strict=True):
        if x != y:
            return -1 if x < y else 1
    if abs(a[2] - b[2]) <= band:
        return 0
    return -1 if a[2] < b[2] else 1


def stress_report(args: argparse.Namespace) -> dict[str, Any]:
    """Per (scenario, seed) rows of every arm, lexicographic W/T/L vs rules and
    vs sim, and per-book reports (``report_<book>.md``)."""
    out = Path(args.out_dir)
    order = pairs(args)
    rows: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    for arm in ARMS:
        for book, seed in order:
            path = out / arm / f"{book}_s{seed}.json"
            if path.exists():
                rows.setdefault(arm, {})[(book, seed)] = json.loads(path.read_text("utf-8"))
    table_rows = []
    for book, seed in order:
        for arm, by_pair in rows.items():
            row = by_pair.get((book, seed))
            if row is None:
                continue
            lead = row.get("shift_lead", {})
            table_rows.append(
                {
                    "book": book,
                    "seed": seed,
                    "arm": arm,
                    "escalated": lead.get("escalated"),
                    "exceptions": lead.get("exceptions"),
                    "qtime_avoidable": row.get("qtime_avoidable"),
                    "qtime_violations": row.get("qtime_violations"),
                    "hot_late": row.get("hot_late"),
                    "hot_due": row.get("hot_due"),
                    "weighted_tardiness_min": row.get("weighted_tardiness_min"),
                    "gate_wall_s": lead.get("gate_wall_s"),
                    "llm_calls": lead.get("llm_calls"),
                    "fallbacks": lead.get("fallbacks"),
                    "wall_s": row.get("wall_s"),
                }
            )
    summary: dict[str, Any] = {}
    for arm, by_pair in rows.items():
        entry: dict[str, Any] = {"pairs": len(by_pair)}
        for key in ("qtime_avoidable", "hot_late", "weighted_tardiness_min"):
            entry[key] = round(sum(float(r.get(key) or 0) for r in by_pair.values()), 1)
        entry["escalated"] = sum(
            int(r.get("shift_lead", {}).get("escalated") or 0) for r in by_pair.values()
        )
        for ref in ("rules", "sim"):
            if ref == arm or ref not in rows:
                continue
            common = [p for p in by_pair if p in rows[ref]]
            res = [lexi_cmp(by_pair[p], rows[ref][p]) for p in common]
            entry[f"wtl_vs_{ref}"] = [res.count(-1), res.count(0), res.count(1)]
            entry[f"more_avoidable_than_{ref}"] = sum(
                1
                for p in common
                if (by_pair[p].get("qtime_avoidable") or 0)
                > (rows[ref][p].get("qtime_avoidable") or 0)
            )
        summary[arm] = entry
    books = sorted({b for b, _ in order}, key=[b for b, _ in order].index)
    for book in books:
        report_book(args, book, name=f"report_{book}")
    result = {"book": args.book, "order": order, "rows": table_rows, "summary": summary}
    (out / "report.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (out / "report.md").write_text(stress_table(result), encoding="utf-8")
    print(stress_table(result), flush=True)
    return result


def stress_table(result: dict[str, Any]) -> str:
    cols = (
        "escalated",
        "exceptions",
        "qtime_avoidable",
        "qtime_violations",
        "hot_late",
        "hot_due",
        "weighted_tardiness_min",
        "gate_wall_s",
        "llm_calls",
        "fallbacks",
        "wall_s",
    )
    lines = [
        f"{result['book']} book (pre-registered, docs/AI_SHIFT_LEAD_STRESS.md)",
        "",
        "| scenario | seed | arm | " + " | ".join(cols) + " |",
        "|---|---|---|" + "---|" * len(cols),
    ]
    for r in result["rows"]:
        cells = [str(r.get(k, "")) for k in cols]
        lines.append(f"| {r['book']} | {r['seed']} | {r['arm']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "lexicographic (avoidable Q-time, hot late, wt ±0.5 min): W/T/L",
        "",
        "| arm | pairs | escalated | avoidable | hot late | wt min | vs rules | vs sim |"
        " more avoidable than rules |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, e in result["summary"].items():
        lines.append(
            f"| {arm} | {e['pairs']} | {e['escalated']} | {e['qtime_avoidable']} | "
            f"{e['hot_late']} | {e['weighted_tardiness_min']} | {e.get('wtl_vs_rules', '')} | "
            f"{e.get('wtl_vs_sim', '')} | {e.get('more_avoidable_than_rules', '')} |"
        )
    return "\n".join(lines) + "\n"


def table(result: dict[str, Any]) -> str:
    cols = (
        ("weighted_tardiness_min", "wt min"),
        ("d_weighted_tardiness_min_vs_rules", "Δwt vs rules"),
        ("wt_wins_ties_losses", "W/T/L"),
        ("on_time_pct", "on-time %"),
        ("qtime_violations", "Q-viol"),
        ("d_qtime_violations_vs_rules", "ΔQ vs rules"),
        ("qtime_avoidable", "Q-avoid"),
        ("hot_late", "hot late"),
        ("queue_cv_families", "queue CV"),
        ("exceptions", "exceptions"),
        ("escalated", "escalated"),
        ("rule_handled", "rule-handled"),
        ("gate_wall_s", "gate s"),
        ("llm_calls", "LLM calls"),
        ("llm_ms_p50", "LLM p50 ms"),
        ("fallbacks", "fallbacks"),
        ("non_nemotron_replies", "non-Nemotron"),
        ("wall_s", "wall s"),
    )
    lines = [
        f"book {result['book']} (means over seeds; Δ paired vs rules)",
        "",
        "| arm | seeds | " + " | ".join(c[1] for c in cols) + " |",
        "|---|---|" + "---|" * len(cols),
    ]
    for arm, e in result["arms"].items():
        cells = [str(e.get(k, "")) for k, _ in cols]
        lines.append(f"| {arm} | {len(e['seeds'])} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    from resilimes.smt.qtime_study import HELDOUT_SEEDS

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", nargs="?", default="run", choices=("run", "report"))
    p.add_argument("--arms", default="rules,heuristic,sim,sim_hmem")
    p.add_argument(
        "--book",
        default="heldout_published",
        help="study book; 'stress' / 'stress2' = the pre-registered stress books",
    )
    p.add_argument(
        "--seeds", default=None, help="default: 9-13 (stress: the pre-registered 9,10,11)"
    )
    p.add_argument(
        "--first",
        type=int,
        default=0,
        help="stress: run only the first N (scenario, seed) pairs of the fixed order",
    )
    p.add_argument("--warm-seeds", default="1,2,3")
    p.add_argument("--horizon-h", type=float, default=24.0)
    p.add_argument("--fork-h", type=float, default=8.0)
    p.add_argument("--futures", type=int, default=3)
    p.add_argument("--workers", type=int, default=3, help="twin fork processes")
    p.add_argument("--llm-timeout", type=float, default=1200.0, help="per LLM call, s")
    p.add_argument("--budget", type=int, default=None, help="max escalations (default: no cap)")
    p.add_argument(
        "--max-plans",
        type=int,
        default=4,
        help="proposer plan budget per escalation (default: 4, the shipped MAX_PLANS)",
    )
    p.add_argument("--progress-s", type=float, default=30.0)
    p.add_argument("--out-dir", default="study_sim_select")
    args = p.parse_args(argv)
    args.arms = [a for a in args.arms.split(",") if a]
    for arm in args.arms:
        if arm not in ARMS:
            p.error(f"unknown arm {arm!r}; choose from {', '.join(ARMS)}")
    if args.seeds is None:
        from resilimes.smt.stress_book import STRESS_SEEDS

        stress = args.book in ("stress", "stress2")
        args.seeds = ",".join(map(str, STRESS_SEEDS if stress else HELDOUT_SEEDS))
    args.seeds = [int(s) for s in str(args.seeds).split(",") if s]
    args.warm_seeds = [int(s) for s in str(args.warm_seeds).split(",") if s]
    # The horizon is read from the env by qtime_study._setup.
    os.environ["RESILIMES_STUDY_HORIZON_H"] = f"{args.horizon_h:g}"
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    if args.command == "report":
        report(args)
    else:
        run_arms(args)


if __name__ == "__main__":  # spawn-safe: nothing runs on import
    main(sys.argv[1:])
