"""Deliberate-gap records: why a tool stood idle on purpose.

A schedule often leaves a tool idle for a reason a human cannot see from the
Gantt alone: waiting to fill a batch (BATCHMN), a Q-time gate holding an
origin lot until its whole CQT segment fits, a start refused because it would
overrun the next PM, and so on. This module finds idle gaps on tools,
classifies each one from evidence, and records the classification so an
explainer (``gap_explainer``) can answer "why is this empty?" without
inventing a reason.

Honesty rules (they are the point of the feature):

* The classifier only uses the evidence it is given. A gap whose evidence
  does not match any known pattern is ``unknown`` -- never guessed.
* When several patterns match, a fixed priority decides, so the same
  evidence always yields the same reason.
* v1 classification is *post-hoc inference* from a finished run's timeline
  and evidence. It is not a dispatch-time decision log; the ``source`` field
  says where a record came from (``inferred`` here) and ``tier`` how strong
  the attribution is. Dispatch-time records (v1.5) carry
  ``source="dispatch_log"`` and ``tier="decision_record"`` and win over
  inferred ones for the same tool and window.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from resilimes.evidence.timeline import Timeline
from resilimes.smt.dispatch_log import DispatchRecord

_WAFERS = 25


class GapReason(StrEnum):
    BATCH_WAIT = "batch_wait"
    QTIME_GATE = "qtime_gate"
    PLAN_WAIT = "plan_wait"
    PM_AVOIDANCE = "pm_avoidance"
    SETUP_SAVING = "setup_saving"
    CAPACITY_RESERVE = "capacity_reserve"
    DOWNSTREAM_BLOCKED = "downstream_blocked"
    UNKNOWN = "unknown"


# Fixed tie-break order when several evidence patterns match one gap.
REASON_PRIORITY: tuple[GapReason, ...] = (
    GapReason.PM_AVOIDANCE,
    GapReason.QTIME_GATE,
    GapReason.BATCH_WAIT,
    GapReason.PLAN_WAIT,
    GapReason.CAPACITY_RESERVE,
    GapReason.SETUP_SAVING,
    GapReason.DOWNSTREAM_BLOCKED,
)

TIER_DECISION_RECORD = "decision_record"
TIER_INFERRED = "inferred_evidence"
TIER_UNKNOWN = "unknown"

SOURCE_INFERRED = "inferred"
SOURCE_DISPATCH_LOG = "dispatch_log"


@dataclass
class GapEvidence:
    """Everything the classifier may look at for one gap. ``None`` = no evidence."""

    # A PM span on this tool starts inside the gap (the tool waits out the PM
    # rather than starting a job that would overrun it).
    pm_at: float | None = None
    # A lot sat ready at a CQT origin step across the whole gap (the Q-time
    # gate would not let it start).
    qtime_blocked_lot: int | None = None
    qtime_target_step: int | None = None
    # The start that ends the gap is a batch start, with its lot count and the
    # route's BATCHMN lot floor.
    next_batch_lots: int | None = None
    batch_min_lots: int | None = None
    # The planning layer's band releases this tool's next start at this time.
    plan_wait_until: float | None = None
    # Capacity is being held for this (hot / VIP) lot, expected shortly.
    reserve_for_lot: int | None = None
    # The next start continues the same recipe (no setup paid by waiting).
    same_recipe_next: bool = False
    # The downstream family was busy / blocked for the whole gap.
    downstream_busy: bool = False

    def to_json(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, False)}


def classify_gap(ev: GapEvidence) -> GapReason:
    """One reason for one gap, by fixed priority; ``unknown`` if nothing matches."""
    matched: set[GapReason] = set()
    if ev.pm_at is not None:
        matched.add(GapReason.PM_AVOIDANCE)
    if ev.qtime_blocked_lot is not None:
        matched.add(GapReason.QTIME_GATE)
    if ev.next_batch_lots is not None and ev.batch_min_lots is not None:
        matched.add(GapReason.BATCH_WAIT)
    if ev.plan_wait_until is not None:
        matched.add(GapReason.PLAN_WAIT)
    if ev.reserve_for_lot is not None:
        matched.add(GapReason.CAPACITY_RESERVE)
    if ev.same_recipe_next:
        matched.add(GapReason.SETUP_SAVING)
    if ev.downstream_busy:
        matched.add(GapReason.DOWNSTREAM_BLOCKED)
    for reason in REASON_PRIORITY:
        if reason in matched:
            return reason
    return GapReason.UNKNOWN


@dataclass
class GapRecord:
    """One idle gap on one tool, with its classified reason and provenance."""

    tool: int
    family: int
    start: float  # seconds after the snapshot
    end: float
    reason: GapReason = GapReason.UNKNOWN
    lot: int | None = None
    step: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    source: str = SOURCE_INFERRED
    tier: str = TIER_INFERRED
    # Twin re-run evidence ("what if the gap had been filled?"). v1: not
    # computed; the field exists so consumers can rely on its shape, and
    # ``None`` is the explicit "not verified" marker.
    counterfactual: dict[str, Any] | None = None

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end - self.start)

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["reason"] = self.reason.value
        out["duration_s"] = round(self.duration_s, 1)
        return out


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for left, right in sorted(spans):
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        elif right > left:
            merged.append([left, right])
    return [(left, right) for left, right in merged]


def find_gaps(timeline: Timeline, *, min_gap_s: float = 60.0) -> list[tuple[int, float, float]]:
    """Idle intervals per tool: covered by neither busy, down nor PM spans."""
    out: list[tuple[int, float, float]] = []
    horizon = timeline.horizon
    for tool in range(len(timeline.busy)):
        covered = _merge(
            list(timeline.busy[tool]) + list(timeline.downs[tool]) + list(timeline.pm[tool])
        )
        cursor = 0.0
        for left, right in covered:
            if left - cursor >= min_gap_s:
                out.append((tool, cursor, min(left, horizon)))
            cursor = max(cursor, right)
        if horizon - cursor >= min_gap_s:
            out.append((tool, cursor, horizon))
    return out


def _evidence_for_gap(
    timeline: Timeline, tool: int, start: float, end: float
) -> tuple[GapEvidence, int | None, int | None]:
    """Post-hoc evidence for one gap from the timeline (v1: batch / PM / CQT only).

    Plan-band, reserve, setup and downstream evidence is not recoverable
    from a finished run's timeline, so those fields stay empty here and such
    gaps classify ``unknown`` on real runs. That is a v1 limit, stated rather
    than papered over.
    """
    fab = timeline.fab
    ev = GapEvidence()
    lot: int | None = None
    step: int | None = None
    for span_start, _span_end in timeline.pm[tool]:
        if start <= span_start <= end:
            ev.pm_at = span_start
            break
    family = fab.tool_family[tool]
    for visit in timeline.by_family.get(family, []):
        if visit.tool != tool or visit.start is None:
            continue
        if abs(visit.start - end) <= 1e-6 and visit.batch_lots > 1:
            route = fab.routes[fab.lot_route[visit.lot]]
            ev.next_batch_lots = visit.batch_lots
            ev.batch_min_lots = max(1, route.batch_min[visit.step] // _WAFERS)
        if visit.ready <= start and visit.start >= end:
            route = fab.routes[fab.lot_route[visit.lot]]
            if route.cqt_limit[visit.step] > 0:
                ev.qtime_blocked_lot = visit.lot
                ev.qtime_target_step = route.cqt_target[visit.step]
                lot, step = visit.lot, visit.step
    return ev, lot, step


def gaps_from_dispatch(
    records: list[DispatchRecord], timeline: Timeline | None = None
) -> list[GapRecord]:
    """Gap records from dispatch-time decisions (v1.5, ``decision_record`` tier).

    A dispatch record marks the moment of the decision; its *duration* is
    only known from the run itself, so when a timeline is given the gap end
    is resolved to the tool's next busy start after the decision (or the
    record's wake time when that is later). Without a timeline the end is
    the wake time if known, else the decision moment itself.
    """
    out: list[GapRecord] = []
    for rec in records:
        end = rec.wake if rec.wake is not None else rec.t
        if timeline is not None and rec.tool >= 0:
            for left, _right in sorted(timeline.busy[rec.tool]):
                if left > rec.t:
                    end = max(end, left)
                    break
            else:
                end = max(end, timeline.horizon if rec.t < timeline.horizon else rec.t)
        evidence = dict(rec.evidence)
        evidence["decisions"] = rec.count
        evidence["lots"] = list(rec.lots)
        out.append(
            GapRecord(
                tool=rec.tool,
                family=rec.family,
                start=rec.t,
                end=end,
                reason=GapReason(rec.reason),
                lot=rec.lot,
                step=rec.step,
                evidence=evidence,
                source=SOURCE_DISPATCH_LOG,
                tier=TIER_DECISION_RECORD,
            )
        )
    return out


def gaps_from_run(
    run: Any,
    *,
    min_gap_s: float = 300.0,
    dispatch_records: list[DispatchRecord] | None = None,
) -> list[GapRecord]:
    """Classified gaps of one recorded run (``RecordedRun``-shaped).

    When ``dispatch_records`` (v1.5) are given, gaps they cover are taken
    from the dispatch log at ``decision_record`` tier and inferred gaps on
    the same tool overlapping one are dropped: a recorded decision beats a
    post-hoc guess for the same window.
    """
    timeline: Timeline = run.timeline
    out: list[GapRecord] = []
    dispatch_gaps = gaps_from_dispatch(
        dispatch_records or [], timeline if dispatch_records else None
    )
    covered: dict[int, list[tuple[float, float]]] = {}
    for gap in dispatch_gaps:
        covered.setdefault(gap.tool, []).append((gap.start, gap.end))
    for tool, start, end in find_gaps(timeline, min_gap_s=min_gap_s):
        if any(start < cov_end and cov_start < end for cov_start, cov_end in covered.get(tool, [])):
            continue
        ev, lot, step = _evidence_for_gap(timeline, tool, start, end)
        reason = classify_gap(ev)
        out.append(
            GapRecord(
                tool=tool,
                family=timeline.fab.tool_family[tool],
                start=start,
                end=end,
                reason=reason,
                lot=lot,
                step=step,
                evidence=ev.to_json(),
                source=SOURCE_INFERRED,
                tier=TIER_UNKNOWN if reason is GapReason.UNKNOWN else TIER_INFERRED,
            )
        )
    return sorted(dispatch_gaps + out, key=lambda gap: (gap.tool, gap.start))
