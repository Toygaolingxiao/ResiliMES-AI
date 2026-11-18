"""Read-only timeline API. The Gantt page is the only caller."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from resilimes.config import ConfigError, Settings
from resilimes.data.zetaris_source import ZetarisDataError
from resilimes.domain.plant import PlantDataError
from resilimes.timeline.model import Book, TimelineQuery, window_payload
from resilimes.timeline.sample_book import load_sample_book

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


@router.get("")
def timeline(
    request: Request,
    t0: float | None = Query(default=None, ge=0.0, le=200_000.0),
    t1: float | None = Query(default=None, ge=0.0, le=200_000.0),
    view_t0: float | None = Query(default=None, ge=0.0, le=200_000.0),
    view_t1: float | None = Query(default=None, ge=0.0, le=200_000.0),
    product: str = Query(default="", max_length=80),
    lot: str = Query(default="", max_length=80),
    machine: str = Query(default="", max_length=80),
    group: str = Query(default="", max_length=80),
    step: str = Query(default="", max_length=80),
    priority: int | None = Query(default=None, ge=0, le=99),
    q: str = Query(default="", max_length=80),
    focus: str = Query(default="", max_length=80),
    idle: bool = Query(default=False),
    limit: int = Query(default=8000, ge=1, le=20000),
    lots: int = Query(default=100, ge=1, le=5000),
    now_min: float = Query(default=0.0, ge=0.0, le=200_000.0),
    book: str = Query(default="base", max_length=40, pattern=r"^[a-z0-9_\-]+$"),
    seed: int | None = Query(default=None, ge=1, le=9),
    horizon_h: float | None = Query(default=None, gt=0.0, le=168.0),
) -> dict[str, object]:
    """Window of one recorded book. ``timeline/v1`` for the Gantt page and later APS screens."""
    if t0 is not None and t1 is not None and t1 <= t0:
        raise HTTPException(status_code=422, detail="Window end is not after the start.")
    if view_t0 is not None and view_t1 is not None and view_t1 <= view_t0:
        raise HTTPException(status_code=422, detail="View end is not after the start.")
    settings: Settings = request.app.state.settings
    try:
        loaded = _book(settings, book, seed, horizon_h)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown book.") from exc
    except (PlantDataError, ZetarisDataError, ConfigError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return window_payload(
        loaded,
        TimelineQuery(
            t0=t0,
            t1=t1,
            view_t0=view_t0,
            view_t1=view_t1,
            product=product,
            lot=lot,
            machine=machine,
            group=group,
            step=step,
            priority=priority,
            q=q,
            focus=focus,
            idle=idle,
            limit=limit,
            lots=lots,
            now_min=now_min,
        ),
    )


def _book(settings: Settings, book: str, seed: int | None, horizon_h: float | None) -> Book:
    if settings.fab != "smt2020":
        return load_sample_book(settings)
    from resilimes.timeline.smt_book import load_smt_book

    return load_smt_book(book=book, seed=seed, horizon_h=horizon_h)
