"""Import page: the dropped file itself is shown under the result.

The page parses the file in the browser (CSV / JSON / JSON lines) and
renders the first rows as a table, so the reader sees what was in the
file, not only the verdict. The parser itself is browser JS; its
behaviour is pinned by a node driver below (vm sandbox, same pattern as
the timeline scope/whyHref parity tests), not by substring hooks alone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.i18n import catalog

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "resilimes" / "demo" / "static"
IMPORT = STATIC / "product" / "import"
IMPORT_JS = IMPORT / "import.js"

# The driver runs import.js in a vm sandbox and exercises the pure
# parser functions it exposes as window.ResiliImport. init() fetches the
# catalogue at load; the stub fetch never resolves, so init stays pending
# and can neither throw nor paint with the stub document.
IMPORT_DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf-8");
const sandbox = {
  window: {},
  document: { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [], documentElement: {} },
  localStorage: { getItem: () => null, setItem: () => {} },
  fetch: () => new Promise(() => {}),
  console,
};
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const F = sandbox.window.ResiliImport;
const failures = [];
function check(name, cond, extra) {
  if (!cond) failures.push(extra === undefined ? name : `${name}: ${JSON.stringify(extra)}`);
}
function eq(actual, expected) {
  return JSON.stringify(actual) === JSON.stringify(expected);
}

// H2: a stray quote mid-field is literal text, not a quoted field.
check("inch mark does not swallow the next row",
  eq(F.parseCsv('name,size\nnail,5" long\nbolt,3\n'),
    [["name", "size"], ["nail", '5" long'], ["bolt", "3"]]),
  F.parseCsv('name,size\nnail,5" long\nbolt,3\n'));
check("stray quote inside a number keeps the row",
  eq(F.parseCsv('a,b\n1,2"3\n4,5\n'), [["a", "b"], ["1", '2"3'], ["4", "5"]]),
  F.parseCsv('a,b\n1,2"3\n4,5\n'));
check("quoted field with a comma still parses",
  eq(F.parseCsv('"a, b",c\n1,2\n'), [["a, b", "c"], ["1", "2"]]));
check("doubled quote inside a quoted field is one quote",
  eq(F.parseCsv('"a""b",c\n'), [['a"b', "c"]]));
check("newline inside a quoted field is kept",
  eq(F.parseCsv('"a\nb",c\n1,2\n'), [["a\nb", "c"], ["1", "2"]]));
check("unclosed quote fails the parse instead of swallowing rows",
  F.parseCsv('"abc\ndef') === null && F.parseContents('"abc\ndef') === null,
  F.parseCsv('"abc\ndef'));
check("CR-only line endings still split rows",
  eq(F.parseCsv("a,b\rc,d\r"), [["a", "b"], ["c", "d"]]));
check("CRLF still splits rows",
  eq(F.parseCsv("a,b\r\n1,2\r\n"), [["a", "b"], ["1", "2"]]));
check("missing trailing newline still flushes the last row",
  eq(F.parseCsv("a,b\n1,2"), [["a", "b"], ["1", "2"]]));

// H1: columns and rows are bounded; totals stay honest.
const wide = [];
for (let i = 0; i < 200; i++) {
  const o = {};
  for (let k = 0; k < 100; k++) o[`k${i}_${k}`] = 1;
  wide.push(o);
}
const wideTable = F.tableFromObjects(wide);
check("wide JSON shows 20 columns of 20000",
  wideTable.columns.length === 20 && wideTable.columnsTotal === 20000, wideTable.columnsTotal);
check("wide JSON materialises 100 rows of 200",
  wideTable.rows.length === 100 && wideTable.total === 200 && wideTable.rows[0].length === 20,
  [wideTable.rows.length, wideTable.total]);
const lateKey = Array.from({ length: 250 }, (_, i) => (i === 249 ? { a: 1, late: 1 } : { a: 1 }));
const lateTable = F.tableFromObjects(lateKey);
check("a key first seen after item 200 is no longer dropped",
  eq(lateTable.columns, ["a", "late"]) && lateTable.columnsTotal === 2, lateTable.columns);
const wideCsv = "h0,h1,h2,h3,h4,h5,h6,h7,h8,h9,h10,h11,h12,h13,h14,h15,h16,h17,h18,h19,h20,h21,h22,h23,h24,h25,h26,h27,h28,h29\n"
  + "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29\n"
  + "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29\n";
const wideCsvTable = F.parseContents(wideCsv);
check("wide CSV header is cut to 20 columns with the true count kept",
  wideCsvTable.columns.length === 20 && wideCsvTable.columnsTotal === 30 && wideCsvTable.total === 2
    && wideCsvTable.rows[0].length === 20,
  wideCsvTable);
const manyRows = Array.from({ length: 250 }, (_, i) => ({ a: i }));
const manyTable = F.tableFromObjects(manyRows);
check("250 rows materialise 100 with total 250",
  manyTable.rows.length === 100 && manyTable.total === 250, [manyTable.rows.length, manyTable.total]);

// H3: a broken JSONL line is skipped and counted, never folded into CSV.
const partial = F.parseContents('{"a":1}\nBAD\n{"a":2}\n');
check("broken JSONL line renders the good rows with a skip count",
  partial && eq(partial.columns, ["a"]) && eq(partial.rows, [["1"], ["2"]])
    && partial.total === 2 && partial.skipped === 1,
  partial);
const scalarLine = F.parseContents('{"a":1}\n42\n{"a":2}');
check("a scalar JSONL line is skipped, not rendered as a blank row",
  scalarLine && scalarLine.total === 2 && scalarLine.skipped === 1 && scalarLine.rows.length === 2,
  scalarLine);
check("all-bad JSONL is unparsed, not a CSV table",
  F.parseContents('{"a":}\n{bad}') === null);
check("JSON-smelling input never falls through to CSV",
  F.parseContents("{bad}\nmore bad") === null);
check("whole-document JSON still works",
  eq(F.parseContents('[{"a":1},{"a":2,"b":9}]').columns, ["a", "b"])
    && F.parseContents('[{"a":1},{"a":2,"b":9}]').total === 2);
check("JSONL key union still works",
  eq(F.parseContents('{"a":1}\n{"a":2,"b":9}').columns, ["a", "b"]));
// H3, second half: a bad FIRST line must not resurrect the fake table.
// The JSONL attempt runs before the CSV fallback for every input; a
// JSON-smelling file needs one object line, anything else needs two,
// so a real CSV with a single JSON-looking line is not hijacked.
const badFirst = F.parseContents('BAD\n{"a":1}\n{"a":2}\n');
check("bad first JSONL line renders the good rows with a skip count",
  badFirst && eq(badFirst.columns, ["a"]) && eq(badFirst.rows, [["1"], ["2"]])
    && badFirst.total === 2 && badFirst.skipped === 1,
  badFirst);
check("scalar first line is skipped, not the header",
  eq(F.parseContents('42\n{"a":1}\n{"a":2}\n').columns, ["a"])
    && F.parseContents('42\n{"a":1}\n{"a":2}\n').skipped === 1);
check("leading log line is skipped, not the header",
  eq(F.parseContents('log start 2026-11-25\n{"a":1}\n{"a":2}\n').columns, ["a"]));
check("comment first line is skipped, not the header",
  F.parseContents('# header\n{"a":1}\n{"a":2}\n').skipped === 1);
check("CR-only JSONL still splits rows",
  eq(F.parseContents('{"a":1}\r{"a":2}\r').rows, [["1"], ["2"]]));
check("a CSV with one JSON-looking line stays a CSV",
  eq(F.parseContents('a,b\n1,2\n{"x":9}\n3,4').columns, ["a", "b"])
    && F.parseContents('a,b\n1,2\n{"x":9}\n3,4').total === 3);
check("ghost empty row from CR CR LF is filtered",
  F.parseContents("a,b\r\r\n1,2").total === 1);

// M4: a leading BOM does not leak into the first column name.
check("BOM is stripped from the first header",
  eq(F.parseContents("\uFEFFa,b\n1,2\n").columns, ["a", "b"]));

// Unchanged behaviour: empty, single-line, and non-tabular JSON stay unparsed.
check("empty and blank files are unparsed",
  F.parseContents("") === null && F.parseContents("   \n  ") === null);
check("single-line CSV is unparsed",
  F.parseContents("only,one\n") === null);
check("JSON scalar array is unparsed",
  F.parseContents("[1,2,3]") === null);
check("JSON array of arrays is unparsed",
  F.parseContents("[[1,2],[3,4]]") === null);

// contentsNotes: one short line per hidden fact, none when nothing hides.
const noteCopy = { contentsColumnsNote: "first {shown} of {total}", contentsSkippedNote: "skipped {skipped}" };
check("column truncation note names shown and total",
  eq(F.contentsNotes({ columns: ["a"], columnsTotal: 5 }, noteCopy), ["first 1 of 5"]));
check("skipped-lines note names the count",
  eq(F.contentsNotes({ columns: ["a"], columnsTotal: 1, skipped: 2 }, noteCopy), ["skipped 2"]));
check("both notes appear together, columns first",
  eq(F.contentsNotes({ columns: ["a"], columnsTotal: 5, skipped: 2 }, noteCopy),
    ["first 1 of 5", "skipped 2"]));
check("no note when nothing is hidden",
  eq(F.contentsNotes({ columns: ["a"], columnsTotal: 1 }, noteCopy), []));
check("missing catalogue keys produce no note, not an empty paragraph",
  eq(F.contentsNotes({ columns: ["a"], columnsTotal: 5, skipped: 2 }, {}), []));

// truncateCell: code-point truncation, never a split surrogate pair.
check("short cell is unchanged",
  F.truncateCell("abc") === "abc");
check("120 code points are unchanged",
  F.truncateCell("a".repeat(120)) === "a".repeat(120));
check("121 code points are cut to 120 plus an ellipsis",
  F.truncateCell("a".repeat(200)) === "a".repeat(120) + "…");
check("a surrogate pair at the cut stays whole",
  F.truncateCell("a".repeat(119) + "\u{1F600}" + "b") === "a".repeat(119) + "\u{1F600}" + "…"
    && Array.from(F.truncateCell("a".repeat(119) + "\u{1F600}" + "b")).length === 121);
console.log(JSON.stringify({ failures }));
"""


def test_import_page_has_a_contents_section_under_the_result() -> None:
    html = (IMPORT / "import.html").read_text(encoding="utf-8")
    assert 'id="contents"' in html
    assert html.index('id="result"') < html.index('id="contents"')
    # Anchor to the closing quote: a bare "?v=3" substring would also
    # match "?v=30" / "?v=300" and silently pass a drifted version.
    # The count pins the reference to exactly one <script> tag: a second
    # copy (e.g. a pasted duplicate with another version) must fail.
    assert '/assets/product/import/import.js?v=4"' in html
    assert '/assets/product/import/import.js"' not in html
    assert html.count("/assets/product/import/import.js") == 1


def test_import_script_parses_and_renders_the_file() -> None:
    script = (IMPORT / "import.js").read_text(encoding="utf-8")
    for hook in (
        "function parseContents",
        "function parseCsv",
        "function tableFromObjects",
        "function jsonLinesTable",
        "function renderContents",
        "function contentsNotes",
        "function truncateCell",
        "window.ResiliImport",
        "contentsTitle",
        "contentsMeta",
        "contentsColumnsNote",
        "contentsSkippedNote",
        "contentsUnparsed",
    ):
        assert hook in script
    # The preview is a preview: rows, cells and columns are capped.
    assert "MAX_SHOWN = 100" in script
    assert "MAX_CELL = 120" in script
    assert "MAX_COLUMNS = 20" in script


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_import_parser_behaviour_parity(tmp_path: Path) -> None:
    driver = tmp_path / "import_parser_driver.cjs"
    driver.write_text(IMPORT_DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(IMPORT_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []


def test_contents_strings_exist_in_every_language() -> None:
    data = catalog()
    for lang in ("en", "zh", "ja"):
        section = data[lang]["import"]
        assert section["contentsTitle"].strip()
        assert "{total}" in section["contentsMeta"]
        assert "{shown}" in section["contentsMeta"]
        assert "{name}" in section["contentsMeta"]
        assert "{shown}" in section["contentsColumnsNote"]
        assert "{total}" in section["contentsColumnsNote"]
        assert "{skipped}" in section["contentsSkippedNote"]
        assert section["contentsUnparsed"].strip()


def test_import_route_still_serves_the_page() -> None:
    settings = Settings(
        mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="<redacted>"
    )
    client = TestClient(create_app(settings))
    response = client.get("/import")
    assert response.status_code == 200
    assert 'id="contents"' in response.text
    # Served page must carry the same versioned script as the file on
    # disk; the disk-only pin above cannot catch a serving-layer drift.
    assert '/assets/product/import/import.js?v=4"' in response.text
