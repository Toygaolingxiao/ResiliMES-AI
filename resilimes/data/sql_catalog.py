"""Read-only SQL the live Zetaris source sends and the sample source records.

The schema name is an identifier, never a free-form string. Zetaris statement
shape follows the scaffold and the public SQL editor contract:
POST {rest}/sql-editor/sqls/run  {"sql": "<one statement>"}
Some tenants use /sql-editor/sqls/run-query; override with ZETARIS_SQL_PATH.
"""

from __future__ import annotations

import re

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

COLUMNS = {
    "equipment": (
        "equipment_id, name, area, status, capability, setup_time_min, "
        "operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since"
    ),
    "wip_jobs": (
        "job_id, product_id, priority, qty, current_step, assigned_equipment, status, "
        "due_at, started_at, process_time_min, remaining_steps, preferred_equipment, "
        "released_through, rework_of, rework_count, rework_limit"
    ),
    "products": "product_id, name, route_id",
    "route": "route_id, product_id, name",
    "route_steps": (
        "product_id, step_index, step, capability, process_time_min, setup_family, "
        "step_no, operation, area, recipe, layer, rework"
    ),
    "qtime_rule": "rule_id, product_id, from_step, to_step, max_min",
    "bom": "product_id, material_id, qty_per_lot",
    "materials": "material_id, name, on_hand, unit",
    "operators": "operator_id, name, certified, shift",
    "maintenance_logs": (
        "log_id, equipment_id, event_type, occurred_at, severity_code, description, "
        "estimated_repair_min, technician"
    ),
}


def validate_schema(schema: str) -> str:
    if not _IDENT.match(schema or ""):
        raise ValueError(f"ZETARIS_SCHEMA is not a safe identifier: {schema!r}")
    return schema


def statements(schema: str) -> dict[str, str]:
    safe = validate_schema(schema)
    return {name: f"SELECT {columns} FROM {safe}.{name}" for name, columns in COLUMNS.items()}
