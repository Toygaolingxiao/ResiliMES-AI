"""Cases page parity: the browser-side validator/summaries in
``resilimes/demo/static/product/cases/cases.js`` must agree with
``resilimes/explain/cases.py`` (CaseBook.from_json / lots / summary)
on the fixture corpus.

The fixture (``tests/fixtures/cases-book-sample.json``) holds a real
``to_json`` export plus hand-built edge payloads; the ``valid`` flag on
each edge payload is what ``CaseBook.from_json`` returns.
``illegal_transition`` is rejected by both the page and ``from_json``.

Runs under node when it is available; skips honestly when it is not
(the page is browser JS and has no Python equivalent). The driver is
embedded here so the check needs no extra file in the static tree.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES_JS = ROOT / "resilimes" / "demo" / "static" / "product" / "cases" / "cases.js"
FIXTURE = ROOT / "tests" / "fixtures" / "cases-book-sample.json"

DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const fixturePath = process.argv[2];
const casesJs = process.argv[3];
const src = fs.readFileSync(casesJs, "utf-8");
const data = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + "\nthis.__t = { validateCaseBook, normalizeCaseBook, casesLotRows, casesSummary, casesFilteredBook, casesParseIso };", ctx);
const F = ctx.__t;
const failures = [];
function check(name, cond, extra) {
  if (!cond) failures.push(extra === undefined ? name : `${name}: ${JSON.stringify(extra)}`);
}
check("valid book passes", F.validateCaseBook(data.valid).length === 0, F.validateCaseBook(data.valid));
const rows = F.casesLotRows(data.valid);
check("lot order matches cases.py", JSON.stringify(rows.map((r) => r.lot)) === JSON.stringify(data.expected_lots), rows.map((r) => r.lot));
const summary = F.casesSummary(data.valid);
const expected = data.expected_summary;
check("summary matches cases.py",
  summary.total === expected.total && summary.lots === expected.lots && summary.openTotal === expected.open_total
  && JSON.stringify(summary.byStatus) === JSON.stringify(expected.by_status)
  && JSON.stringify(summary.bySeverity) === JSON.stringify(expected.by_severity), summary);
for (const [name, payload] of Object.entries(data.broken)) {
  const errors = F.validateCaseBook(payload);
  if (name === "tampered_seal") check("tampered seal still loads", errors.length === 0, errors);
  else check(`broken book rejected: ${name}`, errors.length > 0, errors);
}
for (const [name, item] of Object.entries(data.edge)) {
  const errors = F.validateCaseBook(item.payload);
  check(`edge ${name}: valid=${item.valid}`, (errors.length === 0) === item.valid, errors);
}
const norm = F.normalizeCaseBook(data.edge.padded_lot.payload);
check("padded lot trimmed", norm.cases[0].lot === "LOT-1004");
check("normalized book has one lot", F.casesSummary(norm).lots === 1);
const normNum = F.normalizeCaseBook(data.edge.numeric_strings.payload);
check("numeric strings coerced", normNum.cases[0].lateness_min === 45 && normNum.cases[0].run.seed === 1);
const ordRows = F.casesLotRows(data.ordering);
check("ordering lot order is code-point", JSON.stringify(ordRows.map((r) => r.lot)) === JSON.stringify(data.expected_lot_order), ordRows.map((r) => r.lot));
const lot1 = ordRows.find((r) => r.lot === "LOT-1");
check("ordering case order is numeric", JSON.stringify(lot1.cases.map((c) => c.case_id)) === JSON.stringify(data.expected_case_order_lot1), lot1.cases.map((c) => c.case_id));
const filtered = F.casesFilteredBook(data.valid, "resolved");
check("filter resolved keeps 1 case", filtered.cases.length === 1 && filtered.cases[0].status === "resolved");
check("Feb 30 rejected", F.casesParseIso("2026-02-30T09:00:00Z") === null);
check("Feb 29 leap year accepted", F.casesParseIso("2024-02-29T09:00:00Z") !== null);
console.log(JSON.stringify({ failures }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_cases_page_parity_with_cases_py(tmp_path: Path) -> None:
    driver = tmp_path / "cases_page_driver.cjs"
    driver.write_text(DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(FIXTURE), str(CASES_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []


def test_cases_page_fixture_is_valid_json() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["valid"]["book_version"] == "cases/v0"
    assert data["expected_lots"]
    assert data["edge"]


def test_illegal_transition_is_rejected_by_from_json() -> None:
    from pydantic import ValidationError

    from resilimes.explain.cases import CaseBook

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        CaseBook.from_json(data["edge"]["illegal_transition"]["payload"])
