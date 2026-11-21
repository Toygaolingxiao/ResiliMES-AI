"""Count style violations against the Wave 0 budget file.

The allowed spacing set is still the legacy token ladder {0,4,8,12,16}
for counting; the owner-locked control/row heights 24/32/40/48 land as
lint targets in Wave 1. Raising any metric above its budget fails CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from resilimes.config import ROOT

BUDGET_PATH = ROOT / "docs" / "design" / "VIOLATION_BUDGET.json"
STATIC = ROOT / "resilimes" / "demo" / "static"

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGBA = re.compile(r"rgba?\([^)]+\)")
_SPACE = re.compile(
    r"(?:padding|margin|gap|row-gap|column-gap|inset|"
    r"(?:padding|margin)-(?:top|right|bottom|left)|"
    r"top|right|bottom|left)\s*:[^;{}]*?(\d+)px"
)
_FONT = re.compile(r"font-size:\s*([\d.]+)px")
_BP = re.compile(r"@media[^{]*?(?:max|min)-width:\s*(\d+)px")
_TOKEN_DEF = re.compile(r"^\s*--[\w-]+\s*:")

_ALLOWED_SPACE = {0, 4, 8, 12, 16}
_ALLOWED_FONT = {12.0, 13.0, 14.0, 16.0, 28.0, 32.0}
_BASELINE_BP = {1500, 1440, 1320, 1279, 1023}


def load_budget() -> dict[str, Any]:
    return json.loads(BUDGET_PATH.read_text(encoding="utf-8"))


def _iter_css() -> list[Path]:
    return sorted(STATIC.rglob("*.css"))


def _iter_js() -> list[Path]:
    return sorted(STATIC.rglob("*.js"))


def count_violations() -> dict[str, int]:
    css_hex = css_rgba = 0
    for path in _iter_css():
        for line in path.read_text(encoding="utf-8").splitlines():
            if _TOKEN_DEF.match(line):
                continue
            css_hex += len(_HEX.findall(line))
            css_rgba += len(_RGBA.findall(line))

    js_hex = js_rgba = 0
    for path in _iter_js():
        text = path.read_text(encoding="utf-8")
        js_hex += len(_HEX.findall(text))
        js_rgba += len(_RGBA.findall(text))

    spacing = font = bp = 0
    for path in _iter_css():
        for line in path.read_text(encoding="utf-8").splitlines():
            for match in _SPACE.finditer(line):
                if int(match.group(1)) not in _ALLOWED_SPACE:
                    spacing += 1
            for match in _FONT.finditer(line):
                if float(match.group(1)) not in _ALLOWED_FONT:
                    font += 1
            for match in _BP.finditer(line):
                if int(match.group(1)) not in _BASELINE_BP:
                    bp += 1

    return {
        "css_hex_outside_token_defs": css_hex,
        "css_rgba_outside_token_defs": css_rgba,
        "js_hex_literals": js_hex,
        "js_rgba_literals": js_rgba,
        "spacing_outside_legacy_ladder": spacing,
        "font_size_outside_text_tokens": font,
        "breakpoints_outside_baseline": bp,
    }
