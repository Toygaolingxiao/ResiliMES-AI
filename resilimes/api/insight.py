"""AI evidence endpoints (investigator; explainer and handover are added beside it).

New routes only: nothing here changes an existing endpoint or KPI. Without
Nightshift every answer comes from the offline stand-in and says so
(``mocked: true``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/ai", tags=["ai"])


class InvestigateBody(BaseModel):
    case_id: str = Field(max_length=60)


def _provider(request: Request) -> Any:
    from resilimes.llm.factory import build_provider

    provider = build_provider(request.app.state.settings)
    return None if provider.mocked else provider


def _fab() -> Any:
    from resilimes.smt.fab import load_fab

    return load_fab()


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
    """Re-run the case's faulted simulation and investigate it (advice only)."""
    from resilimes.evidence.toolkit import Toolkit
    from resilimes.insight.injector import rebuild
    from resilimes.insight.investigator import baseline_rank, investigate, score
    from resilimes.insight.study import load_cases

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
