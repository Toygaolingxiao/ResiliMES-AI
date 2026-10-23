"""Constraint-aware list scheduler.

The committed schedule comes from this heuristic, not from the language model.
A model may explain the result or propose an alternative; the critic drops any
alternative that breaks a physical constraint.

Assumptions (also listed in docs/ASSUMPTIONS.md):
- A tool processes one lot at a time. max_wip is the simultaneous lot limit,
  so a non-overlapping schedule is legal whenever max_wip >= 1.
- Setup time is charged only when the setup family changes. The family already
  on a tool at the horizon is unknown, so the first lot pays no setup.
- In-progress lots on an up tool are not preempted.
- Lot material is consumed when a not-yet-started lot is dispatched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    Action,
    Equipment,
    Job,
    Plant,
    RouteStep,
    Schedule,
    ScheduledOp,
    StepWork,
    Unscheduled,
)
from .plant import minutes_between

POLICY_FROZEN = "frozen"
POLICY_RECOVER = "recover"
UNAVAILABLE = {"DOWN", "MAINTENANCE"}


@dataclass
class _Machine:
    equipment_id: str
    available_at: int
    last_family: str | None = None
    jobs: set[str] = field(default_factory=set)


@dataclass
class _Reservation:
    start: int
    end: int
    operators: int


def schedule_plant(plant: Plant, policy: str) -> Schedule:
    if policy not in {POLICY_FROZEN, POLICY_RECOVER}:
        raise ValueError(f"Unknown scheduling policy: {policy}")
    work = _expand(plant)
    machines = {
        item.equipment_id: _Machine(
            equipment_id=item.equipment_id,
            available_at=item.available_at_min,
        )
        for item in plant.equipment
    }
    reservations: list[_Reservation] = []
    inventory = {item.material_id: item.on_hand for item in plant.materials}
    operations: list[ScheduledOp] = []
    unscheduled: list[Unscheduled] = []
    consumed: set[str] = set()

    pinned, queue = _split_pinned(work, plant, policy)
    for step in pinned:
        placed = _place_pinned(step, plant, machines, reservations)
        if placed is None:
            unscheduled.append(
                Unscheduled(
                    job_id=step.job_id,
                    step=step.step,
                    reason=f"In-progress step could not stay on {step.assigned_equipment}.",
                )
            )
            continue
        operations.append(placed)
        _take_material(step, plant, inventory, consumed)
        nxt = _successor(step, work)
        if nxt is not None:
            nxt.ready_at = placed.end_min
            queue.append(nxt)

    while queue:
        queue.sort(key=lambda step: (step.priority, step.due_min, step.ready_at, step.job_id))
        step = queue.pop(0)
        placed, reason = _place_flexible(
            step, plant, policy, machines, reservations, inventory, consumed
        )
        if placed is None:
            unscheduled.append(Unscheduled(job_id=step.job_id, step=step.step, reason=reason))
            continue
        operations.append(placed)
        nxt = _successor(step, work)
        if nxt is not None:
            nxt.ready_at = placed.end_min
            queue.append(nxt)

    operations.sort(key=lambda op: (op.start_min, op.equipment_id, op.job_id))
    return Schedule(
        policy=policy,
        operations=operations,
        unscheduled=unscheduled,
        actions=_actions(plant, operations, unscheduled),
    )


def _expand(plant: Plant) -> dict[str, list[StepWork]]:
    products = plant.product_map()
    expanded: dict[str, list[StepWork]] = {}
    for job in plant.jobs:
        product = products[job.product_id]
        expanded[job.job_id] = _job_steps(job, product.route, plant)
    return expanded


def _job_steps(job: Job, route: list[RouteStep], plant: Plant) -> list[StepWork]:
    due_min = minutes_between(plant.horizon, job.due_at)
    names = [step.step for step in route]
    index = names.index(job.current_step) if job.current_step in names else 0
    in_progress = False
    remaining_process: int | None = None
    if job.status == "RUNNING" and job.started_at is not None and job.current_step in names:
        elapsed = max(0, minutes_between(job.started_at, plant.horizon))
        full = job.process_time_min or route[index].process_time_min
        if elapsed >= full:
            index += 1
        else:
            in_progress = True
            remaining_process = full - elapsed
    steps: list[StepWork] = []
    for offset, route_step in enumerate(route[index:]):
        process = route_step.process_time_min
        if offset == 0 and remaining_process is not None:
            process = remaining_process
        steps.append(
            StepWork(
                job_id=job.job_id,
                product_id=job.product_id,
                priority=job.priority,
                due_min=due_min,
                step=route_step.step,
                step_index=index + offset,
                capability=route_step.capability,
                setup_family=route_step.setup_family,
                process_min=process,
                in_progress=in_progress and offset == 0,
                assigned_equipment=(
                    job.assigned_equipment
                    if offset == 0 and job.current_step == route_step.step
                    else None
                ),
                preferred_equipment=list(job.preferred_equipment) if offset == 0 else [],
                is_first=offset == 0,
                consumes_material=offset == 0 and not in_progress,
            )
        )
    return steps


def _split_pinned(
    work: dict[str, list[StepWork]],
    plant: Plant,
    policy: str,
) -> tuple[list[StepWork], list[StepWork]]:
    equipment = plant.equipment_map()
    pinned: list[StepWork] = []
    queue: list[StepWork] = []
    for steps in work.values():
        if not steps:
            continue
        first = steps[0]
        machine = equipment.get(first.assigned_equipment or "")
        stay = first.in_progress and machine is not None and machine.status not in UNAVAILABLE
        if stay:
            pinned.append(first)
        else:
            if policy == POLICY_FROZEN and first.in_progress and machine is not None:
                first.in_progress = False
            queue.append(first)
    return pinned, queue


def _successor(step: StepWork, work: dict[str, list[StepWork]]) -> StepWork | None:
    steps = work[step.job_id]
    location = next((idx for idx, item in enumerate(steps) if item.step == step.step), None)
    if location is None or location + 1 >= len(steps):
        return None
    return steps[location + 1]


def _place_pinned(
    step: StepWork,
    plant: Plant,
    machines: dict[str, _Machine],
    reservations: list[_Reservation],
) -> ScheduledOp | None:
    equipment_id = step.assigned_equipment
    if equipment_id is None or equipment_id not in machines:
        return None
    equipment = plant.equipment_map()[equipment_id]
    machine = machines[equipment_id]
    end = step.process_min
    machine.available_at = max(machine.available_at, end)
    machine.last_family = step.setup_family
    machine.jobs.add(step.job_id)
    reservations.append(_Reservation(start=0, end=end, operators=equipment.operators_required))
    return ScheduledOp(
        job_id=step.job_id,
        product_id=step.product_id,
        step=step.step,
        step_index=step.step_index,
        equipment_id=equipment_id,
        start_min=0,
        end_min=end,
        setup_min=0,
        process_min=step.process_min,
        setup_family=step.setup_family,
        priority=step.priority,
        pinned=True,
    )


def _place_flexible(
    step: StepWork,
    plant: Plant,
    policy: str,
    machines: dict[str, _Machine],
    reservations: list[_Reservation],
    inventory: dict[str, int],
    consumed: set[str],
) -> tuple[ScheduledOp | None, str]:
    if step.consumes_material and not _material_ok(step, plant, inventory, consumed):
        short = [
            (mid, qty, inventory.get(mid, 0))
            for mid, qty in _needs(step, plant)
            if inventory.get(mid, 0) < qty
        ]
        detail = ", ".join(f"{mid} needs {qty} but on hand is {have}" for mid, qty, have in short)
        return None, f"Material short for {step.job_id}: {detail}."
    candidates = _candidates(step, plant, policy)
    if not candidates:
        return None, f"No tool with capability {step.capability} for {step.step}."
    best: tuple[tuple[int, int, int, str], ScheduledOp] | None = None
    blockers: list[str] = []
    for equipment in candidates:
        placed = _try_machine(step, equipment, plant, machines, reservations)
        if placed is None:
            blockers.append(equipment.equipment_id)
            continue
        weight = {1: 8, 2: 4, 3: 2, 4: 1}.get(step.priority, 1)
        later = _later_process(step, plant)
        estimate = placed.end_min + later
        tardiness = max(0, estimate - step.due_min)
        score = (tardiness * weight, placed.end_min, placed.setup_min, equipment.equipment_id)
        if best is None or score < best[0]:
            best = (score, placed)
    if best is None:
        if blockers:
            return None, (
                f"No feasible slot for {step.job_id} {step.step} "
                f"on {', '.join(blockers)} (WIP, operators, or calendar)."
            )
        return None, f"No feasible tool for {step.job_id} {step.step}."
    placed = best[1]
    machine = machines[placed.equipment_id]
    machine.available_at = placed.end_min
    machine.last_family = placed.setup_family
    machine.jobs.add(step.job_id)
    need = plant.equipment_map()[placed.equipment_id].operators_required
    reservations.append(_Reservation(start=placed.start_min, end=placed.end_min, operators=need))
    _take_material(step, plant, inventory, consumed)
    return placed, ""


def _try_machine(
    step: StepWork,
    equipment: Equipment,
    plant: Plant,
    machines: dict[str, _Machine],
    reservations: list[_Reservation],
) -> ScheduledOp | None:
    machine = machines[equipment.equipment_id]
    # max_wip is the tool's simultaneous lot limit. The scheduler never overlaps
    # lots on a tool, so any max_wip >= 1 is feasible; a zero cap means "do not use".
    if equipment.max_wip < 1:
        return None
    setup = 0
    if machine.last_family is not None and machine.last_family != step.setup_family:
        setup = equipment.setup_time_min
    earliest = max(machine.available_at, step.ready_at, equipment.available_at_min)
    duration = setup + step.process_min
    start = _earliest_staffed(
        earliest,
        duration,
        equipment.operators_required,
        plant.operator_pool,
        reservations,
        earliest + 24 * 60,
    )
    if start is None:
        return None
    # Staffing may push the start past the machine's previous family window.
    # Setup is unchanged because nothing else is inserted on this tool.
    end = start + duration
    return ScheduledOp(
        job_id=step.job_id,
        product_id=step.product_id,
        step=step.step,
        step_index=step.step_index,
        equipment_id=equipment.equipment_id,
        start_min=start,
        end_min=end,
        setup_min=setup,
        process_min=step.process_min,
        setup_family=step.setup_family,
        priority=step.priority,
        pinned=False,
    )


def _candidates(step: StepWork, plant: Plant, policy: str) -> list[Equipment]:
    capable = [item for item in plant.equipment if step.capability in item.capability]
    if policy == POLICY_FROZEN and step.is_first:
        if step.assigned_equipment:
            locked = [
                item for item in plant.equipment if item.equipment_id == step.assigned_equipment
            ]
            return locked
        if step.preferred_equipment:
            preferred = [item for item in capable if item.equipment_id in step.preferred_equipment]
            if preferred:
                return preferred
    return capable


def _later_process(step: StepWork, plant: Plant) -> int:
    route = plant.product_map()[step.product_id].route
    return sum(item.process_time_min for item in route[step.step_index + 1 :])


def _needs(step: StepWork, plant: Plant) -> list[tuple[str, int]]:
    product = plant.product_map()[step.product_id]
    return [(item.material_id, item.qty_per_lot) for item in product.materials]


def _material_ok(
    step: StepWork,
    plant: Plant,
    inventory: dict[str, int],
    consumed: set[str],
) -> bool:
    if step.job_id in consumed or not step.consumes_material:
        return True
    return all(inventory.get(mid, 0) >= qty for mid, qty in _needs(step, plant))


def _take_material(
    step: StepWork,
    plant: Plant,
    inventory: dict[str, int],
    consumed: set[str],
) -> None:
    if not step.consumes_material or step.job_id in consumed:
        return
    for mid, qty in _needs(step, plant):
        inventory[mid] = inventory.get(mid, 0) - qty
    consumed.add(step.job_id)


def _earliest_staffed(
    earliest: int,
    duration: int,
    need: int,
    pool: int,
    reservations: list[_Reservation],
    latest: int,
) -> int | None:
    if need > pool:
        return None
    points = {earliest}
    for reservation in reservations:
        if earliest < reservation.end <= latest:
            points.add(reservation.end)
    for start in sorted(points):
        if _staff_ok(start, start + duration, need, pool, reservations):
            return start
    return None


def _staff_ok(
    start: int,
    end: int,
    need: int,
    pool: int,
    reservations: list[_Reservation],
) -> bool:
    points = {start}
    for reservation in reservations:
        if start <= reservation.start < end:
            points.add(reservation.start)
        if start < reservation.end < end:
            points.add(reservation.end)
    for point in points:
        used = sum(item.operators for item in reservations if item.start <= point < item.end)
        if used + need > pool:
            return False
    return True


def _actions(
    plant: Plant,
    operations: list[ScheduledOp],
    unscheduled: list[Unscheduled],
) -> list[Action]:
    jobs = plant.job_map()
    first: dict[str, ScheduledOp] = {}
    for op in operations:
        if op.job_id not in first:
            first[op.job_id] = op
    actions: list[Action] = []
    for job_id, op in first.items():
        job = jobs[job_id]
        origin = job.assigned_equipment
        if op.pinned:
            kind = "continue"
            reason = f"{job_id} stays on {op.equipment_id}; the lot is already running."
        elif origin and origin != op.equipment_id:
            kind = "reassign"
            reason = (
                f"{job_id} moves from {origin} to {op.equipment_id} for {op.step}. "
                "The destination is up, capability matches, and the slot protects the due date."
            )
        elif origin and origin == op.equipment_id:
            equipment = plant.equipment_map().get(origin)
            if equipment is not None and equipment.status in UNAVAILABLE:
                kind = "hold"
                reason = (
                    f"{job_id} waits on {origin} until t={equipment.available_at_min} min "
                    f"({equipment.status})."
                )
            else:
                kind = "keep"
                reason = f"{job_id} keeps {origin} for {op.step}."
        else:
            kind = "assign"
            reason = f"{job_id} is dispatched to {op.equipment_id} for {op.step}."
        evidence = [
            f"equipment:{op.equipment_id}",
            f"product:{job.product_id}",
            f"step:{op.step}",
            f"priority:{job.priority}",
        ]
        actions.append(
            Action(
                type=kind,
                job_id=job_id,
                step=op.step,
                from_equipment=origin,
                to_equipment=op.equipment_id,
                start_min=op.start_min,
                end_min=op.end_min,
                reason=reason,
                evidence=evidence,
            )
        )
    held = {item.job_id for item in unscheduled}
    for job_id in sorted(held):
        reasons = [item.reason for item in unscheduled if item.job_id == job_id]
        job = jobs[job_id]
        actions.append(
            Action(
                type="hold",
                job_id=job_id,
                step=next(item.step for item in unscheduled if item.job_id == job_id),
                from_equipment=job.assigned_equipment,
                to_equipment=None,
                reason=reasons[0],
                evidence=[f"product:{job.product_id}"],
            )
        )
    return actions
