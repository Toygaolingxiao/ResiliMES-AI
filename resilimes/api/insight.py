"""AI evidence endpoints (investigator; explainer and handover are added beside it).

New routes only: nothing here changes an existing endpoint or KPI. Without
Nightshift every answer comes from the offline stand-in and says so
(``mocked: true``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

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


def _provider(request: Request) -> Any:
    from resilimes.llm.factory import build_provider

    provider = build_provider(request.app.state.settings)
    return None if provider.mocked else provider


def _fab() -> Any:
    from resilimes.smt.fab import load_fab

    return load_fab()


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
    answer = investigate(
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
        "answer": answer.to_json(),
        "baseline": rank[:2],
        "truth": case.fault,
        "score": score(case.fault, answer.primary_cause, answer.secondary_cause),
        "system_score": score(
            case.fault, answer.system.get("primary_cause"), answer.system.get("secondary_cause")
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
