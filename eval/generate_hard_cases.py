"""Generate the hard investigator case set: ``python eval/generate_hard_cases.py [--jobs N]``.

Runs the templates in :mod:`resilimes.insight.hard_cases` (combo / misleading /
ood), keeps only cases that pass the symptom, signal and (for misleading
cases) ablation checks, and writes ``eval/investigator_hard_cases.json``
incrementally as templates finish. Templates that produce no valid case are
reported, not silently dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path(__file__).resolve().parent / "investigator_hard_cases.json"

_FAB: Any = None
_BASES: dict[int, Any] = {}


def _init(seeds: list[int]) -> None:
    global _FAB, _BASES
    from resilimes.evidence.toolkit import HOUR, record_run
    from resilimes.insight.injector import HORIZON_H
    from resilimes.smt.fab import load_fab

    _FAB = load_fab()
    _BASES = {seed: record_run(_FAB, seed=seed, horizon=HORIZON_H * HOUR) for seed in seeds}


def _work(index: int) -> tuple[str, str, dict[str, Any] | None, list[str]]:
    from resilimes.insight.hard_cases import TEMPLATES, make_hard_case

    template = TEMPLATES[index]
    case, log = make_hard_case(_FAB, template, _BASES[template.seed])
    return template.name, template.category, (case.to_json() if case else None), log


def _write(out: Path, cases: list[dict[str, Any]]) -> None:
    from resilimes.insight.injector import HORIZON_H

    payload = {
        "horizon_h": HORIZON_H,
        "note": (
            "Hard investigator cases: combo (two injected causes), misleading (decoy "
            "indicator louder than the primary, ablation-verified) and ood (boundary "
            "stacks / out-of-range strengths). Ground truth is the injected fault set; "
            "see resilimes/insight/hard_cases.py."
        ),
        "cases": cases,
    }
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_hard_cases")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated template names to (re)generate; other cases "
        "already in --out are kept and merged",
    )
    args = parser.parse_args(argv)

    from resilimes.insight.hard_cases import TEMPLATES

    only = {name.strip() for name in args.only.split(",") if name.strip()}
    templates = [t for t in TEMPLATES if not only or t.name in only]
    seeds = sorted({t.seed for t in templates})
    indices = [TEMPLATES.index(t) for t in templates]
    kept: list[dict[str, Any]] = []
    if only and args.out.exists():
        existing = json.loads(args.out.read_text(encoding="utf-8"))["cases"]
        kept = [case for case in existing if case["case_id"] not in only]
    done: dict[str, tuple[str, dict[str, Any] | None, list[str]]] = {}

    def accept(result: tuple[str, str, dict[str, Any] | None, list[str]]) -> None:
        name, category, case, log = result
        done[name] = (category, case, log)
        for line in log:
            print(f"  {name}: {line}", flush=True)
        if case:
            kept.append(case)
            kept.sort(key=lambda c: c["case_id"])
            _write(args.out, kept)
            print(f"{name} [{category}] KEPT -> {case['family']} ({len(kept)} kept)", flush=True)
        else:
            print(f"{name} [{category}] REJECTED (no valid family)", flush=True)

    if args.jobs > 1:
        with ProcessPoolExecutor(
            max_workers=args.jobs, initializer=_init, initargs=(seeds,)
        ) as pool:
            futures = [pool.submit(_work, index) for index in indices]
            for future in as_completed(futures):
                accept(future.result())
    else:
        _init(seeds)
        for index in indices:
            accept(_work(index))

    by_cat: dict[str, int] = {}
    for case in kept:
        by_cat[case["category"]] = by_cat.get(case["category"], 0) + 1
    rejected = [t.name for t in templates if done[t.name][1] is None]
    print(f"wrote {len(kept)} cases to {args.out}: {by_cat}; rejected: {rejected}")
    return 0 if len(kept) >= 12 else 1


if __name__ == "__main__":
    sys.exit(main())
