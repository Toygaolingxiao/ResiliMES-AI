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
BASELINE_PATH = ROOT / "docs" / "design" / "VIOLATION_BUDGET_BASELINE.json"
STATIC = ROOT / "resilimes" / "demo" / "static"
_TOKEN_EMIT = STATIC / "design"

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGBA = re.compile(r"rgba?\([^)]+\)")
# A spacing declaration: <property>: <value>, where the property is one of
# padding/margin/gap/row-gap/column-gap/inset, a padding-/margin- side, or
# a bare top/right/bottom/left offset. The (?<![\w-]) guard keeps the
# property name from matching inside a longer name: without it,
# "border-top: 1px" matched as "top: 1px" and the border width was counted
# as a spacing violation (11(c) fix). Group 1 is the whole declaration
# value, so every px value in it is examined; shorthand later positions
# used to be missed ("padding: 6px 14px" counted only the 6).
# Calibre note: grid-gap, scroll-margin/scroll-padding and logical
# properties (padding-inline etc.) are NOT in this set, so they are not
# counted — a deliberate narrowing vs the old counter, which counted
# grid-gap via substring match. No such property occurs in the counted
# files today (verified 2026-11-24), so the 185 is unaffected.
_COMMENT = re.compile(r"/\*.*?\*/")
_SPACE = re.compile(
    r"(?<![\w-])(?:padding|margin|gap|row-gap|column-gap|inset|"
    r"(?:padding|margin)-(?:top|right|bottom|left)|"
    r"top|right|bottom|left)\s*:([^;{}]*)"
)
_PX_VALUE = re.compile(r"(\d+(?:\.\d+)?)px")
_FONT = re.compile(r"font-size:\s*([\d.]+)px")
_BP = re.compile(r"@media[^{]*?(?:max|min)-width:\s*(\d+)px")
_TOKEN_DEF = re.compile(r"^\s*--[\w-]+\s*:")

_ALLOWED_SPACE = {0, 4, 8, 12, 16}
_ALLOWED_FONT = {12.0, 13.0, 14.0, 16.0, 28.0, 32.0}
_BASELINE_BP = {1500, 1440, 1320, 1279, 1023}


def load_budget() -> dict[str, Any]:
    return json.loads(BUDGET_PATH.read_text(encoding="utf-8"))


def load_baseline() -> dict[str, Any]:
    """Frozen Wave 0 budget values (see VIOLATION_BUDGET_BASELINE.json).

    The baseline is the ratchet's anchor: budgets may only descend from
    it. Raising a budget without also editing that file fails CI; editing
    the baseline file is itself the deliberate, reviewable act, and the
    test cannot check the reason given for it.
    """
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def count_spacing_line(line: str) -> int:
    """Count off-ladder px values in spacing declarations on one line.

    Border widths are not spacing ("border-top: 1px" contributes 0), and
    shorthand counts every position ("padding: 6px 14px" contributes 2).
    Single-line /* ... */ comments are stripped first, so a commented-out
    declaration contributes 0; a comment opened on an earlier line is NOT
    stripped (line-level scan — known limitation, no such case in the
    counted files). Decimal px values are compared as floats ("6.4px"
    counts 1, "4.0px" counts 0); negative values count by magnitude
    ("margin: 0 -2px" counts 1, "margin: 0 -16px" counts 0).
    This is the counter's own ruler, pinned by fixture tests in
    tests/test_style_budget.py (11(c) pins the ruler at line level and
    the counted file set; a count==budget equality assertion is not
    pinned, so silent undercounting still relies on review).
    """
    line = _COMMENT.sub("", line)
    n = 0
    for match in _SPACE.finditer(line):
        for value in _PX_VALUE.findall(match.group(1)):
            if float(value) not in _ALLOWED_SPACE:
                n += 1
    return n


def _skip_token_emit(path: Path) -> bool:
    """Exclude generated design/tokens.* from hex-literal budgets."""
    try:
        path.relative_to(_TOKEN_EMIT)
    except ValueError:
        return False
    return True


def _iter_css() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*.css") if not _skip_token_emit(p))


def _iter_js() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*.js") if not _skip_token_emit(p))


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
            spacing += count_spacing_line(line)
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
