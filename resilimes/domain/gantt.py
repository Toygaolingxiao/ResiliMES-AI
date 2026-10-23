"""Gantt payload for the console. Times are minutes from the scenario horizon."""

from __future__ import annotations

from resilimes.domain.kpis import completion_of
from resilimes.domain.models import Plant, Schedule
from resilimes.domain.plant import minutes_between


def build_gantt(plant: Plant, schedule: Schedule) -> dict[str, object]:
    jobs = plant.job_map()
    rows: list[dict[str, object]] = []
    for equipment in plant.equipment:
        bars: list[dict[str, object]] = []
        for op in schedule.operations:
            if op.equipment_id != equipment.equipment_id:
                continue
            job = jobs[op.job_id]
            due = minutes_between(plant.horizon, job.due_at)
            finished = completion_of(schedule, op.job_id)
            late = finished is None or finished > due
            bars.append(
                {
                    "job_id": op.job_id,
                    "step": op.step,
                    "start_min": op.start_min,
                    "end_min": op.end_min,
                    "priority": op.priority,
                    "pinned": op.pinned,
                    "late": late and op.step_index == _last_index(schedule, op.job_id),
                    "setup_min": op.setup_min,
                }
            )
        bars.sort(key=lambda bar: int(str(bar["start_min"])))
        rows.append(
            {
                "equipment_id": equipment.equipment_id,
                "name": equipment.name,
                "status": equipment.status,
                "available_at_min": equipment.available_at_min,
                "bars": bars,
            }
        )
    return {"rows": rows}


def _last_index(schedule: Schedule, job_id: str) -> int:
    indexes = [op.step_index for op in schedule.operations if op.job_id == job_id]
    return max(indexes) if indexes else -1
