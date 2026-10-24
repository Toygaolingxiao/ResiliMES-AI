"""Progress on or off, a shift-lead study gives the same decisions and KPIs."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from resilimes.smt import shift_lead_study
from resilimes.smt.progress import Progress


def _strip(row: dict[str, Any]) -> dict[str, Any]:
    row = {key: value for key, value in row.items() if key != "wall_s"}
    if "decisions" in row:
        row["decisions"] = [
            {key: value for key, value in entry.items() if key != "latency_ms"}
            for entry in row["decisions"]
        ]
    if "shift_lead" in row:
        row["shift_lead"] = {
            key: value for key, value in row["shift_lead"].items() if "latency" not in key
        }
    return row


def test_mock_run_is_identical_with_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIMES_STUDY_HORIZON_H", "4")
    monkeypatch.setenv("RESILIMES_STUDY_KPI", "0")
    monkeypatch.setattr(shift_lead_study, "_ARGS", {"lang": "zh", "timeout": 30.0, "budget": 12})
    item = ("published", 1, "mock")
    plain = shift_lead_study._run(item)
    stream = io.StringIO()
    progress = Progress(study="shift_lead", plan=["mock"], budget=12, stream=stream, tty=False)
    monkeypatch.setattr(shift_lead_study, "_LIVE", [progress])
    watched = shift_lead_study._run(item)
    assert plain["decisions"], "the 4 h mock run should meet exceptions"
    assert _strip(watched) == _strip(plain)
    snap = progress.snapshot()
    summary = plain["shift_lead"]
    assert snap["runs"]["done"] == 1
    assert snap["totals"]["exceptions"] == summary["exceptions"]
    assert snap["totals"]["calls"] == 12
    assert snap["totals"]["overrides"] == summary["differs"]
    assert snap["totals"]["fallbacks"]["budget"] == summary["fallback_causes"].get("budget", 0)
    assert snap["sim"]["pct"] == 100.0


def test_cli_writes_the_progress_file_and_same_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RESILIMES_STUDY_HORIZON_H", "4")
    monkeypatch.setenv("RESILIMES_STUDY_KPI", "0")
    args = ["--provider", "mock", "--books", "published", "--seeds", "1", "--budget", "5"]
    args += ["--workers", "1"]
    shift_lead_study.main([*args, "--out", str(tmp_path / "on.json")])
    err = capsys.readouterr().err
    assert "shift_lead 2/2 published s1 mock | sim" in err
    assert "shift_lead 2/2 DONE" in err
    shift_lead_study.main([*args, "--no-progress", "--out", str(tmp_path / "off.json")])
    assert "DONE" not in capsys.readouterr().err
    assert not (tmp_path / "off.json.progress.json").exists()
    body = json.loads((tmp_path / "on.json.progress.json").read_text(encoding="utf-8"))
    assert body["status"] == "done"
    assert body["runs"] == {"done": 2, "total": 2}
    assert body["totals"]["calls"] == 5
    on = json.loads((tmp_path / "on.json").read_text(encoding="utf-8"))
    off = json.loads((tmp_path / "off.json").read_text(encoding="utf-8"))
    assert [_strip(row) for row in on["rows"]] == [_strip(row) for row in off["rows"]]
    assert on["report"] == off["report"]
