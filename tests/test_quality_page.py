"""Quality page parity: the browser-side validator/summaries in
``resilimes/demo/static/product/quality/quality-report.js`` must
agree with ``resilimes/explain/quality.py`` (QualityReport /
evaluate) on the fixture corpus.

The fixture (``tests/fixtures/quality-report-sample.json``) holds a
real ``evaluate()`` export (12 samples, also stored in the fixture
as ``samples``) plus hand-built edge payloads. The ``valid`` flag on
each edge payload is what ``QualityReport.model_validate`` returned
when the fixture was generated; ``test_quality_fixture_matches_model``
re-checks those flags against the model whenever
``resilimes.explain.quality`` is importable, and skips honestly
while quality.py is still in unmerged PR #88. Until then the node
parity test below is fixture-based: it compares the JS validator
against the stored flags, it does not execute the Python model.

Nine edge payloads are deliberate divergences: the Python model
accepts them, the page rejects them (see docs/QUALITY_PAGE.md —
empty-bin mean/accuracy, [0, 1] ranges, cross-field consistency,
bin geometry, missing bins with calibration samples). The driver
asserts the rejection explicitly instead of comparing to the flag.

Runs under node when it is available; skips honestly when it is not
(the page is browser JS and has no Python equivalent). The drivers
are embedded here so the checks need no extra file in the static tree.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUALITY_JS = ROOT / "resilimes" / "demo" / "static" / "product" / "quality" / "quality-report.js"
QUALITY_PAGE_JS = ROOT / "resilimes" / "demo" / "static" / "product" / "quality" / "quality.js"
FIXTURE = ROOT / "tests" / "fixtures" / "quality-report-sample.json"

# Python accepts these, the page deliberately rejects them.
DIVERGENT = {
    "bin_accuracy_without_count",
    "bin_mean_without_count",
    "ece_out_of_range",
    "bin_mean_out_of_range",
    "inconsistent_counts",
    "inconsistent_bins",
    "inconsistent_denominators",
    "bin_geometry",
    "missing_bins",
}

DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const fixturePath = process.argv[2];
const qualityJs = process.argv[3];
const src = fs.readFileSync(qualityJs, "utf-8");
const data = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + "\nthis.__t = { validateQualityReport, normalizeQualityReport, qualitySummary, qualityRateText, qualityBinRows };", ctx);
const F = ctx.__t;
const failures = [];
function check(name, cond, extra) {
  if (!cond) failures.push(extra === undefined ? name : `${name}: ${JSON.stringify(extra)}`);
}
const DIVERGENT = new Set(JSON.parse(process.argv[4]));
check("valid report passes", F.validateQualityReport(data.valid).length === 0, F.validateQualityReport(data.valid));
const summary = F.qualitySummary(data.valid);
const expected = data.expected;
check("summary matches quality.py",
  summary.total === expected.total_samples && summary.answered === expected.answered
  && summary.unknownAnswers === expected.unknown_answers && summary.truthKnown === expected.truth_known
  && summary.calibrationSamples === expected.calibration_samples
  && summary.excludedNoConfidence === expected.calibration_excluded_no_confidence, summary);
check("ECE matches quality.py", data.valid.expected_calibration_error === expected.expected_calibration_error);
check("misattribution rate text", F.qualityRateText(data.valid.misattribution) === "2/7 · 28.6%", F.qualityRateText(data.valid.misattribution));
check("over-unknown rate text", F.qualityRateText(data.valid.over_unknown) === "3/10 · 30.0%", F.qualityRateText(data.valid.over_unknown));
check("unknown-share rate text", F.qualityRateText(data.valid.unknown_share) === "4/12 · 33.3%", F.qualityRateText(data.valid.unknown_share));
const rows = F.qualityBinRows(data.valid);
check("bin counts match quality.py", JSON.stringify(rows.map((r) => r.count)) === JSON.stringify(expected.bin_counts), rows.map((r) => r.count));
check("bin 5 mean/accuracy", rows[5].mean === 0.55 && rows[5].accuracy === 0, rows[5]);
const validBins = data.valid.calibration_bins;
for (const idx of [6, 7, 8, 9]) {
  check(`bin ${idx} mean/accuracy`, rows[idx].mean === validBins[idx].mean_confidence && rows[idx].accuracy === validBins[idx].accuracy, rows[idx]);
}
check("empty bins carry nulls", rows[0].mean === null && rows[0].accuracy === null, rows[0]);
check("bin 9 range is closed", rows[9].range === "[0.9, 1]", rows[9].range);
check("bin 5 range is half-open", rows[5].range === "[0.5, 0.6)", rows[5].range);
for (const [name, item] of Object.entries(data.edge)) {
  const errors = F.validateQualityReport(item.payload);
  if (DIVERGENT.has(name)) {
    check(`divergent edge ${name}: JS rejects, Python accepts`, errors.length > 0 && item.valid === true, errors);
  } else {
    check(`edge ${name}: valid=${item.valid}`, (errors.length === 0) === item.valid, errors);
  }
}
const norm = F.normalizeQualityReport(data.edge.numeric_strings.payload);
check("numeric strings coerced", norm.total_samples === 12 && norm.misattribution.numerator === 2, norm);
const normBins = F.normalizeQualityReport(data.edge.missing_bins.payload);
check("missing bins default to []", Array.isArray(normBins.calibration_bins) && normBins.calibration_bins.length === 0, normBins.calibration_bins);
const normVer = F.normalizeQualityReport(data.edge.missing_version.payload);
check("missing version defaults to quality/v0", normVer.metrics_version === "quality/v0", normVer.metrics_version);
const normEce = F.normalizeQualityReport(data.edge.missing_ece.payload);
check("missing ECE defaults to null", normEce.expected_calibration_error === null, normEce.expected_calibration_error);
const normVal = F.normalizeQualityReport(data.edge.missing_rate_value_zero_denominator.payload);
check("missing rate value at denominator 0 defaults to null", normVal.over_unknown.value === null, normVal.over_unknown);
const shortRows = F.qualityBinRows(F.normalizeQualityReport(data.edge.bins_short.payload));
check("short consistent bins render", shortRows.length === 3 && shortRows[0].range === "[0, 0.5)" && shortRows[2].range === "[0.9, 1]", shortRows);
check("non-grid bin range is not rounded onto the grid", F.qualityBinRows({ calibration_bins: [{ lower: 0.05, upper: 0.15, count: 1, mean_confidence: 0.1, accuracy: 1 }] })[0].range === "[0.05, 0.15)");
const emptyRows = F.qualityBinRows(F.normalizeQualityReport(data.edge.empty_report.payload));
check("empty report rate text is null", F.qualityRateText(data.edge.empty_report.payload.misattribution) === null);
check("empty report has 10 empty bins", emptyRows.length === 10 && emptyRows.every((r) => r.count === 0 && r.mean === null), emptyRows.length);
console.log(JSON.stringify({ failures }));
"""

# paintAnalyze must survive quality-report.js failing to load (404):
# with no qualityViewToggle / paintQualityReport defined, it falls
# back to the KPI view instead of throwing inside paint().
FALLBACK_DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const qualityJs = fs.readFileSync(process.argv[2], "utf-8");
const failures = [];
const appended = [];
const host = {
  innerHTML: "",
  scrollTop: 42,
  appendChild(node) { appended.push(node); return node; },
  contains() { return true; },
};
const sandbox = {
  $: () => host,
  t: () => ({ analyzeEmpty: "no report" }),
  state: { qualityView: "trust", report: null },
  document: { activeElement: null, getElementById: () => null, createElement: () => ({}) },
  emptyLine: (text) => ({ tag: "p", text }),
  console,
};
vm.createContext(sandbox);
// Deliberately no qualityViewToggle / paintQualityReport here.
vm.runInContext(qualityJs, sandbox);
try {
  sandbox.paintAnalyze();
} catch (error) {
  failures.push(`paintAnalyze threw without quality-report.js: ${error}`);
}
if (appended.length === 0 || appended[appended.length - 1].text !== "no report") {
  failures.push(`expected the KPI empty state, got ${JSON.stringify(appended)}`);
}
if (host.scrollTop !== 42) failures.push(`scroll was not restored: ${host.scrollTop}`);
console.log(JSON.stringify({ failures }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_quality_page_parity_with_quality_py(tmp_path: Path) -> None:
    driver = tmp_path / "quality_page_driver.cjs"
    driver.write_text(DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(FIXTURE), str(QUALITY_JS), json.dumps(sorted(DIVERGENT))],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_quality_page_falls_back_when_report_script_missing(tmp_path: Path) -> None:
    driver = tmp_path / "quality_page_fallback_driver.cjs"
    driver.write_text(FALLBACK_DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(QUALITY_PAGE_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []


def test_quality_fixture_matches_model() -> None:
    """Re-check the fixture against the Python model when available.

    Skips while quality.py is still in unmerged PR #88; once it
    merges this test pins the stored ``valid`` export and every edge
    ``valid`` flag to ``evaluate()`` / ``model_validate``.
    """
    try:
        from resilimes.explain.quality import (
            AttributionSample,
            QualityReport,
            evaluate,
        )
    except ImportError:
        pytest.skip("resilimes.explain.quality is not in this tree yet (PR #88)")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    samples = [AttributionSample(**row) for row in data["samples"]]
    report = evaluate(samples)
    assert json.loads(report.model_dump_json()) == data["valid"]
    for name, item in data["edge"].items():
        try:
            QualityReport.model_validate(item["payload"])
            model_valid = True
        except Exception:
            model_valid = False
        assert model_valid == item["valid"], name


def test_quality_page_fixture_is_valid_json() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["valid"]["metrics_version"] == "quality/v0"
    assert data["expected"]["total_samples"] == 12
    assert len(data["samples"]) == 12
    assert data["edge"]
