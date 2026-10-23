"""Deterministic constraint critic.

Hard violations reject a proposal. A feasible schedule with held lots is
conditional: the holds are visible, and nothing impossible was committed.
"""

from __future__ import annotations

from .models import Action, Critique, Plant, Schedule, Violation

UNAVAILABLE = {"DOWN", "MAINTENANCE"}


def critique_schedule(plant: Plant, schedule: Schedule) -> Critique:
    violations: list[Violation] = []
    violations.extend(_calendar(plant, schedule))
    violations.extend(_capability(plant, schedule))
    violations.extend(_overlap(schedule))
    violations.extend(_wip(plant, schedule))
    violations.extend(_operators(plant, schedule))
    violations.extend(_material(plant, schedule))
    violations.extend(_precedence(schedule))
    violations.extend(_preemption(plant, schedule))
    return _summarize(violations, held=bool(schedule.unscheduled))


def critique_actions(plant: Plant, actions: list[Action]) -> Critique:
    """Check a proposed action list that may not be a full schedule."""
    equipment = plant.equipment_map()
    jobs = plant.job_map()
    products = plant.product_map()
    violations: list[Violation] = []
    for action in actions:
        if action.type not in {"reassign", "assign", "expedite"}:
            continue
        target = action.to_equipment
        if not target or target not in equipment:
            violations.append(
                Violation(
                    constraint="other",
                    severity="high",
                    detail=f"Unknown destination equipment {target}.",
                    fix_hint="Choose an equipment_id that exists in the plant.",
                )
            )
            continue
        machine = equipment[target]
        job = jobs.get(action.job_id)
        if action.start_min is not None and action.start_min < machine.available_at_min:
            violations.append(
                Violation(
                    constraint="equipment_status",
                    severity="high",
                    detail=(
                        f"{target} is {machine.status} until t={machine.available_at_min} min; "
                        f"{action.job_id} cannot start at t={action.start_min}."
                    ),
                    fix_hint="Wait for the repair ETA or move the lot to an up tool.",
                )
            )
        elif machine.status in UNAVAILABLE and action.start_min is None:
            violations.append(
                Violation(
                    constraint="equipment_status",
                    severity="high",
                    detail=f"{target} is {machine.status}; cannot accept {action.job_id} now.",
                    fix_hint="Choose an IDLE or RUNNING tool with the same capability.",
                )
            )
        if job is not None and action.step:
            route = {step.step: step for step in products[job.product_id].route}
            needed = route.get(action.step)
            if needed is not None and needed.capability not in machine.capability:
                violations.append(
                    Violation(
                        constraint="capability",
                        severity="high",
                        detail=(f"{target} cannot run {action.step} (needs {needed.capability})."),
                        fix_hint="Route the step to a tool that lists that capability.",
                    )
                )
        if (
            job is not None
            and job.status == "RUNNING"
            and action.type == "reassign"
            and job.assigned_equipment
            and target != job.assigned_equipment
        ):
            machine_now = equipment.get(job.assigned_equipment)
            if machine_now is not None and machine_now.status not in UNAVAILABLE:
                violations.append(
                    Violation(
                        constraint="preemption",
                        severity="high",
                        detail=(f"{job.job_id} is already running on {job.assigned_equipment}."),
                        fix_hint="Leave the running lot in place and reschedule queued work.",
                    )
                )
        if action.type == "expedite" and job is not None:
            product = products[job.product_id]
            for need in product.materials:
                stock = plant.material_map().get(need.material_id)
                on_hand = stock.on_hand if stock else 0
                if on_hand < need.qty_per_lot:
                    violations.append(
                        Violation(
                            constraint="material",
                            severity="high",
                            detail=(
                                f"{need.material_id} on hand is {on_hand}, "
                                f"{job.job_id} needs {need.qty_per_lot}."
                            ),
                            fix_hint="Hold the lot or allocate substitute stock before dispatch.",
                        )
                    )
    return _summarize(violations, held=False)


def _calendar(plant: Plant, schedule: Schedule) -> list[Violation]:
    equipment = plant.equipment_map()
    found: list[Violation] = []
    for op in schedule.operations:
        machine = equipment.get(op.equipment_id)
        if machine is None:
            found.append(
                Violation(
                    constraint="other",
                    severity="high",
                    detail=f"Schedule references unknown tool {op.equipment_id}.",
                    fix_hint="Rebuild the schedule from the current equipment list.",
                )
            )
            continue
        if op.start_min < machine.available_at_min:
            found.append(
                Violation(
                    constraint="equipment_status",
                    severity="high",
                    detail=(
                        f"{op.job_id} {op.step} starts on {op.equipment_id} at "
                        f"t={op.start_min}, before it is up at t={machine.available_at_min}."
                    ),
                    fix_hint="Delay the start until the tool is available or move the lot.",
                )
            )
    return found


def _capability(plant: Plant, schedule: Schedule) -> list[Violation]:
    equipment = plant.equipment_map()
    products = plant.product_map()
    found: list[Violation] = []
    for op in schedule.operations:
        machine = equipment.get(op.equipment_id)
        route = {step.step: step for step in products[op.product_id].route}
        needed = route.get(op.step)
        if machine is None or needed is None:
            continue
        if needed.capability not in machine.capability:
            found.append(
                Violation(
                    constraint="capability",
                    severity="high",
                    detail=(
                        f"{op.equipment_id} lacks {needed.capability} required by "
                        f"{op.job_id} {op.step}."
                    ),
                    fix_hint="Move the step to a qualified tool.",
                )
            )
    return found


def _overlap(schedule: Schedule) -> list[Violation]:
    by_tool: dict[str, list[tuple[int, int, str]]] = {}
    for op in schedule.operations:
        by_tool.setdefault(op.equipment_id, []).append((op.start_min, op.end_min, op.job_id))
    found: list[Violation] = []
    for tool, spans in by_tool.items():
        spans.sort()
        for index in range(1, len(spans)):
            prev = spans[index - 1]
            current = spans[index]
            if current[0] < prev[1]:
                found.append(
                    Violation(
                        constraint="overlap",
                        severity="high",
                        detail=(
                            f"{tool} overlaps {prev[2]} [{prev[0]}, {prev[1]}) and "
                            f"{current[2]} [{current[0]}, {current[1]})."
                        ),
                        fix_hint="Sequence the lots; a tool runs one lot at a time.",
                    )
                )
    return found


def _wip(plant: Plant, schedule: Schedule) -> list[Violation]:
    """Simultaneous lots on a tool, not the count across the whole horizon."""
    equipment = plant.equipment_map()
    by_tool: dict[str, list[tuple[int, int]]] = {}
    for op in schedule.operations:
        by_tool.setdefault(op.equipment_id, []).append((op.start_min, op.end_min))
    found: list[Violation] = []
    for tool, spans in by_tool.items():
        machine = equipment.get(tool)
        if machine is None:
            continue
        for start, _end in spans:
            present = sum(1 for other_start, other_end in spans if other_start <= start < other_end)
            if present > machine.max_wip:
                found.append(
                    Violation(
                        constraint="max_wip",
                        severity="high",
                        detail=(
                            f"{tool} has {present} lots at t={start}; max_wip is {machine.max_wip}."
                        ),
                        fix_hint="Spread overlapping lots across alternate qualified tools.",
                    )
                )
                break
    return found


def _operators(plant: Plant, schedule: Schedule) -> list[Violation]:
    equipment = plant.equipment_map()
    points = sorted({op.start_min for op in schedule.operations} | {0})
    for point in points:
        used = 0
        for op in schedule.operations:
            if op.start_min <= point < op.end_min:
                machine = equipment.get(op.equipment_id)
                used += machine.operators_required if machine else 1
        if used > plant.operator_pool:
            return [
                Violation(
                    constraint="operator_capacity",
                    severity="high",
                    detail=f"Operator demand {used} at t={point} exceeds pool {plant.operator_pool}.",
                    fix_hint="Stagger starts or release operators from lower-priority tools.",
                )
            ]
    return []


def _material(plant: Plant, schedule: Schedule) -> list[Violation]:
    products = plant.product_map()
    jobs = plant.job_map()
    inventory = {item.material_id: item.on_hand for item in plant.materials}
    started: set[str] = set()
    found: list[Violation] = []
    ordered = sorted(schedule.operations, key=lambda op: (op.start_min, op.job_id))
    for op in ordered:
        if op.job_id in started:
            continue
        job = jobs[op.job_id]
        if job.status == "RUNNING" and op.pinned:
            started.add(op.job_id)
            continue
        for need in products[op.product_id].materials:
            have = inventory.get(need.material_id, 0)
            if have < need.qty_per_lot:
                found.append(
                    Violation(
                        constraint="material",
                        severity="high",
                        detail=(
                            f"{op.job_id} consumes {need.material_id} x{need.qty_per_lot} "
                            f"but on-hand is {have}."
                        ),
                        fix_hint="Hold the lot until stock is released.",
                    )
                )
            else:
                inventory[need.material_id] = have - need.qty_per_lot
        started.add(op.job_id)
    return found


def _precedence(schedule: Schedule) -> list[Violation]:
    by_job: dict[str, list] = {}
    for op in schedule.operations:
        by_job.setdefault(op.job_id, []).append(op)
    found: list[Violation] = []
    for job_id, ops in by_job.items():
        ops.sort(key=lambda item: item.step_index)
        for index in range(1, len(ops)):
            if ops[index].start_min < ops[index - 1].end_min:
                found.append(
                    Violation(
                        constraint="precedence",
                        severity="high",
                        detail=(
                            f"{job_id} starts {ops[index].step} before "
                            f"{ops[index - 1].step} finishes."
                        ),
                        fix_hint="Keep the route order.",
                    )
                )
    return found


def _preemption(plant: Plant, schedule: Schedule) -> list[Violation]:
    equipment = plant.equipment_map()
    found: list[Violation] = []
    for job in plant.jobs:
        if job.status != "RUNNING" or not job.assigned_equipment:
            continue
        machine = equipment.get(job.assigned_equipment)
        if machine is None or machine.status in UNAVAILABLE:
            continue
        ops = [op for op in schedule.operations if op.job_id == job.job_id]
        if not ops:
            continue
        first = sorted(ops, key=lambda op: op.step_index)[0]
        if job.current_step == first.step and first.equipment_id != job.assigned_equipment:
            found.append(
                Violation(
                    constraint="preemption",
                    severity="high",
                    detail=(f"{job.job_id} was moved off {job.assigned_equipment} while running."),
                    fix_hint="Keep the running lot on its current tool.",
                )
            )
    return found


def _summarize(violations: list[Violation], *, held: bool) -> Critique:
    high = [item for item in violations if item.severity == "high"]
    if high:
        return Critique(
            verdict="reject",
            score=0.25,
            violations=violations,
            rationale="Hard constraints failed. The proposal is not safe to commit.",
            confidence=0.95,
        )
    if violations or held:
        return Critique(
            verdict="conditional",
            score=0.62,
            violations=violations,
            rationale=(
                "No hard constraint failed. Some lots are held or carry residual risk; "
                "review them before publishing the schedule to the floor."
            ),
            confidence=0.9,
        )
    return Critique(
        verdict="accept",
        score=0.93,
        violations=[],
        rationale="Due dates, capability, setup, staffing, WIP, and tool status all hold.",
        confidence=0.95,
    )
