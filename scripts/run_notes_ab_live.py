#!/usr/bin/env python3
"""LIVE notes A/B/C — the owner's headline run for Plan 2.

``scripts/compare_notes_ab.py --runner live`` runs the arms on the REAL
simulator, but its ``llm`` extractor is wired to ``ScriptedNotesCompleter``
(deterministic, offline). This wrapper is the same comparison with ONE
difference: the B arm's extractor is ``LlmExtractor`` over the real provider
from settings (``build_provider`` — Nightshift / Nemotron on the owner's
machine). Everything else — fact-check validation, the event-to-simulation
mapping, the arms, the metrics — is the shared code, so tonight's numbers
are directly comparable with the offline rehearsal (A 17 / B 14 / C 14,
scripted extraction).

Preconditions (owner's machine): Nightshift up on 127.0.0.1:8088 with the
Nemotron model, ``RESILIMES_MODE=live`` and ``METERLESS_RUNTIME_TOKEN`` set.
Calls are serial: 46 notes, one extraction call each (a caching completer
makes the scoring pass reuse the same responses — identical prompts, so no
second round of model calls). Expect ~30-60 min for extraction plus ~6 min
of simulation for the three arms.

Outputs: ``outputs/notes_ab_live.json`` / ``outputs/notes_ab_live.md``,
stamped ``extraction_mode: LIVE`` so they can never be confused with the
scripted-extraction report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resilimes.config import Settings
from resilimes.insight.notes import (
    LlmExtractor,
    RegexExtractor,
    build_fab_index,
    extract_validated,
    load_notes,
    score_extractor,
)
from resilimes.insight.notes_ab import compare_arms, render_markdown
from resilimes.insight.notes_ab_live import build_runner
from resilimes.llm.factory import build_provider


class _CachingCompleter:
    """Memoising Completer: the scoring pass and the B-arm pass ask the
    provider identical questions; a live model should only be billed (and
    waited on) once per distinct prompt."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = inner.name
        self.mocked = inner.mocked
        self._cache: dict[str, Any] = {}

    def model_for(self, lane: str) -> str:
        return self.inner.model_for(lane)

    def complete(self, messages: Any, *, lane: str, temperature: float = 0.2) -> Any:
        key = json.dumps(
            {"m": messages, "lane": lane, "t": temperature},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if key not in self._cache:
            self._cache[key] = self.inner.complete(messages, lane=lane, temperature=temperature)
        return self._cache[key]


def main() -> int:
    provider = _CachingCompleter(build_provider(Settings()))
    print(f"provider={provider.name} mocked={provider.mocked}")
    if provider.mocked:
        print(
            "WARNING: the configured provider is a MOCK — this run is a wiring "
            "check, not a live extraction. Set RESILIMES_MODE=live first.",
            file=sys.stderr,
        )

    notes = load_notes()
    fab_index = build_fab_index()
    llm = LlmExtractor(provider)
    extraction = {
        "regex": score_extractor(RegexExtractor(), notes, fab_index),
        "llm": score_extractor(llm, notes, fab_index),
    }
    b_events_by_note = {note["id"]: extract_validated(llm, note, fab_index)[1] for note in notes}

    comparison = compare_arms(notes, b_events_by_note, build_runner())
    report = {
        "extraction_mode": "LIVE",
        "provider": provider.name,
        "b_extractor": "llm",
        "comparison": comparison,
        "extraction": extraction,
    }
    out_json = Path("outputs/notes_ab_live.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out_md = Path("outputs/notes_ab_live.md")
    banner = (
        "# Notes A/B/C — LIVE extraction (Nemotron via Nightshift)\n\n"
        f"Provider: {provider.name}. B arm events were extracted by the live "
        "model and passed through the same fact-check validation and "
        "simulation mapping as every other arm.\n\n"
    )
    out_md.write_text(banner + render_markdown(report), encoding="utf-8")

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
