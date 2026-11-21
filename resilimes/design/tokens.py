"""Load ``docs/design/tokens.json`` and render the generated review table.

Wave 0 locks the file format and the generator contract (same shape as
``i18n.json`` → ``docs/i18n_review.md``). Wave 1 emits CSS / JS from the
same source; this module already owns the markdown side so the ratchet
can land now.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from resilimes.config import ROOT

TOKENS_PATH = ROOT / "docs" / "design" / "tokens.json"
REVIEW_PATH = ROOT / "docs" / "design" / "TOKENS_REVIEW.md"


@cache
def load_tokens() -> dict[str, Any]:
    data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("$schema") != "resilimes.design.tokens/v1":
        raise TypeError("tokens.json must declare $schema resilimes.design.tokens/v1")
    return data


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _lum(hexv: str) -> float:
    h = hexv.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = _lum(fg), _lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def text_warning_contrast_rows() -> list[tuple[str, str, float]]:
    """Scripted contrast for ``--text-warning`` (#684e00) on common surfaces."""
    data = load_tokens()
    semantic = data["semantic"]["light"]
    fg = semantic["text-warning"]["value"]
    surfaces = [
        ("--card / white", "#ffffff"),
        ("--ground", semantic["ground"]["value"]),
        ("--amber-wash", semantic.get("bg-warning-subtle", {}).get("value", "#fcf4d6")),
        ("--layer-hover", semantic.get("layer-hover", {}).get("value", "#e8e8e8")),
    ]
    return [(label, bg, contrast_ratio(fg, bg)) for label, bg in surfaces]


def review_markdown() -> str:
    data = load_tokens()
    lines = [
        "# ResiliMES design tokens",
        "",
        "Generated from `docs/design/tokens.json`. Do not edit the table by hand —",
        "run `python scripts/regen_tokens_review.py`. Format: `resilimes.design.tokens/v1`.",
        "Wave 1 will emit CSS variables and JS constants from the same file.",
        "",
        "| Token | Layer | Light | Dark | Role |",
        "| --- | --- | --- | --- | --- |",
    ]
    primitive = data.get("primitive", {})
    for name, node in primitive.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{name}`",
                    "primitive",
                    _cell(str(node.get("value", ""))),
                    "—",
                    _cell(str(node.get("role", ""))),
                ]
            )
            + " |"
        )
    for theme_name, theme in (
        ("light", data["semantic"]["light"]),
        ("dark", data["semantic"]["dark"]),
    ):
        if theme_name == "dark":
            continue
        dark = data["semantic"]["dark"]
        for name, node in theme.items():
            dark_node = dark.get(name, {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`--{name}`",
                        "semantic",
                        _cell(str(node.get("value", ""))),
                        _cell(str(dark_node.get("value", "—"))),
                        _cell(str(node.get("role", ""))),
                    ]
                )
                + " |"
            )
    chart = data.get("chart", {})
    for theme_name, palette in chart.items():
        for name, node in palette.items():
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`chart.{theme_name}.{name}`",
                        "chart",
                        _cell(str(node.get("value", ""))) if theme_name == "light" else "—",
                        _cell(str(node.get("value", ""))) if theme_name == "dark" else "—",
                        _cell(str(node.get("role", "chart data"))),
                    ]
                )
                + " |"
            )
    lines.append("")
    lines.append("## `--text-warning` contrast (scripted)")
    lines.append("")
    lines.append("| Foreground | Background | Ratio | AA text (≥4.5) |")
    lines.append("| --- | --- | --- | --- |")
    for label, bg, ratio in text_warning_contrast_rows():
        ok = "pass" if ratio >= 4.5 else "FAIL"
        lines.append(f"| `--text-warning` `#684e00` | {label} `{bg}` | {ratio:.2f}:1 | {ok} |")
    lines.append("")
    return "\n".join(lines)
