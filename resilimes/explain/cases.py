"""ResiliTrace case system v0: one case per late lot that needs follow-up.

The explain layer answers, for one lot, why it is late. It does not answer
what happens next: which lots are still waiting for a human, in what order,
and what was decided about each. That is the case system. A case is the
follow-up record for one lot in one run: severity, status, the lateness
behind it, and a link to the evidence bundle that supports it.

Severity is a four-level scale, defined here and nowhere else in the
explain layer (the scheduler's own ``domain.checks`` severity is a
different scale for a different purpose and is not imported):

* ``critical``: the lateness is large enough that the case needs
  escalation now (suggested at 120 min late or more).
* ``major``: the lot is materially late and needs a decision this shift
  (suggested at 30 min late or more).
* ``minor``: the lot is late but by a margin the shift can absorb
  (suggested at any lateness above 0).
* ``info``: the lot is not late; the case is a watch item, e.g. a near-miss
  a reviewer wants tracked.

The lateness thresholds above are a suggestion heuristic only
(``suggest_severity``). A case's severity is always assigned by a human
with a written reason (``severity_reason``); the suggestion never assigns
itself. When the caller omits the reason, the book fills in the suggestion
as the reason — but only when the assigned severity matches the suggestion.
An assigned severity that differs from the suggestion needs an explicit
reason of its own: a record whose reason names one severity and whose
field names another is a contradiction, not an audit trail. The
thresholds live in one place so a later increment can retune them
without touching the model.

Status is a small state machine:

* ``open`` -> ``investigating`` | ``resolved`` | ``dismissed``
* ``investigating`` -> ``open`` | ``resolved`` | ``dismissed``
* ``resolved`` -> ``open`` | ``dismissed``
* ``dismissed`` -> ``open`` | ``investigating``

``open -> resolved`` is allowed on purpose: triage often resolves a case
outright (duplicate, lot already recovered, no action needed), and
forcing a fake ``investigating`` step would put a lie in the history.
Likewise ``resolved -> dismissed`` (found to be a duplicate after
resolving) and ``dismissed -> investigating`` (new information after a
dismissal) are direct moves. Every transition is recorded in ``history``
with the previous status, the new status, a timestamp and a note, and
creation itself is the first history event (``previous`` is None only
there). ``resolved`` and ``dismissed`` are not terminal: a case can
always be reopened, and the reopening is on the record too.

A ``CaseBook`` is the in-memory collection: it assigns ``case_id`` values
(``case-0001``, ``case-0002``, ... — book-local sequence, not a global
key), enforces the state machine, and answers the lot-first questions a
Cases page needs: which lots have cases, worst open severity first, and
the cases for one lot in severity order. It does not persist anything and
it does not create cases by itself; wiring case creation into ``explain()``
is a later decision, not part of v0.

A case carries ``content_hash`` (SHA-256, same pattern as
``EvidenceBundle`` and the claim ledger). The hash covers the case's
content — id, lot, run, title, severity and its reason, status,
lateness, evidence link, notes, and the status history without
timestamps — but not ``created_at`` / ``updated_at`` or the history
timestamps, so re-stamping a case does not change its hash. The hash is
a content self-consistency check, not a signature and not a proof that
the record was never edited: timestamps can be rewritten without
breaking the seal, so an audit that needs trustworthy times must get
them from another source. There is no book-level seal: ``verify_all()``
checks each case, but deleting a case or reordering the book is not
detected.

Known limits of v0 (not hidden, just not built yet):

* No persistence: a book lives in memory; ``to_json`` / ``from_json``
  is the only export. A store with retention policy is a later increment.
* No owner or assignment: the book cannot say who is following up a
  case, only that its status moved. ``investigating`` means somebody set
  it so, not that a named person is on it.
* No waiting/blocked state: a case waiting on repair, a PM window or a
  customer decision can only sit in ``investigating``; "looking into it"
  and "waiting on something else" cannot be told apart yet.
* No frontend page: the lot-first listing is a data interface only; the
  Cases page (with the design-system baseline the standards require for
  the first page increment) comes later.
* ``case_id`` is book-local: the same lot in another book gets another
  id. Do not use it as a cross-book key.
* ``evidence_hash`` links a case to one evidence bundle by hash, but the
  book does not check that the bundle exists; a dangling link is a
  data-entry error, not a validation error. Only lowercase hex is
  accepted, matching what ``EvidenceBundle`` itself produces.
* Severity suggestion uses lateness alone. A case opened for a reason
  other than lateness (a quality hold, a note-only cause) must be
  assigned its severity by hand.
* ``lots()`` and ``cases_for_lot()`` aggregate across runs unless a run
  is passed: the same lot in two runs shares one row. Use ``for_run``
  to look at one run only.
* Case coverage is not measured: the book only counts cases it holds,
  it cannot say how many late lots have no case at all. That ratio
  needs the explain side to supply the denominator.

Version rule: ``cases/v0``. Changing a severity definition, a status
transition, the suggestion thresholds or a field is a new version,
not an edit.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resilimes.explain.schema import RunRef, canonical_json

CASES_VERSION: Literal["cases/v0"] = "cases/v0"

Severity = Literal["critical", "major", "minor", "info"]
SEVERITIES: tuple[str, ...] = ("critical", "major", "minor", "info")
# Worst first. Used for every severity ordering in this module.
SEVERITY_ORDER: dict[str, int] = {"critical": 0, "major": 1, "minor": 2, "info": 3}

# Suggestion thresholds (lateness minutes). Advisory only; see module docstring.
SUGGEST_CRITICAL_MIN = 120.0
SUGGEST_MAJOR_MIN = 30.0

Status = Literal["open", "investigating", "resolved", "dismissed"]
STATUSES: tuple[str, ...] = ("open", "investigating", "resolved", "dismissed")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("investigating", "resolved", "dismissed"),
    "investigating": ("open", "resolved", "dismissed"),
    "resolved": ("open", "dismissed"),
    "dismissed": ("open", "investigating"),
}

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CASE_ID_RE = re.compile(r"^case-(\d+)$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp. Must carry a timezone; naive and
    date-only values are rejected, because string ordering across offsets
    is not time ordering."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone, got {value!r}")
    return parsed


def _check_iso(value: str, field: str) -> str:
    try:
        _parse_iso(value)
    except ValueError:
        raise ValueError(f"{field} must be an ISO 8601 timestamp with a timezone, got {value!r}")
    return value


def _case_id_key(case_id: str) -> tuple[int, Any]:
    """Numeric order for book-assigned ids (case-10000 after case-9999);
    anything else sorts after, by string."""
    match = _CASE_ID_RE.match(case_id)
    if match:
        return (0, int(match.group(1)))
    return (1, case_id)


def suggest_severity(lateness_min: float | None) -> Severity | None:
    """Suggested severity from lateness alone, or None when unknown.

    Advisory: the caller still assigns the severity with a reason.
    """
    if lateness_min is None:
        return None
    if isinstance(lateness_min, bool) or not math.isfinite(lateness_min):
        raise ValueError("lateness_min must be a finite number")
    if lateness_min < 0:
        raise ValueError("lateness_min cannot be negative")
    if lateness_min >= SUGGEST_CRITICAL_MIN:
        return "critical"
    if lateness_min >= SUGGEST_MAJOR_MIN:
        return "major"
    if lateness_min > 0:
        return "minor"
    return "info"


class StatusEvent(BaseModel):
    """One recorded status change. ``previous`` is None only for the
    creation event, which is always the first history entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    previous: Status | None = None
    status: Status
    at: str
    note: str = ""

    @model_validator(mode="after")
    def _at_is_iso(self) -> StatusEvent:
        _check_iso(self.at, "at")
        return self


class Case(BaseModel):
    """One lot's follow-up record in one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cases_version: Literal["cases/v0"] = CASES_VERSION
    case_id: str
    lot: str
    run: RunRef
    title: str
    severity: Severity
    severity_reason: str
    status: Status = "open"
    lateness_min: float | None = Field(default=None, ge=0.0)
    evidence_hash: str | None = None
    notes: tuple[str, ...] = ()
    history: tuple[StatusEvent, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    content_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _strip_text_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ("lot", "title", "severity_reason"):
                value = data.get(field)
                if isinstance(value, str):
                    data = {**data, field: value.strip()}
        return data

    @model_validator(mode="after")
    def _case_rules(self) -> Case:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if not self.lot.strip():
            raise ValueError("lot must not be empty")
        if "\n" in self.title or "\r" in self.title:
            raise ValueError("title must be a single line")
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.severity_reason.strip():
            raise ValueError("severity_reason must not be empty")
        if self.lateness_min is not None and not math.isfinite(self.lateness_min):
            raise ValueError("lateness_min must be finite")
        if self.evidence_hash is not None and not _HASH_RE.match(self.evidence_hash):
            raise ValueError(
                "evidence_hash must be an evidence content hash "
                "(sha256:<64 lowercase hex chars>), got "
                f"{self.evidence_hash!r}"
            )
        for note in self.notes:
            if not isinstance(note, str) or not note.strip():
                raise ValueError("notes must be non-empty strings")
        if not self.created_at:
            raise ValueError("created_at is required")
        if not self.updated_at:
            raise ValueError("updated_at is required")
        _check_iso(self.created_at, "created_at")
        _check_iso(self.updated_at, "updated_at")
        self._check_history()
        return self

    def _check_history(self) -> None:
        """History is a chain from the creation event to the current status."""
        if not self.history:
            if self.status != "open":
                raise ValueError(
                    f"a case with no history must be open, got status {self.status!r}"
                )
            return
        first = self.history[0]
        if first.previous is not None or first.status != "open":
            raise ValueError("history must start with the creation event (previous None, open)")
        previous: Status | None = None
        for event in self.history:
            if event.previous != previous:
                raise ValueError(
                    f"history is not a chain: {event.previous!r} does not follow {previous!r}"
                )
            previous = event.status
        if self.history[-1].status != self.status:
            raise ValueError(
                f"history ends at {self.history[-1].status!r} but status is {self.status!r}"
            )

    def body(self) -> dict[str, Any]:
        """Everything the hash covers: content, not timestamps."""
        return {
            "cases_version": self.cases_version,
            "case_id": self.case_id,
            "lot": self.lot,
            "run": self.run.model_dump(mode="json"),
            "title": self.title,
            "severity": self.severity,
            "severity_reason": self.severity_reason,
            "status": self.status,
            "lateness_min": self.lateness_min,
            "evidence_hash": self.evidence_hash,
            "notes": list(self.notes),
            "history": [
                {"previous": e.previous, "status": e.status, "note": e.note}
                for e in self.history
            ],
        }

    def sealed(self) -> Case:
        return self.model_copy(
            update={"content_hash": "sha256:" + hashlib.sha256(canonical_json(self.body()).encode("utf-8")).hexdigest()}
        )

    def verify(self) -> bool:
        return bool(self.content_hash) and self.content_hash == (
            "sha256:" + hashlib.sha256(canonical_json(self.body()).encode("utf-8")).hexdigest()
        )


class LotSummary(BaseModel):
    """Lot-first roll-up: one row per lot that has cases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lot: str
    total: int = Field(ge=0)
    open_count: int = Field(ge=0)
    worst_severity: Severity
    worst_open_severity: Severity | None = None
    latest_updated_at: str
    case_ids: tuple[str, ...] = ()


class CaseBookSummary(BaseModel):
    """Counts only. Ratios are the quality module's job, with denominators."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(ge=0)
    lots: int = Field(ge=0)
    open_total: int = Field(ge=0)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class CaseBook(BaseModel):
    """In-memory collection of cases. Methods return a new book.

    Keep the returned book: the old one is unchanged, so branching off
    it forks the history. There is no merge; the caller owns the one
    book that is current.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    book_version: Literal["cases/v0"] = CASES_VERSION
    cases: tuple[Case, ...] = ()
    next_seq: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _book_rules(self) -> CaseBook:
        seen: set[str] = set()
        for case in self.cases:
            if case.case_id in seen:
                raise ValueError(f"duplicate case_id in book: {case.case_id!r}")
            seen.add(case.case_id)
        seqs = [
            int(m.group(1))
            for case in self.cases
            if (m := _CASE_ID_RE.match(case.case_id))
        ]
        if seqs and self.next_seq <= max(seqs):
            raise ValueError(
                f"next_seq {self.next_seq} must be above the highest case number {max(seqs)}"
            )
        return self

    def get(self, case_id: str) -> Case:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(f"unknown case_id: {case_id!r}")

    def add_case(
        self,
        *,
        lot: str,
        run: RunRef,
        title: str,
        severity: Severity,
        severity_reason: str | None = None,
        lateness_min: float | None = None,
        evidence_hash: str | None = None,
        notes: tuple[str, ...] = (),
        created_at: str | None = None,
    ) -> tuple[CaseBook, Case]:
        """Open a case. Returns (new book, the sealed case).

        When ``severity_reason`` is omitted and ``lateness_min`` is known,
        the reason records the suggestion that was followed — but only
        when the assigned severity matches the suggestion. An assigned
        severity that differs from the suggestion needs an explicit
        reason: the record must not claim a suggestion it did not follow.
        """
        if isinstance(notes, str):
            raise TypeError("notes must be a tuple of strings, not a single string")
        if severity_reason is None:
            suggested = suggest_severity(lateness_min)
            if suggested is None:
                raise ValueError(
                    "severity_reason is required when lateness_min is unknown: "
                    "a severity without a stated reason is not recorded"
                )
            if severity != suggested:
                raise ValueError(
                    f"severity {severity!r} differs from the suggestion "
                    f"{suggested!r} for lateness {lateness_min:g} min: "
                    "give an explicit severity_reason"
                )
            severity_reason = (
                f"suggested from lateness {lateness_min:g} min -> {suggested}"
            )
        now = created_at or _now_iso()
        case = Case(
            case_id=f"case-{self.next_seq:04d}",
            lot=lot,
            run=run,
            title=title,
            severity=severity,
            severity_reason=severity_reason,
            lateness_min=lateness_min,
            evidence_hash=evidence_hash,
            notes=tuple(notes),
            history=(StatusEvent(previous=None, status="open", at=now, note="created"),),
            created_at=now,
            updated_at=now,
        ).sealed()
        return (
            self.model_copy(update={"cases": (*self.cases, case), "next_seq": self.next_seq + 1}),
            case,
        )

    def transition(
        self,
        case_id: str,
        to: Status,
        note: str = "",
        at: str | None = None,
    ) -> CaseBook:
        """Move a case to a new status. Illegal moves raise ValueError."""
        case = self.get(case_id)
        allowed = TRANSITIONS[case.status]
        if to not in allowed:
            raise ValueError(
                f"{case_id}: cannot move {case.status} -> {to}; "
                f"allowed from {case.status}: {', '.join(allowed) or 'none'}"
            )
        stamp = at or _now_iso()
        event = StatusEvent(previous=case.status, status=to, at=stamp, note=note)
        updated = case.model_copy(
            update={
                "status": to,
                "history": (*case.history, event),
                "updated_at": stamp,
            }
        ).sealed()
        return self.model_copy(
            update={"cases": tuple(updated if c.case_id == case_id else c for c in self.cases)}
        )

    def add_note(self, case_id: str, note: str, at: str | None = None) -> CaseBook:
        """Append a progress note to a case. No status change."""
        if not note.strip():
            raise ValueError("note must not be empty")
        case = self.get(case_id)
        stamp = at or _now_iso()
        updated = case.model_copy(
            update={
                "notes": (*case.notes, note.strip()),
                "updated_at": stamp,
            }
        ).sealed()
        return self.model_copy(
            update={"cases": tuple(updated if c.case_id == case_id else c for c in self.cases)}
        )

    def for_run(self, run: RunRef) -> tuple[Case, ...]:
        """Cases of one run, worst severity first, then oldest first."""
        rows = [c for c in self.cases if c.run == run]
        rows.sort(key=lambda c: (SEVERITY_ORDER[c.severity], _parse_iso(c.created_at), _case_id_key(c.case_id)))
        return tuple(rows)

    def cases_for_lot(self, lot: str, run: RunRef | None = None) -> tuple[Case, ...]:
        """Cases for one lot, worst severity first, then oldest first.

        Without ``run`` this aggregates across runs; pass a run to look
        at one run only.
        """
        rows = [c for c in self.cases if c.lot == lot and (run is None or c.run == run)]
        rows.sort(key=lambda c: (SEVERITY_ORDER[c.severity], _parse_iso(c.created_at), _case_id_key(c.case_id)))
        return tuple(rows)

    def lots(self, run: RunRef | None = None) -> tuple[LotSummary, ...]:
        """One row per lot with cases, worst *open* severity first.

        The queue is for work still waiting, so a lot whose only
        critical case is already resolved sorts behind lots with open
        major cases. Lots with no open case at all sort last. Ties break
        by open count (more open first), then lot id, so the list is
        deterministic.
        """
        grouped: dict[str, list[Case]] = {}
        for case in self.cases:
            if run is not None and case.run != run:
                continue
            grouped.setdefault(case.lot, []).append(case)
        rows = []
        for lot, items in grouped.items():
            open_items = [c for c in items if c.status in ("open", "investigating")]
            rows.append(
                LotSummary(
                    lot=lot,
                    total=len(items),
                    open_count=len(open_items),
                    worst_severity=min(items, key=lambda c: SEVERITY_ORDER[c.severity]).severity,
                    worst_open_severity=(
                        min(open_items, key=lambda c: SEVERITY_ORDER[c.severity]).severity
                        if open_items
                        else None
                    ),
                    latest_updated_at=max(items, key=lambda c: _parse_iso(c.updated_at)).updated_at,
                    case_ids=tuple(
                        c.case_id for c in sorted(items, key=lambda c: _case_id_key(c.case_id))
                    ),
                )
            )
        rows.sort(
            key=lambda r: (
                0 if r.worst_open_severity is not None else 1,
                SEVERITY_ORDER[r.worst_open_severity] if r.worst_open_severity else 99,
                -r.open_count,
                r.lot,
            )
        )
        return tuple(rows)

    def summary(self) -> CaseBookSummary:
        by_status = dict.fromkeys(STATUSES, 0)
        by_severity = dict.fromkeys(SEVERITIES, 0)
        for case in self.cases:
            by_status[case.status] += 1
            by_severity[case.severity] += 1
        return CaseBookSummary(
            total=len(self.cases),
            lots=len({c.lot for c in self.cases}),
            open_total=sum(1 for c in self.cases if c.status in ("open", "investigating")),
            by_status=by_status,
            by_severity=by_severity,
        )

    def verify_all(self) -> list[str]:
        """case_ids whose seal no longer matches their content."""
        return [c.case_id for c in self.cases if not c.verify()]

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> CaseBook:
        return cls.model_validate(payload)
