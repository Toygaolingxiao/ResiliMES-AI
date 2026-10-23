"""Load a plant snapshot from the sample documents and stamp tool availability."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    Equipment,
    Inhibit,
    Job,
    MaintenanceEvent,
    MaterialStock,
    Operator,
    Plant,
    Product,
    QTimeRule,
    Reticle,
)

UNAVAILABLE = {"DOWN", "MAINTENANCE"}
DEFAULT_REPAIR_MIN = 240


class PlantDataError(ValueError):
    """Raised when sample or Zetaris rows cannot form a plant."""


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def minutes_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def load_sample(data_dir: Path, horizon: datetime) -> Plant:
    equipment_doc = _read_json(data_dir / "equipment.json")
    jobs_doc = _read_json(data_dir / "wip_jobs.json")
    bom_doc = _read_json(data_dir / "bom.json")
    materials_doc = _read_json(data_dir / "materials.json")
    operators_doc = _read_json(data_dir / "operators.json")
    maintenance = _read_maintenance(data_dir / "maintenance_logs.csv")
    qtime_doc = (
        _read_json(data_dir / "qtime_rules.json")
        if (data_dir / "qtime_rules.json").exists()
        else {}
    )
    reticle_doc = (
        _read_json(data_dir / "reticle.json") if (data_dir / "reticle.json").exists() else {}
    )
    inhibit_doc = (
        _read_json(data_dir / "inhibit.json") if (data_dir / "inhibit.json").exists() else {}
    )
    plant = Plant(
        plant_id=str(equipment_doc.get("plant_id") or jobs_doc.get("plant_id") or "FAB-A"),
        horizon=horizon,
        operator_pool=int(operators_doc.get("pool", 4)),
        equipment=[Equipment.model_validate(row) for row in equipment_doc.get("equipment", [])],
        jobs=[_job(row) for row in jobs_doc.get("jobs", [])],
        products=[Product.model_validate(row) for row in bom_doc.get("products", [])],
        materials=[MaterialStock.model_validate(row) for row in materials_doc.get("materials", [])],
        operators=[Operator.model_validate(row) for row in operators_doc.get("operators", [])],
        maintenance=maintenance,
        qtime_rules=[QTimeRule.model_validate(row) for row in qtime_doc.get("rules", [])],
        reticles=[Reticle.model_validate(row) for row in reticle_doc.get("reticles", [])],
        inhibits=[Inhibit.model_validate(row) for row in inhibit_doc.get("inhibits", [])],
        source="sample",
    )
    _validate(plant)
    return enrich_availability(plant)


def plant_from_rows(
    *,
    plant_id: str,
    horizon: datetime,
    operator_pool: int,
    equipment_rows: list[dict[str, Any]],
    job_rows: list[dict[str, Any]],
    product_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    bom_rows: list[dict[str, Any]],
    material_rows: list[dict[str, Any]],
    operator_rows: list[dict[str, Any]],
    maintenance_rows: list[dict[str, Any]],
    source: str,
    qtime_rows: list[dict[str, Any]] | None = None,
    reticle_rows: list[dict[str, Any]] | None = None,
    inhibit_rows: list[dict[str, Any]] | None = None,
) -> Plant:
    """Build a plant from flat relational rows (the Zetaris table shape)."""
    products = _products_from_rows(product_rows, route_rows, bom_rows)
    plant = Plant(
        plant_id=plant_id,
        horizon=horizon,
        operator_pool=operator_pool,
        equipment=[_equipment_from_row(row) for row in equipment_rows],
        jobs=[_job_from_row(row) for row in job_rows],
        products=products,
        materials=[_material_from_row(row) for row in material_rows],
        operators=[_operator_from_row(row) for row in operator_rows],
        maintenance=[_maintenance_from_row(row) for row in maintenance_rows],
        qtime_rules=[_qtime_from_row(row) for row in (qtime_rows or [])],
        reticles=[_reticle_from_row(row) for row in (reticle_rows or [])],
        inhibits=[_inhibit_from_row(row) for row in (inhibit_rows or [])],
        source=source,
    )
    _validate(plant)
    return enrich_availability(plant)


def enrich_availability(plant: Plant) -> Plant:
    repairs = _latest_repair(plant)
    for equipment in plant.equipment:
        equipment.available_at_min = _available_at(equipment, repairs, plant.horizon)
    return plant


def _available_at(
    equipment: Equipment,
    repairs: dict[str, int],
    horizon: datetime,
) -> int:
    if equipment.status not in UNAVAILABLE:
        return 0
    repair = equipment.repair_min
    if repair is None:
        repair = repairs.get(equipment.equipment_id, DEFAULT_REPAIR_MIN)
    if equipment.eta_from_horizon and equipment.repair_min is not None:
        return max(0, equipment.repair_min)
    if equipment.down_since:
        down_at = parse_dt(equipment.down_since)
        if down_at is not None:
            back = minutes_between(horizon, down_at) + repair
            return max(0, back)
    return max(0, repair)


def _latest_repair(plant: Plant) -> dict[str, int]:
    found: dict[str, tuple[str, int]] = {}
    for event in plant.maintenance:
        if event.estimated_repair_min <= 0:
            continue
        previous = found.get(event.equipment_id)
        if previous is None or event.occurred_at >= previous[0]:
            found[event.equipment_id] = (event.occurred_at, event.estimated_repair_min)
    return {key: value[1] for key, value in found.items()}


def _validate(plant: Plant) -> None:
    products = plant.product_map()
    missing = sorted({job.product_id for job in plant.jobs if job.product_id not in products})
    if missing:
        raise PlantDataError(f"Jobs reference unknown products: {', '.join(missing)}")
    if plant.operator_pool < 1:
        raise PlantDataError("operator_pool must be >= 1")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PlantDataError(f"Missing plant file: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PlantDataError(f"Expected object in {path}")
    return loaded


def _read_maintenance(path: Path) -> list[MaintenanceEvent]:
    if not path.exists():
        return []
    events: list[MaintenanceEvent] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            events.append(
                MaintenanceEvent(
                    log_id=row["log_id"],
                    equipment_id=row["equipment_id"],
                    event_type=row["event_type"],
                    occurred_at=row["severity_at"],
                    severity_code=row["severity_code"],
                    description=row["description"],
                    estimated_repair_min=int(row.get("estimated_repair_min") or 0),
                    technician=row.get("technician") or "",
                )
            )
    return events


def _job(row: dict[str, Any]) -> Job:
    due = parse_dt(str(row["due_at"]))
    if due is None:
        raise PlantDataError(f"Job {row.get('job_id')} is missing due_at")
    started = parse_dt(str(row["started_at"])) if row.get("started_at") else None
    remaining = row.get("remaining_steps") or []
    preferred = row.get("preferred_equipment") or []
    return Job(
        job_id=str(row["job_id"]),
        product_id=str(row["product_id"]),
        priority=int(row["priority"]),
        qty=int(row["qty"]),
        current_step=str(row["current_step"]),
        assigned_equipment=_optional_str(row.get("assigned_equipment")),
        status=str(row["status"]),
        due_at=due,
        started_at=started,
        process_time_min=int(row["process_time_min"]),
        remaining_steps=[str(item) for item in remaining] if isinstance(remaining, list) else [],
        preferred_equipment=[str(item) for item in preferred]
        if isinstance(preferred, list)
        else [],
        released_through=_optional_str(row.get("released_through")),
        rework_of=_optional_str(row.get("rework_of")),
        rework_count=int(row.get("rework_count") or 0),
        rework_limit=int(row.get("rework_limit") or 1),
        release_min=int(row.get("release_min") or 0),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _equipment_from_row(row: dict[str, Any]) -> Equipment:
    repair = row.get("repair_min")
    return Equipment(
        equipment_id=str(row["equipment_id"]),
        name=str(row.get("name") or row["equipment_id"]),
        area=str(row.get("area") or ""),
        status=str(row.get("status") or "IDLE"),
        capability=_split_list(row.get("capability")),
        setup_time_min=int(row.get("setup_time_min") or 0),
        operators_required=int(row.get("operators_required") or 1),
        max_wip=int(row.get("max_wip") or 1),
        fault_code=_optional_str(row.get("fault_code")),
        down_since=_optional_str(row.get("down_since")),
        repair_min=int(repair) if repair not in (None, "") else None,
    )


def _job_from_row(row: dict[str, Any]) -> Job:
    due = parse_dt(str(row["due_at"]))
    if due is None:
        raise PlantDataError(f"Job {row.get('job_id')} is missing due_at")
    started = parse_dt(_optional_str(row.get("started_at")))
    return Job(
        job_id=str(row["job_id"]),
        product_id=str(row["product_id"]),
        priority=int(row["priority"]),
        qty=int(row.get("qty") or 1),
        current_step=str(row.get("current_step") or "QUEUED"),
        assigned_equipment=_optional_str(row.get("assigned_equipment")),
        status=str(row.get("status") or "QUEUED"),
        due_at=due,
        started_at=started,
        process_time_min=int(row.get("process_time_min") or 0),
        remaining_steps=_split_list(row.get("remaining_steps")),
        preferred_equipment=_split_list(row.get("preferred_equipment")),
        released_through=_optional_str(row.get("released_through")),
        rework_of=_optional_str(row.get("rework_of")),
        rework_count=int(row.get("rework_count") or 0),
        rework_limit=int(row.get("rework_limit") or 1),
        release_min=int(row.get("release_min") or 0),
    )


def _products_from_rows(
    product_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    bom_rows: list[dict[str, Any]],
) -> list[Product]:
    routes: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for row in route_rows:
        routes.setdefault(str(row["product_id"]), []).append((int(row.get("step_index") or 0), row))
    materials: dict[str, list[dict[str, Any]]] = {}
    for row in bom_rows:
        materials.setdefault(str(row["product_id"]), []).append(row)
    products: list[Product] = []
    for row in product_rows:
        product_id = str(row["product_id"])
        ordered = [item[1] for item in sorted(routes.get(product_id, []), key=lambda pair: pair[0])]
        products.append(
            Product(
                product_id=product_id,
                name=str(row.get("name") or product_id),
                route_id=str(row.get("route_id") or ""),
                route=[
                    {
                        "step": str(step["step"]),
                        "capability": str(step["capability"]),
                        "process_time_min": int(step["process_time_min"]),
                        "setup_family": str(step["setup_family"]),
                        "step_no": int(step.get("step_no") or 0),
                        "operation": str(step.get("operation") or step["step"]),
                        "area": str(step.get("area") or ""),
                        "recipe": str(step.get("recipe") or step["setup_family"]),
                        "layer": str(step.get("layer") or ""),
                        "rework": str(step.get("rework") or "").lower() in {"1", "true", "yes"},
                    }
                    for step in ordered
                ],
                materials=[
                    {
                        "material_id": str(need["material_id"]),
                        "qty_per_lot": int(need["qty_per_lot"]),
                    }
                    for need in materials.get(product_id, [])
                ],
            )
        )
    return products


def _qtime_from_row(row: dict[str, Any]) -> QTimeRule:
    return QTimeRule(
        rule_id=str(row["rule_id"]),
        product_id=str(row["product_id"]),
        from_step=str(row["from_step"]),
        to_step=str(row["to_step"]),
        max_min=int(row["max_min"]),
    )


def _reticle_from_row(row: dict[str, Any]) -> Reticle:
    return Reticle(
        reticle_id=str(row["reticle_id"]),
        product_id=str(row.get("product_id") or ""),
        layer=str(row.get("layer") or ""),
        step=str(row.get("step") or ""),
    )


def _inhibit_from_row(row: dict[str, Any]) -> Inhibit:
    return Inhibit(
        inhibit_id=str(row["inhibit_id"]),
        equipment_id=str(row["equipment_id"]),
        product_id=str(row.get("product_id") or ""),
        recipe=str(row.get("recipe") or ""),
    )


def _material_from_row(row: dict[str, Any]) -> MaterialStock:
    return MaterialStock(
        material_id=str(row["material_id"]),
        name=str(row.get("name") or row["material_id"]),
        on_hand=int(row.get("on_hand") or 0),
        unit=str(row.get("unit") or "unit"),
    )


def _operator_from_row(row: dict[str, Any]) -> Operator:
    return Operator(
        operator_id=str(row["operator_id"]),
        name=str(row.get("name") or row["operator_id"]),
        certified=_split_list(row.get("certified")),
        shift=str(row.get("shift") or "A"),
    )


def _maintenance_from_row(row: dict[str, Any]) -> MaintenanceEvent:
    return MaintenanceEvent(
        log_id=str(row["log_id"]),
        equipment_id=str(row["equipment_id"]),
        event_type=str(row.get("event_type") or ""),
        occurred_at=str(row.get("occurred_at") or row.get("severity_at") or ""),
        severity_code=str(row.get("severity_code") or ""),
        description=str(row.get("description") or ""),
        estimated_repair_min=int(row.get("estimated_repair_min") or 0),
        technician=str(row.get("technician") or ""),
    )
