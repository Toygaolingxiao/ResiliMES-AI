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
    assert client.get("/timeline").status_code == 200


def test_product_pages_share_console_back_and_peer_links() -> None:
    """Charter workline 5: back means the console everywhere; peers link each other."""
    i18n = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
    for lang in ("en", "zh", "ja"):
        report_back = i18n[lang]["report"]["back"]
        assert i18n[lang]["import"]["back"] == report_back
        assert i18n[lang]["timeline"]["back"] == report_back
        assert report_back  # never blank
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    index = client.get("/")
    assert 'href="/timeline"' in index.text
    assert 'href="/report"' in index.text
    assert 'href="/import"' in index.text
    for path in ("/report", "/import"):
        page = client.get(path)
        assert page.status_code == 200
        assert 'href="/"' in page.text
        assert 'href="/timeline"' in page.text
        assert 'href="/report"' in page.text
        assert 'href="/import"' in page.text
        assert 'data-nav="timeline"' in page.text
        assert 'data-nav="report"' in page.text
        assert 'data-nav="import"' in page.text
        assert 'class="back"' in page.text
    # Timeline chrome is built in JS (empty HTML host).
    timeline_js = client.get("/assets/product/timeline/timeline.js").text
    assert 'href="/"' in timeline_js
    assert 'href="/timeline"' in timeline_js
    assert 'href="/report"' in timeline_js
    assert 'href="/import"' in timeline_js
    assert 'class="tl-home"' in timeline_js
    assert 'data-nav="timeline"' in timeline_js


def test_report_css_link_is_versioned_on_both_pages() -> None:
    """report.css is shared by /report and /import; its link must carry a
    cache-busting version, as the JS links do. #124 changed report.css
    without versioning the link, so returning users could keep stale
    styles; the same PR bumped import.js to ?v=3 while its test still
    pinned ?v=2, which turned main CI red. Pin the version here so a
    future bump without a test update fails loudly instead of silently.
    Wave 1a: semantic tokens load from design/tokens.css before report.css.
    """
    for page in ("report", "import"):
        html = (STATIC / "product" / page / f"{page}.html").read_text(encoding="utf-8")
        assert '/assets/design/tokens.css?v=1"' in html
        tokens_idx = html.index("/assets/design/tokens.css")
        report_idx = html.index("/assets/product/report/report.css")
        assert tokens_idx < report_idx
        # Anchor to the closing quote: a bare "?v=2" substring would also
        # match "?v=20" / "?v=200" and silently pass a drifted version.
        assert '/assets/product/report/report.css?v=3"' in html
        assert '/assets/product/report/report.css"' not in html
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    served = client.get("/assets/product/report/report.css?v=3")
    assert served.status_code == 200
    assert ".product-nav" in served.text
    assert "var(--accent)" in served.text


def test_i18n_json_fetch_is_versioned_everywhere() -> None:
    """i18n.json is fetched bare from four scripts; #124 changed its copy
    (back copy now reads "Back to the console") without versioning any of
    them, so a returning user can get new JS with stale strings. Same
    defect class as report.css in this increment, fixed in the same pass.
    Version rule (per-asset counter, first versioning is v=1); the
    pre-existing timeline.css?v=2 anomaly from #124 is left as-is.
    """
    for script in (
        "product/import/import.js",
        "product/report/report.js",
        "product/timeline/timeline.js",
        "workshop/console/console.js",
    ):
        text = (STATIC / script).read_text(encoding="utf-8")
        assert '/assets/i18n.json?v=2"' in text
        assert '"/assets/i18n.json"' not in text
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    served = client.get("/assets/i18n.json?v=2")
    assert served.status_code == 200
    assert "Back to the console" in served.text


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
    assert "function qualityServerReport" in report_js
    assert "function qualityLoadServer" in report_js
    assert "/api/quality?variant=" in report_js
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
