"""Dispatch-time gap reason log (Plan 4 v1.5).

The gap classifier in ``resilimes.insight.gaps`` (v1) infers *after* a run
why a tool stood idle. Inference can be wrong, and the explainer has to say
so. This module is the other half: a recorder the simulator feeds *at the
decision moment*, when a start is refused by the hard Q-time gate, held to
fill a batch, or refused because it would overrun the next PM. Those are
the deliberate gaps whose reason is known exactly when they happen.

Hard constraints (tested in ``tests/test_gap_reason_codes.py``):

* Pure observation. The recorder only appends to its own list; it never
  returns a value a decision can use, and a run with the recorder on must
  be bit-identical to one with it off.
* Off by default. ``make_sim`` creates no recorder unless one is passed in
  or ``RESILIMES_GAP_LOG=1`` is set.
* Repeated evaluations of the same decision coalesce into one record with
  a ``count`` (the gate re-tests a held lot at every wake; that is one
  episode, not hundreds of gaps).

Only the reasons the simulator can know at decision time are recorded
here: ``qtime_gate``, ``batch_wait``, ``pm_avoidance``. Plan-band waits,
capacity reserve, setup saving and downstream blocking have no single
decision point in the dispatcher and stay post-hoc inference (v1).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

REASON_QTIME_GATE = "qtime_gate"
REASON_BATCH_WAIT = "batch_wait"
REASON_PM_AVOIDANCE = "pm_avoidance"

DISPATCH_REASONS = (REASON_QTIME_GATE, REASON_BATCH_WAIT, REASON_PM_AVOIDANCE)


@dataclass
class DispatchRecord:
    """One deliberate-gap decision, recorded when it was made."""

    reason: str  # one of DISPATCH_REASONS
    lot: int | None  # head / refused lot (index into fab.lot_id)
    lots: tuple[int, ...]  # every lot held by this decision
    step: int  # the step the lot(s) were held at
    tool: int  # the tool whose start was refused / held (-1 if not tool-bound)
    family: int
    t: float  # decision time, seconds after the snapshot
    wake: float | None = None  # when the decision is next re-evaluated, if known
    evidence: dict[str, Any] = field(default_factory=dict)
    count: int = 1  # coalesced re-evaluations of this same decision

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["lots"] = list(self.lots)
        return out


class GapRecorder:
    """Run-level sink for dispatch-time gap records. Append-only, no feedback."""

    def __init__(self) -> None:
        self.records: list[DispatchRecord] = []
        self._index: dict[tuple[Any, ...], DispatchRecord] = {}

    def record(
        self,
        reason: str,
        *,
        lot: int | None,
        lots: tuple[int, ...],
        step: int,
        tool: int,
        family: int,
        t: float,
        wake: float | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        if reason == REASON_BATCH_WAIT:
            key: tuple[Any, ...] = (reason, tool, step, tuple(sorted(lots)))
        else:
            key = (reason, lot, step, tool)
        existing = self._index.get(key)
        if existing is not None:
            existing.count += 1
            if wake is not None:
                existing.wake = wake
            return
        rec = DispatchRecord(
            reason=reason,
            lot=lot,
            lots=tuple(lots),
            step=step,
            tool=tool,
            family=family,
            t=t,
            wake=wake,
            evidence=dict(evidence or {}),
        )
        self._index[key] = rec
        self.records.append(rec)

    def by_reason(self, reason: str) -> list[DispatchRecord]:
        return [rec for rec in self.records if rec.reason == reason]

    def to_json(self) -> list[dict[str, Any]]:
        return [rec.to_json() for rec in self.records]
