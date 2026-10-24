"""Late-lot explainer: why is this lot late, and what one change would have helped?

The lateness split comes from ``evidence.lateness`` and sums exactly to the
lateness (that is checked, not assumed). The model (Nemotron through
Nightshift; a scripted stand-in offline) gets the split and the longest waits,
writes a short explanation, and proposes ONE counterfactual from a fixed lever
menu with the minutes it expects to save. The counterfactual is then verified
by one re-run of the same seed with that lever applied. Every number and id in
the explanation must appear in the evidence (one rewrite, then flagged). The
counterfactual is advice only: the re-run is a what-if, the plan is not changed.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from resilimes.agents.jsonutil import extract_json_object
from resilimes.evidence.factcheck import FactRegistry, check
from resilimes.evidence.lateness import decompose
from resilimes.evidence.toolkit import HOUR, RecordedRun, Toolkit, record_run
from resilimes.llm.base import Completer, LlmResult

LANE = "explainer"
LEVERS = ("prioritise", "clear_down", "skip_pm")
LEVER_TEXT = {
    "prioritise": "make this lot the hot lot for its whole stay (dispatch takes it first)",
    "clear_down": "the tools of one family have no unscheduled down while this lot waits there",
    "skip_pm": "the tools of one family defer PM that overlaps this lot's wait there",
}
LANGUAGES = {"en": "English", "zh": "Simplified Chinese", "ja": "Japanese"}
HIT_FRACTION = 0.5
MAX_TURNS = 4

SYSTEM = """You explain why one wafer lot in a semiconductor fab simulation finished late.
You get EVIDENCE as JSON: the lateness split (minutes while late and over the whole stay;
the parts add up to the totals), the longest queue waits by step with their causes, and
no_wait_late_min (how late it would be with zero waiting; > 0 means processing alone
already misses the due time).
Reply with ONE JSON object, no prose outside it:
{"explanation": "<= 3 sentences for a shift engineer>",
 "dominant": "<largest bucket while late>",
 "counterfactual": {"lever": "prioritise|clear_down|skip_pm",
                    "family": "<family name, required for clear_down and skip_pm>",
                    "expected_saving_min": <number > 0>,
                    "claim": "<one sentence>"}}
Rules: use only numbers and names from EVIDENCE in explanation and claim (the expected
saving is your own estimate). Pick the lever that removes the most waiting for THIS lot.
Do not invent tools, lots or times."""


@dataclass
class Explanation:
    lot: str
    explanation: str = ""
    dominant: str | None = None
    lever: str | None = None
    family: str | None = None
    expected_saving_min: float | None = None
    claim: str = ""
    fact_misses: list[str] = field(default_factory=list)
    fact_ok: bool = False
    repaired: bool = False
    llm_calls: int = 0
    latency_ms: float = 0.0
    provider: str = ""
    model: str = ""
    mocked: bool = True
    language: str = "en"
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def evidence(kit: Toolkit, lot_id: str) -> dict[str, Any]:
    return {"lateness": kit.lot_lateness(lot_id), "waits": kit.lot_waits(lot_id)}


def _family_minutes(waits: dict[str, Any], bucket: str) -> tuple[str | None, float]:
    best: tuple[str | None, float] = (None, 0.0)
    per: dict[str, float] = {}
    for row in waits["longest_waits"]:
        per[row["family"]] = per.get(row["family"], 0.0) + row["buckets_min"].get(bucket, 0.0)
    for fam, minutes in per.items():
        if minutes > best[1]:
            best = (fam, minutes)
    return best


class ScriptedExplainer:
    """Offline stand-in: picks the lever with the most waiting behind it and writes a
    templated explanation from the evidence. Same parser, fact check and re-run."""

    name = "scripted-mock"
    mocked = True

    def __init__(self, ev: dict[str, Any]) -> None:
        self.ev = ev

    def model_for(self, lane: str) -> str:
        return "scripted-mock"

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.2
    ) -> LlmResult:
        late = self.ev["lateness"]
        waits = self.ev["waits"]
        while_late = late["while_late_min"]
        dominant = max(while_late, key=while_late.get) if while_late else "processing"
        whole = late["whole_stay_min"]
        options: list[tuple[str, str | None, float]] = [
            ("prioritise", None, float(whole.get("lots_ahead", 0.0)))
        ]
        fam, minutes = _family_minutes(waits, "down")
        if fam:
            options.append(("clear_down", fam, minutes))
        fam, minutes = _family_minutes(waits, "pm")
        if fam:
            options.append(("skip_pm", fam, minutes))
        lever, family, saving = max(options, key=lambda item: item[2])
        parts = sorted(while_late.items(), key=lambda kv: -kv[1])[:2]
        split = " and ".join(f"{name} {value:g} min" for name, value in parts)
        text = f"{late['lot']} finished {late['late_min']:g} min late; while late it spent {split}."
        if waits["no_wait_late_min"] > 0:
            text += (
                f" Even with no waiting it would be {waits['no_wait_late_min']:g} min late,"
                " so the due time was out of reach."
            )
        if waits["longest_waits"]:
            top = waits["longest_waits"][0]
            text += f" Its longest wait was {top['wait_min']:g} min at {top['family']}."
        target = f" at {family}" if family else ""
        payload = {
            "explanation": text,
            "dominant": dominant,
            "counterfactual": {
                "lever": lever,
                "family": family,
                "expected_saving_min": round(max(saving, 1.0), 1),
                "claim": f"Applying {lever}{target} removes the waiting behind it.",
            },
        }
        return LlmResult(
            content=json.dumps(payload),
            model="scripted-mock",
            provider="scripted-mock",
            lane=lane,
            latency_ms=0.0,
            mocked=True,
        )


def _validate(payload: dict[str, Any], kit: Toolkit) -> list[str]:
    errors: list[str] = []
    if not str(payload.get("explanation", "")).strip():
        errors.append("explanation is empty")
    cf = payload.get("counterfactual")
    if not isinstance(cf, dict):
        return [*errors, "counterfactual must be an object"]
    if cf.get("lever") not in LEVERS:
        errors.append(f"lever must be one of {', '.join(LEVERS)}")
    if cf.get("lever") in ("clear_down", "skip_pm"):
        try:
            kit.family_id(str(cf.get("family") or ""))
        except KeyError:
            errors.append("family must be a family name from the evidence")
    try:
        if float(cf.get("expected_saving_min") or 0) <= 0:
            errors.append("expected_saving_min must be > 0")
    except (TypeError, ValueError):
        errors.append("expected_saving_min must be a number")
    return errors


def explain(
    kit: Toolkit,
    lot_id: str,
    provider: Completer | None = None,
    *,
    language: str = "en",
    temperature: float = 0.2,
) -> Explanation:
    kit.registry = kit.registry or FactRegistry()
    ev = evidence(kit, lot_id)
    if provider is None or provider.mocked:
        provider = ScriptedExplainer(ev)
    out = Explanation(
        lot=lot_id,
        provider=provider.name,
        model=provider.model_for(LANE),
        mocked=provider.mocked,
        language=language,
    )
    lang = LANGUAGES.get(language, "English")
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "LEVERS: "
            + json.dumps(LEVER_TEXT)
            + f"\nWrite explanation and claim in {lang}; keep JSON keys and lever names in "
            "English.\nEVIDENCE: " + json.dumps(ev, ensure_ascii=False),
        },
    ]
    started = time.perf_counter()
    payload: dict[str, Any] | None = None
    schema_repairs = 0
    for _turn in range(MAX_TURNS):
        try:
            reply = provider.complete(messages, lane=LANE, temperature=temperature)
        except Exception as exc:
            out.error = f"provider: {type(exc).__name__}"
            break
        out.llm_calls += 1
        messages.append({"role": "assistant", "content": reply.content})
        try:
            candidate = extract_json_object(reply.content)
        except (ValueError, json.JSONDecodeError):
            messages.append({"role": "user", "content": "Reply with one JSON object only."})
            continue
        errors = _validate(candidate, kit)
        if errors:
            if schema_repairs < 2:
                schema_repairs += 1
                messages.append({"role": "user", "content": "Fix: " + "; ".join(errors)})
                continue
            out.error = "invalid answer: " + "; ".join(errors)
            break
        cf = candidate["counterfactual"]
        text = f"{candidate.get('explanation', '')} {cf.get('claim', '')}"
        registry = FactRegistry()
        registry.ids, registry.numbers = set(kit.registry.ids), set(kit.registry.numbers)
        registry.add_text(f"{cf.get('expected_saving_min')} {lot_id}")
        misses = check(text, registry)
        if misses and not out.repaired:
            out.repaired = True
            messages.append(
                {
                    "role": "user",
                    "content": "These numbers/names are not in the evidence: "
                    + ", ".join(misses[:12])
                    + ". Rewrite using only values from EVIDENCE.",
                }
            )
            continue
        out.fact_misses = misses
        payload = candidate
        break
    out.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if payload is None:
        out.error = out.error or "no valid answer"
        return out
    cf = payload["counterfactual"]
    out.explanation = str(payload.get("explanation", ""))
    dominant = payload.get("dominant")
    out.dominant = str(dominant) if dominant else None
    out.lever = str(cf["lever"])
    out.family = str(cf.get("family")) if cf.get("family") else None
    out.expected_saving_min = float(cf["expected_saving_min"])
    out.claim = str(cf.get("claim", ""))
    out.fact_ok = not out.fact_misses
    return out


def _wait_windows(run: RecordedRun, lot: int, fam: int) -> list[tuple[float, float]]:
    end = run.timeline.completed.get(lot, run.horizon)
    windows = []
    for visit in run.timeline.visits.get(lot, []):
        if visit.family != fam:
            continue
        stop = visit.start if visit.start is not None else (visit.leave or end)
        if stop > visit.ready:
            windows.append((visit.ready, stop))
    return windows


def lateness_sec(run: RecordedRun, lot: int) -> float:
    return run.timeline.completed.get(lot, run.horizon) - run.fab.lot_due[lot]


def verify(base: RecordedRun, lot_id: str, answer: Explanation) -> dict[str, Any]:
    """One re-run of the same seed with the proposed lever; did it save what was claimed?"""
    fab = base.fab
    lot = fab.lot_id.index(lot_id)
    kwargs: dict[str, Any] = {}
    if answer.lever == "prioritise":
        kwargs["hot_lot"] = lot
    elif answer.lever in ("clear_down", "skip_pm") and answer.family:
        fam = Toolkit(base).family_id(answer.family)
        windows = _wait_windows(base, lot, fam)
        spans = {tool: windows for tool in base.timeline.family_tools(fam)}
        kwargs["drop_downs" if answer.lever == "clear_down" else "drop_pm"] = spans
    else:
        return {"verified": False, "reason": "no lever"}
    started = time.perf_counter()
    rerun = record_run(
        fab,
        seed=base.seed,
        horizon=base.horizon,
        policy=base.policy,
        label=f"cf-{answer.lever}",
        **kwargs,
    )
    before = lateness_sec(base, lot) / 60.0
    after = lateness_sec(rerun, lot) / 60.0
    saving = before - after
    expected = answer.expected_saving_min or 0.0
    return {
        "verified": True,
        "lever": answer.lever,
        "family": answer.family,
        "late_before_min": round(before, 1),
        "late_after_min": round(after, 1),
        "saving_min": round(saving, 1),
        "expected_saving_min": round(expected, 1),
        "hit": saving > 0 and saving >= HIT_FRACTION * expected,
        "rerun_seconds": round(time.perf_counter() - started, 1),
    }


def exact_split(run: RecordedRun, lot: int) -> dict[str, Any]:
    """Exact-sum check of one late lot (seconds and the rounded minutes shown)."""
    raw = decompose(run.timeline, lot)
    shown = Toolkit(run).lot_lateness(run.fab.lot_id[lot])
    return {
        "exact": bool(raw["exact"]),
        "residual_sec": max(abs(raw["history_residual_sec"]), abs(raw["overrun_residual_sec"])),
        "shown_sum_ok": abs(sum(shown["while_late_min"].values()) - raw["lateness_sec"] / 60.0)
        <= 0.051,
        "late_min": round(raw["lateness_sec"] / 60.0, 1),
    }


HORIZON_H = 48
SEEDS = (1, 2)


def base_run(fab: Any, seed: int) -> RecordedRun:
    return record_run(fab, seed=seed, horizon=HORIZON_H * HOUR)
