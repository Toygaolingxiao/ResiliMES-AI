"""Zetaris seed for the synthetic fab. Same tables as the sample catalog."""

from __future__ import annotations

from datetime import UTC, datetime

from resilimes.data.sql_export import TABLES, render_csv_rows, render_tables
from resilimes.domain.models import Equipment, Job, Plant
from resilimes.domain.scale_fab import SCALE_LOTS, build_scale_plant

SCALE_HORIZON = datetime(2026, 10, 22, 6, 30, tzinfo=UTC)


def scale_plant(lots: int = SCALE_LOTS) -> Plant:
    return build_scale_plant(SCALE_HORIZON, lots=lots)


def scale_rows(plant: Plant | None = None) -> dict[str, list[dict[str, str]]]:
    source = plant or scale_plant()
    return {
        "equipment": [_equipment(item) for item in source.equipment],
        "wip_jobs": [_job(item) for item in source.jobs],
        "products": [
            {
                "product_id": item.product_id,
                "name": item.name,
                "route_id": item.route_id,
            }
            for item in source.products
        ],
        "route": [
            {
                "route_id": item.route_id,
                "product_id": item.product_id,
                "name": item.name,
            }
            for item in source.products
            if item.route_id
        ],
        "route_steps": _steps(source),
        "qtime_rule": [
            {
                "rule_id": item.rule_id,
                "product_id": item.product_id,
                "from_step": item.from_step,
                "to_step": item.to_step,
                "max_min": str(item.max_min),
            }
            for item in source.qtime_rules
        ],
        "reticle": [
            {
                "reticle_id": item.reticle_id,
                "product_id": item.product_id,
                "layer": item.layer,
                "step": item.step,
            }
            for item in source.reticles
        ],
        "inhibit": [
            {
                "inhibit_id": item.inhibit_id,
                "product_id": item.product_id,
                "recipe": item.recipe,
                "equipment_id": item.equipment_id,
            }
            for item in source.inhibits
        ],
        "bom": [
            {
                "product_id": product.product_id,
                "material_id": need.material_id,
                "qty_per_lot": str(need.qty_per_lot),
            }
            for product in source.products
            for need in product.materials
        ],
        "materials": [
            {
                "material_id": item.material_id,
                "name": item.name,
                "on_hand": str(item.on_hand),
                "unit": item.unit,
            }
            for item in source.materials
        ],
        "operators": [
            {
                "operator_id": item.operator_id,
                "name": item.name,
                "certified": ",".join(item.certified),
                "shift": item.shift,
            }
            for item in source.operators
        ],
        "maintenance_logs": [
            {
                "log_id": item.log_id,
                "equipment_id": item.equipment_id,
                "event_type": item.event_type,
                "occurred_at": item.occurred_at,
                "severity_code": item.severity_code,
                "description": item.description,
                "estimated_repair_min": str(item.estimated_repair_min),
                "technician": item.technician,
            }
            for item in source.maintenance
        ],
    }


def render_scale_sql(schema: str = "resilimes") -> str:
    return render_tables(
        scale_rows(),
        schema=schema,
        preamble=[
            "-- ResiliMES scale-fab seed for the Zetaris SQL editor.",
            "-- Generated from the seeded fab. Do not edit by hand;",
            "-- run: python scripts/export_scale_sql.py",
            "--",
            "-- Same catalog as data/sql/seed.sql. Numeric columns are VARCHAR.",
            "-- Load this instead of the hero seed when the table should hold the 1,000-lot fab.",
            "",
        ],
    )


def render_scale_csv(name: str) -> str:
    if name not in TABLES:
        raise KeyError(name)
    return render_csv_rows(scale_rows()[name])


def _equipment(row: Equipment) -> dict[str, str]:
    return {
        "equipment_id": row.equipment_id,
        "name": row.name,
        "area": row.area,
        "status": row.status,
        "capability": ",".join(row.capability),
        "setup_time_min": str(row.setup_time_min),
        "operators_required": str(row.operators_required),
        "max_wip": str(row.max_wip),
        "mtbf_hours": "" if row.mtbf_hours is None else str(row.mtbf_hours),
        "last_pm_at": row.last_pm_at or "",
        "fault_code": row.fault_code or "",
        "down_since": row.down_since or "",
    }


def _job(row: Job) -> dict[str, str]:
    return {
        "job_id": row.job_id,
        "product_id": row.product_id,
        "priority": str(row.priority),
        "qty": str(row.qty),
        "current_step": row.current_step,
        "assigned_equipment": row.assigned_equipment or "",
        "status": row.status,
        "due_at": _z(row.due_at),
        "started_at": _z(row.started_at),
        "process_time_min": str(row.process_time_min),
        "remaining_steps": ",".join(row.remaining_steps),
        "preferred_equipment": ",".join(row.preferred_equipment),
        "released_through": row.released_through or "",
        "rework_of": row.rework_of or "",
        "rework_count": str(row.rework_count),
        "rework_limit": str(row.rework_limit),
        "release_min": str(row.release_min),
    }


def _steps(plant: Plant) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for product in plant.products:
        for index, step in enumerate(product.route):
            rows.append(
                {
                    "product_id": product.product_id,
                    "step_index": str(index),
                    "step": step.step,
                    "capability": step.capability,
                    "process_time_min": str(step.process_time_min),
                    "setup_family": step.setup_family,
                    "step_no": str(step.step_no),
                    "operation": step.operation or step.step,
                    "area": step.area,
                    "recipe": step.recipe,
                    "layer": step.layer,
                    "rework": "true" if step.rework else "false",
                }
            )
    return rows


def _z(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
