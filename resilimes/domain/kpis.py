"""Before/after manufacturing KPIs. All times are minutes from the scenario horizon."""

from __future__ import annotations

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
