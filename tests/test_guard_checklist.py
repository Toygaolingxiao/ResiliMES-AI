"""Wave 0: listed guard tests and doc headings must stay present (#121 / #119)."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from resilimes.config import ROOT

CHECKLIST = ROOT / "docs" / "design" / "GUARD_CHECKLIST.json"


def _load() -> dict:
    return json.loads(CHECKLIST.read_text(encoding="utf-8"))


def _def_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_guard_checklist_present() -> None:
    data = _load()
    assert data["tests"], "guard checklist tests must not be empty"
    assert data["doc_headings"], "guard checklist doc headings must not be empty"

    missing_tests: list[str] = []
    for entry in data["tests"]:
        path = ROOT / entry["file"]
        if not path.is_file():
            missing_tests.append(f"{entry['id']}: missing file {entry['file']}")
            continue
        names = _def_names(path)
        if entry["node"] not in names:
            missing_tests.append(
                f"{entry['id']}: {entry['node']} not in {entry['file']} "
                f"(present={sorted(n for n in names if n.startswith('test_'))[:8]}…)"
            )
    assert not missing_tests, "guard tests disappeared:\n" + "\n".join(missing_tests)

    missing_docs: list[str] = []
    for entry in data["doc_headings"]:
        path = ROOT / entry["file"]
        if not path.is_file():
            missing_docs.append(f"{entry['id']}: missing file {entry['file']}")
            continue
        text = path.read_text(encoding="utf-8")
        if entry["heading"] not in text.splitlines():
            missing_docs.append(
                f"{entry['id']}: heading {entry['heading']!r} missing from {entry['file']}"
            )
    assert not missing_docs, "guard doc headings disappeared:\n" + "\n".join(missing_docs)


def test_tokens_review_matches_generator() -> None:
    from resilimes.design.tokens import REVIEW_PATH, review_markdown

    assert REVIEW_PATH.is_file(), "run python scripts/regen_tokens_review.py"
    text = REVIEW_PATH.read_text(encoding="utf-8")
    expected = review_markdown()
    assert text.startswith(expected), "TOKENS_REVIEW.md drifted from tokens.json"


def test_screenshot_matrix_covers_wave0_scope() -> None:
    matrix = json.loads(
        (ROOT / "tools" / "screenshot-baseline" / "matrix.json").read_text(encoding="utf-8")
    )
    langs = set(matrix["langs"])
    themes = set(matrix["themes"])
    widths = set(matrix["widths_px"])
    assert langs == {"en", "zh", "ja"}
    assert themes == {"light", "dark"}
    assert 1023 in widths
    assert len(widths) == 2
    pages = {p["id"] for p in matrix["pages"]}
    for required in ("console", "report", "import", "timeline"):
        assert required in pages, f"screenshot matrix missing page {required}"
    assert any(p.get("pseudo_l10n") for p in matrix["pages"]), (
        "matrix must include one pseudo-localization page"
    )
    # expected shot count: pages x langs x themes x widths (+ pseudo extras)
    base_pages = [p for p in matrix["pages"] if not p.get("pseudo_l10n")]
    expected = len(base_pages) * len(langs) * len(themes) * len(widths)
    # plus pseudo-l10n variants declared by the matrix
    pseudo = [p for p in matrix["pages"] if p.get("pseudo_l10n")]
    expected += (
        len(pseudo)
        * len(matrix.get("pseudo_langs", ["en"]))
        * len(matrix.get("pseudo_themes", ["light"]))
        * len(matrix.get("pseudo_widths", [max(widths)]))
    )
    assert matrix["expected_shot_count"] == expected
    assert re.fullmatch(r"[0-9]+", str(matrix["expected_shot_count"]))
