"""Live A/B/C runner (notes_ab_live): real simulator, no mock ledger.

Fast probes inspect the exact simulator inputs an arm would receive (the
strongest evidence an event took effect); the end-to-end tests run the
smallest feasible horizon (2 h) so the whole file stays near a minute.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from resilimes.insight.notes import (
    LlmExtractor,
    ScriptedNotesCompleter,
    build_fab_index,
    extract_validated,
    load_notes,
)
from resilimes.insight.notes_ab import compare_arms, render_markdown
from resilimes.insight.notes_ab_live import build_runner
from resilimes.smt.simulate import pm_windows, run_policy, sample_downs

ROOT = Path(__file__).resolve().parents[1]
H = 2.0  # smallest feasible horizon for the live tests


@pytest.fixture(scope="module")
def runner():
    return build_runner(seed=1, horizon_hours=H)


def test_probe_planned_down_enters_downs(runner):
    fab, kwargs, applied, unsupported = runner._build_inputs(
        [
            {
                "type": "planned_down",
                "equipment": "Litho_FE_92-1",
                "start": "2026-10-22T01:00:00Z",
                "duration_min": 60,
                "_note_id": "probe",
            }
        ]
    )
    tool = runner._tool_index["Litho_FE_92-1"]
    assert (3600.0, 7200.0) in kwargs["downs"][tool]
    assert len(applied) == 1 and unsupported == 0
    assert fab is runner.fab  # a down does not need a fab copy


def test_probe_planned_down_family_covers_all_tools(runner):
    _, kwargs, applied, unsupported = runner._build_inputs(
        [
            {
                "type": "planned_down",
                "equipment": "Litho_FE_98",
                "start": "2026-10-22T00:30:00Z",
                "duration_min": 30,
                "_note_id": "probe",
            }
        ]
    )
    fam = runner.fab.family_index["Litho_FE_98"]
    tools = runner._family_tools[fam]
    assert len(tools) > 1
    assert all((1800.0, 3600.0) in kwargs["downs"][t] for t in tools)
    assert len(applied) == 1 and unsupported == 0


def test_probe_priority_change_rewrites_fab_copy(runner):
    note = load_notes()[0]
    idx = runner._lot_index["Init_Lot_2_13"]
    before_due = runner.fab.lot_due[idx]
    fab, _, applied, unsupported = runner._build_inputs(
        [
            {
                "type": "priority_change",
                "lot": "Init_Lot_2_13",
                "priority": "vip",
                "new_due_h": 6.0,
                "_note_id": note["id"],
            }
        ]
    )
    expected_due = runner._note_ts[note["id"]] + 6.0 * 3600.0
    assert fab is not runner.fab
    assert fab.lot_due[idx] == pytest.approx(expected_due)
    assert fab.lot_class[idx] == "VIP"
    assert runner.fab.lot_due[idx] == before_due  # base fab untouched
    assert len(applied) == 1 and unsupported == 0


def test_probe_hold_uses_fault_plan(runner):
    idx = runner._lot_index["Init_Lot_2_13"]
    _, kwargs, applied, unsupported = runner._build_inputs(
        [
            {
                "type": "hold",
                "scope": "lot",
                "lot": "Init_Lot_2_13",
                "reason": "quality_review",
                "_note_id": "probe",
            }
        ]
    )
    assert kwargs["faults"].hold_until[idx] == H * 3600.0
    assert len(applied) == 1 and unsupported == 0


def test_unsupported_events_never_enter_inputs(runner):
    events = [
        # step hold: no step-hold mechanism in the simulator
        {"type": "hold", "scope": "step", "step": "LITHO", "reason": "other", "_note_id": "p"},
        # derate: no capacity-scaling mechanism (downs are binary)
        {
            "type": "capacity_derate",
            "equipment": "Litho_FE_98",
            "factor": 0.5,
            "window_h": 4.0,
            "_note_id": "p",
        },
        # sample-bay equipment is not in the SMT2020 fab
        {
            "type": "planned_down",
            "equipment": "LITHO-02",
            "start": "2026-10-22T01:00:00Z",
            "duration_min": 60,
            "_note_id": "p",
        },
        # window entirely outside the run horizon
        {
            "type": "planned_down",
            "equipment": "Litho_FE_92-1",
            "start": "2026-10-23T01:00:00Z",
            "duration_min": 60,
            "_note_id": "p",
        },
        # sample-bay lot is not SMT2020 WIP
        {"type": "priority_change", "lot": "LOT-1001", "new_due_h": 5.0, "_note_id": "p"},
    ]
    fab, kwargs, applied, unsupported = runner._build_inputs(events)
    assert applied == []
    assert unsupported == len(events)
    assert fab is runner.fab and "faults" not in kwargs


def test_arm_a_matches_plain_baseline(runner):
    outcome = runner.run([], {})
    horizon = H * 3600.0
    baseline = run_policy(
        runner.fab,
        policy="resilimes",
        seed=1,
        horizon=horizon,
        downs=sample_downs(runner.fab, 1, horizon),
        pm=pm_windows(runner.fab, horizon),
    )
    assert runner.is_mock is False
    assert outcome.applied == [] and outcome.unsupported == 0
    assert outcome.avoidable_qtime == baseline.qtime_miss_class.get("avoidable", 0)
    assert outcome.qtime_violations == baseline.qtime_violations
    assert outcome.completed == baseline.completed_routes
    assert outcome.on_time_pct == baseline.on_time_pct


def test_live_compare_end_to_end_small(runner):
    notes = load_notes()[:6]
    fab_index = build_fab_index()
    extractor = LlmExtractor(ScriptedNotesCompleter())
    b_events = {n["id"]: extract_validated(extractor, n, fab_index)[1] for n in notes}
    report = compare_arms(notes, b_events, runner)
    assert report["is_mock"] is False
    assert report["runner"].startswith("live-")
    for arm in ("A", "B", "C"):
        assert report["arms"][arm]["avoidable_qtime"] >= 0
    md = render_markdown({"comparison": report, "extraction": {}})
    assert "LIVE" in md and "MOCK" not in md


def test_cli_runner_live(tmp_path):
    env = dict(os.environ, RESILIMES_NOTES_HORIZON_H=str(H))
    out_md, out_json = tmp_path / "report.md", tmp_path / "report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "compare_notes_ab.py"),
            "--runner",
            "live",
            "--out-md",
            str(out_md),
            "--out-json",
            str(out_json),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["comparison"]["is_mock"] is False
    assert report["comparison"]["runner"].startswith("live-")
    assert "LIVE" in out_md.read_text(encoding="utf-8")
