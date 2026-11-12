"""Ids and numbers in a text, checked against a fact table.

Moved out of ``resilimes.agents.facts`` so the explain layer can use it without
importing agents. ``agents.facts`` re-exports these names.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b")


def narrative_mismatches(text: str, facts: dict[str, set[str]]) -> list[str]:
    """Ids and numbers in ``text`` that the fact table does not contain."""
    misses: list[str] = []
    seen: set[str] = set()
    for token in _ID.findall(text):
        if token.upper() in facts["ids"] or token.upper() in seen:
            continue
        seen.add(token.upper())
        misses.append(f"unknown id {token}")
    for raw in _NUMBER.findall(text):
        number = _norm(raw)
        if number in facts["numbers"] or number in seen:
            continue
        seen.add(number)
        misses.append(f"unknown number {raw}")
    return misses


def _numbers(blob: str) -> set[str]:
    return {_norm(item) for item in _NUMBER.findall(blob)}


def _norm(raw: str) -> str:
    if "." in raw:
        return raw.rstrip("0").rstrip(".")
    return raw
