"""Legality of the notes-rooted investigator cases (eval/investigator_notes_cases.json).

Fast tests validate the case/notes structure against the fab_notes item
format and the injection record; one slow spot check rebuilds a case and
verifies the generation gate still holds: the rule baseline's top-1 misses
the truth (the root cause is only in the notes text).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from resilimes.insight.injector import TAXONOMY
from resilimes.insight.notes_cases import NotesCase, notes_hint

CASES_PATH = Path(__file__).resolve().parent.parent / "eval" / "investigator_notes_cases.json"
PAYLOAD = json.loads(CASES_PATH.read_text(encoding="utf-8"))
CASES = [NotesCase.from_json(item) for item in PAYLOAD["cases"]]
GOLD_TYPES = {"planned_down", "priority_change", "capacity_derate", "hold"}


@pytest.fixture(scope="module")
def fab():
    from resilimes.smt.fab import load_fab

    return load_fab()


def test_case_count_and_shape() -> None:
    assert 4 <= len(CASES) <= 6
    ids = [case.case_id for case in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        assert case.category == "notes"
        assert len(case.truths) == 1 and case.truths[0] in TAXONOMY
        assert case.decoy is None
        assert 0 <= case.t1_h < case.t2_h <= 16.0
        # the generation gate, recorded: baseline top-1 missed the truth
        assert case.baseline_pred and case.baseline_pred[0] != case.truths[0]


def test_notes_items_follow_fab_notes_format(fab) -> None:
    tool_names = set(fab.tool_name)
    for case in CASES:
        assert 3 <= len(case.notes_items) <= 6
        for item in case.notes_items:
            assert set(item) >= {"id", "ts", "source", "lang", "text", "gold"}
            assert item["ts"].startswith("2026-10-2")
            assert isinstance(item["gold"], list)
            for gold in item["gold"]:
                assert gold["type"] in GOLD_TYPES
                if gold["type"] == "planned_down":
                    assert gold["equipment"] in tool_names
                    assert gold["duration_min"] > 0
                elif gold["type"] == "capacity_derate":
                    assert gold["equipment"] in tool_names
                    assert 0 < gold["factor"] < 1
                elif gold["type"] == "priority_change":
                    assert re.fullmatch(r"Init_(Hot)?Lot_\d+_\d+", gold["lot"])


def test_gold_note_matches_injected_truth(fab) -> None:
    for case in CASES:
        truth = case.truths[0]
        golds = [g for item in case.notes_items for g in item["gold"]]
        if truth in ("tool_down", "pm_in_peak"):
            # the release_burst describe part carries no window_h; fall back
            # to the injected spec's start hour
            window = case.injection[0].get("window_h") or [case.specs[0]["t0_h"]]
            match = [
                g
                for g in golds
                if g["type"] == "planned_down" and g["equipment"].startswith(case.family + "-")
            ]
            assert match, case.case_id
            start_h = int(match[0]["start"][11:13]) + int(match[0]["start"][14:16]) / 60
            assert start_h == window[0]
        elif truth == "upstream_starvation":
            assert case.upstream
            match = [
                g
                for g in golds
                if g["type"] == "planned_down" and g["equipment"].startswith(case.upstream + "-")
            ]
            assert match, case.case_id
        elif truth == "batch_cap":
            match = [
                g
                for g in golds
                if g["type"] == "capacity_derate" and g["equipment"].startswith(case.family + "-")
            ]
            assert match, case.case_id
        elif truth == "release_burst":
            match = [g for g in golds if g["type"] == "priority_change"]
            assert match, case.case_id
        else:  # pragma: no cover - templates only use the causes above
            raise AssertionError(f"unexpected notes truth {truth}")


def test_notes_hint_reads_the_gold_cause() -> None:
    # the disclosed keyword extractor, run over the full note set (gold +
    # distractors), names the truth for every case
    for case in CASES:
        assert notes_hint(case.notes_items, case.family, case.upstream) == case.truths[0], (
            case.case_id
        )


@pytest.fixture(scope="module")
def bases(fab):
    from resilimes.evidence.toolkit import HOUR, record_run
    from resilimes.insight.injector import HORIZON_H

    seeds = {case.seed for case in CASES}
    return {seed: record_run(fab, seed=seed, horizon=HORIZON_H * HOUR) for seed in seeds}


def test_baseline_misses_rebuilt_case(fab, bases) -> None:
    from resilimes.evidence.toolkit import Toolkit
    from resilimes.insight.hard_cases import rebuild_hard
    from resilimes.insight.investigator import baseline_rank

    case = CASES[0]
    run = rebuild_hard(fab, case, bases[case.seed])
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    assert rank[0] != case.truths[0]
