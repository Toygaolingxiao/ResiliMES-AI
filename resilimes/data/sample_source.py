"""Sample-file data source. Same logical tables as Zetaris, no network."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from resilimes.data.sql_catalog import statements
from resilimes.domain.models import Plant
from resilimes.domain.plant import load_sample


class QueryRecord(BaseModel):
    name: str
    sql: str
    mode: str
    row_count: int


class SampleSource:
    name = "sample"

    def __init__(self, data_dir: Path, schema: str = "resilimes") -> None:
        self._data_dir = data_dir
        self._schema = schema

    def load_plant(self, horizon: datetime) -> tuple[Plant, list[QueryRecord]]:
        plant = load_sample(self._data_dir, horizon)
        counts = {
            "equipment": len(plant.equipment),
            "wip_jobs": len(plant.jobs),
            "products": len(plant.products),
            "route": sum(1 for product in plant.products if product.route_id),
            "route_steps": sum(len(product.route) for product in plant.products),
            "qtime_rule": len(plant.qtime_rules),
            "reticle": len(plant.reticles),
            "inhibit": len(plant.inhibits),
            "bom": sum(len(product.materials) for product in plant.products),
            "materials": len(plant.materials),
            "operators": len(plant.operators),
            "maintenance_logs": len(plant.maintenance),
        }
        records = [
            QueryRecord(name=name, sql=sql, mode="sample-equivalent", row_count=counts[name])
            for name, sql in statements(self._schema).items()
        ]
        return plant, records
