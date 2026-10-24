"""HTTP API and static console."""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from resilimes import __version__
from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.api.insight import router as insight_router
from resilimes.api.intents import (
    ConfirmationState,
    ConfirmBody,
    IntentBody,
    UnknownConfirmation,
    confirm_intent,
    propose_intent,
)
from resilimes.config import ConfigError, Settings, get_settings
from resilimes.data.factory import build_source
from resilimes.data.zetaris_source import ZetarisDataError
from resilimes.demo.overview import build_overview
from resilimes.domain.plant import PlantDataError
from resilimes.domain.scenarios import list_scenarios
from resilimes.engines.contracts import ContractError
from resilimes.llm.nightshift import probe_nightshift
from resilimes.logging_config import configure_logging
from resilimes.smt.freeze import list_tick_logs, read_tick_log, tick_log_dir
from resilimes.smt.scenarios import SCENARIOS as SMT_SCENARIOS
from resilimes.smt.scenarios import run_smt, scenario_payload
from resilimes.txn.engine import InMemoryEngine, LockError
from resilimes.txn.store import build_store

_STATIC = Path(__file__).resolve().parents[1] / "demo" / "static"


class RecoverBody(BaseModel):
    scenario: str | None = None
    incident: str | None = None
    actor_id: str = "planner.ops"
    actor_role: str = Field(default="planner", max_length=40)
    pace_ms: int | None = Field(default=None, ge=0, le=2000)


def create_app(settings: Settings | None = None) -> FastAPI:
    active = settings or get_settings()
    configure_logging(active.log_level)
    app = FastAPI(
        title="ResiliMES",
        version=__version__,
        summary="Autonomous rescheduling and fault recovery for smart manufacturing.",
    )
    app.state.settings = active
    app.state.engine = InMemoryEngine(build_store(active.redis_url))

    @app.get("/api/health")
    def health() -> dict[str, object]:
        cfg: Settings = app.state.settings
        try:
            llm = "nightshift" if cfg.use_nightshift else "mock"
            data = "smt2020" if cfg.fab == "smt2020" else "zetaris" if cfg.use_zetaris else "sample"
        except ConfigError as exc:
            return {"status": "misconfigured", "detail": str(exc), "version": __version__}
        body: dict[str, object] = {
            "status": "ok",
            "version": __version__,
            "mode": cfg.mode,
            "fab": cfg.fab,
            "llm": llm,
            "data": data,
            "data_source": data,
            "label": ("NIGHTSHIFT" if llm == "nightshift" else "SMT2020")
            if data == "smt2020"
            else ("OFFLINE MOCK" if llm == "mock" and data == "sample" else llm.upper()),
            "benchmark": "public industry benchmark (SMT2020)" if data == "smt2020" else "",
            "nightshift_configured": cfg.token_configured,
            "zetaris_configured": cfg.zetaris_configured,
            "nemotron_model": cfg.nemotron_model if cfg.token_configured else None,
            "engines": ["scout-intent", "world-model", "markovian"],
            "horizon": cfg.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if cfg.fab == "smt2020":
            from resilimes.smt.fab import fab_source, load_fab

            fab = load_fab(cfg)
            body["smt_source"] = fab_source(fab)
            body["horizon"] = fab.snapshot
            body["groups"] = len(fab.families)
            body["tools"] = len(fab.tool_name)
            body["litho_tools"] = fab.litho_tools
            body["lots"] = len(fab.lot_id)
        return body

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, object]:
        cfg: Settings = app.state.settings
        if cfg.fab == "smt2020":
            from resilimes.smt.fab import load_fab

            try:
                fab = load_fab(cfg)
            except Exception as exc:  # RESILIMES_SMT_SOURCE=zetaris and the read failed
                raise HTTPException(status_code=503, detail=str(exc)[:300]) from exc
            return scenario_payload(fab)
        try:
            plant, _records = build_source(cfg).load_plant(cfg.horizon)
        except (ConfigError, ZetarisDataError, PlantDataError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        bay: list[dict[str, str]] = [
            {"id": equipment.equipment_id, "kind": "tool", "status": equipment.status}
            for equipment in plant.equipment
        ]
        bay.extend(
            {
                "id": stock.material_id,
                "kind": "material",
                "status": "short" if stock.on_hand <= 0 else "ok",
            }
            for stock in plant.materials
        )
        return {
            "scenarios": [item.model_dump() for item in list_scenarios()],
            "bay": bay,
            "overview": build_overview(plant),
        }

    @app.post("/api/intents")
    def intents(body: IntentBody) -> dict[str, object]:
        try:
            return propose_intent(app.state.settings, app.state.engine, body)
        except (ConfigError, ZetarisDataError, PlantDataError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/intents/confirm")
    def intents_confirm(body: ConfirmBody) -> dict[str, object]:
        try:
            return confirm_intent(app.state.settings, app.state.engine, body)
        except UnknownConfirmation as exc:
            raise HTTPException(status_code=404, detail="Unknown confirmation.") from exc
        except ConfirmationState as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ConfigError, ZetarisDataError, PlantDataError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/recover")
    def recover(body: RecoverBody) -> dict[str, object]:
        if _smt_request(app.state.settings, body.scenario):
            try:
                return run_smt(
                    app.state.settings,
                    body.scenario or "",
                    actor_role=body.actor_role,
                    actor_id=body.actor_id,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        _guard_fab(app.state.settings, body.scenario)
        try:
            report = run_recovery(
                app.state.settings,
                RecoverInput(
                    scenario=body.scenario,
                    incident=body.incident,
                    actor_id=body.actor_id,
                    actor_role=body.actor_role,
                ),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ConfigError, ZetarisDataError, PlantDataError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return report.model_dump()

    @app.post("/api/recover/stream")
    def recover_stream(body: RecoverBody) -> StreamingResponse:
        pace = _pace_ms(app.state.settings, body.pace_ms)

        def generate() -> Iterator[bytes]:
            events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

            def on_event(event: dict[str, Any]) -> None:
                events.put(("step", event))

            def work() -> None:
                try:
                    if _smt_request(app.state.settings, body.scenario):
                        report = run_smt(
                            app.state.settings,
                            body.scenario or "",
                            actor_role=body.actor_role,
                            actor_id=body.actor_id,
                            on_event=on_event,
                        )
                        events.put(("report", report))
                        return
                    _guard_fab(app.state.settings, body.scenario)
                    sample = run_recovery(
                        app.state.settings,
                        RecoverInput(
                            scenario=body.scenario,
                            incident=body.incident,
                            actor_id=body.actor_id,
                            actor_role=body.actor_role,
                        ),
                        on_event=on_event,
                    )
                    events.put(("report", sample.model_dump()))
                except KeyError as exc:
                    events.put(("error", {"status": 404, "detail": str(exc)}))
                except ValueError as exc:
                    events.put(("error", {"status": 422, "detail": str(exc)}))
                except ContractError as exc:
                    events.put(("error", {"status": 409, "detail": str(exc)}))
                except (ConfigError, ZetarisDataError, PlantDataError) as exc:
                    events.put(("error", {"status": 503, "detail": str(exc)}))
                finally:
                    events.put(None)

            threading.Thread(target=work, daemon=True).start()
            while True:
                item = events.get()
                if item is None:
                    break
                kind, payload = item
                yield _sse(kind, payload)
                if kind == "step" and pace > 0:
                    time.sleep(pace / 1000)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/sched/ticks")
    def sched_ticks(run: str | None = None, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Scheduling-tick log of a sim run (sched-freeze), paged; no run lists runs."""
        folder = tick_log_dir()
        if run is None:
            return {"folder": folder, "runs": list_tick_logs(folder)}
        try:
            return read_tick_log(folder, run, max(0, offset), max(1, min(limit, 500)))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown tick log.") from exc

    @app.post("/api/providers/probe")
    def probe() -> dict[str, object]:
        cfg: Settings = app.state.settings
        if not cfg.use_nightshift:
            return {"llm": "mock", "skipped": True, "detail": "Nightshift is not selected."}
        return {"llm": "nightshift", "skipped": False, **probe_nightshift(cfg)}

    app.include_router(insight_router)

    if _STATIC.exists():
        app.mount("/assets", StaticFiles(directory=_STATIC), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(_STATIC / "index.html")

    return app


def _smt_request(settings: Settings, scenario: str | None) -> bool:
    return settings.fab == "smt2020" and scenario in SMT_SCENARIOS


def _guard_fab(settings: Settings, scenario: str | None) -> None:
    if settings.fab == "smt2020" and scenario not in SMT_SCENARIOS:
        raise ValueError(
            "The SMT2020 console runs litho_down, hot_lot, pm_avoid, "
            "wip_threshold, qtime, tight_p1, and xfactor."
        )


def _pace_ms(settings: Settings, requested: int | None) -> int:
    if requested is not None:
        return requested
    if settings.mode == "live":
        return 0
    if settings.mode == "auto" and settings.token_configured:
        return 0
    return 680


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {data}\n\n".encode()
