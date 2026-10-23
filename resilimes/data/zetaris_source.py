"""Zetaris-backed plant source.

Uses the existing REST client in agent.tools_zetaris. One SELECT per table.
The response is normalized by rows_as_dicts, which accepts the documented
`headers` + `data` shape and a few observed alternates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from resilimes.data.sample_source import QueryRecord
from resilimes.data.sql_catalog import statements
from resilimes.domain.models import Plant
from resilimes.domain.plant import plant_from_rows


class ZetarisDataError(RuntimeError):
    """Raised when the Zetaris plant tables cannot be read."""


class ZetarisSource:
    name = "zetaris"

    def __init__(self, schema: str = "resilimes", timeout_s: float = 30.0) -> None:
        self._schema = schema
        self._timeout_s = timeout_s

    def load_plant(self, horizon: datetime) -> tuple[Plant, list[QueryRecord]]:
        from agent.tools_zetaris import ZetarisError, rows_as_dicts, run_sql

        queries = statements(self._schema)
        tables: dict[str, list[dict[str, Any]]] = {}
        records: list[QueryRecord] = []
        try:
            for name, sql in queries.items():
                payload = run_sql(sql, timeout_s=self._timeout_s)
                rows = rows_as_dicts(payload)
                tables[name] = rows
                records.append(QueryRecord(name=name, sql=sql, mode="zetaris", row_count=len(rows)))
        except ZetarisError as exc:
            raise ZetarisDataError(str(exc)) from exc
        pool_row = tables["operators"]
        plant = plant_from_rows(
            plant_id="FAB-A",
            horizon=horizon,
            operator_pool=max(1, len(pool_row)),
            equipment_rows=tables["equipment"],
            job_rows=tables["wip_jobs"],
            product_rows=tables["products"],
            route_rows=tables["route_steps"],
            bom_rows=tables["bom"],
            material_rows=tables["materials"],
            operator_rows=tables["operators"],
            maintenance_rows=tables["maintenance_logs"],
            qtime_rows=tables.get("qtime_rule", []),
            source="zetaris",
        )
        return plant, records
