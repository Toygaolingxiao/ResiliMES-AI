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


def annotate_moves(before: dict[str, object], after: dict[str, object]) -> None:
    """Mark after-bars that changed tool or start, and the before-bars they left."""
    prior: dict[tuple[str, str], tuple[str, int]] = {}
    for row in _rows(before):
        equipment_id = str(row["equipment_id"])
        for bar in _bars(row):
            prior[(str(bar["job_id"]), str(bar["step"]))] = (
                equipment_id,
                int(str(bar["start_min"])),
            )
            bar["moved"] = False
            bar["fresh"] = False
    for row in _rows(after):
        equipment_id = str(row["equipment_id"])
        for bar in _bars(row):
            key = (str(bar["job_id"]), str(bar["step"]))
            old = prior.get(key)
            moved = old is not None and old != (equipment_id, int(str(bar["start_min"])))
            bar["moved"] = moved
            bar["fresh"] = old is None
            if moved and old is not None:
                _mark_left(before, old[0], key)


def _mark_left(gantt: dict[str, object], equipment_id: str, key: tuple[str, str]) -> None:
    for row in _rows(gantt):
        if str(row["equipment_id"]) != equipment_id:
            continue
        for bar in _bars(row):
            if (str(bar["job_id"]), str(bar["step"])) == key:
                bar["moved"] = True


def _rows(gantt: dict[str, object]) -> list[dict[str, object]]:
    rows = gantt.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _bars(row: dict[str, object]) -> list[dict[str, object]]:
    bars = row.get("bars")
    if not isinstance(bars, list):
        return []
    return [bar for bar in bars if isinstance(bar, dict)]


def _last_index(schedule: Schedule, job_id: str) -> int:
    indexes = [op.step_index for op in schedule.operations if op.job_id == job_id]
    return max(indexes) if indexes else -1
