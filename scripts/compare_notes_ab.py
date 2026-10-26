"""A/B/C comparison for notes-driven scheduling (Plan-2 evaluation).

Arms: A = no notes, B = extractor events after fact-check validation,
C = gold events. Headline metric: gap closure (A-B)/(A-C) on avoidable
Q-time violations, plus collateral damage (wrong events applied / new
violations, target 0) and per-type extraction precision/recall.

    python3 scripts/compare_notes_ab.py                  # mock runner, scripted B
    python3 scripts/compare_notes_ab.py --b-extractor regex
    python3 scripts/compare_notes_ab.py --runner live    # needs notes_ab_live

The mock runner is a deterministic ledger model (numbers are NOT fab
simulation results); it exists so the full pipeline and the report template
run end-to-end offline. The live runner is supplied on the owner's machine
as ``resilimes/insight/notes_ab_live.py`` with ``build_runner()``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resilimes.insight.notes import (
    LlmExtractor,
    RegexExtractor,
    ScriptedNotesCompleter,
    build_fab_index,
    extract_validated,
    load_notes,
    score_extractor,
)
from resilimes.insight.notes_ab import MockScheduleRunner, compare_arms, render_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b-extractor", choices=["llm", "regex"], default="llm")
    parser.add_argument("--runner", choices=["mock", "live"], default="mock")
    parser.add_argument("--out-md", default="outputs/notes_ab_report.md")
    parser.add_argument("--out-json", default="outputs/notes_ab.json")
    args = parser.parse_args()

    notes = load_notes()
    fab_index = build_fab_index()
    extractors = {
        "regex": RegexExtractor(),
        "llm": LlmExtractor(ScriptedNotesCompleter()),
    }
    b_extractor = extractors[args.b_extractor]

    # Extraction quality on the same set for every extractor (regex kept).
    extraction = {name: score_extractor(e, notes, fab_index) for name, e in extractors.items()}
    b_events_by_note = {
        note["id"]: extract_validated(b_extractor, note, fab_index)[1] for note in notes
    }

    if args.runner == "live":
        try:
            from resilimes.insight.notes_ab_live import build_runner
        except ImportError:
            print(
                "live runner not available: add resilimes/insight/notes_ab_live.py "
                "with build_runner() (see resilimes/insight/notes_ab.py docstring).",
                file=sys.stderr,
            )
            return 2
        runner = build_runner()
    else:
        runner = MockScheduleRunner()

    comparison = compare_arms(notes, b_events_by_note, runner)
    report = {
        "b_extractor": args.b_extractor,
        "comparison": comparison,
        "extraction": extraction,
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out_md = Path(args.out_md)
    out_md.write_text(render_markdown(report), encoding="utf-8")

    arms = comparison["arms"]
    print(f"runner={comparison['runner']} mock={comparison['is_mock']}")
    print(
        f"A avoidable={arms['A']['avoidable_qtime']}  "
        f"B avoidable={arms['B']['avoidable_qtime']}  "
        f"C avoidable={arms['C']['avoidable_qtime']}"
    )
    print(f"gap_closure={comparison['gap_closure']}")
    print(
        f"collateral wrong_events_applied={comparison['collateral']['wrong_events_applied']} "
        f"new_violations={comparison['collateral']['new_violations']}"
    )
    print(f"Wrote {out_md} and {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
