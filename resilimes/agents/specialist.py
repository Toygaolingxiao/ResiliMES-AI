"""Evidence the specialist surfaces before anyone proposes a move."""

from __future__ import annotations

from resilimes.data.sample_source import QueryRecord
from resilimes.domain.models import Plant

UNAVAILABLE = {"DOWN", "MAINTENANCE"}


def gather(plant: Plant, queries: list[QueryRecord]) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    for record in queries:
        facts.append(
            {
                "name": f"query.{record.name}",
                "value": record.row_count,
                "source": "zetaris" if record.mode == "zetaris" else "sample",
                "evidence": f"{record.mode}: {record.sql}",
            }
        )
    for equipment in plant.equipment:
        if equipment.status not in UNAVAILABLE:
            continue
        repair = next(
            (
                event.estimated_repair_min
                for event in reversed(plant.maintenance)
                if event.equipment_id == equipment.equipment_id and event.estimated_repair_min
            ),
            None,
        )
        facts.append(
            {
                "name": "equipment.down",
                "value": {
                    "equipment_id": equipment.equipment_id,
                    "status": equipment.status,
                    "fault_code": equipment.fault_code,
                    "available_at_min": equipment.available_at_min,
                    "log_repair_min": repair,
                },
                "source": "derived",
                "evidence": (
                    f"{equipment.equipment_id} {equipment.status} "
                    f"fault={equipment.fault_code or 'n/a'} "
                    f"available_at={equipment.available_at_min} min"
                ),
            }
        )
    for job in plant.jobs:
        if job.status != "BLOCKED" and job.priority > 2:
            continue
        facts.append(
            {
                "name": "job.attention",
                "value": {
                    "job_id": job.job_id,
                    "status": job.status,
                    "priority": job.priority,
                    "assigned_equipment": job.assigned_equipment,
                    "product_id": job.product_id,
                },
                "source": "derived",
                "evidence": (
                    f"{job.job_id} priority {job.priority} {job.status} "
                    f"on {job.assigned_equipment or 'unassigned'}"
                ),
            }
        )
    for material in plant.materials:
        if material.on_hand <= 3:
            facts.append(
                {
                    "name": "material.level",
                    "value": {"material_id": material.material_id, "on_hand": material.on_hand},
                    "source": "sample" if plant.source == "sample" else "zetaris",
                    "evidence": f"{material.material_id} on hand {material.on_hand} {material.unit}",
                }
            )
    facts.append(
        {
            "name": "operators.pool",
            "value": plant.operator_pool,
            "source": "derived",
            "evidence": f"Operator pool {plant.operator_pool}",
        }
    )
    return facts
