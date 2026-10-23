"""Before/after manufacturing KPIs. All times are minutes from the scenario horizon."""

from __future__ import annotations

from itertools import pairwise
from typing import cast

from .models import JobOutcome, KpiReport, Plant, Schedule, ScheduledOp, priority_weight
from .plant import minutes_between

_UNSCHEDULED_LATE = 24 * 60


def evaluate(plant: Plant, schedule: Schedule) -> KpiReport:
    completions = _completions(plant, schedule)
    weights = 0
    weighted = 0
    late: list[str] = []
    flows: list[int] = []
    at_risk = 0
    for job in plant.jobs:
        completion = completions[job.job_id]
        due = minutes_between(plant.horizon, job.due_at)
        if completion is None:
            tardiness = _UNSCHEDULED_LATE
            late.append(job.job_id)
        else:
            tardiness = max(0, completion - due)
            flows.append(completion)
            if tardiness > 0:
                late.append(job.job_id)
        weighted += tardiness * priority_weight(job.priority)
        weights += 1
        if job.priority <= 2 and (completion is None or tardiness > 0):
            at_risk += 1
    on_time = len(plant.jobs) - len(late)
    makespan = max((op.end_min for op in schedule.operations), default=0)
    return KpiReport(
        on_time_delivery_pct=round(100.0 * on_time / weights, 1) if weights else 100.0,
        weighted_tardiness_min=float(weighted),
        makespan_min=makespan,
        utilization_pct=round(_utilization(plant, schedule, makespan), 1),
        lots_at_risk=at_risk,
        setup_changes=sum(1 for op in schedule.operations if op.setup_min > 0),
        mean_remaining_flow_min=round(sum(flows) / len(flows), 1) if flows else 0.0,
        late_lots=late,
        unscheduled_lots=sorted({item.job_id for item in schedule.unscheduled}),
    )


def job_outcomes(
    before_plant: Plant,
    before: Schedule,
    after_plant: Plant,
    after: Schedule,
) -> list[JobOutcome]:
    """Compare lots across two books. A lot missing from one book is not late there."""
    before_done = _completions(before_plant, before)
    after_done = _completions(after_plant, after)
    before_tool = _first_tool(before)
    after_tool = _first_tool(after)
    before_ids = {job.job_id for job in before_plant.jobs}
    after_ids = {job.job_id for job in after_plant.jobs}
    catalog = {job.job_id: job for job in before_plant.jobs}
    for job in after_plant.jobs:
        catalog.setdefault(job.job_id, job)
    rows: list[JobOutcome] = []
    for job in sorted(catalog.values(), key=lambda item: (item.priority, item.job_id)):
        due = minutes_between(after_plant.horizon, job.due_at)
        in_before = job.job_id in before_ids
        in_after = job.job_id in after_ids
        rows.append(
            JobOutcome(
                job_id=job.job_id,
                product_id=job.product_id,
                priority=job.priority,
                due_min=due,
                before_completion_min=before_done.get(job.job_id) if in_before else None,
                after_completion_min=after_done.get(job.job_id) if in_after else None,
                before_tardiness_min=(
                    _tardiness(before_done.get(job.job_id), due) if in_before else 0
                ),
                after_tardiness_min=_tardiness(after_done.get(job.job_id), due) if in_after else 0,
                before_equipment=before_tool.get(job.job_id) if in_before else None,
                after_equipment=after_tool.get(job.job_id) if in_after else None,
            )
        )
    return rows


def _tardiness(completion: int | None, due: int) -> int:
    if completion is None:
        return _UNSCHEDULED_LATE
    return max(0, completion - due)


def _completions(plant: Plant, schedule: Schedule) -> dict[str, int | None]:
    blocked = {item.job_id for item in schedule.unscheduled}
    ends: dict[str, int] = {}
    seen: set[str] = set()
    for op in schedule.operations:
        seen.add(op.job_id)
        ends[op.job_id] = max(ends.get(op.job_id, 0), op.end_min)
    result: dict[str, int | None] = {}
    for job in plant.jobs:
        if job.job_id in blocked or job.job_id not in seen:
            result[job.job_id] = (
                None if job.job_id in blocked or job.job_id not in seen else ends[job.job_id]
            )
            if job.job_id not in blocked and job.job_id not in seen:
                # Nothing left to run. Treat the lot as finished at the horizon.
                result[job.job_id] = 0
            elif job.job_id in blocked:
                result[job.job_id] = None
            else:
                result[job.job_id] = ends[job.job_id]
        else:
            result[job.job_id] = ends[job.job_id]
    return result


def _first_tool(schedule: Schedule) -> dict[str, str]:
    found: dict[str, str] = {}
    ordered = sorted(schedule.operations, key=lambda op: (op.step_index, op.start_min))
    for op in ordered:
        if op.job_id not in found:
            found[op.job_id] = op.equipment_id
    return found


def makespan_of(schedule: Schedule) -> int:
    return max((op.end_min for op in schedule.operations), default=0)


def shared_horizon(before: Schedule, after: Schedule) -> int:
    """One clock for both books: the longer makespan.

    A shorter recovered book must not shrink the denominator.
    """
    return max(makespan_of(before), makespan_of(after))


def compare_load(
    before_plant: Plant,
    before: Schedule,
    after_plant: Plant,
    after: Schedule,
) -> dict[str, object]:
    """Available-tool utilization of both books on ``shared_horizon``."""
    horizon = shared_horizon(before, after)
    return {
        "horizon_min": horizon,
        "before": load_side(before_plant, before, horizon),
        "after": load_side(after_plant, after, horizon),
    }


def load_side(plant: Plant, schedule: Schedule, horizon: int) -> dict[str, object]:
    """Busy time over up-time inside a fixed window.

    Down minutes are not in the denominator. They are returned separately so a
    tool that is down cannot raise utilization by disappearing from the window.
    """
    areas = area_utilization(plant, schedule, horizon)
    busy = sum(cast(int, row["busy_min"]) for row in areas)
    available = sum(cast(int, row["available_min"]) for row in areas)
    pct = round(100.0 * busy / available, 1) if available else 0.0
    down: list[dict[str, object]] = []
    for equipment in plant.equipment:
        down_min = _down_min(equipment.available_at_min, horizon)
        if down_min <= 0:
            continue
        down.append(
            {
                "equipment_id": equipment.equipment_id,
                "down_min": down_min,
                "status": equipment.status,
            }
        )
    return {
        "utilization_pct": pct,
        "busy_min": busy,
        "available_min": available,
        "areas": areas,
        "down": down,
    }


def area_utilization(plant: Plant, schedule: Schedule, horizon: int) -> list[dict[str, object]]:
    """Busy time over up-time for each tool area, on a caller-supplied horizon."""
    by_area: dict[str, list[str]] = {}
    available_at: dict[str, int] = {}
    for equipment in plant.equipment:
        by_area.setdefault(equipment.area, []).append(equipment.equipment_id)
        available_at[equipment.equipment_id] = equipment.available_at_min
    busy_by_tool: dict[str, int] = {}
    for op in schedule.operations:
        busy_by_tool[op.equipment_id] = busy_by_tool.get(op.equipment_id, 0) + (
            op.process_min + op.setup_min
        )
    rows: list[dict[str, object]] = []
    for area in sorted(by_area):
        tool_ids = by_area[area]
        available = 0
        busy = 0
        for tool_id in tool_ids:
            available += _up_min(available_at[tool_id], horizon)
            busy += busy_by_tool.get(tool_id, 0)
        pct = round(100.0 * busy / available, 1) if available else 0.0
        rows.append(
            {
                "area": area,
                "tools": len(tool_ids),
                "utilization_pct": pct,
                "busy_min": busy,
                "available_min": available,
            }
        )
    return rows


def flow_metrics(schedule: Schedule) -> dict[str, float]:
    """Lead time, inter-step wait, and X-factor for lots the book actually finishes.

    Lead time is completion minus the scenario clock. X-factor is that lead time
    divided by raw process time. Held lots are omitted, not charged 24 hours.
    """
    unscheduled = {item.job_id for item in schedule.unscheduled}
    leads: list[float] = []
    waits: list[int] = []
    factors: list[float] = []
    for job_id, ordered in _by_job(schedule).items():
        if job_id in unscheduled:
            continue
        completion = ordered[-1].end_min
        process = sum(op.process_min for op in ordered)
        leads.append(float(completion))
        for left, right in pairwise(ordered):
            waits.append(max(0, right.start_min - left.end_min))
        if process > 0:
            factors.append(completion / process)
    return {
        "mean_lead_min": round(sum(leads) / len(leads), 1) if leads else 0.0,
        "mean_wait_min": round(sum(waits) / len(waits), 1) if waits else 0.0,
        "mean_x_factor": round(sum(factors) / len(factors), 2) if factors else 0.0,
    }


def step_waits(schedule: Schedule) -> list[dict[str, object]]:
    """Average and max gap between consecutive steps, ranked by the average."""
    buckets: dict[tuple[str, str], list[int]] = {}
    for ordered in _by_job(schedule).values():
        for left, right in pairwise(ordered):
            gap = max(0, right.start_min - left.end_min)
            buckets.setdefault((left.step, right.step), []).append(gap)
    rows: list[dict[str, object]] = []
    for (src, dst), values in buckets.items():
        rows.append(
            {
                "from_step": src,
                "to_step": dst,
                "avg_min": round(sum(values) / len(values), 1),
                "max_min": max(values),
                "n": len(values),
            }
        )
    rows.sort(
        key=lambda row: (
            -cast(float, row["avg_min"]),
            str(row["from_step"]),
            str(row["to_step"]),
        )
    )
    return rows


def _by_job(schedule: Schedule) -> dict[str, list[ScheduledOp]]:
    grouped: dict[str, list[ScheduledOp]] = {}
    for op in schedule.operations:
        grouped.setdefault(op.job_id, []).append(op)
    return {
        job_id: sorted(ops, key=lambda op: (op.step_index, op.start_min))
        for job_id, ops in grouped.items()
    }


def _up_min(available_at: int, horizon: int) -> int:
    if horizon <= 0:
        return 0
    return max(0, horizon - available_at)


def _down_min(available_at: int, horizon: int) -> int:
    if horizon <= 0:
        return 0
    return min(max(available_at, 0), horizon)


def lots_moved(before: Schedule, after: Schedule) -> list[str]:
    """Lots whose tool changed on a step that exists in both books.

    A new lot, a held lot, and a lot that only moved in time stay out of this list.
    """
    prior: dict[tuple[str, str], str] = {}
    for op in before.operations:
        prior.setdefault((op.job_id, op.step), op.equipment_id)
    moved: set[str] = set()
    for op in after.operations:
        old = prior.get((op.job_id, op.step))
        if old is not None and old != op.equipment_id:
            moved.add(op.job_id)
    return sorted(moved)


def _utilization(plant: Plant, schedule: Schedule, makespan: int) -> float:
    if makespan <= 0:
        return 0.0
    available = 0
    for equipment in plant.equipment:
        if makespan > equipment.available_at_min:
            available += makespan - equipment.available_at_min
    if available <= 0:
        return 0.0
    busy = sum(op.process_min + op.setup_min for op in schedule.operations)
    return 100.0 * busy / available


def completion_of(schedule: Schedule, job_id: str) -> int | None:
    ends = [op.end_min for op in schedule.operations if op.job_id == job_id]
    if not ends:
        return None
    if any(item.job_id == job_id for item in schedule.unscheduled):
        return None
    return max(ends)


def first_op(schedule: Schedule, job_id: str) -> ScheduledOp | None:
    ops = [op for op in schedule.operations if op.job_id == job_id]
    if not ops:
        return None
    return sorted(ops, key=lambda op: op.step_index)[0]
