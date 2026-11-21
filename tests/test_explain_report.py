"""The report page lays out an Evidence Schema bundle and does not run the twin."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.explain.lateness import decompose
from resilimes.explain.record import Timeline, Visit
from resilimes.explain.report import build_report
from resilimes.explain.schema import (
    EvidenceBundle,
    EvidenceItem,
    RunRef,
    Subject,
    lateness_bundle,
)

REF = RunRef(seed=1, horizon_sec=3600.0, policy="resilimes")


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        subject=Subject(kind="lot", id="Lot-1"),
        run=REF,
        items=(
            EvidenceItem(key="lateness", tier="recorded", value=60.0, unit="sec", sources=("due",)),
            EvidenceItem(
                key="overrun.down", tier="attributed", value=40.0, unit="sec", sources=("visits",)
            ),
            EvidenceItem(
                key="overrun.dispatch_other",
                tier="unknown",
                value=20.0,
                unit="sec",
                reason="a tool was idle and the record has no cause (pin, gate or wake latency)",
            ),
        ),
    ).sealed()


def test_report_lists_tier_sources_and_hash():
    bundle = _bundle()
    report = build_report(bundle)
    assert report["schema_version"] == "evidence/v0"
    assert report["verified"] is True
    assert report["content_hash"] == bundle.content_hash
    assert report["content_hash"].startswith("sha256:")
    by_key = {row["key"]: row for row in report["statements"]}
    assert by_key["lateness"]["tier"] == "recorded"
    assert by_key["lateness"]["sources"] == ["due"]
    assert by_key["overrun.down"]["tier"] == "attributed"
    assert by_key["overrun.dispatch_other"]["tier"] == "unknown"
    assert by_key["overrun.dispatch_other"]["reason"]
    assert report["sections"]["what"] == ["lateness"]
    assert report["sections"]["why"] == ["overrun.down"]
    assert report["sections"]["unconfirmed"] == [
        {
            "key": "overrun.dispatch_other",
            "reason": by_key["overrun.dispatch_other"]["reason"],
        }
    ]
    assert report["coverage"]["percent"] == {
        "recorded": 50.0,
        "attributed": 33.3,
        "unknown": 16.7,
    }
    changed = bundle.model_copy(update={"content_hash": "sha256:" + "0" * 64})
    assert build_report(changed)["verified"] is False


def _hand_record():
    route = SimpleNamespace(batch_max=[0], cycle=[300.0])
    fab = SimpleNamespace(
        families=[SimpleNamespace(tool0=0, tools=1, name="F0")],
        routes=[route],
        lot_route=[0],
        lot_due=[100.0],
        lot_id=["Lot-1"],
        lot_product=["P"],
        lot_class=["regular"],
    )
    visit = Visit(lot=0, step=0, family=0, ready=0.0, start=100.0, tool=0, leave=400.0)
    visit.outcome = "done"
    timeline = Timeline(
        fab=fab,
        horizon=1000.0,
        downs=[[(0.0, 100.0)]],
        pm=[[]],
        visits={0: [visit]},
        busy=[[(100.0, 400.0)]],
        reserved=[[]],
        completed={0: 400.0},
        by_family={0: [visit]},
    )
    ref = RunRef(seed=1, horizon_sec=1000.0, policy="resilimes")
    return SimpleNamespace(timeline=timeline, ref=ref)


def test_report_routes_read_a_bundle_and_leave_the_console(monkeypatch):
    record = _hand_record()
    monkeypatch.setattr(
        "resilimes.api.explain_pages.baseline_record", lambda seed, horizon_h: record
    )
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    listed = client.get("/api/explain/report/lots", params={"seed": 1, "horizon_h": 1})
    assert listed.status_code == 200
    assert listed.json()["lots"][0]["lot"] == "Lot-1"

    body = client.get("/api/explain/report", params={"lot": "Lot-1", "seed": 1, "horizon_h": 1})
    assert body.status_code == 200
    payload = body.json()
    assert payload["verified"] is True
    assert payload["subject"]["id"] == "Lot-1"
    assert any(row["sources"] for row in payload["statements"])
    split = lateness_bundle(decompose(record.timeline, 0), record.ref)
    assert payload["content_hash"] == split.content_hash

    checked = client.post("/api/explain/report/verify", json=payload["bundle"])
    assert checked.status_code == 200
    assert checked.json()["verified"] is True
    assert checked.json()["recomputed"] == payload["content_hash"]

    tampered = dict(payload["bundle"])
    tampered["content_hash"] = "sha256:" + "ab" * 32
    assert client.post("/api/explain/report/verify", json=tampered).json()["verified"] is False
    assert (
        client.get("/api/explain/report", params={"lot": "missing", "seed": 1}).status_code == 404
    )

    page = client.get("/report")
    assert page.status_code == 200
    assert "/assets/product/report/report.js" in page.text
    index = client.get("/")
    assert index.status_code == 200
    assert 'id="report-link"' in index.text
    assert 'href="/report"' in index.text
    assert 'id="panel-recover"' in index.text


# --- Visible range validation on the report form (2026-11-21 UI audit,
# high finding 3): an out-of-range seed read as [invalid] to assistive
# tech but showed nothing on screen and the request still fired. The
# page now checks each value against the domain the server enforces
# and renders the message next to the field, in all three languages.
# The domains differ per field: seed is an integer in [1, 4];
# horizon_h is a float in (0, 168] — fractional horizons are legal
# and arrive via Gantt deep links, so the horizon is not held to the
# seed's integer rule.

ROOT = Path(__file__).resolve().parents[1]
REPORT_JS = ROOT / "resilimes" / "demo" / "static" / "product" / "report" / "report.js"
I18N = ROOT / "resilimes" / "demo" / "static" / "i18n.json"


def test_report_range_messages_exist_in_all_languages():
    catalog = json.loads(I18N.read_text(encoding="utf-8"))
    for locale in ("en", "zh", "ja"):
        report = catalog[locale]["report"]
        seed_message = report["seedRange"]
        assert "{min}" in seed_message and "{max}" in seed_message, (locale, seed_message)
        horizon_message = report["horizonRange"]
        assert "{max}" in horizon_message, (locale, horizon_message)
        assert report["notUpdated"], locale


def test_report_page_carries_the_error_elements():
    client = TestClient(
        create_app(
            Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="<redacted>")
        )
    )
    page = client.get("/report")
    assert page.status_code == 200
    assert 'id="seed-error"' in page.text
    assert 'id="horizon-error"' in page.text
    assert 'aria-describedby="seed-error"' in page.text
    assert 'aria-describedby="horizon-error"' in page.text
    # The page's own validation is authoritative; native bubbles
    # would race it and would reject legal fractional horizons.
    assert "novalidate" in page.text


def test_report_js_gates_the_fetch_on_the_range_check():
    src = REPORT_JS.read_text(encoding="utf-8")
    assert "function rangeProblem(" in src
    assert "function horizonProblem(" in src
    body = src[src.index("async function loadReport") :]
    gate = body.index("paintRangeErrors()")
    fetch_at = body.index("/api/explain/report/lots")
    assert gate < fetch_at, "loadReport must validate before it fetches"
    assert "return" in body[gate:fetch_at], "a failed check must stop the load"
    # The values sent are the validated ones in canonical form, so a
    # literal like "3.0" cannot pass the page and 422 at the server.
    assert "String(Number(" in body[gate:]
    assert 'addEventListener("input", onRangeInput)' in src
    exports = src.rsplit("window.ResiliReport", 1)[1]
    assert "rangeProblem" in exports and "horizonProblem" in exports


RANGE_DRIVER = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf-8");
function extract(re) {
  const match = src.match(re);
  return match ? eval(`(${match[0]})`) : null;
}
const rangeProblem = extract(/function rangeProblem\(value, min, max\) \{[\s\S]*?\n  \}/);
const horizonProblem = extract(/function horizonProblem\(value, max\) \{[\s\S]*?\n  \}/);
const failures = [];
function check(name, actual, expected) {
  if (actual !== expected) failures.push(`${name}: got ${actual}, want ${expected}`);
}
if (!rangeProblem || !horizonProblem) {
  failures.push("rangeProblem/horizonProblem not found");
} else {
  // Seed: integer domain, taken from the input's own attributes at
  // the call site, so it must follow any declared domain.
  check("seed lower bound ok", rangeProblem("1", 1, 4), false);
  check("seed upper bound ok", rangeProblem("4", 1, 4), false);
  check("seed zero rejected", rangeProblem("0", 1, 4), true);
  check("seed negative rejected", rangeProblem("-5", 1, 4), true);
  check("seed above max rejected", rangeProblem("5", 1, 4), true);
  check("seed 9 ok once the domain is 1-9", rangeProblem("9", 1, 9), false);
  check("seed 10 rejected in the 1-9 domain", rangeProblem("10", 1, 9), true);
  check("seed fraction rejected", rangeProblem("1.5", 1, 4), true);
  check("empty rejected", rangeProblem("", 1, 4), true);
  check("non-numeric rejected", rangeProblem("abc", 1, 4), true);
  // Horizon: the server's float domain (0, 168].
  check("horizon 48.5 ok", horizonProblem("48.5", 168), false);
  check("horizon 0.5 ok", horizonProblem("0.5", 168), false);
  check("horizon upper bound ok", horizonProblem("168", 168), false);
  check("horizon zero rejected", horizonProblem("0", 168), true);
  check("horizon negative rejected", horizonProblem("-1", 168), true);
  check("horizon above max rejected", horizonProblem("168.5", 168), true);
  check("horizon empty rejected", horizonProblem("", 168), true);
  check("horizon non-numeric rejected", horizonProblem("abc", 168), true);
}
console.log(JSON.stringify({ failures }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_report_range_problem_parity(tmp_path):
    driver = tmp_path / "report_range_driver.cjs"
    driver.write_text(RANGE_DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(REPORT_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []
