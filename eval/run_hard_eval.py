"""Score the hard investigator cases: ``python eval/run_hard_eval.py [--provider mock|nightshift]``.

Runs ``baseline_rank`` and the Investigator (offline ScriptedCompleter by
default) over two case files, reported as SEPARATE tables per category:

  - ``eval/investigator_hard_cases.json``  (combo / misleading / ood)
  - ``eval/investigator_notes_cases.json`` (notes: the root cause is stated
    only in fab-notes text attached to the question; for these, a third arm
    ``notes_reader`` -- the disclosed keyword extractor
    ``resilimes.insight.notes_cases.notes_hint`` -- scores what the text
    channel alone can answer)

The old 24-case results are NOT recomputed or mixed in; they are cited in the
printout for reference (baseline top-1 20/24, AI top-1 20/24, per
docs/AI_INVESTIGATOR.md).

Metrics per category, for the rule baseline and the AI: top1 (predicted
primary == ground-truth primary), top2 (truth inside predicted top-2), pair
(multi-cause cases only: both truths inside the predicted top-2). Plus, for
the AI: fact-check pass rate, mean turns, mean wall-clock seconds, degraded
count and timed-out count. Every case's full investigation (trace, tool
calls, answer) is written to ``eval/traces/<case_id>.json`` for deck
screenshots and for tonight's live re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CASES_PATH = Path(__file__).resolve().parent / "investigator_hard_cases.json"
NOTES_PATH = Path(__file__).resolve().parent / "investigator_notes_cases.json"
TRACE_DIR = Path(__file__).resolve().parent / "traces"
OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "ai_eval"
CATEGORIES = ("combo", "misleading", "ood", "notes")

_FAB: Any = None
_BASES: dict[int, Any] = {}
_PROVIDER: Any = None


def load_cases(path: Path, kind: str) -> list[Any]:
    from resilimes.insight.hard_cases import HardCase
    from resilimes.insight.notes_cases import NotesCase

    cls = NotesCase if kind == "notes" else HardCase
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [cls.from_json(item) for item in payload["cases"]]


def load_hard_cases(path: Path = CASES_PATH) -> list[Any]:
    return load_cases(path, "hard")


def _init(seeds: list[int], provider_name: str) -> None:
    global _FAB, _BASES, _PROVIDER
    from resilimes.evidence.toolkit import HOUR, record_run
    from resilimes.insight.injector import HORIZON_H
    from resilimes.smt.fab import load_fab

    _FAB = load_fab()
    _BASES = {seed: record_run(_FAB, seed=seed, horizon=HORIZON_H * HOUR) for seed in seeds}
    if provider_name == "nightshift":
        from resilimes.config import get_settings
        from resilimes.insight.study import provider_for

        _PROVIDER = provider_for("nightshift", get_settings())


def _metrics(truths: list[str], primary: str | None, secondary: str | None) -> dict[str, Any]:
    top2 = {cause for cause in (primary, secondary) if cause}
    out: dict[str, Any] = {
        "top1": primary == truths[0],
        "top2": truths[0] in top2,
    }
    if len(truths) > 1:
        out["pair"] = set(truths) <= top2
    return out


def _work(item: tuple[int, str, dict[str, Any]]) -> dict[str, Any]:
    from resilimes.evidence.toolkit import Toolkit
    from resilimes.insight.hard_cases import HardCase, rebuild_hard
    from resilimes.insight.investigator import baseline_rank, investigate
    from resilimes.insight.notes_cases import NotesCase, notes_hint

    index, kind, payload = item
    case: HardCase = (NotesCase if kind == "notes" else HardCase).from_json(payload)
    started = time.perf_counter()
    row: dict[str, Any] = {
        "case_id": case.case_id,
        "category": case.category,
        "truths": case.truths,
        "decoy": case.decoy,
    }
    try:
        run = rebuild_hard(_FAB, case, _BASES[case.seed])
        rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
        row["baseline_pred"] = rank[:2]
        row["baseline"] = _metrics(case.truths, rank[0], rank[1])
        answer = investigate(
            Toolkit(run), case.question, case.family, case.t1_h, case.t2_h, _PROVIDER, None
        )
        row["ai_pred"] = [answer.primary_cause, answer.secondary_cause]
        row["ai"] = _metrics(case.truths, answer.primary_cause, answer.secondary_cause)
        row["fact_ok"] = answer.fact_ok
        row["turns"] = answer.turns
        row["tool_calls"] = len(answer.calls)
        row["elapsed_s"] = round(answer.elapsed_s, 2)
        row["degraded"] = answer.degraded
        row["timed_out"] = answer.timed_out
        row["stop_reason"] = answer.stop_reason
        row["mocked"] = answer.mocked
        row["trace"] = {
            "case_id": case.case_id,
            "category": case.category,
            "question": case.question,
            "truths": case.truths,
            "baseline_pred": rank[:2],
            "investigation": answer.to_json(),
        }
        if kind == "notes" and isinstance(case, NotesCase):
            hint = notes_hint(case.notes_items, case.family, case.upstream)
            row["notes_reader"] = {"pred": hint, "top1": hint == case.truths[0]}
    except Exception as exc:  # a broken case is a result too; never hide it
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    row["seconds"] = round(time.perf_counter() - started, 1)
    print(f"[{index}] {case.case_id}: {row.get('baseline')} / {row.get('ai')}", flush=True)
    return row


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in rows if "error" not in row]
    multi = [row for row in ok if len(row["truths"]) > 1]

    def block(key: str) -> dict[str, Any]:
        return {
            "top1": sum(int(r[key]["top1"]) for r in ok),
            "top2": sum(int(r[key]["top2"]) for r in ok),
            "pair": sum(int(r[key]["pair"]) for r in multi if "pair" in r[key]),
            "pair_n": len(multi),
        }

    out = {
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "baseline": block("baseline"),
        "ai": block("ai"),
        "fact_ok": sum(int(r["fact_ok"]) for r in ok),
        "mean_turns": round(sum(r["turns"] for r in ok) / max(1, len(ok)), 2),
        "mean_tool_calls": round(sum(r["tool_calls"] for r in ok) / max(1, len(ok)), 2),
        "mean_elapsed_s": round(sum(r["elapsed_s"] for r in ok) / max(1, len(ok)), 2),
        "degraded": sum(int(r["degraded"]) for r in ok),
        "timed_out": sum(int(r["timed_out"]) for r in ok),
    }
    reader = [row for row in ok if "notes_reader" in row]
    if reader:
        out["notes_reader_top1"] = sum(int(r["notes_reader"]["top1"]) for r in reader)
        out["notes_reader_n"] = len(reader)
    return out


def _fmt(block: dict[str, Any], n: int) -> str:
    return f"top1 {block['top1']}/{n}  top2 {block['top2']}/{n}  pair {block['pair']}/{block['pair_n']}"


def _print_block(label: str, rows: list[dict[str, Any]]) -> None:
    part = _summarize(rows)
    print(f"{label:11} n={part['n']} errors={part['errors']}")
    print(f"  baseline: {_fmt(part['baseline'], part['n'])}")
    print(f"  ai      : {_fmt(part['ai'], part['n'])}")
    if "notes_reader_top1" in part:
        print(
            f"  notes_reader (scripted text extraction): "
            f"top1 {part['notes_reader_top1']}/{part['notes_reader_n']}"
        )
    print(
        f"  ai fact_ok {part['fact_ok']}/{part['n']}  mean turns {part['mean_turns']}  "
        f"mean elapsed {part['mean_elapsed_s']}s  degraded {part['degraded']}  "
        f"timed_out {part['timed_out']}"
    )


def _print_table(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    print("\n=== Hard investigator cases (this set only) ===")
    print(f"{'case':28} {'category':11} {'truths':28} {'baseline':18} ai")
    for row in rows:
        if "error" in row:
            print(f"{row['case_id']:28} {row['category']:11} ERROR {row['error']}")
            continue
        print(
            f"{row['case_id']:28} {row['category']:11} {','.join(row['truths']):28} "
            f"{row['baseline_pred']!s:18} {row['ai_pred']}"
        )
    print()
    _print_block("overall", rows)
    for category in CATEGORIES:
        sub = [row for row in rows if row["category"] == category]
        if sub:
            _print_block(category, sub)
    print(
        "\nReference only (old 24 single-fault cases, NOT recomputed here): "
        "baseline top-1 20/24, AI top-1 20/24 (docs/AI_INVESTIGATOR.md)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_hard_eval")
    parser.add_argument("--provider", choices=["mock", "nightshift"], default="mock")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--notes", type=Path, default=NOTES_PATH)
    args = parser.parse_args(argv)

    work: list[tuple[int, str, dict[str, Any]]] = []
    cases = load_cases(args.cases, "hard")
    work += [(i, "hard", case.to_json()) for i, case in enumerate(cases)]
    if args.notes.exists():
        notes = load_cases(args.notes, "notes")
        offset = len(work)
        work += [(offset + i, "notes", case.to_json()) for i, case in enumerate(notes)]
    seeds = sorted({payload["seed"] for _, _, payload in work})
    if args.jobs > 1:
        with ProcessPoolExecutor(
            max_workers=args.jobs, initializer=_init, initargs=(seeds, args.provider)
        ) as pool:
            rows = list(pool.map(_work, work))
    else:
        _init(seeds, args.provider)
        rows = [_work(item) for item in work]
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    for row in rows:
        trace = row.pop("trace", None)
        if trace is not None:
            path = TRACE_DIR / f"{row['case_id']}.json"
            path.write_text(
                json.dumps(trace, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            row["trace_file"] = f"eval/traces/{row['case_id']}.json"
    summary = _summarize(rows)
    _print_table(rows, summary)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"investigator_hard_{args.provider}.json"
    out.write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} and {len(rows)} trace files under {TRACE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
