"""Every id and number an AI text quotes must come from evidence it was given.

Reuses ``agents.facts.narrative_mismatches`` (hyphenated ids, numbers) and adds
the SMT2020 id shape, which uses underscores (``Init_Lot_3_17``,
``Diffusion_FE_120``): any underscore token with a digit must be a known id.
Small counting words (0-10) are allowed because "two causes" and "step 1"
are prose, not data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from resilimes.agents.facts import _norm, _numbers, narrative_mismatches

_UNDERSCORE_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_HAS_DIGIT = re.compile(r"\d")
ALWAYS_OK_NUMBERS = frozenset(str(n) for n in range(11))


class FactRegistry:
    """Ids and numbers seen in tool results (and the question)."""

    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.numbers: set[str] = set(ALWAYS_OK_NUMBERS)

    def add_text(self, text: str) -> None:
        self.numbers |= _numbers(text)
        for token in _UNDERSCORE_ID.findall(text):
            self.ids.add(token.upper())
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b", text):
            self.ids.add(token.upper())

    def add(self, payload: Any) -> None:
        self.add_text(json.dumps(payload, ensure_ascii=False, default=str))

    def add_ids(self, ids: Iterable[str]) -> None:
        self.ids |= {item.upper() for item in ids}

    def facts(self) -> dict[str, set[str]]:
        return {"ids": set(self.ids), "numbers": set(self.numbers)}


def check(text: str, registry: FactRegistry) -> list[str]:
    """Unknown ids and numbers in ``text``. Empty list means it passes."""
    facts = registry.facts()
    misses = narrative_mismatches(text, facts)
    seen = {item.split(" ", 2)[-1].upper() for item in misses}
    for token in _UNDERSCORE_ID.findall(text):
        upper = token.upper()
        if not _HAS_DIGIT.search(token) or upper in facts["ids"] or upper in seen:
            continue
        seen.add(upper)
        misses.append(f"unknown id {token}")
    return misses


def number_known(value: str, registry: FactRegistry) -> bool:
    return _norm(value) in registry.numbers
