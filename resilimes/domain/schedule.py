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
  The EDD policy ignores priority and the bottleneck: it dispatches by due
  date, then release, onto the qualified tool that can start soonest.
- An overlay fail inserts a wet strip, one re-expose, and one re-measure,
  and stops when `rework_count` has reached `rework_limit`.
- A lithography reticle is on one tool at a time. The same tool may use it
  for the next lot. A lot does not start before its release minute.
- An inhibit row removes that tool from the flexible candidates.
"""

from __future__ import annotations

import bisect
import heapq
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
POLICY_EDD = "edd"
UNAVAILABLE = {"DOWN", "MAINTENANCE"}
_POLICIES = {POLICY_FROZEN, POLICY_RECOVER, POLICY_EDD}


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
    start: int
    end: int
    tool_id: str


class _Staff:
    """Operator load by minute. Range add and range max, both O(log minutes)."""

    def __init__(self, minutes: int = 1 << 18) -> None:
        size = 1
        while size < minutes:
            size *= 2
        self.limit = minutes
        self._size = size
        self._max = [0] * (2 * size)
        self._lazy = [0] * (2 * size)

    def add(self, start: int, end: int, operators: int) -> None:
        if operators == 0 or start >= end:
            return
        self._add(1, 0, self._size, max(0, start), min(self.limit, end), operators)

    def peak(self, start: int, end: int) -> int:
        if start >= end:
            return 0
        return self._peak(1, 0, self._size, max(0, start), min(self.limit, end))

    def covers(self, start: int, end: int) -> bool:
        return start >= 0 and end <= self.limit

    def _add(self, node: int, lo: int, hi: int, start: int, end: int, operators: int) -> None:
        if end <= lo or hi <= start:
            return
        if start <= lo and hi <= end:
            self._lazy[node] += operators
            self._max[node] += operators
            return
        self._push(node)
        mid = (lo + hi) // 2
        self._add(node * 2, lo, mid, start, end, operators)
        self._add(node * 2 + 1, mid, hi, start, end, operators)
        self._max[node] = max(self._max[node * 2], self._max[node * 2 + 1])

    def _peak(self, node: int, lo: int, hi: int, start: int, end: int) -> int:
        if end <= lo or hi <= start:
            return 0
        if start <= lo and hi <= end:
            return self._max[node]
        self._push(node)
        mid = (lo + hi) // 2
        return max(
            self._peak(node * 2, lo, mid, start, end),
            self._peak(node * 2 + 1, mid, hi, start, end),
        )

    def _push(self, node: int) -> None:
        lazy = self._lazy[node]
        if lazy == 0:
            return
        for child in (node * 2, node * 2 + 1):
            self._lazy[child] += lazy
            self._max[child] += lazy
        self._lazy[node] = 0


@dataclass
class _Board:
    machines: dict[str, _Machine]
    staff: _Staff
    ends: list[int]
    masks: dict[str, list[_ReticleUse]]
    mask_of: dict[tuple[str, str], str]
    rules: dict[tuple[str, str, str], int]
    reservations: list[_Reservation] = field(default_factory=list)


def schedule_plant(plant: Plant, policy: str) -> Schedule:
    if policy not in _POLICIES:
        raise ValueError(f"Unknown scheduling policy: {policy}")
    board = _board(plant)
    work = _expand(plant, board.rules)
    inventory = {item.material_id: item.on_hand for item in plant.materials}
    operations: list[ScheduledOp] = []
    unscheduled: list[Unscheduled] = []
    consumed: set[str] = set()

    bottleneck = _bottleneck_area(plant, work)
    pinned, queue = _split_pinned(work, plant, policy)
    for step in pinned:
        placed = _place_pinned(step, plant, board)
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
        _arm_after(step, placed.end_min, work, plant, queue, board)

    heap: list[tuple[int, int, int, int, str, str, int, StepWork]] = []
    sequence = 0
    for step in queue:
        sequence = _push(heap, step, bottleneck, sequence, policy)
    while heap:
        step = heapq.heappop(heap)[-1]
        placed, reason = _place_flexible(step, plant, policy, board, inventory, consumed)
        if placed is None:
            unscheduled.append(Unscheduled(job_id=step.job_id, step=step.step, reason=reason))
            continue
        operations.append(placed)
        opened: list[StepWork] = []
        _arm_after(step, placed.end_min, work, plant, opened, board)
        for nxt in opened:
            sequence = _push(heap, nxt, bottleneck, sequence, policy)

    operations.sort(key=lambda op: (op.start_min, op.equipment_id, op.job_id))
    return Schedule(
        policy=policy,
        operations=operations,
        unscheduled=unscheduled,
        actions=_actions(plant, operations, unscheduled, bottleneck),
        bottleneck_area=bottleneck,
    )


def _expand(
    plant: Plant, rules: dict[tuple[str, str, str], int] | None = None
) -> dict[str, list[StepWork]]:
    if rules is None:
        rules = {
            (item.product_id, item.from_step, item.to_step): item.max_min
            for item in plant.qtime_rules
        }
    products = plant.product_map()
    expanded: dict[str, list[StepWork]] = {}
    for job in plant.jobs:
        product = products[job.product_id]
        expanded[job.job_id] = _job_steps(job, product.route, plant, rules)
    return expanded


def _job_steps(
    job: Job,
    route: list[RouteStep],
    plant: Plant,
    rules: dict[tuple[str, str, str], int],
) -> list[StepWork]:
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
        q_from, q_anchor, q_latest = _qtime_window(rules, job, previous, route_step.step, anchor)
        if carried_from and carried_anchor is not None and carried_from != previous:
            far_from, far_anchor, far_latest = _qtime_window(
                rules, job, carried_from, route_step.step, carried_anchor
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
    rules: dict[tuple[str, str, str], int],
    job: Job,
    previous: str,
    step: str,
    carried_anchor: int | None,
) -> tuple[str, int | None, int | None]:
    if not previous:
        return "", None, None
    limit = rules.get((job.product_id, previous, step))
    if limit is None:
        return "", None, None
    anchor = carried_anchor
    return previous, anchor, None if anchor is None else anchor + limit


def _push(
    heap: list[tuple[int, int, int, int, str, str, int, StepWork]],
    step: StepWork,
    bottleneck: str,
    sequence: int,
    policy: str,
) -> int:
    if policy == POLICY_EDD:
        # Due date, then the moment the step is ready. Priority and the
        # bottleneck do not change who goes next.
        key = (step.due_min, step.ready_at, 0, 0, step.job_id, step.step, sequence, step)
    else:
        feeds = bool(bottleneck) and (step.area == bottleneck or step.feeds == bottleneck)
        key = (
            step.priority,
            step.due_min,
            0 if feeds else 1,
            step.ready_at,
            step.job_id,
            step.step,
            sequence,
            step,
        )
    heapq.heappush(heap, key)
    return sequence + 1


def _board(plant: Plant) -> _Board:
    masks: dict[tuple[str, str], str] = {}
    for item in plant.reticles:
        masks[(item.product_id, item.step)] = item.reticle_id
    fallback = {"LITHO-RW": "LITHO", "LITHO-L2-RW": "LITHO-L2"}
    resolved: dict[tuple[str, str], str] = dict(masks)
    products = {item.product_id for item in plant.reticles}
    for product_id in products:
        for alias, origin in fallback.items():
            mask = masks.get((product_id, origin))
            if mask is not None:
                resolved[(product_id, alias)] = mask
    return _Board(
        machines={
            item.equipment_id: _Machine(
                equipment_id=item.equipment_id,
                available_at=item.available_at_min,
            )
            for item in plant.equipment
        },
        staff=_Staff(),
        ends=[],
        masks={},
        mask_of=resolved,
        rules={
            (item.product_id, item.from_step, item.to_step): item.max_min
            for item in plant.qtime_rules
        },
    )


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
    board: _Board,
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
        _bind_qtime(later, step.step, end_min, board)


def _bind_qtime(step: StepWork, previous: str, end_min: int, board: _Board) -> None:
    limit = board.rules.get((step.product_id, previous, step.step))
    if limit is None:
        return
    latest = end_min + limit
    if step.qtime_latest is not None and step.qtime_latest <= latest:
        return
    step.qtime_from = previous
    step.qtime_anchor = end_min
    step.qtime_latest = latest


def _place_pinned(step: StepWork, plant: Plant, board: _Board) -> ScheduledOp | None:
    equipment_id = step.assigned_equipment
    if equipment_id is None or equipment_id not in board.machines:
        return None
    equipment = plant.equipment_map()[equipment_id]
    machine = board.machines[equipment_id]
    end = step.process_min
    machine.available_at = max(machine.available_at, end)
    machine.last_family = step.setup_family
    machine.jobs.add(step.job_id)
    _occupy(board, 0, end, equipment.operators_required)
    _remember_reticle(step, equipment_id, 0, end, board)
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
    board: _Board,
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
        placed = _try_machine(step, equipment, plant, board)
        if placed is None:
            blockers.append(equipment.equipment_id)
            continue
        if step.qtime_latest is not None and placed.start_min > step.qtime_latest:
            qtime_missed = True
            continue
        if policy == POLICY_EDD:
            # The tool that can start this step soonest. No remaining-route estimate.
            score = (placed.start_min, placed.end_min, placed.setup_min, equipment.equipment_id)
        else:
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
    machine = board.machines[placed.equipment_id]
    machine.available_at = placed.end_min
    machine.last_family = placed.setup_family
    machine.jobs.add(step.job_id)
    need = plant.equipment_map()[placed.equipment_id].operators_required
    _occupy(board, placed.start_min, placed.end_min, need)
    _remember_reticle(step, placed.equipment_id, placed.start_min, placed.end_min, board)
    _take_material(step, plant, inventory, consumed)
    return placed, ""


def _try_machine(
    step: StepWork,
    equipment: Equipment,
    plant: Plant,
    board: _Board,
) -> ScheduledOp | None:
    machine = board.machines[equipment.equipment_id]
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
            board,
        )
        if start is None:
            return None
        end = start + duration
        ready = _reticle_ready(step, equipment.equipment_id, start, end, board)
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
    tool_id: str,
    start: int,
    end: int,
    board: _Board,
) -> int | None:
    """Earliest start that keeps this mask off every other lithography tool."""
    reticle_id = board.mask_of.get((step.product_id, step.step))
    if reticle_id is None:
        return start
    uses = board.masks.get(reticle_id)
    if not uses:
        return start
    # Uses are sorted by start and do not overlap, so only the tail can hit this window.
    conflict = start
    blocked = False
    index = bisect.bisect_left(uses, end, key=lambda item: item.start)
    cursor = index - 1
    while cursor >= 0 and uses[cursor].end > start:
        used = uses[cursor]
        if used.tool_id != tool_id and start < used.end and end > used.start:
            blocked = True
            conflict = max(conflict, used.end)
        cursor -= 1
    if not blocked:
        return start
    if conflict > start + 24 * 60:
        return None
    return conflict


def _remember_reticle(
    step: StepWork,
    tool_id: str,
    start: int,
    end: int,
    board: _Board,
) -> None:
    reticle_id = board.mask_of.get((step.product_id, step.step))
    if reticle_id is None:
        return
    uses = board.masks.setdefault(reticle_id, [])
    bisect.insort(
        uses,
        _ReticleUse(start=start, end=end, tool_id=tool_id),
        key=lambda item: item.start,
    )


def _occupy(board: _Board, start: int, end: int, operators: int) -> None:
    board.reservations.append(_Reservation(start=start, end=end, operators=operators))
    if board.staff.covers(start, end):
        board.staff.add(start, end, operators)
    bisect.insort(board.ends, end)


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
    board: _Board,
) -> int | None:
    if need > pool:
        return None
    latest = earliest + 24 * 60
    if board.staff.covers(earliest, latest + duration):
        index = bisect.bisect_right(board.ends, earliest)
        while True:
            if _staffed(board, earliest, earliest + duration, need, pool):
                return earliest
            if index >= len(board.ends) or board.ends[index] > latest:
                return None
            earliest = board.ends[index]
            index += 1
    points = {earliest}
    for reservation in board.reservations:
        if earliest < reservation.end <= latest:
            points.add(reservation.end)
    for start in sorted(points):
        if _staff_ok(start, start + duration, need, pool, board.reservations):
            return start
    return None


def _staffed(board: _Board, start: int, end: int, need: int, pool: int) -> bool:
    return board.staff.peak(start, end) + need <= pool


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
