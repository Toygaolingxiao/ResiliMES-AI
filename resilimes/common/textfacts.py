"""Ids and numbers in a text, checked against a fact table.

Moved out of ``resilimes.agents.facts`` so the explain layer can use it without
importing agents. Callers import these names from here.

This module is the single place that decides what counts as an id or a
number in a text. The fact-check gate (``explain.factcheck``) and the claim
ledger (``explain.claims``) both extract through here, so the two can never
drift apart on token shapes.

Extraction rules:

- Numbers: plain integers and decimals, plus comma-grouped thousands
  (``1,000`` is one number, normalised to ``1000`` — never ``1`` and ``000``).
- Ids: separator tokens — alphanumerical segments joined by ``-`` or ``_``,
  separators may mix (``FE-120_A``) and the first segment may start with a
  digit (``3M_Lot_9``). A token only counts as a claimable id when it
  carries both a letter and a digit: ``tool-hours`` and ``snake_case`` are
  prose, and a pure-numeric token such as a date (``2026-11-18``) or a
  range (``5-10``) is not an id.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b")
_ID_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+")
_HAS_DIGIT = re.compile(r"\d")
_HAS_LETTER = re.compile(r"[A-Za-z]")


def id_token_matches(text: str) -> list[re.Match[str]]:
    """Separator-token matches that count as ids (letter + digit present)."""
    return [
        match
        for match in _ID_TOKEN.finditer(text)
        if _HAS_DIGIT.search(match.group()) and _HAS_LETTER.search(match.group())
    ]


def id_tokens(text: str) -> list[str]:
    """The id-shaped tokens in ``text``, in order of appearance."""
    return [match.group() for match in id_token_matches(text)]


def narrative_mismatches(text: str, facts: dict[str, set[str]]) -> list[str]:
    """Ids and numbers in ``text`` that the fact table does not contain."""
    misses: list[str] = []
    seen: set[str] = set()
    ext_spans = [(m.start(), m.end()) for m in id_token_matches(text)]
    for match in _ID.finditer(text):
        token = match.group()
        # A legacy hyphen match that is only the head of a longer
        # mixed-separator token ("FE-120" inside "FE-120_A") is not a
        # separate id; the longer token is judged below, once.
        if any(start <= match.start() and match.end() < end for start, end in ext_spans):
            continue
        if token.upper() in facts["ids"] or token.upper() in seen:
            continue
        seen.add(token.upper())
        misses.append(f"unknown id {token}")
    for token in id_tokens(text):
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
    raw = raw.replace(",", "")
    if "." in raw:
        return raw.rstrip("0").rstrip(".")
    return raw
