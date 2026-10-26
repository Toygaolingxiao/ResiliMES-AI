"""Generate the notes-rooted investigator cases: ``python eval/generate_notes_cases.py``.

Each template in ``resilimes.insight.notes_cases.NOTES_TEMPLATES`` is built on
the fab at the first family whose injected fault (a) shows a visible WIP
symptom and (b) is NOT convicted by the rule baseline's top-1 -- the fab notes
attached to the case are the only channel that names the root cause. Kept
cases are written to ``eval/investigator_notes_cases.json``; ``--only a,b``
rebuilds just those templates and merges them into the existing file.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_PATH = Path(__file__).resolve().parent / "investigator_notes_cases.json"

_FAB: Any = None
_BASES: dict[int, Any] = {}


def _init(seeds: list[int]) -> None:
    global _FAB, _BASES
    from resilimes.evidence.toolkit import HOUR, record_run
    from resilimes.insight.injector import HORIZON_H
    from resilimes.smt.fab import load_fab

    _FAB = load_fab()
    _BASES = {seed: record_run(_FAB, seed=seed, horizon=HORIZON_H * HOUR) for seed in seeds}


def _work(name: str) -> dict[str, Any] | None:
    from resilimes.insight.notes_cases import NOTES_TEMPLATES, make_notes_case

    template = next(t for t in NOTES_TEMPLATES if t.name == name)
    case = make_notes_case(_FAB, template, _BASES[template.seed])
    if case is None:
        print(f"{name} [{template.spec.cause}] REJECTED (no valid family)", flush=True)
        return None
    print(
        f"{name} [{template.spec.cause}] KEPT -> {case.family} "
        f"(baseline top-1 {case.baseline_pred[0]})",
        flush=True,
    )
    return case.to_json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_notes_cases")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--only", type=str, default="")
    args = parser.parse_args(argv)

    from resilimes.insight.notes_cases import NOTES_TEMPLATES

    names = [t.name for t in NOTES_TEMPLATES]
    if args.only:
        names = [name for name in names if name in set(args.only.split(","))]
    seeds = sorted({t.seed for t in NOTES_TEMPLATES if t.name in names})
    if args.jobs > 1:
        with ProcessPoolExecutor(
            max_workers=args.jobs, initializer=_init, initargs=(seeds,)
        ) as pool:
            results = list(pool.map(_work, names))
    else:
        _init(seeds)
        results = [_work(name) for name in names]
    kept = {row["case_id"]: row for row in results if row}
    rejected = [name for name in names if name not in kept]
    if args.only and OUT_PATH.exists():
        old = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        merged = {row["case_id"]: row for row in old["cases"]}
        merged.update(kept)
        kept = merged
    cases = [kept[name] for name in sorted(kept)]
    OUT_PATH.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "notes-rooted hard cases; ground truth by injection, "
                "root cause stated only in the attached fab notes (format of "
                "data/notes/fab_notes.json items)",
                "cases": cases,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases to {OUT_PATH}; rejected: {rejected}")
    return 0 if len(cases) >= 4 and not rejected else 1


if __name__ == "__main__":
    sys.exit(main())
