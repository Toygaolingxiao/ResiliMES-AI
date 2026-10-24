"""Read-only operator views over one recorded SMT2020 full-fab run.

Every endpoint takes ``book`` (which recorded run) and, where it matters,
``t`` in seconds since the start of the run. Nothing here changes state; the
first call for a book records it once (about 3 s for 48 h, 2156 lots).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from resilimes.config import Settings
from resilimes.smt import kpi, replay
from resilimes.smt.fab import load_fab

router = APIRouter(prefix="/api/fab", tags=["fab"])


def _book_query() -> Any:
    return Query(default="base", max_length=40, pattern=r"^[a-z0-9_\-]+$")


def _time_query() -> Any:
    # A fresh Query per parameter: a shared FieldInfo picks up the first alias.
    return Query(default=None, ge=0.0, le=10_000_000.0)


def _book(request: Request, key: str) -> replay.Replay:
    settings: Settings = request.app.state.settings
    if settings.fab != "smt2020":
        raise HTTPException(status_code=404, detail="Fab views need fab=smt2020.")
    try:
        spec = replay.known_spec(load_fab(), key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown book {key}.") from exc
    return replay.get_replay(spec)


def _books() -> list[dict[str, Any]]:
    return [{"key": key, "ready": replay.cached(key)} for key in replay.SCENARIO_BOOKS]


@router.get("/meta")
def fab_meta(request: Request, book: str = _book_query()) -> dict[str, Any]:
    rp = _book(request, book)
    body = replay.meta(rp)
    body["books"] = _books()
    return body


@router.get("/overview")
def fab_overview(
    request: Request, book: str = _book_query(), t: float | None = _time_query()
) -> dict[str, Any]:
    rp = _book(request, book)
    return replay.overview(rp, replay.clamp_t(rp, t))


@router.get("/tools")
def fab_tools(
    request: Request,
    book: str = _book_query(),
    t: float | None = _time_query(),
    group: str | None = Query(default=None, max_length=40),
    family: str | None = Query(default=None, max_length=60),
) -> dict[str, Any]:
    rp = _book(request, book)
    fab = rp.fab
    if family is not None and family not in fab.family_index:
        raise HTTPException(status_code=404, detail=f"Unknown family {family}.")
    if group is not None and group not in {item.group for item in fab.families}:
        raise HTTPException(status_code=404, detail=f"Unknown group {group}.")
    if group is None and family is None:
        counts = replay.queue_counts(rp, replay.clamp_t(rp, t))
        worst = max(range(len(fab.families)), key=lambda index: counts[index] / rp.threshold[index])
        group = fab.families[worst].group
    return replay.tools_view(rp, replay.clamp_t(rp, t), group, family)


@router.get("/flow")
def fab_flow(
    request: Request, book: str = _book_query(), t: float | None = _time_query()
) -> dict[str, Any]:
    rp = _book(request, book)
    return replay.flow_view(rp, replay.clamp_t(rp, t))


@router.get("/lot/{lot_id}")
def fab_lot(
    request: Request, lot_id: str, book: str = _book_query(), t: float | None = _time_query()
) -> dict[str, Any]:
    rp = _book(request, book)
    lot = replay.resolve_lot(rp, lot_id)
    if lot is None:
        raise HTTPException(status_code=404, detail=f"Unknown lot {lot_id}.")
    return replay.lot_view(rp, lot, replay.clamp_t(rp, t))


@router.get("/batches")
def fab_batches(
    request: Request, book: str = _book_query(), t: float | None = _time_query()
) -> dict[str, Any]:
    rp = _book(request, book)
    return replay.batches_view(rp, replay.clamp_t(rp, t))


@router.get("/events")
def fab_events(
    request: Request,
    book: str = _book_query(),
    t0: float = Query(default=0.0, ge=0.0),
    t1: float | None = _time_query(),
    kind: str = Query(default="", max_length=200),
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    rp = _book(request, book)
    kinds = tuple(item for item in kind.split(",") if item in replay.EVENT_KINDS)
    end = replay.clamp_t(rp, t1) if t1 is not None else rp.horizon
    body = replay.events_view(rp, t0, end, kinds or replay.DEFAULT_KINDS, q, limit)
    body["breakdowns"] = replay.breakdowns(rp, t0, end)[-limit:]
    return body


@router.get("/kpis")
def fab_kpis(request: Request, book: str = _book_query()) -> dict[str, Any]:
    rp = _book(request, book)
    body = kpi.daily(rp)
    return {"book": rp.spec.key, "counters": replay.counters(rp), **body}


def warm_on_start(settings: Settings) -> None:
    """Record the baseline book in the background so the first view is quick."""
    if settings.fab == "smt2020" and os.environ.get("RESILIMES_NO_WARM") != "1":
        replay.warm()
