"""Claim ledger v0: every number and id the fact-check gate recognises, on the record.

The fact-check gate (``explain.factcheck.check``) already rejects an
explanation whose numbers or ids are not in the evidence. What it does not
leave behind is a record: which value was claimed, in which sentence, against
which evidence rows, and whether it passed. That is the ledger. It is the
audit trail a quality review or a customer audit asks for, and it is also the
raw material for the quality metrics: a claim that failed the gate is a
misattribution with a name on it.

The ledger agrees with the gate by construction: ``build_ledger`` runs
``factcheck.check`` once and derives every claim's result from its misses,
so a value the gate passes is never recorded as failed, and vice versa —
provided the caller passes the registry the gate actually used. For an
``Explanation`` that means the registry as the explainer augmented it (see
``ledger_for_explanation``): the explainer adds the counterfactual's
``expected_saving_min`` and the lot id before checking, and the ledger
reproduces that step.

Known limits of v0 (not hidden, just not built yet):

* ``sources`` are ledger-level row references supplied by the caller. The
  ledger does not yet know, per claim, which evidence row a value came from,
  because ``FactRegistry`` does not record provenance. Per-claim source
  attribution is a later increment.
* The ledger records what was quoted and whether it checked out. It does not
  record which run produced the explanation (no seed / horizon / policy /
  label), which provider or model said it, when the explanation was
  generated, or what the registry contained at check time: ``content_hash``
  covers the ledger only, not the evidence it was checked against. An audit
  that needs that binding has to keep the explanation and its evidence bundle
  next to the ledger. Recording the run reference and a registry fingerprint
  is a later increment.
* ``claim_id`` identifies a quotation (kind + value + statement), not one
  claim in one run: the same sentence in another lot or run gets the same id,
  and its result there can differ. Do not use it as a cross-ledger key.
* The ledger is an adapter: ``ledger_for_explanation`` builds one from an
  ``Explanation`` after the fact. Nothing in ``explain()`` writes to a ledger
  yet; wiring it into the explainer flow is a separate, later decision.

Version rule: ``claim/v0``. Changing a field, a result value or the
extraction rule is a new version, not an edit.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resilimes.common.textfacts import _norm
from resilimes.explain.factcheck import FactRegistry, check
from resilimes.explain.schema import canonical_json

if TYPE_CHECKING:  # typing only; the ledger never calls the explainer.
    from resilimes.explain.explainer import Explanation

LEDGER_VERSION: Literal["claim/v0"] = "claim/v0"

KINDS: tuple[str, ...] = ("number", "id")
RESULTS: tuple[str, ...] = ("passed", "failed", "unchecked")

# The gate only treats an id-shaped token as a claim when it carries a digit:
# "tool-hours" is prose, "Diffusion_FE_120" and "Lot-1" are ids. The ledger
# follows the same rule so it never records what the gate would not judge.
_UNDERSCORE_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_HYPHEN_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b")
_HAS_DIGIT = re.compile(r"\d")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Abbreviations whose period must not split a sentence. Protected with a
# placeholder before splitting, restored afterwards.
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "Fig.", "vs.")
_ABBREV_PLACEHOLDER = "\u0001"


def _protect_abbreviations(text: str) -> str:
    for abbrev in _ABBREVIATIONS:
        text = text.replace(abbrev, abbrev.replace(".", _ABBREV_PLACEHOLDER))
    return text


def _restore_abbreviations(text: str) -> str:
    return text.replace(_ABBREV_PLACEHOLDER, ".")


def _claim_id(kind: str, value: str, statement: str) -> str:
    digest = hashlib.sha256(
        f"{kind}|{value}|{statement}".encode("utf-8")
    ).hexdigest()[:12]
    return f"claim-{digest}"


def _sentences(text: str) -> list[str]:
    protected = _protect_abbreviations(text)
    return [
        _restore_abbreviations(part.strip())
        for part in _SENTENCE_SPLIT.split(protected)
        if part.strip()
    ]


class Claim(BaseModel):
    """One quoted value: what was said, where, and whether it checked out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    kind: Literal["number", "id"]
    value: str  # normalised: numbers via _norm, ids upper-cased
    statement: str  # the sentence the value was quoted in
    sources: tuple[str, ...] = ()  # evidence row references, ledger-level for now
    result: Literal["passed", "failed", "unchecked"]
    checked_at: str  # ISO 8601 UTC timestamp of the check
    reason: str | None = None  # why unchecked, or the gate's miss text on failure

    @model_validator(mode="after")
    def _unchecked_needs_reason_and_checked_at_must_parse(self) -> Claim:
        if self.result == "unchecked" and not self.reason:
            raise ValueError("an unchecked claim needs a reason")
        try:
            datetime.fromisoformat(self.checked_at)
        except ValueError:
            raise ValueError(f"checked_at must be an ISO 8601 timestamp: {self.checked_at!r}")
        return self


class ClaimLedger(BaseModel):
    """The claims of one explanation (or one text), with a tamper hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_version: Literal["claim/v0"] = LEDGER_VERSION
    subject: str | None = None  # e.g. the lot id the explanation is about
    source: str | None = None  # what produced the text, e.g. "explainer"
    claims: tuple[Claim, ...] = ()
    content_hash: str = ""

    def body(self) -> dict[str, Any]:
        """Everything the hash covers.

        The hash attests to what was claimed and the verdicts, not to when
        the check ran: ``checked_at`` is recorded on each claim but excluded
        from the hash, so the same text and registry always build the same
        hash. It is a self-consistency check, not a signature: anyone who can
        rewrite the ledger can recompute it.
        """
        dumped = self.model_dump(mode="json", exclude={"content_hash"})
        for claim in dumped["claims"]:
            claim.pop("checked_at", None)
        return dumped

    def sealed(self) -> ClaimLedger:
        return self.model_copy(
            update={
                "content_hash": "sha256:"
                + hashlib.sha256(canonical_json(self.body()).encode("utf-8")).hexdigest()
            }
        )

    def verify(self) -> bool:
        return bool(self.content_hash) and self.content_hash == (
            "sha256:"
            + hashlib.sha256(canonical_json(self.body()).encode("utf-8")).hexdigest()
        )

    def failed(self) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if c.result == "failed")

    def passed(self) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if c.result == "passed")

    def unchecked(self) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if c.result == "unchecked")

    def by_value(self, value: str, kind: str | None = None) -> tuple[Claim, ...]:
        """Find claims quoting ``value``; the query is normalised like storage.

        ``by_value("Lot-1")`` and ``by_value("120.0")`` hit the stored
        ``LOT-1`` and ``120``. Without ``kind`` both normalisations are tried.
        """
        if kind == "number":
            wanted = {_norm(value)}
        elif kind == "id":
            wanted = {value.upper()}
        else:
            wanted = {_norm(value), value.upper()}
        return tuple(
            c for c in self.claims if c.value in wanted and (kind is None or c.kind == kind)
        )

    def summary(self) -> dict[str, int]:
        """Counts only. Rates belong to the quality module, not the ledger."""
        return {
            "total": len(self.claims),
            "passed": len(self.passed()),
            "failed": len(self.failed()),
            "unchecked": len(self.unchecked()),
        }


def _misses_by_kind(text: str, registry: FactRegistry) -> tuple[set[str], set[str]]:
    """What the gate rejects, split into normalised numbers and upper ids."""
    failed_numbers: set[str] = set()
    failed_ids: set[str] = set()
    for miss in check(text, registry):
        if miss.startswith("unknown number "):
            failed_numbers.add(_norm(miss[len("unknown number ") :]))
        elif miss.startswith("unknown id "):
            failed_ids.add(miss[len("unknown id ") :].upper())
    return failed_numbers, failed_ids


def build_ledger(
    text: str,
    registry: FactRegistry,
    *,
    subject: str | None = None,
    source: str | None = None,
    sources: tuple[str, ...] = (),
    checked_at: str | None = None,
) -> ClaimLedger:
    """Extract every claimed number and id from ``text`` and check each one.

    The same text and registry always build the same claims and the same
    hash; only ``checked_at`` varies, and it is excluded from the hash. A
    claim's result comes from the gate's own misses, so the ledger can never
    disagree with ``factcheck.check`` on the same text and the same registry.
    """
    stamp = checked_at or datetime.now(timezone.utc).isoformat()
    failed_numbers, failed_ids = _misses_by_kind(text, registry)

    # One claim per quotation, not per distinct value: the same number quoted
    # in two sentences is two claims. The same value twice in one sentence
    # is one claim (the sentence is the unit the audit reads). Claims are
    # built sentence by sentence so each claim's statement is the sentence
    # its own occurrence sits in. Numbers are taken exactly as the gate sees
    # them, including digits inside an id ("Lot-1" also quotes the number 1,
    # which the gate allows as a counting word).
    claims: list[Claim] = []
    seen: set[tuple[str, str, str]] = set()
    for sentence in _sentences(text):
        for raw in re.findall(r"\d+(?:\.\d+)?", sentence):
            value = _norm(raw)
            if ("number", value, sentence) in seen:
                continue
            seen.add(("number", value, sentence))
            claims.append(
                Claim(
                    claim_id=_claim_id("number", value, sentence),
                    kind="number",
                    value=value,
                    statement=sentence,
                    sources=sources,
                    result="failed" if value in failed_numbers else "passed",
                    checked_at=stamp,
                    reason=f"unknown number {raw}" if value in failed_numbers else None,
                )
            )
        ids: dict[str, str] = {}  # upper id -> first raw token seen
        for token in _UNDERSCORE_ID.findall(sentence):
            if _HAS_DIGIT.search(token):
                ids.setdefault(token.upper(), token)
        for token in _HYPHEN_ID.findall(sentence):
            if _HAS_DIGIT.search(token):
                ids.setdefault(token.upper(), token)
        for upper in sorted(ids):
            if ("id", upper, sentence) in seen:
                continue
            seen.add(("id", upper, sentence))
            claims.append(
                Claim(
                    claim_id=_claim_id("id", upper, sentence),
                    kind="id",
                    value=upper,
                    statement=sentence,
                    sources=sources,
                    result="failed" if upper in failed_ids else "passed",
                    checked_at=stamp,
                    reason=f"unknown id {ids[upper]}" if upper in failed_ids else None,
                )
            )
    return ClaimLedger(
        subject=subject, source=source, claims=tuple(claims)
    ).sealed()


def ledger_for_explanation(
    explanation: Explanation,
    registry: FactRegistry,
    *,
    sources: tuple[str, ...] = (),
    checked_at: str | None = None,
) -> ClaimLedger:
    """Build a ledger for an ``Explanation``: explanation text plus its claim.

    The subject is the lot id. ``sources`` are the evidence row references
    the caller can vouch for, applied ledger-wide (see the module docstring).

    The registry the gate actually used is reproduced here: the explainer
    adds the counterfactual's ``expected_saving_min`` and the lot id to its
    registry copy before checking (``explainer._explain``), so a claim
    sentence that quotes the expected saving passes here exactly as it
    passed the gate. The caller's registry is not mutated. Note the saving
    itself is the model's own estimate and is never quoted as a claim unless
    the text says it; verifying it is ``verify_counterfactual``'s job, and
    the re-run result is not part of this ledger.

    The two texts are joined as two sentences: if the explanation does not
    end with sentence punctuation, a period is added first, so claims from
    the claim sentence are never attributed to a merged pseudo-sentence.
    """
    augmented = FactRegistry()
    augmented.ids = set(registry.ids)
    augmented.numbers = set(registry.numbers)
    if explanation.expected_saving_min is not None:
        augmented.add_text(str(explanation.expected_saving_min))
    augmented.add_text(explanation.lot)
    explanation_text = explanation.explanation.strip()
    claim_text = explanation.claim.strip()
    if explanation_text and explanation_text[-1] not in ".!?":
        explanation_text += "."
    text = f"{explanation_text} {claim_text}".strip()
    return build_ledger(
        text,
        augmented,
        subject=explanation.lot,
        source="explainer",
        sources=sources,
        checked_at=checked_at,
    )
