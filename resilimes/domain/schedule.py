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
- A queue-time rule caps the wait from the end of `from_step` to the start
  of `to_step`. Steps may sit between them. The scheduler takes a slot inside
  the window, or holds the lot.
- Same-priority lots that feed the bottleneck area are dispatched first.
- An overlay fail inserts a wet strip, one re-expose, and one re-measure,
  and stops when `rework_count` has reached `rework_limit`.
- A lithography reticle is on one tool at a time. The same tool may use it
  for the next lot. A lot does not start before its release minute.
- An inhibit row removes that tool from the flexible candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .checks import inhibited, reticle_for
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


@dataclass
class _ReticleUse:
    reticle_id: str
    tool_id: str
    start: int
    end: int


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
    reticles: list[_ReticleUse] = []
    inventory = {item.material_id: item.on_hand for item in plant.materials}
    operations: list[ScheduledOp] = []
    unscheduled: list[Unscheduled] = []
    consumed: set[str] = set()

    bottleneck = _bottleneck_area(plant, work)
    pinned, queue = _split_pinned(work, plant, policy)
    for step in pinned:
        placed = _place_pinned(step, plant, machines, reservations, reticles)
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
        _arm_after(step, placed.end_min, work, plant, queue)

    while queue:
        queue.sort(key=lambda step: _dispatch_key(step, bottleneck))
        step = queue.pop(0)
        placed, reason = _place_flexible(
            step, plant, policy, machines, reservations, reticles, inventory, consumed
        )
        if placed is None:
            unscheduled.append(Unscheduled(job_id=step.job_id, step=step.step, reason=reason))
            continue
        operations.append(placed)
        _arm_after(step, placed.end_min, work, plant, queue)

    operations.sort(key=lambda op: (op.start_min, op.equipment_id, op.job_id))
    return Schedule(
        policy=policy,
        operations=operations,
        unscheduled=unscheduled,
        actions=_actions(plant, operations, unscheduled, bottleneck),
        bottleneck_area=bottleneck,
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
    route = _released(_with_rework(job, route), job)
    names = [step.step for step in route]
    index = names.index(job.current_step) if job.current_step in names else 0
    in_progress = False
    remaining_process: int | None = None
    carried_anchor: int | None = None
    carried_from = ""
    if job.status == "RUNNING" and job.started_at is not None and job.current_step in names:
        elapsed = max(0, minutes_between(job.started_at, plant.horizon))
        full = job.process_time_min or route[index].process_time_min
        if elapsed >= full:
            carried_from = route[index].step
            carried_anchor = full - elapsed
            index += 1
        else:
            in_progress = True
            remaining_process = full - elapsed
    steps: list[StepWork] = []
    for offset, route_step in enumerate(route[index:]):
        process = route_step.process_time_min
        if offset == 0 and remaining_process is not None:
            process = remaining_process
        nxt = route[index + offset + 1] if index + offset + 1 < len(route) else None
        if offset == 0 and carried_from:
            previous = carried_from
        elif index + offset > 0:
            previous = route[index + offset - 1].step
        else:
            previous = ""
        anchor = carried_anchor if previous == carried_from else None
        q_from, q_anchor, q_latest = _qtime_window(plant, job, previous, route_step.step, anchor)
        if carried_from and carried_anchor is not None and carried_from != previous:
            far_from, far_anchor, far_latest = _qtime_window(
                plant, job, carried_from, route_step.step, carried_anchor
            )
            if far_latest is not None and (q_latest is None or far_latest < q_latest):
                q_from, q_anchor, q_latest = far_from, far_anchor, far_latest
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
                ready_at=job.release_min if offset == 0 and not in_progress else 0,
                area=route_step.area,
                feeds=nxt.area if nxt is not None else "",
                recipe=route_step.recipe,
                rework=route_step.rework,
                qtime_from=q_from,
                qtime_anchor=q_anchor,
                qtime_latest=q_latest,
            )
        )
    return steps


def _with_rework(job: Job, route: list[RouteStep]) -> list[RouteStep]:
    """Overlay fail: wet strip, one re-expose, one re-measure.

    Only the re-measure is marked rework. The limit counts that pass, and the
    check expects the step name `{rework_of}-RW`.
    """
    if not job.rework_of or job.rework_count >= job.rework_limit:
        return route
    built: list[RouteStep] = []
    for step in route:
        built.append(step)
        if step.step != job.rework_of or step.rework:
            continue
        layer = step.layer or "L1"
        exposure = _exposure(route, layer)
        expose_name = f"{exposure.step}-RW" if exposure is not None else "LITHO-RW"
        built.append(
            RouteStep(
                step="STRIP",
                capability="wet_clean",
                process_time_min=15,
                setup_family="WET",
                step_no=step.step_no,
                operation="Strip",
                area="Clean",
                recipe="STRIP_PR",
                layer=layer,
            )
        )
        built.append(
            RouteStep(
                step=expose_name,
                capability="litho_193nm",
                process_time_min=exposure.process_time_min if exposure is not None else 40,
                setup_family=exposure.setup_family if exposure is not None else "LITHO_A",
                step_no=step.step_no,
                operation="Lithography",
                area="Lithography",
                recipe="LITHO_RW",
                layer=layer,
            )
        )
        built.append(
            RouteStep(
                step=f"{job.rework_of}-RW",
                capability=step.capability,
                process_time_min=step.process_time_min,
                setup_family=step.setup_family,
                step_no=step.step_no,
                operation=step.operation or "Metrology",
                area=step.area or "Metrology",
                recipe=step.recipe,
                layer=layer,
                rework=True,
            )
        )
    return built


def _exposure(route: list[RouteStep], layer: str) -> RouteStep | None:
    for step in route:
        if step.layer == layer and step.capability == "litho_193nm" and not step.rework:
            return step
    return None


def _released(route: list[RouteStep], job: Job) -> list[RouteStep]:
    if not job.released_through:
        return route
    for index, step in enumerate(route):
        if step.step == job.released_through:
            return route[: index + 1]
    return route


def _qtime_window(
    plant: Plant, job: Job, previous: str, step: str, carried_anchor: int | None
) -> tuple[str, int | None, int | None]:
    if not previous:
        return "", None, None
    rule = next(
        (
            item
            for item in plant.qtime_rules
            if item.product_id == job.product_id
            and item.from_step == previous
            and item.to_step == step
        ),
        None,
    )
    if rule is None:
        return "", None, None
    anchor = carried_anchor
    return rule.from_step, anchor, None if anchor is None else anchor + rule.max_min


def _dispatch_key(step: StepWork, bottleneck: str) -> tuple[int, int, int, int, str]:
    feeds = bool(bottleneck) and (step.area == bottleneck or step.feeds == bottleneck)
    return (step.priority, step.due_min, 0 if feeds else 1, step.ready_at, step.job_id)


def _bottleneck_area(plant: Plant, work: dict[str, list[StepWork]]) -> str:
    """Area with the most remaining minutes per up-tool minute, over one day."""
    demand: dict[str, int] = {}
    for steps in work.values():
        for step in steps:
            if not step.area:
                continue
            demand[step.area] = demand.get(step.area, 0) + step.process_min
    supply: dict[str, int] = {}
    window = 24 * 60
    for tool in plant.equipment:
        free = 0 if tool.status in UNAVAILABLE else max(0, window - tool.available_at_min)
        supply[tool.area] = supply.get(tool.area, 0) + free
    best = ""
    best_score = -1.0
    for area, minutes in demand.items():
        cap = supply.get(area, 0)
        score = (minutes / cap) if cap else float(minutes + 1)
        if score > best_score or (score == best_score and (best == "" or area < best)):
            best_score = score
            best = area
    return best


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


def _arm_after(
    step: StepWork,
    end_min: int,
    work: dict[str, list[StepWork]],
    plant: Plant,
    queue: list[StepWork],
) -> None:
    """Open the next step, and arm every later queue-time rule this step starts."""
    steps = work[step.job_id]
    location = next((idx for idx, item in enumerate(steps) if item is step), None)
    if location is None:
        return
    for offset, later in enumerate(steps[location + 1 :]):
        if offset == 0:
            later.ready_at = end_min
            queue.append(later)
        _bind_qtime(later, step.step, end_min, plant)


def _bind_qtime(step: StepWork, previous: str, end_min: int, plant: Plant) -> None:
    rule = next(
        (
            item
            for item in plant.qtime_rules
            if item.product_id == step.product_id
            and item.from_step == previous
            and item.to_step == step.step
        ),
        None,
    )
    if rule is None:
        return
    latest = end_min + rule.max_min
    if step.qtime_latest is not None and step.qtime_latest <= latest:
        return
    step.qtime_from = rule.from_step
    step.qtime_anchor = end_min
    step.qtime_latest = latest


def _place_pinned(
    step: StepWork,
    plant: Plant,
    machines: dict[str, _Machine],
    reservations: list[_Reservation],
    reticles: list[_ReticleUse],
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
    _remember_reticle(step, plant, equipment_id, 0, end, reticles)
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
        rework=step.rework,
    )


def _place_flexible(
    step: StepWork,
    plant: Plant,
    policy: str,
    machines: dict[str, _Machine],
    reservations: list[_Reservation],
    reticles: list[_ReticleUse],
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
    qtime_missed = False
    for equipment in candidates:
        placed = _try_machine(step, equipment, plant, machines, reservations, reticles)
        if placed is None:
            blockers.append(equipment.equipment_id)
            continue
        if step.qtime_latest is not None and placed.start_min > step.qtime_latest:
            qtime_missed = True
            continue
        weight = {1: 8, 2: 4, 3: 2, 4: 1}.get(step.priority, 1)
        later = _later_process(step, plant)
        estimate = placed.end_min + later
        tardiness = max(0, estimate - step.due_min)
        score = (tardiness * weight, placed.end_min, placed.setup_min, equipment.equipment_id)
        if best is None or score < best[0]:
            best = (score, placed)
    if best is None:
        if qtime_missed and step.qtime_latest is not None:
            return None, (
                f"Q-time would break for {step.job_id}: {step.qtime_from} ended at "
                f"t={step.qtime_anchor} min; {step.step} must start by t={step.qtime_latest} min."
            )
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
    _remember_reticle(step, plant, placed.equipment_id, placed.start_min, placed.end_min, reticles)
    _take_material(step, plant, inventory, consumed)
    return placed, ""


def _try_machine(
    step: StepWork,
    equipment: Equipment,
    plant: Plant,
    machines: dict[str, _Machine],
    reservations: list[_Reservation],
    reticles: list[_ReticleUse],
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
    start: int | None = None
    end = earliest
    for _ in range(8):
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
        end = start + duration
        ready = _reticle_ready(step, plant, equipment.equipment_id, start, end, reticles)
        if ready is None:
            return None
        if ready == start:
            break
        earliest = ready
    else:
        return None
    if start is None:
        return None
    # Staffing may push the start past the machine's previous family window.
    # Setup is unchanged because nothing else is inserted on this tool.
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
        rework=step.rework,
    )


def _reticle_ready(
    step: StepWork,
    plant: Plant,
    tool_id: str,
    start: int,
    end: int,
    uses: list[_ReticleUse],
) -> int | None:
    """Earliest start that keeps this mask off every other lithography tool."""
    reticle_id = reticle_for(plant, step.product_id, step.step)
    if reticle_id is None:
        return start
    conflict = start
    blocked = False
    for used in uses:
        if used.reticle_id != reticle_id or used.tool_id == tool_id:
            continue
        if start < used.end and end > used.start:
            blocked = True
            conflict = max(conflict, used.end)
    if not blocked:
        return start
    if conflict > start + 24 * 60:
        return None
    return conflict


def _remember_reticle(
    step: StepWork,
    plant: Plant,
    tool_id: str,
    start: int,
    end: int,
    uses: list[_ReticleUse],
) -> None:
    reticle_id = reticle_for(plant, step.product_id, step.step)
    if reticle_id is None:
        return
    uses.append(_ReticleUse(reticle_id=reticle_id, tool_id=tool_id, start=start, end=end))


def _candidates(step: StepWork, plant: Plant, policy: str) -> list[Equipment]:
    stuck = _stuck_equipment(step, plant)
    if policy == POLICY_FROZEN and stuck is not None:
        locked = [item for item in plant.equipment if item.equipment_id == stuck]
        if locked:
            return locked
    capable = [item for item in plant.equipment if step.capability in item.capability]
    if policy == POLICY_FROZEN and step.is_first:
        if step.assigned_equipment:
            locked = [
                item for item in plant.equipment if item.equipment_id == step.assigned_equipment
            ]
            return locked
        if step.preferred_equipment:
            preferred = [
                item
                for item in capable
                if item.equipment_id in step.preferred_equipment
                and not inhibited(plant, step.product_id, step.recipe, item.equipment_id)
            ]
            if preferred:
                return preferred
    return [
        item
        for item in capable
        if not inhibited(plant, step.product_id, step.recipe, item.equipment_id)
    ]


def _stuck_equipment(step: StepWork, plant: Plant) -> str | None:
    prefix = f"{step.job_id}:{step.step}:"
    for item in plant.frozen_stick:
        if item.startswith(prefix):
            return item[len(prefix) :]
    return None


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


def _bottleneck_clause(
    plant: Plant,
    equipment_id: str,
    bottleneck: str,
    unscheduled: list[Unscheduled],
) -> str:
    """Area name only when this placement is on an up tool and nothing is held."""
    if unscheduled or not bottleneck:
        return ""
    destination = plant.equipment_map().get(equipment_id)
    if destination is None or destination.area != bottleneck:
        return ""
    if destination.status in UNAVAILABLE:
        return ""
    return destination.area


def _actions(
    plant: Plant,
    operations: list[ScheduledOp],
    unscheduled: list[Unscheduled],
    bottleneck: str,
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
            if _bottleneck_clause(plant, op.equipment_id, bottleneck, unscheduled):
                reason += f" This keeps the {bottleneck} bottleneck on an up tool."
            mask = reticle_for(plant, job.product_id, op.step)
            if mask:
                reason += f" Reticle {mask} is on that tool."
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
            if _bottleneck_clause(plant, op.equipment_id, bottleneck, unscheduled):
                reason += f" This feeds the {bottleneck} bottleneck."
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
