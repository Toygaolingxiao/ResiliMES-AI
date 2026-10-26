"""AI evidence endpoints (investigator; explainer and handover are added beside it).

New routes only: nothing here changes an existing endpoint or KPI. Without
Nightshift every answer comes from the offline stand-in and says so
(``mocked: true``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

router = APIRouter(prefix="/api/ai", tags=["ai"])


class InvestigateBody(BaseModel):
    # Case mode (original): re-run one committed investigator case.
    case_id: str | None = Field(default=None, max_length=60)
    # Context mode (Gantt right-click): one context query over the recorded
    # explainer run of ``seed``. Contract: docs/CONTEXT_INVESTIGATION.md.
    type: str | None = Field(default=None, pattern="^(bar|gap|window|free)$")
    tool: str | None = Field(default=None, max_length=80)
    family: str | None = Field(default=None, max_length=80)
    lot: str | None = Field(default=None, max_length=60)
    step: int | None = Field(default=None, ge=0)
    t1_h: float | None = Field(default=None, ge=0.0)
    t2_h: float | None = Field(default=None, ge=0.0)
    question_preset: str | None = Field(default=None, max_length=40)
    question: str | None = Field(default=None, max_length=300)
    seed: int = Field(default=1, ge=1, le=4)
    # Front-end (Gantt) payload alignment: minutes win over hours when both
    # are sent; scenario_id is echoed and "seed-<n>" selects the run seed.
    t1_min: float | None = Field(default=None, ge=0.0)
    t2_min: float | None = Field(default=None, ge=0.0)
    scenario_id: str | None = Field(default=None, max_length=64)
    lang: Literal["en", "zh", "ja"] = "en"

    @model_validator(mode="before")
    @classmethod
    def _blank_is_none(cls, data: Any) -> Any:
        """Blank strings mean "not given" (older front ends sent "" for absent ids)."""
        if isinstance(data, dict):
            return {
                key: (None if isinstance(value, str) and not value.strip() else value)
                for key, value in data.items()
            }
        return data


def _provider(request: Request) -> Any:
    from resilimes.llm.factory import build_provider

    provider = build_provider(request.app.state.settings)
    return None if provider.mocked else provider


def _fab() -> Any:
    from resilimes.smt.fab import load_fab

    return load_fab()


def _context_run(body: InvestigateBody) -> dict[str, Any]:
    """Which recorded run answered the query, and whether it is the on-screen one.

    Only ``scenario_id="seed-<n>"`` names an explainer run directly; any other
    scenario (an SMT book, the sample bay, ...) is answered from the cached
    reference run ``seed-<seed>`` and is labelled ``reference: true``.
    """
    import re

    from resilimes.insight.explainer import HORIZON_H

    named = bool(body.scenario_id and re.fullmatch(r"seed-[1-4]", body.scenario_id))
    return {
        "id": f"seed-{body.seed}",
        "seed": body.seed,
        "horizon_h": HORIZON_H,
        "reference": not named,
        "requested_scenario": body.scenario_id,
    }


def _context_query(body: InvestigateBody) -> Any:
    """Map the wire body to a ContextQuery (minutes win over hours)."""
    import re

    from resilimes.insight.context_investigation import ContextQuery

    t1_h = body.t1_min / 60.0 if body.t1_min is not None else body.t1_h
    t2_h = body.t2_min / 60.0 if body.t2_min is not None else body.t2_h
    if body.scenario_id:
        match = re.fullmatch(r"seed-(\d+)", body.scenario_id)
        if match and 1 <= int(match.group(1)) <= 4:
            body.seed = int(match.group(1))
    return ContextQuery(
        type=str(body.type),
        tool=body.tool,
        family=body.family,
        lot=body.lot,
        step=body.step,
        t1_h=t1_h,
        t2_h=t2_h,
        question_preset=body.question_preset,
        question=body.question,
        scenario_id=body.scenario_id,
        lang=body.lang,
    )


@router.get("/investigator/cases")
def investigator_cases() -> dict[str, Any]:
    from resilimes.insight.study import CASES_PATH, load_cases

    if not CASES_PATH.is_file():
        return {"cases": []}
    return {
        "cases": [
            {
                "case_id": c.case_id,
                "family": c.family,
                "t1_h": c.t1_h,
                "t2_h": c.t2_h,
                "question": c.question,
            }
            for c in load_cases()
        ]
    }


@router.post("/investigate")
def investigate_case(body: InvestigateBody, request: Request) -> dict[str, Any]:
    """Re-run the case's faulted simulation and investigate it (advice only).

    With ``type`` instead of ``case_id`` this is the Gantt context
    investigation over the explainer run (docs/CONTEXT_INVESTIGATION.md).
    """
    from resilimes.evidence.toolkit import Toolkit
    from resilimes.insight.injector import rebuild
    from resilimes.insight.investigator import baseline_rank, investigate, score
    from resilimes.insight.study import load_cases

    if body.type is not None:
        from resilimes.insight.context_investigation import (
            ContextError,
            investigate_context,
        )

        query = _context_query(body)
        try:
            answer = investigate_context(
                Toolkit(_explainer_base(body.seed)),
                query,
                _provider(request),
                request.app.state.settings,
            )
        except ContextError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "context": answer.to_json(),
            "scenario_id": body.scenario_id,
            "run": _context_run(body),
            "advice_only": True,
        }
    if body.case_id is None:
        raise HTTPException(status_code=400, detail="case_id or type is required")

    cases = {c.case_id: c for c in load_cases()}
    case = cases.get(body.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="unknown case")
    fab = _fab()
    run = rebuild(fab, case)
    inv = investigate(
        Toolkit(run),
        case.question,
        case.family,
        case.t1_h,
        case.t2_h,
        _provider(request),
        request.app.state.settings,
    )
    rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
    return {
        "case_id": case.case_id,
        "question": case.question,
        "answer": inv.to_json(),
        "baseline": rank[:2],
        "truth": case.fault,
        "score": score(case.fault, inv.primary_cause, inv.secondary_cause),
        "system_score": score(
            case.fault, inv.system.get("primary_cause"), inv.system.get("secondary_cause")
        ),
        "advice_only": True,
    }


# ---- late-lot explainer --------------------------------------------------------------------
class ExplainBody(BaseModel):
    lot_id: str = Field(max_length=60)
    seed: int = Field(default=1, ge=1, le=4)
    lang: str = Field(default="en", pattern="^(en|zh|ja)$")


@lru_cache(maxsize=2)
def _explainer_base(seed: int) -> Any:
    from resilimes.insight.explainer import base_run

    return base_run(_fab(), seed)


@router.get("/explainer/lots")
def explainer_lots(seed: int = Query(default=1, ge=1, le=4)) -> dict[str, Any]:
    """Late lots of the 48 h explainer run, latest first."""
    from resilimes.evidence.toolkit import Toolkit
    from resilimes.insight.explainer import HORIZON_H

    rows = Toolkit(_explainer_base(seed)).late_lots(limit=60)["late_lots"]
    return {"seed": seed, "horizon_h": HORIZON_H, "lots": rows}


@router.post("/explain")
def explain_lot(body: ExplainBody, request: Request) -> dict[str, Any]:
    """Exact lateness split, model explanation and one counterfactual verified by a re-run."""
    from resilimes.evidence.toolkit import Toolkit
    from resilimes.insight.explainer import exact_split, explain, verify

    base = _explainer_base(body.seed)
    if body.lot_id not in base.fab.lot_id:
        raise HTTPException(status_code=404, detail="unknown lot")
    lot = base.fab.lot_id.index(body.lot_id)
    kit = Toolkit(base)
    lateness = kit.lot_lateness(body.lot_id)
    if lateness["late_min"] <= 0:
        raise HTTPException(status_code=400, detail="lot is not late")
    answer = explain(kit, body.lot_id, _provider(request), language=body.lang)
    return {
        "lot": body.lot_id,
        "seed": body.seed,
        "split": exact_split(base, lot),
        "lateness": lateness,
        "answer": answer.to_json(),
        "counterfactual": verify(base, body.lot_id, answer) if answer.lever else None,
        "advice_only": True,
    }


# ---- fab notes (Plan-2 demo panel) ---------------------------------------------------------
# Read-only demo surface for the notes pipeline: dataset + per-note extraction
# (scripted offline stand-in by default; the live Nightshift model when it is
# configured and ``extractor=live`` is requested) + fact-check verdicts + the
# A/B/C comparison summary when scripts/compare_notes_ab.py has written its
# report. Controlled by RESILIMES_NOTES_PANEL (default on; "0" disables the
# route entirely). It changes no existing path and never writes a schedule.
#
# GET /api/ai/notes?extractor=scripted|live|regex&limit=N ->
# {
#   "enabled": true,
#   "extractor": "scripted" | "live" | "regex",
#   "mocked": bool,               # true unless a live model produced the events
#   "limit": int, "truncated": bool,
#   "summary": {"notes": int, "accepted": int, "rejected": int, "gold_events": int},
#   "notes": [{"note_id", "ts", "source", "lang", "hard_for_regex", "text",
#              "events": [accepted event...],
#              "rejected": [{"event": {...}, "reason": str}],
#              "gold": [gold event...]}],
#   "comparison": null | {"runner", "is_mock", "b_extractor", "arms",
#                          "gap_closure", "collateral"}
# }
# ``comparison`` is the verbatim comparison block of outputs/notes_ab.json
# (path override: RESILIMES_NOTES_AB_JSON); null means the A/B/C run has not
# been executed yet -- the UI says so instead of inventing numbers.


def _notes_enabled() -> bool:
    import os

    return os.environ.get("RESILIMES_NOTES_PANEL", "1") != "0"


@lru_cache(maxsize=1)
def _notes_fab_index() -> Any:
    from resilimes.insight.notes import build_fab_index

    return build_fab_index()


def _notes_extraction(extractor: Any, kind: str, limit: int) -> dict[str, Any]:
    """Run one extractor over the dataset and shape the panel payload."""
    from resilimes.insight.notes import extract_validated, load_notes

    notes = load_notes()
    rows: list[dict[str, Any]] = []
    accepted_total = rejected_total = gold_total = 0
    for note in notes[:limit]:
        _raw, accepted, rejected = extract_validated(extractor, note, _notes_fab_index())
        accepted_total += len(accepted)
        rejected_total += len(rejected)
        gold_total += len(note["gold"])
        rows.append(
            {
                "note_id": note["id"],
                "ts": note["ts"],
                "source": note["source"],
                "lang": note["lang"],
                "hard_for_regex": bool(note["hard_for_regex"]),
                "text": note["text"],
                "events": accepted,
                "rejected": rejected,
                "gold": note["gold"],
            }
        )
    return {
        "extractor": kind,
        "mocked": kind != "live",
        "limit": limit,
        "truncated": len(notes) > limit,
        "summary": {
            "notes": len(rows),
            "accepted": accepted_total,
            "rejected": rejected_total,
            "gold_events": gold_total,
        },
        "notes": rows,
    }


def _notes_comparison() -> dict[str, Any] | None:
    import json
    import os
    from pathlib import Path

    override = os.environ.get("RESILIMES_NOTES_AB_JSON", "")
    path = (
        Path(override)
        if override
        else Path(__file__).resolve().parents[2] / "outputs" / "notes_ab.json"
    )
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        comparison = report["comparison"]
    except (OSError, ValueError, KeyError):
        return None
    comparison = dict(comparison)
    comparison["b_extractor"] = report.get("b_extractor")
    return comparison


@router.get("/notes")
def fab_notes(
    request: Request,
    extractor: str = Query(default="scripted", pattern="^(scripted|live|regex)$"),
    limit: int = Query(default=46, ge=1, le=46),
) -> dict[str, Any]:
    """Notes dataset with extraction + fact-check verdicts per note (read-only)."""
    if not _notes_enabled():
        raise HTTPException(status_code=404, detail="notes panel disabled")
    from resilimes.insight.notes import LlmExtractor, RegexExtractor, ScriptedNotesCompleter

    if extractor == "live":
        provider = _provider(request)
        if provider is None:
            extractor = "scripted"  # honest fall-back: no live model configured
    if extractor == "live":
        payload = _notes_extraction(LlmExtractor(provider), "live", limit)
    elif extractor == "regex":
        payload = _notes_extraction(RegexExtractor(), "regex", limit)
    else:
        payload = _notes_extraction(LlmExtractor(ScriptedNotesCompleter()), "scripted", limit)
    return {"enabled": True, **payload, "comparison": _notes_comparison()}


# ---- shift handover ------------------------------------------------------------------------
class HandoverBody(BaseModel):
    seed: int = Field(default=1, ge=1, le=4)
    start_h: float = Field(default=12.0, ge=0.0, le=36.0)
    lang: str = Field(default="en", pattern="^(en|zh|ja)$")


@router.get("/handover/shifts")
def handover_shifts() -> dict[str, Any]:
    """12 h shifts of the 48 h run that the study and the UI offer."""
    from resilimes.insight.handover import CHUNK_H, LANGUAGES, SHIFT_H, SHIFTS

    return {
        "shift_h": SHIFT_H,
        "chunk_h": CHUNK_H,
        "languages": list(LANGUAGES),
        "shifts": [
            {"seed": seed, "start_h": start, "end_h": start + SHIFT_H} for seed, start in SHIFTS
        ],
    }


@router.post("/handover")
def handover_report(body: HandoverBody, request: Request) -> dict[str, Any]:
    """Write one 12 h handover report in 2 h chunks (advice only, fact-checked)."""
    from resilimes.insight.handover import handover

    return handover(
        _explainer_base(body.seed), body.start_h, _provider(request), language=body.lang
    )
