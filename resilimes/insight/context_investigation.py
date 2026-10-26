"""Context investigation: "what is the basis for this part of the schedule?".

The Gantt front end lets a supervisor right-click a lot-step bar, an idle
gap on one tool, a time window on one family — or ask a free question —
and ask why the schedule looks like that. This module is the backend. One
entry point, ``investigate_context``, routes by query type:

- ``bar``    — why this lot-step started on this tool at this time.
- ``gap``    — why this tool was idle in ``[t1, t2)`` while the fab had work.
- ``window`` — what happened at one family in ``[t1, t2)`` (the
  investigator's bounded tool loop).
- ``free``   — a free question; the service chains whichever evidence
  sources the query touches (bar record, gap classification, window
  investigation, fab notes) and labels each part with its source.

Three-tier honesty, decided by code, never by the model:

- ``decision_record`` — a recorded dispatch/gate decision explains the
  thing asked about (a recorded start reason, a displacement or AI
  decision event, a dispatch-log gap record). The answer may state the
  basis directly.
- ``rule_emergent`` — only the rule and the state at the time are on
  record (the dispatch ranking ``kernel.score.tiered_key`` is recomputed
  at every wake and leaves no per-decision record). The answer must frame
  it as "the result of rule X under the state at the time", never as a
  decision someone made.
- ``unknown`` — the recorded evidence does not say. The answer is the
  scripted unknown text; the model is not even asked to rewrite it.

A model may only rewrite wording *inside* the tier the code assigned: for
``rule_emergent`` answers, rewrites that use decision language ("decided
to", "chose to", "intentionally", …) are refused like a fact-check
failure. Every model text must also pass ``evidence.factcheck.check``
against the answer's own basis — one rewrite, then the deterministic
scripted answer is used and the result is marked ``degraded``. Offline
(provider ``None`` or mocked) the scripted answers are the product.

``basis`` entries carry a ``source`` so the UI (and the eval) can tell
evidence apart: ``run_record`` (visit / tool / queue records),
``decision_log`` (recorded displacements and AI decisions), ``rule``
(the ranking itself), ``gap_classifier`` (the gap classification of
``insight.gaps``, or a mirrored classification with the same taxonomy
until that module is merged), ``investigator`` (the window tool loop),
and ``fab_notes`` (operator notes and their extracted events; notes are
context claims, not run records, and are labelled as such).

Advice only: nothing here changes a plan.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from resilimes.agents.jsonutil import extract_json_object
from resilimes.evidence.factcheck import FactRegistry, check
from resilimes.evidence.lateness import visit_waits
from resilimes.evidence.timeline import DOWN, IDLE, PM, RESERVED
from resilimes.evidence.toolkit import HOUR, RecordedRun, Toolkit
from resilimes.insight.progress import redact
from resilimes.kernel.score import class_tier
from resilimes.llm.base import Completer

LANE = "context_investigation"
QUERY_TYPES = ("bar", "gap", "window", "free")
QUESTION_PRESETS: dict[str, tuple[str, ...]] = {
    "bar": ("why_here", "why_this_tool", "why_this_time"),
    "gap": ("why_idle",),
    "window": ("what_happened", "why_wip_changed"),
    "free": (),
}
TIER_DECISION_RECORD = "decision_record"
TIER_RULE_EMERGENT = "rule_emergent"
TIER_UNKNOWN = "unknown"
TIERS = (TIER_DECISION_RECORD, TIER_RULE_EMERGENT, TIER_UNKNOWN)
_TIER_RANK = {TIER_DECISION_RECORD: 2, TIER_RULE_EMERGENT: 1, TIER_UNKNOWN: 0}
# Phrases that would upgrade a rule-emergent answer into a claimed decision.
_DECISION_LANGUAGE = (
    "decided to",
    "chose to",
    "choice was made",
    "intentionally",
    "deliberately",
    "in order to",
    "the dispatcher wanted",
    "was held back to",
)
# Wait-bucket phrasing for gap answers (evidence.lateness BUCKETS).
_BUCKET_PHRASE = {
    "batch_wait": "waiting to form a batch",
    "pm": "an idle tool would have crossed its next PM window",
    "qtime": "Q-time holding (tools held for a Q-time lot or a re-clean redo)",
    "down": "tools down",
    "lots_ahead": "tools busy with lots ahead in the queue",
    "dispatch_other": "dispatch holds (dedication pin, gate or wake latency)",
    "release_hold": "a release hold",
    "ai_decision": "an explicit AI decision put another lot ahead",
}
# Gap reasons, aligned with insight.gaps.GapReason / REASON_PRIORITY.
_GAP_REASON_PRIORITY = (
    "pm_avoidance",
    "qtime_gate",
    "batch_wait",
    "plan_wait",
    "capacity_reserve",
    "setup_saving",
    "downstream_blocked",
)


class ContextError(ValueError):
    """The query cannot be answered as asked (unknown id, missing fields)."""


@dataclass
class ContextQuery:
    type: str  # bar | gap | window | free
    tool: str | None = None
    family: str | None = None
    lot: str | None = None
    step: int | None = None
    t1_h: float | None = None
    t2_h: float | None = None
    question_preset: str | None = None
    question: str | None = None
    scenario_id: str | None = None
    lang: str = "en"

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "tool": self.tool,
            "family": self.family,
            "lot": self.lot,
            "step": self.step,
            "t1_h": self.t1_h,
            "t2_h": self.t2_h,
            "question_preset": self.question_preset,
            "question": self.question,
            "scenario_id": self.scenario_id,
            "lang": self.lang,
        }


@dataclass
class ContextAnswer:
    query: dict[str, Any]
    type: str
    tier: str = TIER_UNKNOWN  # decided by code; see module docstring
    status: str = "answered"  # answered | unknown
    answer: str = ""
    basis: list[dict[str, Any]] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    part_tiers: dict[str, str] = field(default_factory=dict)  # free: per-source tier
    primary_cause: str | None = None
    secondary_cause: str | None = None
    fact_ok: bool = False
    fact_misses: list[str] = field(default_factory=list)
    source: str = "scripted"  # scripted | llm
    degraded: bool = False
    degrade_reason: str | None = None
    mocked: bool = True
    provider: str = ""
    model: str = ""
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _basis(entries: list[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Entries are (kind, source, facts); ``n`` is the citation number."""
    return [
        {"n": i + 1, "kind": kind, "source": source, "facts": facts}
        for i, (kind, source, facts) in enumerate(entries)
    ]


def _h(seconds: float) -> float:
    return round(seconds / HOUR, 2)


def _weaker(a: str, b: str) -> str:
    return a if _TIER_RANK[a] <= _TIER_RANK[b] else b


# ---- bar ------------------------------------------------------------------------------------
def _select_visit(kit: Toolkit, query: ContextQuery) -> Any:
    try:
        lot = kit.lot_index(str(query.lot))
    except KeyError as exc:
        raise ContextError(str(exc)) from exc
    visits = [v for v in kit.tl.visits.get(lot, []) if v.start is not None]
    if query.step is not None:
        visits = [v for v in visits if v.step == query.step]
    if query.tool:
        if query.tool not in kit.fab.tool_name:
            raise ContextError(f"unknown tool {query.tool!r}")
        tool = kit.fab.tool_name.index(query.tool)
        visits = [v for v in visits if v.tool == tool] or visits
    if query.t1_h is not None and visits:
        moment = query.t1_h * HOUR
        inside = [v for v in visits if v.ready <= moment <= (v.leave or kit.run.horizon)]
        visits = inside or visits
    if not visits:
        raise ContextError(f"lot {query.lot} has no started visit matching the query")
    return visits[-1]


def _bar(kit: Toolkit, query: ContextQuery) -> ContextAnswer:
    visit = _select_visit(kit, query)
    fab, tl = kit.fab, kit.tl
    lot = visit.lot
    lot_id = fab.lot_id[lot]
    family_name = fab.families[visit.family].name
    tool_name = fab.tool_name[visit.tool] if visit.tool >= 0 else None
    start = visit.start or visit.ready
    wait_sec = start - visit.ready
    rows = visit_waits(tl, lot, visit.ready, start)
    buckets: dict[str, float] = {}
    for row in rows:
        if row["visit"] is visit:
            buckets = {k: round(v / 60.0, 1) for k, v in row["buckets"].items() if v > 0}
    down_spans = [
        [_h(max(visit.ready, a)), _h(b)]
        for a, b in kit.run.downs[visit.tool]
        if a < start and b > visit.ready
    ]
    pm_spans = [
        [_h(max(visit.ready, a)), _h(b)]
        for a, b in kit.run.pm[visit.tool]
        if a < start and b > visit.ready
    ]
    displaced = [
        {"at_h": _h(d.at), "until_h": _h(d.until), "source": d.source}
        for d in tl.displaced.get(lot, [])
        if visit.ready - 1.0 <= d.at <= start + 1.0
    ]
    order_class = fab.lot_class[lot]
    entries: list[tuple[str, str, dict[str, Any]]] = [
        (
            "visit",
            "run_record",
            {
                "lot": lot_id,
                "step": visit.step,
                "family": family_name,
                "tool": tool_name,
                "ready_h": _h(visit.ready),
                "start_h": _h(start),
                "leave_h": _h(visit.leave) if visit.leave is not None else None,
                "wait_min": round(wait_sec / 60.0, 1),
                "setup_min": round(visit.setup_sec / 60.0, 1),
                "batch_lots": visit.batch_lots,
                "outcome": visit.outcome,
                "start_reason": visit.reason or None,
            },
        ),
        (
            "lot",
            "run_record",
            {
                "lot": lot_id,
                "class": order_class,
                "tier": class_tier(order_class),
                "due_h": _h(fab.lot_due[lot]),
                "due_slack_at_start_min": round((fab.lot_due[lot] - start) / 60.0, 1),
            },
        ),
        (
            "queue_at_start",
            "run_record",
            {
                "family": family_name,
                "waiting": tl.waiting_at(visit.family, start),
                "in_process": tl.in_process_at(visit.family, start),
            },
        ),
        ("wait_split", "run_record", {"lot": lot_id, "step": visit.step, "buckets_min": buckets}),
        (
            "tool",
            "run_record",
            {
                "tool": tool_name,
                "state_at_start": tl.tool_state(visit.tool, start),
                "down_windows_in_wait_h": down_spans[:4],
                "pm_windows_in_wait_h": pm_spans[:4],
            },
        ),
        ("decisions", "decision_log", {"lot": lot_id, "displaced": displaced}),
        (
            "emergent",
            "rule",
            {
                "ranking": "tiered_key: class tier, late band, Q-time (PED) risk, "
                "setup seconds, remaining slack",
                "recorded_start_reason": bool(visit.reason),
                "note": "The ranking is recomputed at every dispatch wake; beyond "
                "the recorded start reason and the wait split there is no "
                "per-decision record to quote.",
            },
        ),
    ]
    basis = _basis(entries)
    kit.registry.add(basis)
    kit.registry.add_text(f"{lot_id} {family_name} {tool_name}")
    # Tier by code: a recorded start reason or a recorded displacement of
    # this lot is a decision record; everything else is the rule's result.
    tier = (
        TIER_DECISION_RECORD
        if (visit.reason or displaced)
        else TIER_RULE_EMERGENT
    )
    top = sorted(buckets.items(), key=lambda kv: -kv[1])[:2]
    split = (
        " and ".join(f"{name} {value:g} min" for name, value in top)
        if top
        else "no recorded wait buckets"
    )
    reason = (
        f" The simulator recorded the start reason as '{visit.reason}'."
        if visit.reason
        else " No start reason was recorded for this start."
    )
    text = (
        f"{lot_id} step {visit.step} started on {tool_name} at {_h(start):g} h; it was ready "
        f"at {_h(visit.ready):g} h and waited {round(wait_sec / 60.0, 1):g} min.{reason} "
        f"Its wait was split as {split}. When it started, "
        f"{tl.waiting_at(visit.family, start)} lots were waiting at {family_name} and the lot "
        f"is {order_class} class (tier {class_tier(order_class)}), due at {_h(fab.lot_due[lot]):g} h. "
        "Why this lot on this tool is otherwise emergent: the dispatch ranking (class tier, "
        "late band, Q-time risk, setup, slack) is recomputed at every wake and leaves no "
        "single decision record beyond the start reason and wait split above."
    )
    return ContextAnswer(
        query=query.to_json(),
        type="bar",
        tier=tier,
        answer=text,
        basis=basis,
        citations=[entry["n"] for entry in basis],
    )


# ---- gap classification (insight.gaps adapter) ----------------------------------------------
def _gap_classification(
    kit: Toolkit, tool: int, t1: float, t2: float
) -> tuple[str, str, dict[str, Any]]:
    """(reason, tier, facts) for one tool's idle span in [t1, t2) seconds.

    Prefers ``insight.gaps`` (its GapRecord classification) when that module
    is in the tree; otherwise mirrors its taxonomy and priority from the
    same evidence. The mirrored path is labelled in the facts.
    """
    fab, tl = kit.fab, kit.tl
    try:
        from resilimes.insight import gaps as gaps_module

        for record in gaps_module.gaps_from_run(kit.run):
            if record.tool == tool and record.start < t2 and record.end > t1:
                tier = {
                    gaps_module.TIER_DECISION_RECORD: TIER_DECISION_RECORD,
                    gaps_module.TIER_INFERRED: TIER_RULE_EMERGENT,
                    gaps_module.TIER_UNKNOWN: TIER_UNKNOWN,
                }.get(record.tier, TIER_RULE_EMERGENT)
                if record.reason.value == "unknown":
                    tier = TIER_UNKNOWN
                return record.reason.value, tier, {
                    "reason": record.reason.value,
                    "classifier": "insight.gaps",
                    "record_source": record.source,
                    "evidence": record.evidence.to_json()
                    if hasattr(record.evidence, "to_json")
                    else {},
                }
    except ImportError:
        pass
    # Mirrored classification: the same evidence rules as
    # insight.gaps._evidence_for_gap (batch / PM / CQT only; plan-band,
    # reserve, setup and downstream evidence is not recoverable from a
    # finished run's timeline, so those reasons stay unmatched here too).
    fam = fab.tool_family[tool]
    evidence: dict[str, Any] = {}
    for span_start, _span_end in kit.run.pm[tool]:
        if t1 <= span_start < t2:
            evidence["pm_at_h"] = _h(span_start)
            break
    for visit in tl.by_family.get(fam, []):
        if visit.tool != tool or visit.start is None:
            continue
        route = fab.routes[fab.lot_route[visit.lot]]
        if abs(visit.start - t2) <= 1.0 and visit.batch_lots > 1:
            evidence["next_batch_lots"] = visit.batch_lots
            evidence["batch_min_lots"] = max(1, route.batch_min[visit.step] // 25)
        if visit.ready <= t1 and visit.start >= t2 and route.cqt_limit[visit.step] > 0:
            evidence["qtime_blocked_lot"] = fab.lot_id[visit.lot]
    matched: set[str] = set()
    if "pm_at_h" in evidence:
        matched.add("pm_avoidance")
    if "qtime_blocked_lot" in evidence:
        matched.add("qtime_gate")
    if "next_batch_lots" in evidence and "batch_min_lots" in evidence:
        matched.add("batch_wait")
    reason = next((r for r in _GAP_REASON_PRIORITY if r in matched), "unknown")
    facts: dict[str, Any] = {
        "reason": reason,
        "classifier": "mirrored insight.gaps taxonomy (module not in this tree)",
        "evidence": evidence,
        "not_checked": ["plan_wait", "capacity_reserve", "setup_saving", "downstream_blocked"],
    }
    return reason, (TIER_UNKNOWN if reason == "unknown" else TIER_RULE_EMERGENT), facts


# ---- gap ------------------------------------------------------------------------------------
def _gap(kit: Toolkit, query: ContextQuery) -> ContextAnswer:
    fab, tl = kit.fab, kit.tl
    if query.tool is None or query.tool not in fab.tool_name:
        raise ContextError("gap queries need a tool name from the run")
    if query.t1_h is None:
        raise ContextError("gap queries need t1_h")
    tool = fab.tool_name.index(query.tool)
    fam = fab.tool_family[tool]
    family_name = fab.families[fam].name
    t1 = query.t1_h * HOUR
    t2 = (query.t2_h if query.t2_h is not None else query.t1_h + 1.0) * HOUR
    states = tl.state_seconds(tool, t1, t2)
    idle_h = round((states[IDLE] + states[RESERVED]) / HOUR, 2)
    entries: list[tuple[str, str, dict[str, Any]]] = [
        (
            "tool_window",
            "run_record",
            {
                "tool": query.tool,
                "family": family_name,
                "window_h": [query.t1_h, round(t2 / HOUR, 2)],
                "busy_h": round(states["busy"] / HOUR, 2),
                "down_h": round(states[DOWN] / HOUR, 2),
                "pm_h": round(states[PM] / HOUR, 2),
                "idle_h": idle_h,
            },
        )
    ]
    if idle_h <= 0.01:
        basis = _basis(entries)
        kit.registry.add(basis)
        text = (
            f"{query.tool} was not idle in this window: {round(states['busy'] / HOUR, 2):g} h busy, "
            f"{round(states[DOWN] / HOUR, 2):g} h down, {round(states[PM] / HOUR, 2):g} h PM."
        )
        return ContextAnswer(
            query=query.to_json(),
            type="gap",
            tier=TIER_RULE_EMERGENT,
            answer=text,
            basis=basis,
            citations=[1],
        )
    waiting = [
        v
        for v in tl.by_family.get(fam, [])
        if v.ready < t2 and (v.start if v.start is not None else tl.horizon) > t1
    ]
    totals: dict[str, float] = {}
    for visit in waiting:
        for row in visit_waits(tl, visit.lot, t1, t2):
            for key, sec in row["buckets"].items():
                totals[key] = totals.get(key, 0.0) + sec
    buckets = {k: round(v / 60.0, 1) for k, v in totals.items() if v > 0}
    batch_lots = sum(
        1 for v in waiting if fab.routes[fab.lot_route[v.lot]].batch_max[v.step] > 0
    )
    qtime_holds = sum(
        1
        for v in waiting
        for gap in tl.gaps.get(v.lot, [])
        if gap.kind == "qtime_hold" and gap.start < t2 and gap.end > t1
    )
    reason, class_tier_value, class_facts = _gap_classification(kit, tool, t1, t2)
    ai_events_here = sum(
        1
        for event in tl.ai_events
        if int(event.get("tool", -1)) == tool and t1 <= float(event.get("t", -1)) < t2
    )
    displaced_here = sum(
        1
        for lot_displaced in tl.displaced.values()
        for d in lot_displaced
        if d.tool == tool and t1 <= d.at < t2
    )
    entries += [
        (
            "waiting_lots",
            "run_record",
            {
                "family": family_name,
                "count": len(waiting),
                "lots": [fab.lot_id[v.lot] for v in waiting[:8]],
                "batch_step_lots": batch_lots,
                "qtime_holds_in_window": qtime_holds,
            },
        ),
        ("wait_causes", "run_record", {"family": family_name, "buckets_min": buckets}),
        ("gap_classification", "gap_classifier", class_facts),
        (
            "decisions",
            "decision_log",
            {
                "tool": query.tool,
                "ai_events_in_window": ai_events_here,
                "displacements_in_window": displaced_here,
            },
        ),
    ]
    basis = _basis(entries)
    kit.registry.add(basis)
    kit.registry.add_text(f"{query.tool} {family_name}")
    decided = bool(ai_events_here or displaced_here)
    # A classification or a stray decision event alone is not an answer:
    # with no lot waiting and no bucketed wait, nothing was observably
    # held, so the gap stays unknown (both are still reported in basis).
    # A decision record only raises the tier of a gap that has evidence.
    if not (waiting or buckets):
        tier = TIER_UNKNOWN
    elif decided:
        tier = TIER_DECISION_RECORD
    else:
        tier = TIER_RULE_EMERGENT
    if tier == TIER_UNKNOWN:
        text = (
            f"{query.tool} was idle {idle_h:g} h in this window, but no lot was waiting at "
            f"{family_name} and no recorded hold overlaps it. The recorded evidence does "
            "not say why (unknown)."
        )
        return ContextAnswer(
            query=query.to_json(),
            type="gap",
            tier=tier,
            status="unknown",
            answer=text,
            basis=basis,
            citations=[entry["n"] for entry in basis],
        )
    top = sorted(buckets.items(), key=lambda kv: -kv[1])[:2]
    causes = (
        "; ".join(f"{_BUCKET_PHRASE.get(name, name)} ({value:g} min in total)" for name, value in top)
        if top
        else "no bucketed wait was recorded for the waiting lots"
    )
    text = (
        f"{query.tool} was idle {idle_h:g} h between {query.t1_h:g} h and {round(t2 / HOUR, 2):g} h "
        f"while {len(waiting)} lots were waiting at {family_name}. The waiting lots' time in "
        f"this window went mainly to {causes}. The gap classification is {reason}. "
        "That is the recorded evidence for the gap; the dispatcher does not log a "
        "separate idle reason per tool."
    )
    return ContextAnswer(
        query=query.to_json(),
        type="gap",
        tier=tier,
        answer=text,
        basis=basis,
        citations=[entry["n"] for entry in basis],
    )


# ---- window ---------------------------------------------------------------------------------
def _window(
    kit: Toolkit, query: ContextQuery, provider: Completer | None, settings: Any
) -> ContextAnswer:
    from resilimes.insight.investigator import investigate

    if query.family is None or query.t1_h is None or query.t2_h is None:
        raise ContextError("window queries need family, t1_h and t2_h")
    question = query.question or (
        f"Why did {query.family} WIP change between {query.t1_h:g} h and {query.t2_h:g} h?"
    )
    result = investigate(
        kit, question, query.family, query.t1_h, query.t2_h, provider, settings
    )
    entries: list[tuple[str, str, dict[str, Any]]] = [
        (
            "investigation",
            "investigator",
            {
                "family": query.family,
                "window_h": [query.t1_h, query.t2_h],
                "primary_cause": result.primary_cause,
                "secondary_cause": result.secondary_cause,
                "tool_calls": len(result.calls),
                "stop_reason": result.stop_reason,
            },
        )
    ]
    entries += [
        ("tool_call", "investigator", {"n": call.get("n"), "tool": call.get("tool")})
        for call in result.calls
    ]
    basis = _basis(entries)
    if result.degraded:
        system = result.system or {}
        chain = system.get("causal_chain") or []
        text = " ".join(chain) or (
            f"The AI answer was degraded to the rule baseline, which ranks "
            f"{system.get('primary_cause')} first for {query.family} in this window."
        )
        primary = system.get("primary_cause") or result.primary_cause
        secondary = system.get("secondary_cause") or result.secondary_cause
    else:
        text = " ".join(result.causal_chain)
        if result.lever:
            text = f"{text} Lever: {result.lever}" if text else result.lever
        primary, secondary = result.primary_cause, result.secondary_cause
    return ContextAnswer(
        query=query.to_json(),
        type="window",
        tier=TIER_RULE_EMERGENT if primary else TIER_UNKNOWN,
        answer=text,
        basis=basis,
        citations=[1],
        primary_cause=primary,
        secondary_cause=secondary,
        fact_ok=result.fact_ok,
        fact_misses=list(result.fact_misses),
        source="scripted" if result.mocked else "llm",
        degraded=bool(result.degraded),
        degrade_reason=result.degrade_reason,
        mocked=bool(result.mocked),
        provider=result.provider,
        model=result.model,
        error=result.error,
    )


# ---- fab notes (context claims, not run records) ---------------------------------------------
def load_fab_notes() -> list[dict[str, Any]] | None:
    """The fab_notes dataset (operator notes + gold events), or None.

    Looked up at ``$RESILIMES_NOTES_PATH`` first, then at
    ``data/notes/fab_notes.json`` in the repo (the Plan-2 dataset). None
    means "not in this build": callers add a placeholder basis entry and
    the answer simply has no notes part.
    """
    candidates = []
    if os.environ.get("RESILIMES_NOTES_PATH"):
        candidates.append(Path(os.environ["RESILIMES_NOTES_PATH"]))
    candidates.append(Path(__file__).resolve().parents[2] / "data" / "notes" / "fab_notes.json")
    for path in candidates:
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            items = payload.get("items") if isinstance(payload, dict) else payload
            return items if isinstance(items, list) else None
    return None


def _notes_part(
    kit: Toolkit, query: ContextQuery
) -> tuple[list[tuple[str, str, dict[str, Any]]], str]:
    """Basis entries + an answer paragraph from notes mentioning the query's ids."""
    notes = load_fab_notes()
    if notes is None:
        return [
            (
                "fab_notes",
                "fab_notes",
                {
                    "available": False,
                    "note": "fab_notes dataset not in this build; notes chaining is "
                    "an interface placeholder and contributes no evidence.",
                },
            )
        ], ""
    needles = [value for value in (query.tool, query.family, query.lot) if value]
    matched = []
    for note in notes:
        gold = note.get("gold") or []
        haystack = str(note.get("text", "")) + json.dumps(gold, ensure_ascii=False)
        if any(needle in haystack for needle in needles):
            matched.append(note)
        if len(matched) >= 3:
            break
    entries: list[tuple[str, str, dict[str, Any]]] = [
        (
            "fab_notes",
            "fab_notes",
            {
                "available": True,
                "matched": [
                    {
                        "id": note.get("id"),
                        "ts": note.get("ts"),
                        "source": note.get("source"),
                        "text": note.get("text"),
                        "events": gold,
                    }
                    for note in matched
                ],
            },
        )
    ]
    kit.registry.add(_basis(entries))
    if not matched:
        return entries, ""
    first = matched[0]
    events = ", ".join(sorted({str(e.get("type")) for e in (first.get("gold") or [])}))
    text = (
        f"Notes: a {first.get('source')} note ({first.get('id')}, {first.get('ts')}) says: "
        f"\"{first.get('text')}\" Its recorded events: {events or 'none'}. "
        "Notes are context claims from people, not run records."
    )
    return entries, text


# ---- free ------------------------------------------------------------------------------------
def _free(
    kit: Toolkit, query: ContextQuery, provider: Completer | None, settings: Any
) -> ContextAnswer:
    """Chain the evidence sources the query touches; label every part.

    Overall tier is the *weakest* tier among the parts that make a causal
    claim: a decision_record part cannot raise the tier of a rule-emergent
    part. Unknown parts are abstentions, not claims, so they do not drag
    the tier down — unless every part abstains. Per-part tiers are
    returned in ``part_tiers``.
    """
    parts: list[tuple[str, str, str]] = []  # (label, tier, text)
    basis: list[dict[str, Any]] = []

    def absorb(label: str, sub: ContextAnswer) -> None:
        offset = len(basis)
        for entry in sub.basis:
            basis.append({**entry, "n": offset + entry["n"]})
        parts.append((label, sub.tier, sub.answer))

    if query.lot:
        absorb("run_record", _bar(kit, query))
    if query.tool and query.t1_h is not None:
        absorb("gap_classifier", _gap(kit, query))
    if query.family and query.t1_h is not None and query.t2_h is not None:
        absorb("investigator", _window(kit, query, provider, settings))
    note_entries, note_text = _notes_part(kit, query)
    offset = len(basis)
    for entry in _basis(note_entries):
        basis.append({**entry, "n": offset + entry["n"]})
    if note_text:
        parts.append(("fab_notes", TIER_RULE_EMERGENT, note_text))
    kit.registry.add(basis)
    if not parts:
        text = (
            "The recorded evidence available to this service does not answer that "
            "question (unknown): no lot, tool window or family window was given to "
            "attach evidence to."
        )
        return ContextAnswer(
            query=query.to_json(),
            type="free",
            tier=TIER_UNKNOWN,
            status="unknown",
            answer=text,
            basis=basis,
            citations=[entry["n"] for entry in basis],
        )
    causal = [part_tier for _label, part_tier, _text in parts if part_tier != TIER_UNKNOWN]
    tier = TIER_UNKNOWN
    if causal:
        tier = causal[0]
        for part_tier in causal[1:]:
            tier = _weaker(tier, part_tier)
    labels = {"run_record": "Run record", "gap_classifier": "Gap evidence", "investigator": "Investigation", "fab_notes": "Notes"}
    text = " ".join(f"[{labels.get(label, label)}] {part_text}" for label, _t, part_text in parts)
    return ContextAnswer(
        query=query.to_json(),
        type="free",
        tier=tier,
        answer=text,
        basis=basis,
        citations=[entry["n"] for entry in basis],
        part_tiers={label: part_tier for label, part_tier, _t in parts},
        primary_cause=next(
            (e["facts"].get("primary_cause") for e in basis if e["kind"] == "investigation"),
            None,
        ),
    )


# ---- model polish (bar / gap / free; window has its own loop) -------------------------------
_POLISH_SYSTEM = (
    "Rewrite the ANSWER so a shift supervisor reading a Gantt chart understands it. "
    "Use ONLY numbers and names that appear in BASIS or in the ANSWER itself; do not "
    "add facts. The answer's honesty tier is {tier}: "
    "decision_record = a recorded decision may be stated directly; "
    "rule_emergent = the wording must keep it as the result of the rule under the "
    "state at the time — never write that anyone decided, chose, or intended anything; "
    "unknown answers are never rewritten. "
    'Reply with ONE JSON object: {{"answer": "..."}}'
)


def _tier_violation(text: str, tier: str) -> str | None:
    if tier != TIER_RULE_EMERGENT:
        return None
    lowered = text.lower()
    for phrase in _DECISION_LANGUAGE:
        if phrase in lowered:
            return phrase
    return None


def _polish(
    kit: Toolkit, out: ContextAnswer, provider: Completer | None
) -> ContextAnswer:
    if provider is None or provider.mocked or out.tier == TIER_UNKNOWN:
        # Unknown answers are never model-rewritten (tier is code-decided).
        misses = check(out.answer, kit.registry)
        out.fact_ok = not misses
        out.fact_misses = misses
        out.mocked = True
        out.provider = getattr(provider, "name", "scripted") if provider else "scripted"
        return out
    sentences = 5 if out.type == "free" else 3
    messages = [
        {
            "role": "system",
            "content": _POLISH_SYSTEM.format(tier=out.tier)
            + f" At most {sentences} short sentences.",
        },
        {
            "role": "user",
            "content": "BASIS: "
            + json.dumps(out.basis, ensure_ascii=False)
            + "\nANSWER: "
            + out.answer,
        },
    ]
    for attempt in range(2):
        try:
            reply = provider.complete(messages, lane=LANE, temperature=0.2)
        except Exception as exc:  # provider failure degrades, never blocks
            out.degraded = True
            out.degrade_reason = "provider_error"
            out.error = redact(f"provider: {type(exc).__name__}", 200)
            break
        out.provider = provider.name
        out.model = provider.model_for(LANE)
        out.mocked = False
        try:
            candidate = str(extract_json_object(reply.content).get("answer", "")).strip()
        except (ValueError, json.JSONDecodeError):
            candidate = ""
        if not candidate:
            out.degraded = True
            out.degrade_reason = "bad_json"
            break
        misses = check(candidate, kit.registry)
        violation = _tier_violation(candidate, out.tier)
        if violation:
            misses = [*misses, f"tier: decision language '{violation}' in a rule_emergent answer"]
        if not misses:
            out.answer = candidate
            out.source = "llm"
            out.fact_ok = True
            return out
        if attempt == 0:
            messages.append({"role": "assistant", "content": reply.content})
            messages.append(
                {
                    "role": "user",
                    "content": "These are not allowed in the rewrite: "
                    + ", ".join(misses[:12])
                    + ". Rewrite using only values from BASIS and keep the tier framing.",
                }
            )
            continue
        out.degraded = True
        out.degrade_reason = "tier_upgrade_refused" if violation else "fact_check_failed"
        out.fact_misses = misses
    out.fact_ok = not check(out.answer, kit.registry)
    return out


# ---- entry point ----------------------------------------------------------------------------
def investigate_context(
    run_or_kit: RecordedRun | Toolkit,
    query: ContextQuery,
    provider: Completer | None = None,
    settings: Any = None,
) -> ContextAnswer:
    """Answer one Gantt context query over one recorded run. Advice only."""
    if query.type not in QUERY_TYPES:
        raise ContextError(f"type must be one of {', '.join(QUERY_TYPES)}")
    if (
        query.question_preset is not None
        and query.question_preset not in QUESTION_PRESETS[query.type]
    ):
        raise ContextError(
            f"question_preset for {query.type} must be one of "
            f"{', '.join(QUESTION_PRESETS[query.type])}"
        )
    kit = run_or_kit if isinstance(run_or_kit, Toolkit) else Toolkit(run_or_kit)
    kit.registry = kit.registry or FactRegistry()
    if query.type == "window":
        return _window(kit, query, provider, settings)
    if query.type == "free":
        return _polish(kit, _free(kit, query, provider, settings), provider)
    out = _bar(kit, query) if query.type == "bar" else _gap(kit, query)
    return _polish(kit, out, provider)
