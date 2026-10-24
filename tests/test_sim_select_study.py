"""The sim-select study harness: per-run files, resume, paired report."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from resilimes.smt import sim_select_study as study


@pytest.fixture(autouse=True)
def _keep_env() -> object:
    before = os.environ.get("RESILIMES_STUDY_HORIZON_H")
    yield None
    if before is None:
        os.environ.pop("RESILIMES_STUDY_HORIZON_H", None)
    else:
        os.environ["RESILIMES_STUDY_HORIZON_H"] = before


def test_runs_resume_and_report(tmp_path: Path) -> None:
    argv = [
        "--arms", "rules,sim_hmem", "--seeds", "9", "--warm-seeds", "1",
        "--horizon-h", "2", "--fork-h", "1", "--futures", "2", "--workers", "1",
        "--out-dir", str(tmp_path),
    ]  # fmt: skip
    study.main(argv)
    run = tmp_path / "sim_hmem" / "heldout_published_s9.json"
    row = json.loads(run.read_text("utf-8"))
    assert row["config"]["fork_h"] == 1.0 and row["memory"]["receipts"] > 0
    assert (tmp_path / "memory_sim_hmem.json").exists()
    stamp = run.stat().st_mtime_ns
    study.main(argv)  # resumes: nothing re-run
    assert run.stat().st_mtime_ns == stamp
    report = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert report["arms"]["rules"]["d_weighted_tardiness_min_vs_rules"] == 0.0
    assert set(report["arms"]) == {"rules", "sim_hmem"}


def test_unknown_arm_rejected() -> None:
    with pytest.raises(SystemExit):
        study.parse(["--arms", "oracle"])
