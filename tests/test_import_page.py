"""Import page: the dropped file itself is shown under the result.

The page parses the file in the browser (CSV / JSON / JSON lines) and
renders the first rows as a table, so the reader sees what was in the
file, not only the verdict. These tests pin the page hooks and the
catalogue strings; the parser itself is browser JS with no Python
equivalent.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.i18n import catalog

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "resilimes" / "demo" / "static"
IMPORT = STATIC / "product" / "import"


def test_import_page_has_a_contents_section_under_the_result() -> None:
    html = (IMPORT / "import.html").read_text(encoding="utf-8")
    assert 'id="contents"' in html
    assert html.index('id="result"') < html.index('id="contents"')
    assert "import.js?v=3" in html


def test_import_script_parses_and_renders_the_file() -> None:
    script = (IMPORT / "import.js").read_text(encoding="utf-8")
    for hook in (
        "function parseContents",
        "function parseCsv",
        "function tableFromObjects",
        "function renderContents",
        "contentsTitle",
        "contentsMeta",
        "contentsUnparsed",
    ):
        assert hook in script
    # The preview is a preview: rows and cells are capped.
    assert "MAX_SHOWN = 100" in script
    assert "MAX_CELL = 120" in script


def test_contents_strings_exist_in_every_language() -> None:
    data = catalog()
    for lang in ("en", "zh", "ja"):
        section = data[lang]["import"]
        assert section["contentsTitle"].strip()
        assert "{total}" in section["contentsMeta"]
        assert "{shown}" in section["contentsMeta"]
        assert "{name}" in section["contentsMeta"]
        assert section["contentsUnparsed"].strip()


def test_import_route_still_serves_the_page() -> None:
    settings = Settings(
        mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="<redacted>"
    )
    client = TestClient(create_app(settings))
    response = client.get("/import")
    assert response.status_code == 200
    assert 'id="contents"' in response.text
