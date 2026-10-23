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
                    "rework": op.rework,
                }
            )
        bars.sort(key=lambda bar: int(str(bar["start_min"])))
        rows.append(
            {
                "equipment_id": equipment.equipment_id,
                "name": equipment.name,
                "area": equipment.area,
                "status": equipment.status,
                "available_at_min": equipment.available_at_min,
                "bottleneck": bool(schedule.bottleneck_area)
                and equipment.area == schedule.bottleneck_area,
                "bars": bars,
            }
        )
    dues = [
        {
            "job_id": job.job_id,
            "due_min": minutes_between(plant.horizon, job.due_at),
            "priority": job.priority,
        }
        for job in plant.jobs
        if job.priority == 1
    ]
    return {"rows": rows, "dues": dues}


# At most nine labels (span / step <= 8). 15/30/60 stay readable on a short book.
# A 16-hour lithography book steps up to 180 so the labels do not collide.
_STEPS = (15, 30, 60, 120, 180, 240)
_MAX_SPAN_PER_STEP = 8


def choose_step(span: int) -> int:
    """Smallest nice step that keeps the axis labels from crowding."""
    for step in _STEPS:
        if span <= step * _MAX_SPAN_PER_STEP:
            return step
    return _STEPS[-1]


def shared_window(before: dict[str, object], after: dict[str, object]) -> dict[str, int]:
    """One time window for both charts, from the work itself.

    The origin stays at the scenario clock so the Now line is the left edge.
    Down time, maintenance, and priority-1 dues do not stretch the axis: a
    block past the window is clipped, and a due past the window is an edge chip.
    """
    end = _work_end(before, after)
    padded = end + max(end // 20, 10)
    step = choose_step(padded)
    snapped = ((padded + step - 1) // step) * step
    return {"start_min": 0, "end_min": snapped, "step_min": step}


def _work_end(*gantts: dict[str, object]) -> int:
    end = 0
    for gantt in gantts:
        for row in _rows(gantt):
            for bar in _bars(row):
                end = max(end, int(str(bar["end_min"])))
    return end if end > 0 else 60


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
