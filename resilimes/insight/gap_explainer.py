"""Gap explainer: answer "why is this tool idle here?" from the gap record.

The classification and every number come from ``insight.gaps`` (evidence,
not the model). A scripted explainer writes the answer deterministically;
an optional LLM provider may rewrite it in friendlier words, but the rewrite
must pass the fact check against the gap's own evidence -- one repair, then
the scripted text is used and the result is marked ``scripted_fallback``.
A gap classified ``unknown`` is explained as unknown: the honest answer is
that the run carries no evidence for a reason, not an invented one.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from resilimes.agents.jsonutil import extract_json_object
from resilimes.evidence.factcheck import FactRegistry, check
from resilimes.insight.gaps import GapReason, GapRecord
from resilimes.llm.base import Completer, LlmResult

LANE = "gap_explainer"

SYSTEM = """You rewrite one short explanation of why a semiconductor fab tool stood idle
(a "gap" in its schedule). You get the GAP RECORD as JSON: the classified reason, the
evidence numbers behind it, and a DRAFT explanation. Reply with ONE JSON object:
{"explanation": "<= 2 sentences for a shift engineer>"}.
Rules: keep the reason exactly as classified; use only numbers and names from the
GAP RECORD; do not add causes, lots, tools or times that are not in it. If the reason
is "unknown", say plainly that the run shows no recorded reason."""


@dataclass
class GapExplanation:
    tool: int
    family: int
    start: float
    end: float
    reason: str
    text: str = ""
    fact_ok: bool = False
    fact_misses: list[str] = field(default_factory=list)
    # scripted | llm | scripted_fallback
    source: str = "scripted"
    # decision_record | inferred_evidence | unknown (from the gap record)
    tier: str = "inferred_evidence"
    # Twin re-run verification of the reason. v1 never fills this in: the
    # explanation is unverified by counterfactual, and says so by ``None``.
    counterfactual: dict[str, Any] | None = None
    llm_calls: int = 0
    latency_ms: float = 0.0
    provider: str = ""
    model: str = ""
    mocked: bool = True
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _facts(gap: GapRecord) -> dict[str, Any]:
    """The numbers and ids an explanation of this gap may quote."""
    facts: dict[str, Any] = {
        "tool": gap.tool,
        "family": gap.family,
        "start_min": round(gap.start / 60.0, 1),
        "end_min": round(gap.end / 60.0, 1),
        "gap_min": round(gap.duration_s / 60.0, 1),
        "reason": gap.reason.value,
        "lot": gap.lot,
        "step": gap.step,
        "evidence": gap.evidence,
    }
    for key, value in gap.evidence.items():
        if key.endswith("_s") and isinstance(value, (int, float)):
            facts[f"{key}_min"] = round(float(value) / 60.0, 1)
    return facts


def _dispatch_text(gap: GapRecord, mins: float) -> str | None:
    """Explanation for a dispatch-log record: the reason was written down
    when the decision was made, so the text quotes the decision evidence."""
    ev = gap.evidence
    if gap.reason is GapReason.QTIME_GATE:
        return (
            f"Tool {gap.tool} waited {mins:g} min because the Q-time gate refused "
            f"this start at dispatch time: family {ev.get('blocked_family')} could "
            "not fit the lot's whole Q-time segment before its deadline, so "
            "starting would have risked a Q-time violation downstream. "
            f"({ev.get('decisions')} gate refusals recorded for this lot and step.)"
        )
    if gap.reason is GapReason.BATCH_WAIT:
        return (
            f"Tool {gap.tool} waited {mins:g} min to fill a batch, recorded at "
            f"dispatch time: {ev.get('wafers')} wafers were ready against a "
            f"{ev.get('floor_wafers')} wafer batch minimum, with "
            f"{ev.get('expected_arrivals')} more lots expected before the wait cap."
        )
    if gap.reason is GapReason.PM_AVOIDANCE:
        return (
            f"Tool {gap.tool} waited {mins:g} min rather than start a job that "
            "would have overrun planned maintenance, recorded at dispatch time: "
            f"the job needed {round(float(ev.get('proc_s', 0)) / 60.0, 1):g} min "
            "and the PM starts during this gap."
        )
    return None


def scripted_text(gap: GapRecord) -> str:
    """Deterministic explanation from the record alone."""
    facts = _facts(gap)
    mins = facts["gap_min"]
    ev = gap.evidence
    if gap.source == "dispatch_log":
        text = _dispatch_text(gap, mins)
        if text is not None:
            return text
    if gap.reason is GapReason.BATCH_WAIT:
        return (
            f"Tool {gap.tool} waited {mins:g} min to fill a batch: the next start "
            f"ran {ev.get('next_batch_lots')} lots and the batch minimum is "
            f"{ev.get('batch_min_lots')} lots, so starting earlier would have run "
            "the furnace under-filled."
        )
    if gap.reason is GapReason.QTIME_GATE:
        return (
            f"Tool {gap.tool} waited {mins:g} min because the Q-time gate held the "
            "lot at this origin step: its whole Q-time segment did not fit, so "
            "starting it would have created a Q-time violation downstream."
        )
    if gap.reason is GapReason.PM_AVOIDANCE:
        return (
            f"Tool {gap.tool} waited {mins:g} min rather than start a job that "
            "would have overrun the planned maintenance beginning during this gap."
        )
    if gap.reason is GapReason.PLAN_WAIT:
        return f"Tool {gap.tool} waited {mins:g} min for the planning band to release this start."
    if gap.reason is GapReason.CAPACITY_RESERVE:
        return f"Tool {gap.tool} waited {mins:g} min holding capacity for an expected hot lot."
    if gap.reason is GapReason.SETUP_SAVING:
        return (
            f"Tool {gap.tool} waited {mins:g} min so the next start could "
            "continue the same recipe without a setup change."
        )
    if gap.reason is GapReason.DOWNSTREAM_BLOCKED:
        return (
            f"Tool {gap.tool} waited {mins:g} min because the downstream "
            "station could not take its output."
        )
    return (
        f"Tool {gap.tool} was idle for {mins:g} min and this run carries no "
        "evidence of a deliberate reason; the gap is recorded as unknown."
    )


class ScriptedGapExplainer:
    """Offline stand-in with the same output shape as an LLM rewrite."""

    name = "scripted-mock"
    mocked = True

    def __init__(self, gap: GapRecord) -> None:
        self.gap = gap

    def model_for(self, lane: str) -> str:
        return "scripted-mock"

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.2
    ) -> LlmResult:
        return LlmResult(
            content=json.dumps({"explanation": scripted_text(self.gap)}),
            model="scripted-mock",
            provider="scripted-mock",
            lane=lane,
            latency_ms=0.0,
            mocked=True,
        )


def explain_gap(
    gap: GapRecord, provider: Completer | None = None, *, language: str = "en"
) -> GapExplanation:
    """Explain one gap. No provider (or a mocked one) gives the scripted text."""
    out = GapExplanation(
        tool=gap.tool,
        family=gap.family,
        start=gap.start,
        end=gap.end,
        reason=gap.reason.value,
        tier=gap.tier,
        counterfactual=gap.counterfactual,
    )
    draft = scripted_text(gap)
    registry = FactRegistry()
    registry.add(_facts(gap))
    if provider is None or provider.mocked:
        out.text = draft
        out.source = "scripted"
        out.provider = "scripted-mock"
        out.model = "scripted-mock"
        out.fact_misses = check(draft, registry)
        out.fact_ok = not out.fact_misses
        return out
    out.provider = provider.name
    out.model = provider.model_for(LANE)
    out.mocked = False
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "GAP RECORD: "
            + json.dumps(_facts(gap), ensure_ascii=False)
            + "\nDRAFT: "
            + draft,
        },
    ]
    started = time.perf_counter()
    text: str | None = None
    repaired = False
    for _turn in range(3):
        try:
            reply = provider.complete(messages, lane=LANE, temperature=0.2)
        except Exception as exc:  # provider down: degrade to the scripted text
            out.error = f"provider: {type(exc).__name__}"
            break
        out.llm_calls += 1
        messages.append({"role": "assistant", "content": reply.content})
        try:
            candidate = extract_json_object(reply.content)
            candidate_text = str(candidate.get("explanation", "")).strip()
        except (ValueError, json.JSONDecodeError):
            candidate_text = ""
        if not candidate_text:
            messages.append({"role": "user", "content": "Reply with one JSON object only."})
            continue
        misses = check(candidate_text, registry)
        if misses and not repaired:
            repaired = True
            messages.append(
                {
                    "role": "user",
                    "content": "These numbers/names are not in the gap record: "
                    + ", ".join(misses[:12])
                    + ". Rewrite using only values from the GAP RECORD.",
                }
            )
            continue
        out.fact_misses = misses
        if not misses:
            text = candidate_text
        break
    out.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if text is not None:
        out.text = text
        out.source = "llm"
        out.fact_ok = True
    else:
        out.text = draft
        out.source = "scripted_fallback"
        out.fact_misses = check(draft, registry)
        out.fact_ok = not out.fact_misses
    return out
