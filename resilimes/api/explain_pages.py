"""Read-only explain HTTP routes.

The report page reads one Evidence Schema bundle. These routes do not change
a schedule or a KPI.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from resilimes.explain.report import build_report
from resilimes.explain.schema import EvidenceBundle, content_hash

router = APIRouter(prefix="/api/explain", tags=["explain"])


@lru_cache(maxsize=4)
def baseline_record(seed: int, horizon_h: float) -> Any:
    """One recorded run. Cached so the report page does not re-simulate."""
    from resilimes.evidence.adapters import TwinReplayService
    from resilimes.explain.schema import RunRef
    from resilimes.smt.fab import load_fab

    service = TwinReplayService(load_fab())
    return service.baseline(RunRef(seed=seed, horizon_sec=horizon_h * 3600.0, policy="resilimes"))


@router.get("/report/lots")
def report_lots(
    seed: int = Query(default=1, ge=1, le=4),
    horizon_h: float = Query(default=48.0, gt=0.0, le=168.0),
) -> dict[str, Any]:
    """Late lots of one run, latest first. The page uses this as its list."""
    from resilimes.explain.lateness import late_lots

    record = baseline_record(seed, float(horizon_h))
    timeline = record.timeline
    rows = []
    for lot in late_lots(timeline):
        due = float(timeline.fab.lot_due[lot])
        end = timeline.completed.get(lot, timeline.horizon)
        rows.append({"lot": timeline.fab.lot_id[lot], "late_sec": end - due})
    return {"seed": seed, "horizon_h": horizon_h, "policy": "resilimes", "lots": rows}


@router.get("/report")
def report_lot(
    lot: str = Query(min_length=1, max_length=80),
    seed: int = Query(default=1, ge=1, le=4),
    horizon_h: float = Query(default=48.0, gt=0.0, le=168.0),
) -> dict[str, Any]:
    """Evidence report for one lot. Read-only."""
    from resilimes.evidence.adapters import lot_evidence

    record = baseline_record(seed, float(horizon_h))
    try:
        index = record.timeline.fab.lot_id.index(lot)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown lot") from exc
    bundle = lot_evidence(record, index)
    body = build_report(bundle)
    body["seed"] = seed
    body["horizon_h"] = horizon_h
    return body


@router.post("/report/verify")
def verify_report(bundle: EvidenceBundle) -> dict[str, Any]:
    """Recompute the hash. The page calls this with the bundle it is showing."""
    return {
        "verified": bundle.verify(),
        "content_hash": bundle.content_hash,
        "recomputed": content_hash(bundle.body()),
    }
