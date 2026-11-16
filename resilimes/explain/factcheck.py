"""Every id and number an AI text quotes must come from evidence it was given.

Reuses ``common.textfacts.narrative_mismatches`` (hyphenated ids, numbers) and adds
the SMT2020 id shape, which uses underscores (``Init_Lot_3_17``,
``Diffusion_FE_120``): any underscore token with a digit must be a known id.
Small counting words (0-10) are allowed because "two causes" and "step 1"
are prose, not data.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from resilimes.common.textfacts import _norm, _numbers, narrative_mismatches

_UNDERSCORE_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_HYPHEN_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")  # mirrors common.textfacts._NUMBER
_HAS_DIGIT = re.compile(r"\d")
ALWAYS_OK_NUMBERS = frozenset(str(n) for n in range(11))
_MAX_SOURCE_LEN = 200


def _clean_source(source: str | None) -> str | None:
    """Normalise a provenance label, or ``None`` when no label was given.

    Rejects non-strings, empty/whitespace-only labels, labels containing
    control characters, and labels over 200 characters. The stored label
    is the stripped input, so ``"tool:a "`` and ``"tool:a"`` are the same
    source. A rejected label raises before anything is registered.
    """
    if source is None:
        return None
    if not isinstance(source, str):
        raise TypeError("provenance source must be a string")
    label = source.strip()
    if not label:
        raise ValueError("provenance source must not be empty")
    if len(label) > _MAX_SOURCE_LEN:
        raise ValueError("provenance source must be at most 200 characters")
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in label):
        raise ValueError("provenance source must not contain control characters")
    return label


class FactRegistry:
    """Ids and numbers seen in tool results (and the question).

    Provenance (``provenance/v0``) is optional metadata layered on top of
    the gate: ``add_*`` accept a caller-supplied ``source`` label naming
    where a value came from (for example ``"tool:investigator row 3"`` or
    ``"question"``). What the map delivers is per-value candidate source
    labels at whole-payload granularity, in first-seen order — not
    per-occurrence, per-row attribution: a value seen in two sources
    carries both labels, and a label means "this value appeared in that
    source", not "that source supports the quantity being claimed". The
    claim ledger's attribution increment must define its own policy for
    multi-source values on top of this map.

    Provenance never changes what the gate accepts: a value added without
    a source is registered exactly as before, with empty provenance, and
    ``check`` / ``number_known`` read only the sets, never the map. The
    labels themselves are caller-supplied and unverified — quote them as
    "reported source", never as a verified fact — and ``provenance()``
    carries no hash or seal until the registry-fingerprint increment
    lands. Copy a registry through ``copy()``: rebuilding one by copying
    only ``ids``/``numbers`` silently drops provenance.
    """

    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.numbers: set[str] = set(ALWAYS_OK_NUMBERS)
        self._provenance: dict[tuple[str, str], list[str]] = {}

    def _record(self, kind: str, value: str, source: str) -> None:
        known = self._provenance.setdefault((kind, value), [])
        if source not in known:
            known.append(source)

    def add_text(self, text: str, *, source: str | None = None) -> None:
        label = _clean_source(source)
        numbers = _numbers(text)
        underscore_spans = [(m.start(), m.end()) for m in _UNDERSCORE_ID.finditer(text)]
        hyphen_spans = [(m.start(), m.end()) for m in _HYPHEN_ID.finditer(text)]
        underscore_ids = {text[start:end].upper() for start, end in underscore_spans}
        hyphen_ids = {text[start:end].upper() for start, end in hyphen_spans}
        self.numbers |= numbers
        self.ids |= underscore_ids | hyphen_ids
        if label is not None:
            id_spans = underscore_spans + hyphen_spans
            for match in _NUMBER_RE.finditer(text):
                # Digits inside an id token ("3"/"17" in "Init_Lot_3_17")
                # are registered as numbers by the gate, but they are not
                # standalone data: a later claim quoting "3" must not cite
                # this text as the row that contained the number 3.
                if any(start <= match.start() and match.end() <= end for start, end in id_spans):
                    continue
                self._record("number", _norm(match.group()), label)
            for value in underscore_ids | hyphen_ids:
                self._record("id", value, label)

    def add(self, payload: Any, *, source: str | None = None) -> None:
        label = _clean_source(source)
        self.add_text(json.dumps(payload, ensure_ascii=False, default=str), source=label)

    def add_ids(self, ids: Iterable[str], *, source: str | None = None) -> None:
        label = _clean_source(source)
        upper = {item.upper() for item in ids}
        self.ids |= upper
        if label is not None:
            for value in upper:
                if value.strip():
                    self._record("id", value, label)

    def copy(self) -> FactRegistry:
        """A registry with the same facts and the same provenance.

        Copy through this method: rebuilding a registry by copying only
        ``ids``/``numbers`` (as ``explainer.py`` and ``claims.py``'s
        ``ledger_for_explanation`` do today) silently drops provenance,
        and the attribution increment must switch those sites to it.
        """
        other = FactRegistry()
        other.ids = set(self.ids)
        other.numbers = set(self.numbers)
        other._provenance = {key: list(values) for key, values in self._provenance.items()}
        return other

    def facts(self) -> dict[str, set[str]]:
        return {"ids": set(self.ids), "numbers": set(self.numbers)}

    def sources(self, kind: str, value: str) -> tuple[str, ...]:
        """Sources recorded for one value, first-seen order, or ``()``.

        ``kind`` is ``"id"`` or ``"number"`` (case-sensitive); the value
        is normalised the same way registration normalises it (ids
        upper-cased, numbers via ``_norm``), so ``sources("id",
        "init_lot_3_17")`` finds a value registered as
        ``"Init_Lot_3_17"``. A non-string value raises ``TypeError``.
        Values registered without a source — and numbers that only ever
        occurred inside an id token — are omitted, not listed as unknown.
        """
        if kind not in ("id", "number"):
            raise ValueError(f"unknown provenance kind: {kind!r}")
        if not isinstance(value, str):
            raise TypeError("provenance value must be a string")
        cleaned = value.strip()
        key = (kind, cleaned.upper() if kind == "id" else _norm(cleaned))
        return tuple(self._provenance.get(key, ()))

    def provenance(self) -> dict[str, dict[str, list[str]]]:
        """JSON-ready snapshot: ``{"ids": {...}, "numbers": {...}}``.

        A copy with sorted keys: mutating the snapshot never touches the
        registry. Values without a recorded source are omitted.
        """
        snapshot: dict[str, dict[str, list[str]]] = {"ids": {}, "numbers": {}}
        for (kind, value), recorded in sorted(self._provenance.items()):
            snapshot["numbers" if kind == "number" else "ids"][value] = list(recorded)
        return snapshot


def check(text: str, registry: FactRegistry) -> list[str]:
    """Unknown ids and numbers in ``text``. Empty list means it passes."""
    facts = registry.facts()
    # Hyphenated words without a digit ("tool-hours", "re-run") are prose, not ids.
    misses = [
        item
        for item in narrative_mismatches(text, facts)
        if not item.startswith("unknown id ") or _HAS_DIGIT.search(item[len("unknown id ") :])
    ]
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
