"""AI evidence endpoints (investigator; explainer and handover are added beside it).

New routes only: nothing here changes an existing endpoint or KPI. Without
Nightshift every answer comes from the offline stand-in and says so
(``mocked: true``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
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
