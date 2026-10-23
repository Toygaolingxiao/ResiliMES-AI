"""Per-tool load over time. The scale console draws this instead of a lot Gantt."""

from __future__ import annotations

from .models import Plant, Schedule

UNAVAILABLE = {"DOWN", "MAINTENANCE"}


def load_map(
    plant: Plant, schedule: Schedule, horizon_min: int, buckets: int = 12
) -> dict[str, object]:
    """Busy share of each tool in equal buckets across ``horizon_min``."""
    span = max(horizon_min, 1)
    width = max(1, (span + buckets - 1) // buckets)
    by_tool: dict[str, list[tuple[int, int]]] = {}
    for op in schedule.operations:
        by_tool.setdefault(op.equipment_id, []).append((op.start_min, op.end_min))
    rows: list[dict[str, object]] = []
    for equipment in plant.equipment:
        cells: list[dict[str, object]] = []
        spans = by_tool.get(equipment.equipment_id, [])
        for index in range(buckets):
            left = index * width
            right = min(span, left + width)
            if left >= span or right <= left:
                cells.append({"util": None, "down": False})
                continue
            busy = _overlap_sum(spans, left, right)
            down = 0
            if equipment.status in UNAVAILABLE:
                down = _overlap(0, equipment.available_at_min, left, right)
            up = (right - left) - down
            if up <= 0:
                cells.append({"util": None, "down": True})
            else:
                cells.append(
                    {
                        "util": round(100.0 * busy / up),
                        "down": False,
                    }
                )
        rows.append(
            {
                "equipment_id": equipment.equipment_id,
                "area": equipment.area,
                "status": equipment.status,
                "cells": cells,
            }
        )
    return {
        "bucket_min": width,
        "span_min": span,
        "buckets": buckets,
        "rows": rows,
    }


def _overlap_sum(spans: list[tuple[int, int]], left: int, right: int) -> int:
    total = 0
    for start, end in spans:
        total += _overlap(start, end, left, right)
    return total


def _overlap(start: int, end: int, left: int, right: int) -> int:
    return max(0, min(end, right) - max(start, left))
