"""Product pages and workshop pages live in separate directories.

The console route and the old script URLs still respond.
"""

from __future__ import annotations

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
    ):
        assert path in index
    assert 'id="panel-recover"' in index
    assert "function paintAnalyze" not in (STATIC / "workshop/console/console.js").read_text(
        encoding="utf-8"
    )
    assert "function paintAnalyze" in (STATIC / "product/quality/quality.js").read_text(
        encoding="utf-8"
    )
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
