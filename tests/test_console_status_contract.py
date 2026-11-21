"""Wave H①: console failure status must survive paint().

``run()`` used to write ``#status`` in ``catch``, then ``finally`` called
``paint()``, which cleared the line whenever there was no report. The
status line is now decided by ``statusLineFor`` from ``state.runError``.
This test pins that a failed run leaves a non-empty status and offers
retry, and that a later paint with the same state still shows the error.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_JS = ROOT / "resilimes" / "demo" / "static" / "workshop" / "console" / "console.js"
I18N = ROOT / "resilimes" / "demo" / "static" / "i18n.json"
INDEX = ROOT / "resilimes" / "demo" / "static" / "index.html"

DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf-8");
const match = src.match(/function statusLineFor\([\s\S]*?\n\}/);
if (!match) {
  console.log(JSON.stringify({ failures: ["statusLineFor missing"] }));
  process.exit(0);
}
const ctx = {};
vm.createContext(ctx);
vm.runInContext(match[0] + "\nthis.statusLineFor = statusLineFor;", ctx);
const F = ctx.statusLineFor;
const failures = [];
function check(name, cond, extra) {
  if (!cond) failures.push(extra === undefined ? name : `${name}: ${JSON.stringify(extra)}`);
}
const copy = { working: "Rescheduling.", refused: "Request refused.", retry: "Retry" };
const done = (report) => (report && report.ok ? "done" : "done?");
const failed = F({ running: false, report: null, runError: "boom" }, copy, done);
check("failed status non-empty", failed.text === "boom", failed);
check("failed status warns", failed.warn === true, failed);
check("failed status offers retry", failed.retry === true, failed);
const working = F({ running: true, report: null, runError: null }, copy, done);
check("working while running", working.text === "Rescheduling." && !working.retry, working);
const cleared = F({ running: false, report: null, runError: null }, copy, done);
check("idle clears status", cleared.text === "" && !cleared.retry, cleared);
const ok = F({ running: false, report: { blocked: false, ok: true }, runError: null }, copy, done);
check("report success uses done", ok.text === "done" && !ok.retry, ok);
const blocked = F({ running: false, report: { blocked: true }, runError: null }, copy, done);
check("blocked uses refused", blocked.text === "Request refused.", blocked);
const errorWins = F({ running: false, report: { blocked: false, ok: true }, runError: "stale" }, copy, done);
check("runError wins over report", errorWins.text === "stale" && errorWins.retry, errorWins);
console.log(JSON.stringify({ failures }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_status_line_for_keeps_failure_visible(tmp_path: Path) -> None:
    driver = tmp_path / "console_status_driver.cjs"
    driver.write_text(DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(CONSOLE_JS)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []


def test_console_wires_run_error_and_retry_control() -> None:
    text = CONSOLE_JS.read_text(encoding="utf-8")
    assert "runError: null" in text
    assert "state.runError =" in text
    assert "function statusLineFor(" in text
    assert "function paintStatus(" in text
    assert "status-retry" in text
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="status-retry"' in html
    assert 'id="status"' in html


def test_retry_copy_exists_in_all_languages() -> None:
    catalog = json.loads(I18N.read_text(encoding="utf-8"))
    for lang in ("en", "zh", "ja"):
        assert catalog[lang]["retry"].strip(), lang
