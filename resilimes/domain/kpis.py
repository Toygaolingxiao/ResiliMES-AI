"""Before/after manufacturing KPIs. All times are minutes from the scenario horizon."""

from __future__ import annotations

from itertools import pairwise
from typing import cast

from .models import Job, JobOutcome, KpiReport, Plant, Schedule, ScheduledOp, priority_weight
from .plant import minutes_between


def evaluate(plant: Plant, schedule: Schedule) -> KpiReport:
    """Score a book.

    A held lot has no completion. It counts as late for on-time delivery and,
    at priority 1 or 2, as a lot at risk. It is not charged a finish time.
    The old flat 24-hour charge turned two held lots into "12 days" or
    "4 days" of tardiness. That number was the charge, not a modeled clock.
    """
    completions = _completions(plant, schedule)
    weights = 0
    weighted = 0
    late: list[str] = []
    flows: list[int] = []
    at_risk = 0
    for job in plant.jobs:
        completion = completions[job.job_id]
        due = minutes_between(plant.horizon, job.due_at)
        tardiness = 0
        if completion is None:
            late.append(job.job_id)
        else:
            tardiness = max(0, completion - due)
            flows.append(completion)
            weighted += tardiness * priority_weight(job.priority)
            if tardiness > 0:
                late.append(job.job_id)
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
    changes = step_tool_changes(before, after)
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
        change = changes.get(job.job_id)
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
                moved_step=change[0] if change else None,
                moved_from=change[1] if change else None,
                moved_to=change[2] if change else None,
            )
        )
    return rows


def _tardiness(completion: int | None, due: int) -> int:
    if completion is None:
        return 0
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
    The same pairs are on each lot as ``moved_from`` / ``moved_to``.
    """
    return sorted(step_tool_changes(before, after))


def step_tool_changes(before: Schedule, after: Schedule) -> dict[str, tuple[str, str, str]]:
    """First step whose tool changed: job id to (step, before tool, after tool)."""
    prior: dict[tuple[str, str], str] = {}
    for op in before.operations:
        prior.setdefault((op.job_id, op.step), op.equipment_id)
    found: dict[str, tuple[str, str, str]] = {}
    ordered = sorted(after.operations, key=lambda op: (op.job_id, op.step_index, op.start_min))
    for op in ordered:
        old = prior.get((op.job_id, op.step))
        if old is not None and old != op.equipment_id and op.job_id not in found:
            found[op.job_id] = (op.step, old, op.equipment_id)
    return found


_UP_GOOD = frozenset({"on_time_delivery_pct"})
_DOWN_GOOD = frozenset(
    {
        "weighted_tardiness_min",
        "makespan_min",
        "lots_at_risk",
        "setup_changes",
        "mean_lead_min",
        "mean_wait_min",
        "mean_x_factor",
    }
)
# A hold drops unfinished lots out of the book. Shorter makespan, lead, X-factor,
# fewer changeovers, and a tardiness sum that ignores those lots are then not
# a better fab.
_HOLD_NEUTRAL = frozenset(
    {
        "makespan_min",
        "mean_lead_min",
        "mean_x_factor",
        "setup_changes",
        "weighted_tardiness_min",
    }
)
_NEVER_DIRECTIONAL = frozenset({"utilization_pct"})


def metric_tones(
    before: dict[str, object], after: dict[str, object]
) -> dict[str, dict[str, object]]:
    """Green, red, or flat for each compared figure.

    ``comparable`` is false when a rise in held lots makes the figure look
    better only because work left the book. Those tones are flat.
    """
    before_held = _held_count(before.get("unscheduled_lots"))
    after_held = _held_count(after.get("unscheduled_lots"))
    hold = after_held > before_held
    tones: dict[str, dict[str, object]] = {}
    for key in _UP_GOOD | _DOWN_GOOD | _NEVER_DIRECTIONAL:
        delta = cast(float, after[key]) - cast(float, before[key])
        comparable = not (hold and key in _HOLD_NEUTRAL)
        if not comparable or key in _NEVER_DIRECTIONAL or abs(delta) < 1e-9:
            tone = "flat"
        elif key in _UP_GOOD:
            tone = "good" if delta > 0 else "bad"
        else:
            tone = "good" if delta < 0 else "bad"
        tones[key] = {"tone": tone, "comparable": comparable}
    return tones


def _held_count(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def fed_bottleneck(
    before: Schedule,
    after: Schedule,
    after_plant: Plant,
    areas_before: list[dict[str, object]],
    areas_after: list[dict[str, object]],
) -> str:
    """Bottleneck area a recovery move actually kept on an up tool.

    Empty when the book holds work, no step moved onto an up tool in that
    area, or that area's load fell. Copy must not claim the move feeds the
    bottleneck unless this returns the area.
    """
    if after.unscheduled:
        return ""
    area = after.bottleneck_area
    if not area:
        return ""
    equipment = after_plant.equipment_map()
    moved = False
    for _step, _old, new in step_tool_changes(before, after).values():
        destination = equipment.get(new)
        if destination is None or destination.area != area:
            continue
        if destination.status in {"DOWN", "MAINTENANCE"}:
            continue
        moved = True
    if not moved:
        return ""

    def _util(rows: list[dict[str, object]]) -> float:
        for row in rows:
            if row.get("area") == area:
                return float(cast(float, row["utilization_pct"]))
        return 0.0

    if _util(areas_after) + 0.05 < _util(areas_before):
        return ""
    return area


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


def qtime_report(plant: Plant, schedule: Schedule) -> dict[str, object]:
    """Queue-time pairs on this book.

    A pair that starts inside the limit is met. A pair past 80 percent of the
    limit is still met, and counted at risk. A placed pair past the limit is a
    violation. A lot the solver held because the window was already closed is
    held. Compliance is met plus at-risk, over those four.
    """
    by_job: dict[str, dict[str, ScheduledOp]] = {}
    for op in schedule.operations:
        by_job.setdefault(op.job_id, {})[op.step] = op
    held_lots = {item.job_id: item for item in schedule.unscheduled}
    rows: list[dict[str, object]] = []
    for rule in plant.qtime_rules:
        for job in plant.jobs:
            if job.product_id != rule.product_id:
                continue
            ops = by_job.get(job.job_id, {})
            left = ops.get(rule.from_step)
            right = ops.get(rule.to_step)
            hold = held_lots.get(job.job_id)
            anchor = left.end_min if left is not None else _carried_end(job, rule.from_step, plant)
            if anchor is not None and right is not None:
                gap = right.start_min - anchor
                if gap > rule.max_min:
                    state = "violation"
                elif gap > 0.8 * rule.max_min:
                    state = "risk"
                else:
                    state = "met"
                rows.append(
                    {
                        "job_id": job.job_id,
                        "from_step": rule.from_step,
                        "to_step": rule.to_step,
                        "gap_min": gap,
                        "max_min": rule.max_min,
                        "state": state,
                    }
                )
                continue
            if hold is not None and hold.step == rule.to_step and hold.reason.startswith("Q-time"):
                rows.append(
                    {
                        "job_id": job.job_id,
                        "from_step": rule.from_step,
                        "to_step": rule.to_step,
                        "gap_min": None,
                        "max_min": rule.max_min,
                        "state": "held",
                    }
                )
    met = sum(1 for row in rows if row["state"] == "met")
    risk = sum(1 for row in rows if row["state"] == "risk")
    violation = sum(1 for row in rows if row["state"] == "violation")
    held_n = sum(1 for row in rows if row["state"] == "held")
    applicable = met + risk + violation + held_n
    compliance = round(100.0 * (met + risk) / applicable, 1) if applicable else 100.0
    return {
        "compliance_pct": compliance,
        "violations": violation,
        "at_risk": risk,
        "held": held_n,
        "rows": rows,
    }


def _carried_end(job: Job, from_step: str, plant: Plant) -> int | None:
    """End of a step that finished before the scenario clock, in horizon minutes."""
    if job.current_step != from_step or job.started_at is None or job.status != "RUNNING":
        return None
    elapsed = minutes_between(job.started_at, plant.horizon)
    if elapsed < job.process_time_min:
        return None
    return job.process_time_min - elapsed


def bottleneck_report(
    before: Schedule,
    after: Schedule,
    before_areas: list[dict[str, object]],
    after_areas: list[dict[str, object]],
) -> dict[str, object]:
    """The tightest area on the recovered book, with both utilizations."""
    area = after.bottleneck_area or before.bottleneck_area

    def pct(rows: list[dict[str, object]]) -> float:
        for row in rows:
            if row.get("area") == area:
                return float(cast(float, row["utilization_pct"]))
        return 0.0

    return {"area": area, "before_pct": pct(before_areas), "after_pct": pct(after_areas)}


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
