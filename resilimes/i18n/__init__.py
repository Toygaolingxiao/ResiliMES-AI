"""Shared UI strings for the console and the review table."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

_PATH = Path(__file__).resolve().parents[1] / "demo" / "static" / "i18n.json"


@cache
def catalog() -> dict[str, Any]:
    loaded = json.loads(_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError("i18n catalog must be an object")
    return loaded


def phrase(lang: str, key: str, **params: object) -> str:
    node: Any = catalog()[lang]
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(key)
        node = node[part]
    if not isinstance(node, str):
        raise KeyError(key)
    text = node
    for name, value in params.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def flatten(table: dict[str, Any], prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    for key, value in table.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            found.update(flatten(value, name))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                found[f"{name}.{index}"] = str(item)
        else:
            found[name] = str(value)
    return found


def review_markdown() -> str:
    data = catalog()
    en = flatten(data["en"])
    zh = flatten(data["zh"])
    ja = flatten(data["ja"])
    keys = list(en)
    lines = [
        "# ResiliMES UI strings",
        "",
        "Every key the console can show. Chinese is zh-CN. Japanese is the wording a fab engineer would use on a shift.",
        "Times in critic messages are the shift clock (the scenario horizon plus the minute offset), not `t=` minutes.",
        "",
        "| Key | English | 中文 | 日本語 |",
        "| --- | --- | --- | --- |",
    ]
    for key in keys:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{key}`",
                    _cell(en[key]),
                    _cell(zh[key]),
                    _cell(ja[key]),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
