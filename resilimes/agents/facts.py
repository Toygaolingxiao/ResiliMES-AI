"""Fact table for a narrative. A number or id the table does not contain is a miss."""

from __future__ import annotations

import json
from typing import Any

from resilimes.common.textfacts import _numbers
from resilimes.domain.models import JobOutcome, KpiReport, Plant


def fact_table(
    *,
    plant: Plant,
    before: KpiReport,
    after: KpiReport,
    outcomes: list[JobOutcome],
    narrative: str,
    extra: list[str] | None = None,
) -> dict[str, set[str]]:
    ids = {job.job_id for job in plant.jobs}
    ids.update(item.equipment_id for item in plant.equipment)
    ids.update(item.product_id for item in plant.products)
    ids.update(item.material_id for item in plant.materials)
    ids.update(item.reticle_id for item in plant.reticles)
    ids.update(step.step for product in plant.products for step in product.route)
    ids.update(step.recipe for product in plant.products for step in product.route if step.recipe)
    blob = " ".join(
        [
            narrative,
            json.dumps(before.model_dump(), default=str),
            json.dumps(after.model_dump(), default=str),
            json.dumps([item.model_dump() for item in outcomes], default=str),
            " ".join(extra or []),
        ]
    )
    return {"ids": {item.upper() for item in ids}, "numbers": _numbers(blob)}


def degraded_call(provider_name: str, mocked: bool, reason: str, **extra: Any) -> dict[str, Any]:
    """A provider_call that cannot be mistaken for a successful model narrative."""
    call: dict[str, Any] = {
        "content": "",
        "model": "",
        "provider": provider_name,
        "lane": "explainer",
        "latency_ms": 0.0,
        "mocked": mocked,
        "completion_id": "",
        "meterless_request_id": "",
        "provider_model": "",
        "narrative_degraded": True,
        "degraded_reason": reason,
    }
    call.update(extra)
    return call
