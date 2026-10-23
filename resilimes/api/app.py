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
from resilimes.txn.engine import InMemoryEngine, LockError
from resilimes.txn.store import InMemoryStateStore

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
    app.state.engine = InMemoryEngine(InMemoryStateStore())

    @app.get("/api/health")
    def health() -> dict[str, object]:
        cfg: Settings = app.state.settings
        try:
            llm = "nightshift" if cfg.use_nightshift else "mock"
            data = "zetaris" if cfg.use_zetaris else "sample"
        except ConfigError as exc:
            return {"status": "misconfigured", "detail": str(exc), "version": __version__}
        return {
            "status": "ok",
            "version": __version__,
            "mode": cfg.mode,
            "llm": llm,
            "data": data,
            "label": "OFFLINE MOCK" if llm == "mock" and data == "sample" else llm.upper(),
            "nightshift_configured": cfg.token_configured,
            "zetaris_configured": cfg.zetaris_configured,
            "nemotron_model": cfg.nemotron_model if cfg.token_configured else None,
            "engines": ["scout-intent", "world-model", "markovian"],
            "horizon": cfg.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, object]:
        cfg: Settings = app.state.settings
        plant, _records = build_source(cfg).load_plant(cfg.horizon)
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
                    report = run_recovery(
                        app.state.settings,
                        RecoverInput(
                            scenario=body.scenario,
                            incident=body.incident,
                            actor_id=body.actor_id,
                            actor_role=body.actor_role,
                        ),
                        on_event=on_event,
                    )
                    events.put(("report", report.model_dump()))
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

    @app.post("/api/providers/probe")
    def probe() -> dict[str, object]:
        cfg: Settings = app.state.settings
        if not cfg.use_nightshift:
            return {"llm": "mock", "skipped": True, "detail": "Nightshift is not selected."}
        return {"llm": "nightshift", "skipped": False, **probe_nightshift(cfg)}

    if _STATIC.exists():
        app.mount("/assets", StaticFiles(directory=_STATIC), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(_STATIC / "index.html")

    return app


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
