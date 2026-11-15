"""Product pages and workshop pages live in separate directories.

The console route and the old script URLs still respond.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "resilimes" / "demo" / "static"


def test_pages_are_split_and_the_console_route_still_works() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for path in (
        "/assets/workshop/console/console.js",
        "/assets/workshop/overview/overview.js",
        "/assets/ai.js",
        "/assets/product/evidence/evidence.js",
        "/assets/product/explanation/explanation.js",
        "/assets/product/replay/replay.js",
        "/assets/product/quality/quality.js",
        "/assets/product/cases/cases.js",
    ):
        assert path in index
    assert 'id="panel-recover"' in index
    assert 'id="panel-cases"' in index
    assert "function paintAnalyze" not in (STATIC / "workshop/console/console.js").read_text(
        encoding="utf-8"
    )
    assert "function paintAnalyze" in (STATIC / "product/quality/quality.js").read_text(
        encoding="utf-8"
    )
    assert "function paintCases" in (STATIC / "product/cases/cases.js").read_text(encoding="utf-8")
    assert "function paintCases" not in (STATIC / "workshop/console/console.js").read_text(
        encoding="utf-8"
    )
    assert '"cases"' in (STATIC / "workshop/console/console.js").read_text(encoding="utf-8")
    assert 'id: "notes"' in (STATIC / "ai.js").read_text(encoding="utf-8")
    assert "function renderReplay" in (STATIC / "product/replay/replay.js").read_text(
        encoding="utf-8"
    )
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="panel-recover"' in page.text
    assert 'id="panel-cases"' in page.text
    assert "/assets/product/cases/cases.js" in page.text
    console = client.get("/assets/workshop/console/console.js")
    assert console.status_code == 200
    assert "function paint(" in console.text
    legacy = client.get("/assets/app.js")
    assert legacy.status_code == 200
    assert legacy.text == console.text
    overview = client.get("/assets/fab.js")
    assert overview.status_code == 200
    assert "window.Fab" in overview.text
    assert client.get("/report").status_code == 200
    assert client.get("/import").status_code == 200


def test_quality_report_page_wiring() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/assets/product/quality/quality-report.js" in index
    # The trust view loads before quality.js, which calls into it.
    assert index.index("/assets/product/quality/quality-report.js") < index.index(
        "/assets/product/quality/quality.js"
    )
    report_js = (STATIC / "product/quality/quality-report.js").read_text(encoding="utf-8")
    assert "function validateQualityReport" in report_js
    assert "function normalizeQualityReport" in report_js
    assert "function paintQualityReport" in report_js
    assert "function qualityViewToggle" in report_js
    quality_js = (STATIC / "product/quality/quality.js").read_text(encoding="utf-8")
    assert "state.qualityView" in quality_js
    assert "paintQualityReport()" in quality_js
    assert "qualityViewToggle()" in quality_js
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    served = client.get("/assets/product/quality/quality-report.js")
    assert served.status_code == 200
    assert "function validateQualityReport" in served.text
    served_quality = client.get("/assets/product/quality/quality.js")
    assert served_quality.status_code == 200
    assert "function paintAnalyze" in served_quality.text
    page = client.get("/")
    assert page.status_code == 200
    assert "/assets/product/quality/quality-report.js" in page.text
    # The trust view's strings and styles exist in all three languages.
    i18n = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
    for lang in ("en", "zh", "ja"):
        quality = i18n[lang]["quality"]
        for key in (
            "viewKpi",
            "viewTrust",
            "ece",
            "eceDef",
            "unverifiedShort",
            "fileErrorNext",
            "misattributionDen",
        ):
            assert quality[key]
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".quality-report" in styles
    assert ".rate-big" in styles
