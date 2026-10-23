"""Read-only SQL the live Zetaris source sends and the sample source records.

The owner's bundle (verified 2026-10-24) registers three datasources.
``statements`` qualifies each table with its datasource. Cross-datasource
views are not used: a view of the same name unregisters the table.

POST {rest}/sql-editor/sqls/run-query  {"sql": "<one statement>"}
``/sql-editor/sqls/run`` accepts the same body. Set ``ZETARIS_SQL_PATH``.
"""

from __future__ import annotations

from collections.abc import Mapping

from resilimes.data.zetaris_layout import (
    KERNEL_TABLE_SOURCES,
    merged_sources,
    qualify,
    validate_ident,
)

COLUMNS = {
    "equipment": (
        "equipment_id, name, area, status, capability, setup_time_min, "
        "operators_required, max_wip, mtbf_hours, last_pm_at, fault_code, down_since"
    ),
    "wip_jobs": (
        "job_id, product_id, priority, qty, current_step, assigned_equipment, status, "
        "due_at, started_at, process_time_min, remaining_steps, preferred_equipment, "
        "released_through, rework_of, rework_count, rework_limit, release_min"
    ),
    "products": "product_id, name, route_id",
    "route": "route_id, product_id, name",
    "route_steps": (
        "product_id, step_index, step, capability, process_time_min, setup_family, "
        "step_no, operation, area, recipe, layer, rework"
    ),
    "qtime_rule": "rule_id, product_id, from_step, to_step, max_min",
    "reticle": "reticle_id, product_id, layer, step",
    "inhibit": "inhibit_id, product_id, recipe, equipment_id",
    "bom": "product_id, material_id, qty_per_lot",
    "materials": "material_id, name, on_hand, unit",
    "operators": "operator_id, name, certified, shift",
    "maintenance_logs": (
        "log_id, equipment_id, event_type, occurred_at, severity_code, description, "
        "estimated_repair_min, technician"
    ),
}

# Kernel tables. They are not part of the recovery plant SELECT list, so a
# bundle that has not loaded them yet still serves /api/recover.
KERNEL_COLUMNS = {
    "lots": (
        "lot_id, product_id, current_op_id, priority_level, arrival_time, due_date, "
        "ped_remaining_sec, dpi, dpi_updated_at"
    ),
    "operations": (
        "op_id, recipe_id, station_group_id, std_cycle_time, max_ped_sec, "
        "requires_batch, batch_size, ped_target_op_id"
    ),
    "setup_matrix": "station_group_id, from_recipe, to_recipe, setup_time_sec",
    "orders": "order_id, customer, product_id, qty, contract_due, order_class, margin_tier",
    "pm_calendar": "cal_name, family, first_start_sec, interval_sec, duration_sec",
}


def validate_schema(schema: str) -> str:
    try:
        return validate_ident(schema, "ZETARIS_SCHEMA")
    except ValueError as exc:
        raise ValueError(f"ZETARIS_SCHEMA is not a safe identifier: {schema!r}") from exc


def _checked_sources(schema: str, sources: Mapping[str, str] | None) -> dict[str, str] | None:
    """Validate the schema and every override. Datasource values use ``validate_schema``."""
    validate_schema(schema)
    if not sources:
        return None
    checked: dict[str, str] = {}
    for table, source in sources.items():
        checked[validate_ident(table, "table")] = validate_schema(source)
    return checked


def statements(schema: str, sources: Mapping[str, str] | None = None) -> dict[str, str]:
    """One SELECT per plant table.

    ``sources`` overrides the default datasource of a table. Tables that are
    absent from the map use ``schema`` (the ``resilimes`` datasource).
    Defaults are maintenance_logs on fab_cmms, and bom and materials on fab_erp.
    """
    checked = _checked_sources(schema, sources)
    merged_sources(schema, checked)
    return {
        name: f"SELECT {columns} FROM {qualify(name, schema, checked)}"
        for name, columns in COLUMNS.items()
    }


def kernel_statements(schema: str, sources: Mapping[str, str] | None = None) -> dict[str, str]:
    """SELECTs for the SMT2020 kernel tables.

    lots, operations, and setup_matrix stay on the schema datasource.
    pm_calendar is fab_cmms. orders is fab_erp. An override replaces one entry.
    """
    checked = _checked_sources(schema, sources)
    return {
        name: (f"SELECT {columns} FROM {qualify(name, schema, checked, base=KERNEL_TABLE_SOURCES)}")
        for name, columns in KERNEL_COLUMNS.items()
    }
