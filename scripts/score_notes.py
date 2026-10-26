"""Score fab-note extractors against the gold dataset.

Runs RegexExtractor and the LLM pipeline (LlmExtractor over the offline
ScriptedNotesCompleter — no network, no Nightshift) over
``data/notes/fab_notes.json``, passes every raw output through
``validate_events``, and reports per-type precision/recall, the number of raw
events the fact-check layer rejected, and recall split by the dataset's
``hard_for_regex`` flag. Matching rules live in
``resilimes/insight/notes.py`` (``event_key``).

Usage: python3 scripts/score_notes.py [--out outputs/notes_score.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resilimes.insight.notes import (
    EVENT_TYPES,
    LlmExtractor,
    RegexExtractor,
    ScriptedNotesCompleter,
    build_fab_index,
    load_notes,
    score_extractor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="outputs/notes_score.json")
    args = parser.parse_args()

    notes = load_notes()
    fab_index = build_fab_index()
    extractors = [
        RegexExtractor(),
        LlmExtractor(ScriptedNotesCompleter()),
    ]
    results = [score_extractor(e, notes, fab_index) for e in extractors]
    report = {
        "dataset": "data/notes/fab_notes.json",
        "notes": len(notes),
        "gold_events": sum(len(n["gold"]) for n in notes),
        "extractors": results,
        "note": (
            "The 'llm' row is the offline scripted stand-in, not a live "
            "Nightshift run; live LLM scoring is future work."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    for r in results:
        print(f"\n== {r['extractor']} ==")
        print(f"{'type':<18}{'P':>8}{'R':>8}{'TP':>5}{'FP':>5}{'FN':>5}")
        for etype in EVENT_TYPES:
            row = r["per_type"][etype]
            print(
                f"{etype:<18}{row['precision']!s:>8}{row['recall']!s:>8}"
                f"{row['tp']:>5}{row['fp']:>5}{row['fn']:>5}"
            )
        o = r["overall"]
        print(
            f"{'OVERALL':<18}{o['precision']!s:>8}{o['recall']!s:>8}"
            f"{o['tp']:>5}{o['fp']:>5}{o['fn']:>5}"
        )
        print(
            f"raw={r['raw_events']} rejected_by_validation={r['rejected_by_validation']} "
            f"hold_reason_accuracy={r['hold_reason_accuracy']} "
            f"recall plain={r['recall_by_flag']['plain']['recall']} "
            f"hard={r['recall_by_flag']['hard']['recall']}"
        )
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
