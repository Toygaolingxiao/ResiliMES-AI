"""HTTP API and static console."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from resilimes import __version__
from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.config import ConfigError, Settings, get_settings
from resilimes.data.zetaris_source import ZetarisDataError
from resilimes.domain.plant import PlantDataError
from resilimes.domain.scenarios import list_scenarios
from resilimes.engines.contracts import ContractError
from resilimes.llm.nightshift import probe_nightshift
from resilimes.logging_config import configure_logging

_STATIC = Path(__file__).resolve().parents[1] / "demo" / "static"


class RecoverBody(BaseModel):
    scenario: str | None = None
    incident: str | None = None
    actor_id: str = "planner.ops"
    actor_role: str = Field(default="planner", max_length=40)


def create_app(settings: Settings | None = None) -> FastAPI:
    active = settings or get_settings()
    configure_logging(active.log_level)
    app = FastAPI(
        title="ResiliMES",
        version=__version__,
        summary="Autonomous rescheduling and fault recovery for smart manufacturing.",
    )
    app.state.settings = active

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
            "nemotron_model": cfg.nemotron_model,
            "engines": ["scout-intent", "world-model", "markovian"],
            "horizon": cfg.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, object]:
        return {"scenarios": [item.model_dump() for item in list_scenarios()]}

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
