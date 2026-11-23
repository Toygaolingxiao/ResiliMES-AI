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
CSS_PATH = ROOT / "resilimes" / "demo" / "static" / "design" / "tokens.css"
JS_PATH = ROOT / "resilimes" / "demo" / "static" / "design" / "tokens.js"


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
        ("--card / white", semantic["card"]["value"]),
        ("--ground", semantic["ground"]["value"]),
        ("--bg-warning-subtle", semantic.get("bg-warning-subtle", {}).get("value", "#fcf4d6")),
        ("--layer-hover", semantic.get("layer-hover", {}).get("value", "#e8e8e8")),
    ]
    return [(label, bg, contrast_ratio(fg, bg)) for label, bg in surfaces]


def text_contrast_rows() -> list[dict[str, Any]]:
    """AA contrast for every ``text-*`` token; graphic-* on card (non-text 3:1)."""
    data = load_tokens()
    rows: list[dict[str, Any]] = []
    for theme_name in ("light", "dark"):
        semantic = data["semantic"][theme_name]
        card = semantic["card"]["value"]
        ground = semantic["ground"]["value"]
        for name, node in semantic.items():
            if not name.startswith("text-"):
                continue
            fg = str(node["value"])
            surfaces: list[tuple[str, str]] = [
                (f"--card ({theme_name})", card),
                (f"--ground ({theme_name})", ground),
            ]
            role = name.removeprefix("text-")
            subtle_key = f"bg-{role}-subtle"
            if subtle_key in semantic:
                surfaces.append(
                    (f"--{subtle_key} ({theme_name})", str(semantic[subtle_key]["value"]))
                )
            for label, bg in surfaces:
                ratio = contrast_ratio(fg, bg)
                rows.append(
                    {
                        "theme": theme_name,
                        "token": f"--{name}",
                        "foreground": fg,
                        "background_label": label,
                        "background": bg,
                        "ratio": ratio,
                        "min_ratio": 4.5,
                    }
                )
        ink = semantic["ink"]["value"]
        for name, node in semantic.items():
            if not name.startswith("graphic-"):
                continue
            fg = str(node["value"])
            graphic_surfaces: list[tuple[str, str]] = [(f"--card ({theme_name})", card)]
            if theme_name == "light":
                graphic_surfaces.append((f"--ink ({theme_name})", ink))
            for label, bg in graphic_surfaces:
                ratio = contrast_ratio(fg, bg)
                rows.append(
                    {
                        "theme": theme_name,
                        "token": f"--{name}",
                        "foreground": fg,
                        "background_label": label,
                        "background": bg,
                        "ratio": ratio,
                        "min_ratio": 3.0,
                    }
                )
    return rows


def _css_var_block(theme: dict[str, Any], chart: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    for name, node in theme.items():
        lines.append(f"  --{name}: {node['value']};")
    if chart:
        for name, node in chart.items():
            lines.append(f"  --chart-{name}: {node['value']};")
    return lines


def css_text() -> str:
    data = load_tokens()
    lines = [
        "/* Generated from docs/design/tokens.json. Do not edit by hand.",
        "   Run: python scripts/regen_tokens_css.py */",
        "",
        ":root {",
    ]
    lines.extend(_css_var_block(data["semantic"]["light"], data.get("chart", {}).get("light")))
    lines.append("}")
    lines.append("")
    lines.append('html[data-theme="dark"] {')
    lines.extend(_css_var_block(data["semantic"]["dark"], data.get("chart", {}).get("dark")))
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _js_object(d: dict[str, Any]) -> str:
    return json.dumps(
        {k: v["value"] for k, v in d.items()},
        indent=2,
        ensure_ascii=False,
    )


def js_text() -> str:
    data = load_tokens()
    sem_light = _js_object(data["semantic"]["light"])
    sem_dark = _js_object(data["semantic"]["dark"])
    chart = data.get("chart", {})
    chart_light = _js_object(chart.get("light", {}))
    chart_dark = _js_object(chart.get("dark", {}))
    return "\n".join(
        [
            "/* Generated from docs/design/tokens.json. Do not edit by hand.",
            "   Run: python scripts/regen_tokens_js.py */",
            '"use strict";',
            "",
            "const SEMANTIC = {",
            f"  light: {sem_light},",
            f"  dark: {sem_dark},",
            "};",
            "",
            "const CHART = {",
            f"  light: {chart_light},",
            f"  dark: {chart_dark},",
            "};",
            "",
        ]
    )


def review_markdown() -> str:
    data = load_tokens()
    lines = [
        "# ResiliMES design tokens",
        "",
        "Generated from `docs/design/tokens.json`. Do not edit the table by hand —",
        "run `python scripts/regen_tokens_review.py`. Format: `resilimes.design.tokens/v1`.",
        "CSS/JS: scripts/regen_tokens_css.py / regen_tokens_js.py → demo/static/design/.",
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
