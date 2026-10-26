"""Three-role deliberation: long-term plan, current shift, floor reality.

The owner's design: before the AI layer answers an event, three internal
roles argue it from their own evidence, and the deterministic kernel — not
the loudest role — decides.

* ``long_term`` guards the long-window plan. Its only evidence is the
  planning layer's view (``smt.planning``): plan bands, per-lot slack and
  Q-time windows at risk, litho overload days, PM calendar windows.
* ``short_term`` guards this shift's execution. Its only evidence is the
  shift view: scheduling exceptions (``smt.exceptions``) with the options
  the engine built and their projected impacts, plus live queue state.
* ``field`` is the floor's real-time feedback channel. Its only evidence is
  the incoming notification itself (a fab-notes event dict:
  ``planned_down`` / ``priority_change`` / ``hold`` / ``capacity_derate``)
  and on-site observations (tool-state reports, lot holds, down reports).

Guardrails (Guardrailed Autonomy), by construction:

* Each assessor receives ONLY the event and its own context section. A role
  cannot cite another role's evidence because it never sees it.
* Disagreement is data: every conflict is recorded on the record, never
  averaged away.
* The decision is made by the deterministic kernel with the same rule the
  rest of the system uses — Q-time first. Dispatch-changing actions are
  chosen among the exception engine's options by the lexicographic impact
  order of ``smt.exceptions.Impact.key`` (Q-time violations, hot late,
  late lots, idle minutes), under a hard gate: a candidate whose projected
  Q-time violations exceed the rule default's is infeasible, discarded,
  and the rejection is recorded as a conflict. Roles cannot overrule this.
* A large language model, when configured, only rewrites the finished
  record's narrative into prose. Every number and id it writes must appear
  in the evidence (``evidence.factcheck``); on a failed check (after one
  repair turn) the scripted narrative is used and the record is marked
  ``degraded``. The model never sees a vote.

This module is called explicitly only; nothing on the default scheduling
path imports it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from resilimes.agents.jsonutil import extract_json_object
from resilimes.evidence.factcheck import FactRegistry, check
from resilimes.llm.base import Completer

LANE = "deliberation"

ROLES = ("long_term", "short_term", "field")
VERDICTS = ("support", "oppose", "caution", "abstain")

# The fab-notes event vocabulary (impl-notes, resilimes/insight/notes.py).
# Consumed as plain dicts; this module does not import that branch.
NOTE_TYPES = ("planned_down", "priority_change", "hold", "capacity_derate")
EVENT_TYPES = (*NOTE_TYPES, "breakdown", "exception")

ACTIONS = (
    "rule_default",
    "expedite",
    "reroute",
    "keep_pin",
    "start_batch",
    "defer_pm",
    "accept_event",
    "reject_event",
    "hold_lot",
)

# Lever kinds of smt.exceptions -> the deliberation action vocabulary.
_LEVER_ACTIONS = {
    "none": "rule_default",
    "prio": "expedite",
    "keep_pin": "keep_pin",
    "batch": "start_batch",
    "pm_defer": "defer_pm",
}

# What dispatch action an event asks for, before any role speaks.
# "exception_option" means: choose among the shift exception's options.
_IMPLIED_ACTION = {
    "priority_change": "expedite",
    "planned_down": "accept_event",
    "capacity_derate": "accept_event",
    "hold": "hold_lot",
    "breakdown": "exception_option",
    "exception": "exception_option",
}

SYSTEM = """You write the summary of an internal scheduling deliberation in a
semiconductor fab. You get a RECORD as JSON: the event, three role assessments
(long_term, short_term, field), the recorded conflicts, and the decision the
deterministic kernel already made. You do NOT decide anything and you must not
change, soften or hide the decision or any conflict.
Reply with ONE JSON object: {"narrative": "<= 5 sentences for a shift engineer"}.
Rules: use only numbers and names that appear in the RECORD. Name the roles
that disagreed and why the kernel ruled the way it did."""


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------
@dataclass
class RoleAssessment:
    """One role's stance, built only from that role's evidence."""

    role: str  # one of ROLES
    verdict: str = "abstain"  # one of VERDICTS
    evidence: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)  # {"code", "detail"}
    proposal: dict[str, Any] | None = None  # {"action", ...} from ACTIONS
    summary: str = ""  # scripted one-liner; the abstain reason when abstaining

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeliberationRecord:
    event: dict[str, Any]
    assessments: list[RoleAssessment]
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)
    decision_basis: dict[str, Any] = field(default_factory=dict)
    narrative: str = ""
    fact_ok: bool = False
    fact_misses: list[str] = field(default_factory=list)
    source: str = "scripted"  # "scripted", or the provider name when its text passed
    mocked: bool = True
    degraded: bool = False
    degrade_reason: str | None = None
    llm_calls: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "assessments": [item.to_json() for item in self.assessments],
            "conflicts": self.conflicts,
            "decision": self.decision,
            "decision_basis": self.decision_basis,
            "narrative": self.narrative,
            "fact_ok": self.fact_ok,
            "fact_misses": self.fact_misses,
            "source": self.source,
            "mocked": self.mocked,
            "degraded": self.degraded,
            "degrade_reason": self.degrade_reason,
            "llm_calls": self.llm_calls,
        }


# --------------------------------------------------------------------------
# Context adapters: real objects -> the plain-dict views the roles read.
# Canonical context shape (every section optional):
#   plan:  {"now_h", "bands", "qtime_at_risk", "lots": {lot_id: {...}},
#           "litho_overload_days": {family: [day, ...]},
#           "pm_windows": {equipment: [[start_h, end_h], ...]}}
#   shift: {"exceptions": [{"id", "kind", "family", "tool", "lots",
#            "options": [{"id", "action", "lever", "rule_default",
#                         "impact": {...} | None}]}],
#           "queues": {family: waiting lots}, "hot_waiting": [lot_id, ...]}
#   field: {"observations": [{"kind", "subject", "detail", ...}]}
# --------------------------------------------------------------------------
def plan_view(output: Any, *, pm_windows: dict[str, Any] | None = None) -> dict[str, Any]:
    """Adapt a ``smt.planning.PlanningOutput`` to the long-term role's view."""
    summary = output.summary()
    view: dict[str, Any] = {
        "now_h": summary["now_h"],
        "bands": summary["bands"],
        "qtime_at_risk": summary["qtime_at_risk"],
        "qtime_windows": summary["qtime_windows"],
        "litho_overload_days": summary["litho_overload_days"],
        "lots": {item.lot_id: item.public() for item in output.lots},
    }
    if pm_windows:
        view["pm_windows"] = {
            equipment: [[round(s / 3600.0, 2), round(e / 3600.0, 2)] for s, e in spans]
            for equipment, spans in pm_windows.items()
        }
    return view


def exception_views(
    exceptions: list[Any], *, family_names: list[str] | None = None
) -> list[dict[str, Any]]:
    """Adapt ``smt.exceptions.FabException`` objects to the shift role's view."""
    views: list[dict[str, Any]] = []
    for exc in exceptions:
        family: Any = exc.family
        if family_names is not None and isinstance(family, int):
            family = family_names[family]
        options = []
        for option in exc.options:
            lever = getattr(option.lever, "kind", "none")
            options.append(
                {
                    "id": option.id,
                    "action": _LEVER_ACTIONS.get(lever, lever),
                    "lever": lever,
                    "text": option.action,
                    "rule_default": bool(option.default),
                    "impact": None if option.impact is None else option.impact.as_dict(),
                }
            )
        views.append(
            {
                "id": exc.id,
                "kind": exc.kind,
                "family": family,
                "tool": exc.tool,
                "lots": list(exc.lots),
                "options": options,
            }
        )
    return views


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _target(event: dict[str, Any]) -> dict[str, Any]:
    """The lot / equipment / family / step an event is about (whichever exist)."""
    target: dict[str, Any] = {}
    for key in ("lot", "equipment", "family", "tool", "step"):
        if event.get(key) is not None:
            target[key] = event[key]
    return target


def _impact_key(impact: dict[str, Any] | None) -> tuple[float, ...] | None:
    """The system's lexicographic order (smt.exceptions.Impact.key)."""
    if impact is None:
        return None
    return (
        float(impact.get("qtime_violations", 0)),
        float(impact.get("hot_late", 0)),
        float(impact.get("late_lots", 0)),
        round(float(impact.get("idle_min", 0.0)), 1),
    )


def _relevant_exception(event: dict[str, Any], shift: dict[str, Any]) -> dict[str, Any] | None:
    """The shift exception this event is about, if the shift view has one."""
    exceptions = shift.get("exceptions") or []
    if not exceptions:
        return None
    etype = event.get("type")
    lot = event.get("lot")
    family = event.get("family") or event.get("equipment")
    kind_hint = {"breakdown": "breakdown", "priority_change": "hot_insertion"}.get(str(etype))
    for exc in exceptions:
        if (
            kind_hint
            and exc.get("kind") == kind_hint
            and (lot is None or lot in (exc.get("lots") or []) or exc.get("family") == family)
        ):
            return exc
    for exc in exceptions:
        if lot is not None and lot in (exc.get("lots") or []):
            return exc
        if family is not None and exc.get("family") == family:
            return exc
    return None


def _default_option(exc: dict[str, Any]) -> dict[str, Any] | None:
    return next((o for o in exc.get("options") or [] if o.get("rule_default")), None)


# --------------------------------------------------------------------------
# Role assessors. Each sees ONLY the event and its own context section.
# --------------------------------------------------------------------------
def assess_long_term(event: dict[str, Any], plan: dict[str, Any] | None) -> RoleAssessment:
    """Guard the long-window plan: bands, slack, PM calendar, Q-time at risk."""
    out = RoleAssessment(role="long_term")
    if not plan:
        out.summary = "no plan view supplied"
        return out
    etype = str(event.get("type", ""))
    target = _target(event)
    lot = target.get("lot")
    equipment = target.get("equipment") or target.get("family")

    bands = plan.get("bands") or {}
    if bands:
        out.evidence.append({"kind": "plan_bands", **bands})
    at_risk = plan.get("qtime_at_risk")
    if isinstance(at_risk, (int, float)) and at_risk:
        out.evidence.append({"kind": "plan_qtime_at_risk", "windows": at_risk})

    lot_plan = (plan.get("lots") or {}).get(lot) if lot else None
    if lot_plan:
        out.evidence.append(
            {
                "kind": "lot_plan",
                "lot": lot,
                "band": lot_plan.get("band"),
                "score": lot_plan.get("score"),
                "plan_slack_h": lot_plan.get("plan_slack_h"),
                "qtime_at_risk": lot_plan.get("qtime_at_risk"),
            }
        )
        if lot_plan.get("qtime_at_risk"):
            out.risks.append(
                {
                    "code": "lot_qtime_at_risk",
                    "detail": f"{lot} has {lot_plan['qtime_at_risk']} Q-time window(s) "
                    "at risk in the plan",
                }
            )

    overload_days = (plan.get("litho_overload_days") or {}).get(equipment) if equipment else None
    if overload_days:
        out.evidence.append(
            {"kind": "litho_overload", "family": equipment, "days": list(overload_days)}
        )
        out.risks.append(
            {
                "code": "capacity_overload",
                "detail": f"{equipment} is over capacity on plan day(s) {list(overload_days)}",
            }
        )

    # PM overlap: only when the event window is on the plan clock (start_h).
    pm_overlap_h = 0.0
    if equipment and event.get("start_h") is not None:
        start_h = float(event["start_h"])
        duration_h = float(event.get("duration_min") or 0) / 60.0
        if etype == "capacity_derate":
            start_h = float(plan.get("now_h") or 0.0)
            duration_h = float(event.get("window_h") or 0)
        for span in (plan.get("pm_windows") or {}).get(equipment, []):
            overlap = min(start_h + duration_h, float(span[1])) - max(start_h, float(span[0]))
            if overlap > 0:
                pm_overlap_h += overlap
        if pm_overlap_h > 0:
            out.evidence.append(
                {
                    "kind": "pm_overlap",
                    "equipment": equipment,
                    "overlap_h": round(pm_overlap_h, 2),
                }
            )
            out.risks.append(
                {
                    "code": "pm_window_overlap",
                    "detail": f"the event window overlaps a PM window on {equipment} "
                    f"by {round(pm_overlap_h, 2)} h",
                }
            )

    band = (lot_plan or {}).get("band")
    stressed = band in ("critical", "behind") or bool(overload_days)
    if etype == "priority_change":
        if lot_plan is None:
            out.summary = f"{lot} is not in the plan view; cannot judge the expedite"
        elif band in ("critical", "behind"):
            out.verdict = "support"
            out.proposal = {"action": "expedite", "lot": lot}
            out.summary = f"the plan already ranks {lot} {band}; expediting agrees with it"
        elif band == "ahead" and overload_days and (bands.get("critical") or bands.get("behind")):
            out.verdict = "oppose"
            out.risks.append(
                {
                    "code": "capacity_contention",
                    "detail": f"{lot} is ahead of plan while {equipment} is overloaded "
                    "and other lots are critical or behind",
                }
            )
            out.summary = "expediting an ahead-of-plan lot spends overloaded capacity"
        else:
            out.verdict = "caution"
            out.summary = f"{lot} is {band} in the plan; expediting is not needed by the plan"
    elif etype == "planned_down":
        if pm_overlap_h > 0:
            out.verdict = "oppose"
            out.summary = "the down window collides with the PM calendar"
        elif stressed:
            out.verdict = "caution"
            out.summary = "the plan is tight on this equipment; the down eats scarce capacity"
        else:
            out.verdict = "support"
            out.summary = "no plan band, overload or PM conflict on this equipment"
    elif etype == "hold":
        if band == "critical":
            out.verdict = "oppose"
            out.summary = f"holding {lot} breaks the plan: the lot is critical"
        elif band == "behind":
            out.verdict = "caution"
            out.summary = f"{lot} is behind plan; a hold makes recovery harder"
        elif lot_plan is None:
            out.summary = f"{lot} is not in the plan view; cannot judge the hold"
        else:
            out.verdict = "support"
            out.summary = f"{lot} is {band}; the plan can absorb a hold"
    elif etype == "capacity_derate":
        if stressed or pm_overlap_h > 0:
            out.verdict = "caution"
            out.summary = "the derate lands on an already tight plan window"
        else:
            out.verdict = "support"
            out.summary = "the plan has slack for this derate"
    elif etype in ("breakdown", "exception"):
        if stressed:
            out.verdict = "caution"
            out.summary = "the plan is tight here; recovery choices affect plan bands"
        else:
            out.verdict = "support"
            out.summary = "no plan objection to the shift's recovery options"
    else:
        out.summary = f"no long-term rule for event type {etype!r}"
    return out


def assess_short_term(event: dict[str, Any], shift: dict[str, Any] | None) -> RoleAssessment:
    """Guard this shift: exception options and their projected impacts."""
    out = RoleAssessment(role="short_term")
    if not shift:
        out.summary = "no shift view supplied"
        return out
    exc = _relevant_exception(event, shift)
    queues = shift.get("queues") or {}
    family = event.get("family") or event.get("equipment")
    if family is not None and queues.get(family):
        out.evidence.append({"kind": "queue", "family": family, "waiting": queues[family]})
    if exc is None:
        if event.get("type") in ("breakdown", "exception", "priority_change"):
            out.summary = "no exception with projected options covers this event"
        else:
            out.verdict = "support"
            out.summary = (
                "no shift exception is open on this event; intake does not disturb the shift"
            )
        return out

    out.evidence.append(
        {
            "kind": "exception",
            "id": exc.get("id"),
            "exception_kind": exc.get("kind"),
            "family": exc.get("family"),
        }
    )
    for option in exc.get("options") or []:
        out.evidence.append(
            {
                "kind": "option",
                "id": option.get("id"),
                "action": option.get("action"),
                "rule_default": bool(option.get("rule_default")),
                "impact": option.get("impact"),
            }
        )
    default = _default_option(exc)
    default_key = _impact_key(default.get("impact")) if default else None
    implied = _IMPLIED_ACTION.get(str(event.get("type", "")), "")
    best: dict[str, Any] | None = None
    best_key: tuple[float, ...] | None = None
    implied_option: dict[str, Any] | None = None
    for option in exc.get("options") or []:
        if option.get("rule_default"):
            continue
        if option.get("action") == implied:
            implied_option = option
        key = _impact_key(option.get("impact"))
        if key is None:
            continue
        if default_key is not None and key[0] > default_key[0]:
            continue  # hard Q-time gate: never a candidate
        if best_key is None or key < best_key:
            best, best_key = option, key

    if implied_option is not None:
        key = _impact_key(implied_option.get("impact"))
        if key is not None and default_key is not None and key[0] > default_key[0]:
            out.verdict = "oppose"
            out.proposal = {
                "action": "rule_default",
                "option_id": default.get("id") if default else None,
            }
            implied_impact = implied_option.get("impact") or {}
            default_impact = (default or {}).get("impact") or {}
            out.risks.append(
                {
                    "code": "qtime_gate",
                    "detail": f"option {implied_option.get('id')} projects "
                    f"{implied_impact.get('qtime_violations')} Q-time violations "
                    f"against {default_impact.get('qtime_violations')} for the rule default",
                }
            )
            out.summary = "the projected impact of the requested action breaks the Q-time gate"
            return out
    if (
        best is not None
        and best_key is not None
        and (default_key is None or best_key < default_key)
    ):
        out.verdict = "support"
        out.proposal = {
            "action": best.get("action"),
            "option_id": best.get("id"),
            "family": exc.get("family"),
        }
        out.summary = f"option {best.get('id')} ({best.get('action')}) projects the lowest impact"
    elif implied_option is not None:
        out.verdict = "support"
        out.proposal = {
            "action": implied_option.get("action"),
            "option_id": implied_option.get("id"),
            "family": exc.get("family"),
        }
        out.summary = "the requested action is among the projected options and passes the gate"
    else:
        out.verdict = "caution"
        out.summary = "options are projected but none beats the rule default"
    return out


def assess_field(event: dict[str, Any], section: dict[str, Any] | None) -> RoleAssessment:
    """Vouch for floor reality: the notification and on-site observations."""
    out = RoleAssessment(role="field")
    section = section or {}
    etype = str(event.get("type", ""))
    target = _target(event)
    subject = target.get("lot") or target.get("equipment") or target.get("family")

    if etype in NOTE_TYPES:
        note: dict[str, Any] = {"kind": "notification", "type": etype}
        note.update(target)
        for key in ("new_due_h", "priority", "duration_min", "factor", "window_h", "reason"):
            if event.get(key) is not None:
                note[key] = event[key]
        if event.get("source"):
            note["source"] = event["source"]
        out.evidence.append(note)
        if event.get("validated"):
            out.evidence.append({"kind": "validation", "status": "fact_checked"})

    observations = [
        obs
        for obs in section.get("observations") or []
        if subject is not None and obs.get("subject") == subject
    ]
    for obs in observations:
        out.evidence.append(
            {
                "kind": "observation",
                "obs_kind": obs.get("kind"),
                "subject": subject,
                "detail": obs.get("detail"),
            }
        )

    contradiction = False
    for obs in observations:
        kind = obs.get("kind")
        if etype == "planned_down" and kind == "tool_state" and obs.get("state") == "running":
            contradiction = True
            out.risks.append(
                {
                    "code": "contradiction",
                    "detail": f"{subject} is reported running on site; "
                    "the planned-down note does not match the floor",
                }
            )
        if etype == "priority_change" and kind == "lot_hold":
            contradiction = True
            out.risks.append(
                {
                    "code": "contradiction",
                    "detail": f"{subject} is on hold on the floor; it cannot be expedited now",
                }
            )
        if kind == "down_report" and etype in ("breakdown", "exception"):
            out.evidence[-1] = {**out.evidence[-1], "corroborates": True}

    if contradiction:
        out.verdict = "oppose"
        out.proposal = {"action": "reject_event"}
        out.summary = "the floor contradicts the notification"
    elif etype in NOTE_TYPES:
        out.verdict = "support"
        out.proposal = {"action": _IMPLIED_ACTION.get(etype, "accept_event"), **target}
        if etype == "priority_change":
            ask = []
            if event.get("priority"):
                ask.append(f"priority {event['priority']}")
            if event.get("new_due_h") is not None:
                ask.append(f"due in {event['new_due_h']} h")
            out.summary = f"customer notice received: {subject} to {', '.join(ask) or 'expedite'}"
        else:
            out.summary = f"floor notice received and not contradicted: {etype} on {subject}"
    elif observations:
        out.verdict = "support"
        out.summary = "floor observations corroborate the event"
    else:
        out.summary = "no notification and no floor observations for this event"
    return out


# --------------------------------------------------------------------------
# Conflicts and adjudication. The kernel decides; roles never vote.
# --------------------------------------------------------------------------
def _conflicts(
    event: dict[str, Any],
    assessments: list[RoleAssessment],
    gate_conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    by_role = {item.role: item for item in assessments}
    supporters = [r for r in ROLES if by_role[r].verdict == "support"]
    opposers = [r for r in ROLES if by_role[r].verdict == "oppose"]
    if supporters and opposers:
        conflicts.append(
            {
                "kind": "verdict_split",
                "roles": supporters + opposers,
                "topic": f"{event.get('type')} on "
                f"{_target(event).get('lot') or _target(event).get('equipment') or _target(event).get('family')}",
                "detail": "roles disagree: "
                + "; ".join(
                    f"{r} {by_role[r].verdict} ({by_role[r].summary})"
                    for r in supporters + opposers
                ),
            }
        )
    proposals: dict[str, list[str]] = {}
    for item in assessments:
        if item.proposal and item.proposal.get("action") not in (None, "rule_default"):
            key = str(
                item.proposal.get("lot")
                or item.proposal.get("equipment")
                or item.proposal.get("family")
                or ""
            )
            proposals.setdefault(key, []).append(f"{item.role}: {item.proposal['action']}")
    for target_key, asks in proposals.items():
        actions = {ask.split(": ", 1)[1] for ask in asks}
        if len(actions) > 1:
            conflicts.append(
                {
                    "kind": "resource_contention",
                    "roles": [ask.split(": ", 1)[0] for ask in asks],
                    "topic": target_key,
                    "detail": "incompatible proposals for the same target: " + "; ".join(asks),
                }
            )
    for item in assessments:
        for risk in item.risks:
            if risk.get("code") == "contradiction":
                conflicts.append(
                    {
                        "kind": "evidence_mismatch",
                        "roles": [item.role],
                        "topic": str(_target(event)),
                        "detail": risk["detail"],
                    }
                )
            if risk.get("code") == "pm_window_overlap" and by_role["field"].verdict == "support":
                conflicts.append(
                    {
                        "kind": "pm_band_risk",
                        "roles": ["long_term", "field"],
                        "topic": str(_target(event).get("equipment")),
                        "detail": risk["detail"],
                    }
                )
    conflicts.extend(gate_conflicts)
    return conflicts


def _adjudicate(
    event: dict[str, Any],
    assessments: list[RoleAssessment],
    shift: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Deterministic kernel ruling. Returns (decision, basis, gate_conflicts)."""
    etype = str(event.get("type", ""))
    target = _target(event)
    implied = _IMPLIED_ACTION.get(etype, "rule_default")
    basis: dict[str, Any] = {
        "rule": "Q-time first: hard gate on projected Q-time violations, then "
        "lexicographic (qtime_violations, hot_late, late_lots, idle_min); "
        "ties and unknowns keep the rule default",
        "unknown": [
            f"{item.role}: {item.summary}" for item in assessments if item.verdict == "abstain"
        ],
    }
    gate_conflicts: list[dict[str, Any]] = []
    field = next(item for item in assessments if item.role == "field")

    # A notification the floor itself contradicts never enters the plan.
    if field.verdict == "oppose" and any(
        risk.get("code") == "contradiction" for risk in field.risks
    ):
        decision = {"action": "reject_event", "intake": "rejected", **target}
        basis["decided_by"] = "evidence_mismatch: field contradiction"
        return decision, basis, gate_conflicts

    if implied in ("accept_event", "hold_lot"):
        decision = {"action": implied, "intake": "accepted", **target}
        basis["decided_by"] = (
            "event intake: a floor fact/instruction is recorded; "
            "dispatch consequences are re-planned by the scheduling layer"
        )
        return decision, basis, gate_conflicts

    # Dispatch-changing ruling: choose among the exception's options.
    exc = _relevant_exception(event, shift or {})
    options = (exc or {}).get("options") or []
    default = _default_option(exc) if exc else None
    default_key = _impact_key(default.get("impact")) if default else None
    candidates: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None
    chosen_key: tuple[float, ...] | None = None
    for option in options:
        key = _impact_key(option.get("impact"))
        entry: dict[str, Any] = {
            "option_id": option.get("id"),
            "action": option.get("action"),
            "impact": option.get("impact"),
            "feasible": True,
        }
        if key is not None and default_key is not None and key[0] > default_key[0]:
            entry["feasible"] = False
            entry["rejected_by"] = "hard_qtime_gate"
            if option.get("action") == implied and not option.get("rule_default"):
                gate_conflicts.append(
                    {
                        "kind": "qtime_gate",
                        "roles": ["short_term"],
                        "topic": f"option {option.get('id')} ({option.get('action')})",
                        "detail": f"projected Q-time violations {key[0]:g} exceed the "
                        f"rule default's {default_key[0]:g}; the action is infeasible "
                        "under Q-time first and was discarded",
                    }
                )
        candidates.append(entry)
        if not entry["feasible"] or option.get("rule_default"):
            continue
        if key is None:
            continue
        if chosen_key is None or key < chosen_key:
            chosen, chosen_key = option, key
    basis["candidates"] = candidates
    if default is not None:
        basis["gate"] = {
            "rule_default_option": default.get("id"),
            "rule_default_impact": default.get("impact"),
        }

    intake = {"intake": "accepted"} if etype == "priority_change" else {}
    if (
        chosen is not None
        and chosen_key is not None
        and (default_key is None or chosen_key < default_key)
    ):
        decision = {
            "action": chosen.get("action"),
            "option_id": chosen.get("id"),
            **intake,
            **target,
        }
        basis["decided_by"] = "lexicographic minimum among gate-feasible options"
    else:
        decision = {
            "action": "rule_default",
            "option_id": default.get("id") if default else None,
            **intake,
            **target,
        }
        basis["decided_by"] = "rule default kept (no gate-feasible option beats it)"
        if implied == "expedite" and not any(o.get("action") == "expedite" for o in options):
            basis["unknown"].append(
                "short_term: the expedite has no projected impact; "
                "an unprojected dispatch change is never approved"
            )
    return decision, basis, gate_conflicts


# --------------------------------------------------------------------------
# Narrative: scripted first; an LLM may only rewrite the words.
# --------------------------------------------------------------------------
_ROLE_ZH = {"long_term": "long-term", "short_term": "short-term", "field": "field"}


def _scripted_narrative(record: DeliberationRecord) -> str:
    event = record.event
    subject = (
        _target(event).get("lot")
        or _target(event).get("equipment")
        or _target(event).get("family")
        or "the fab"
    )
    lines = [f"Event {event.get('type')} on {subject}."]
    for item in record.assessments:
        lines.append(f"{_ROLE_ZH[item.role]} role: {item.verdict} — {item.summary}.")
    if record.conflicts:
        kinds = ", ".join(sorted({c["kind"] for c in record.conflicts}))
        lines.append(f"Conflicts recorded: {kinds}.")
    decision = record.decision
    lines.append(
        f"Decision: {decision.get('action')}"
        + (f" (option {decision['option_id']})" if decision.get("option_id") else "")
        + f". Basis: {record.decision_basis.get('decided_by', '')}."
    )
    return " ".join(lines)


def _registry_for(record: DeliberationRecord, context: dict[str, Any]) -> FactRegistry:
    registry = FactRegistry()
    registry.add(record.event)
    registry.add(context)
    registry.add([item.to_json() for item in record.assessments])
    registry.add(record.conflicts)
    registry.add(record.decision)
    registry.add(record.decision_basis)
    return registry


def _polish(record: DeliberationRecord, context: dict[str, Any], provider: Completer) -> None:
    """Let the model rewrite the narrative; fact-check it; fall back on failure."""
    scripted = record.narrative
    registry = _registry_for(record, context)
    payload = {"record": record.to_json(), "deterministic_narrative": scripted}
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    for attempt in range(2):
        try:
            reply = provider.complete(messages, lane=LANE, temperature=0.2)
        except Exception as exc:  # provider down: scripted text stands, flagged
            record.degraded = True
            record.degrade_reason = f"provider_error: {type(exc).__name__}"
            record.fact_ok = not check(scripted, registry)
            return
        record.llm_calls += 1
        record.mocked = provider.mocked
        try:
            parsed = extract_json_object(reply.content)
            text = str(parsed.get("narrative", "")).strip()
        except (ValueError, json.JSONDecodeError):
            text = ""
        if not text:
            record.degraded = True
            record.degrade_reason = "no_answer"
            record.fact_ok = not check(scripted, registry)
            return
        misses = check(text, registry)
        if not misses:
            record.narrative = text
            record.fact_ok = True
            record.fact_misses = []
            record.source = provider.name
            return
        if attempt == 0:
            messages.append({"role": "assistant", "content": reply.content})
            messages.append(
                {
                    "role": "user",
                    "content": "These numbers/names are not in the RECORD: "
                    + ", ".join(misses[:12])
                    + ". Rewrite using only values from the RECORD.",
                }
            )
            continue
        record.fact_misses = misses
        record.fact_ok = False
        record.degraded = True
        record.degrade_reason = "fact_check_failed"
        record.narrative = scripted
        record.source = "scripted"
        return


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def deliberate(
    event: dict[str, Any],
    context: dict[str, Any] | None = None,
    provider: Completer | None = None,
) -> DeliberationRecord:
    """Run the three-role deliberation over one event.

    ``event`` is a plain dict: a fab-notes event (``planned_down`` /
    ``priority_change`` / ``hold`` / ``capacity_derate``) or a scheduling
    event (``breakdown`` / ``exception``). ``context`` carries the three
    evidence views (``plan`` / ``shift`` / ``field``); any section may be
    missing, in which case that role abstains and the gap is recorded in
    ``decision_basis["unknown"]``. The caller's dicts are never mutated.
    With ``provider=None`` the narrative is the scripted one.
    """
    if not isinstance(event, dict) or not event.get("type"):
        raise ValueError("event must be a dict with a 'type'")
    event = dict(event)
    context = context or {}
    plan = context.get("plan")
    shift = context.get("shift")
    section = context.get("field")

    assessments = [
        assess_long_term(event, plan),
        assess_short_term(event, shift),
        assess_field(event, section),
    ]
    decision, basis, gate_conflicts = _adjudicate(event, assessments, shift)
    conflicts = _conflicts(event, assessments, gate_conflicts)
    record = DeliberationRecord(
        event=event,
        assessments=assessments,
        conflicts=conflicts,
        decision=decision,
        decision_basis=basis,
    )
    record.narrative = _scripted_narrative(record)
    if provider is None:
        registry = _registry_for(record, context)
        record.fact_misses = check(record.narrative, registry)
        record.fact_ok = not record.fact_misses
        record.source = "scripted"
        record.mocked = True
    else:
        _polish(record, context, provider)
    return record
