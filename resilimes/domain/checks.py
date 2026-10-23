"""Independent constraint checks.

Each check describes itself and returns passed, failed, or skipped.
`validate` runs the registry. The critic still rejects on the hard findings
and treats a hold as conditional, which is what the recovery KPIs depend on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import Action, Plant, Schedule, ScheduledOp, Violation
from .plant import minutes_between

UNAVAILABLE = {"DOWN", "MAINTENANCE"}


@dataclass(frozen=True)
class Finding:
    detail: str
    fix_hint: str
    lot_id: str = ""
    tool_id: str = ""
    severity: str = "high"
    constraint: str = ""

    def violation(self, default_constraint: str) -> Violation:
        return Violation(
            constraint=self.constraint or default_constraint,
            severity=self.severity,
            detail=self.detail,
            fix_hint=self.fix_hint,
        )


@dataclass(frozen=True)
class Check:
    id: str
    name: dict[str, str]
    description: dict[str, str]
    category: str
    fields: tuple[str, ...]
    constraint: str
    hard: bool
    run: Callable[[Plant, Schedule], list[Finding]]
    applies: Callable[[Plant, Schedule], bool] | None = None


def reticle_for(plant: Plant, product_id: str, step: str) -> str | None:
    """Mask for this product step. A rework exposure reuses the lithography mask."""
    for item in plant.reticles:
        if item.product_id == product_id and item.step == step:
            return item.reticle_id
    if step != "LITHO-RW":
        return None
    for item in plant.reticles:
        if item.product_id == product_id and item.step == "LITHO":
            return item.reticle_id
    return None


def recipe_for(plant: Plant, product_id: str, step: str) -> str:
    product = plant.product_map().get(product_id)
    if product is not None:
        for route_step in product.route:
            if route_step.step == step:
                return route_step.recipe
    if step == "LITHO-RW":
        return "LITHO_RW"
    if step == "STRIP":
        return "STRIP_PR"
    return ""


def inhibited(plant: Plant, product_id: str, recipe: str, equipment_id: str) -> bool:
    """True when a dedication row names this tool and the product, the recipe, or both."""
    for item in plant.inhibits:
        if item.equipment_id != equipment_id:
            continue
        product_hit = bool(item.product_id) and item.product_id == product_id
        recipe_hit = bool(item.recipe) and item.recipe == recipe
        if item.product_id and item.recipe:
            if product_hit and recipe_hit:
                return True
        elif product_hit or recipe_hit:
            return True
    return False


def _has_qtime(plant: Plant, schedule: Schedule) -> bool:
    return bool(plant.qtime_rules) and schedule.policy != ""


def _has_reticles(plant: Plant, schedule: Schedule) -> bool:
    return bool(plant.reticles) and schedule.policy != ""


def _has_inhibits(plant: Plant, schedule: Schedule) -> bool:
    return bool(plant.inhibits) and schedule.policy != ""


def _calendar(plant: Plant, schedule: Schedule) -> list[Finding]:
    equipment = plant.equipment_map()
    found: list[Finding] = []
    for op in schedule.operations:
        machine = equipment.get(op.equipment_id)
        if machine is None:
            found.append(
                Finding(
                    constraint="other",
                    lot_id=op.job_id,
                    tool_id=op.equipment_id,
                    detail=f"Schedule references unknown tool {op.equipment_id}.",
                    fix_hint="Rebuild the schedule from the current equipment list.",
                )
            )
            continue
        if op.start_min < machine.available_at_min:
            found.append(
                Finding(
                    lot_id=op.job_id,
                    tool_id=op.equipment_id,
                    detail=(
                        f"{op.job_id} {op.step} starts on {op.equipment_id} at "
                        f"t={op.start_min}, before it is up at t={machine.available_at_min}."
                    ),
                    fix_hint="Delay the start until the tool is available or move the lot.",
                )
            )
    return found


def _capability(plant: Plant, schedule: Schedule) -> list[Finding]:
    equipment = plant.equipment_map()
    products = plant.product_map()
    found: list[Finding] = []
    for op in schedule.operations:
        machine = equipment.get(op.equipment_id)
        if machine is None or op.product_id not in products:
            continue
        route = {step.step: step for step in products[op.product_id].route}
        needed = route.get(op.step)
        if needed is None:
            continue
        if needed.capability not in machine.capability:
            found.append(
                Finding(
                    lot_id=op.job_id,
                    tool_id=op.equipment_id,
                    detail=(
                        f"{op.equipment_id} lacks {needed.capability} required by "
                        f"{op.job_id} {op.step}."
                    ),
                    fix_hint="Move the step to a qualified tool.",
                )
            )
    return found


def _overlap(_plant: Plant, schedule: Schedule) -> list[Finding]:
    by_tool: dict[str, list[tuple[int, int, str]]] = {}
    for op in schedule.operations:
        by_tool.setdefault(op.equipment_id, []).append((op.start_min, op.end_min, op.job_id))
    found: list[Finding] = []
    for tool, spans in by_tool.items():
        spans.sort()
        for index in range(1, len(spans)):
            prev = spans[index - 1]
            current = spans[index]
            if current[0] < prev[1]:
                found.append(
                    Finding(
                        lot_id=current[2],
                        tool_id=tool,
                        detail=(
                            f"{tool} overlaps {prev[2]} [{prev[0]}, {prev[1]}) and "
                            f"{current[2]} [{current[0]}, {current[1]})."
                        ),
                        fix_hint="Sequence the lots; a tool runs one lot at a time.",
                    )
                )
    return found


def _wip(plant: Plant, schedule: Schedule) -> list[Finding]:
    """Simultaneous lots on a tool, not the count across the whole horizon."""
    equipment = plant.equipment_map()
    by_tool: dict[str, list[tuple[int, int]]] = {}
    for op in schedule.operations:
        by_tool.setdefault(op.equipment_id, []).append((op.start_min, op.end_min))
    found: list[Finding] = []
    for tool, spans in by_tool.items():
        machine = equipment.get(tool)
        if machine is None:
            continue
        for start, _end in spans:
            present = sum(1 for other_start, other_end in spans if other_start <= start < other_end)
            if present > machine.max_wip:
                found.append(
                    Finding(
                        tool_id=tool,
                        detail=(
                            f"{tool} has {present} lots at t={start}; max_wip is {machine.max_wip}."
                        ),
                        fix_hint="Spread overlapping lots across alternate qualified tools.",
                    )
                )
                break
    return found


def _operators(plant: Plant, schedule: Schedule) -> list[Finding]:
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
                Finding(
                    detail=f"Operator demand {used} at t={point} exceeds pool {plant.operator_pool}.",
                    fix_hint="Stagger starts or release operators from lower-priority tools.",
                )
            ]
    return []


def _material(plant: Plant, schedule: Schedule) -> list[Finding]:
    products = plant.product_map()
    jobs = plant.job_map()
    inventory = {item.material_id: item.on_hand for item in plant.materials}
    started: set[str] = set()
    found: list[Finding] = []
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
                    Finding(
                        lot_id=op.job_id,
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


def _precedence(_plant: Plant, schedule: Schedule) -> list[Finding]:
    by_job: dict[str, list[ScheduledOp]] = {}
    for op in schedule.operations:
        by_job.setdefault(op.job_id, []).append(op)
    found: list[Finding] = []
    for job_id, ops in by_job.items():
        ops.sort(key=lambda item: item.step_index)
        for index in range(1, len(ops)):
            if ops[index].start_min < ops[index - 1].end_min:
                found.append(
                    Finding(
                        lot_id=job_id,
                        detail=(
                            f"{job_id} starts {ops[index].step} before "
                            f"{ops[index - 1].step} finishes."
                        ),
                        fix_hint="Keep the route order.",
                    )
                )
    return found


def _preemption(plant: Plant, schedule: Schedule) -> list[Finding]:
    equipment = plant.equipment_map()
    found: list[Finding] = []
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
                Finding(
                    lot_id=job.job_id,
                    tool_id=job.assigned_equipment,
                    detail=f"{job.job_id} was moved off {job.assigned_equipment} while running.",
                    fix_hint="Keep the running lot on its current tool.",
                )
            )
    return found


def _qtime(plant: Plant, schedule: Schedule) -> list[Finding]:
    found: list[Finding] = []
    by_job: dict[str, dict[str, ScheduledOp]] = {}
    for op in schedule.operations:
        by_job.setdefault(op.job_id, {})[op.step] = op
    jobs = plant.job_map()
    for rule in plant.qtime_rules:
        for job_id, ops in by_job.items():
            job = jobs.get(job_id)
            if job is None or job.product_id != rule.product_id:
                continue
            left = ops.get(rule.from_step)
            right = ops.get(rule.to_step)
            if left is None or right is None:
                continue
            gap = right.start_min - left.end_min
            if gap <= rule.max_min:
                continue
            found.append(
                Finding(
                    lot_id=job_id,
                    tool_id=right.equipment_id,
                    detail=(
                        f"{rule.from_step} ended at t={left.end_min} min; "
                        f"{job_id} {rule.to_step} starts at t={right.start_min} min, "
                        f"past the {rule.max_min} min queue time."
                    ),
                    fix_hint="Start the next step inside the queue-time window, or hold the lot.",
                )
            )
    return found


def _rework_limit(plant: Plant, schedule: Schedule) -> list[Finding]:
    counts: dict[str, list[ScheduledOp]] = {}
    for op in schedule.operations:
        if op.rework:
            counts.setdefault(op.job_id, []).append(op)
    jobs = plant.job_map()
    found: list[Finding] = []
    seen = set(counts) | {job.job_id for job in plant.jobs if job.rework_of or job.rework_count}
    for job_id in sorted(seen):
        job = jobs.get(job_id)
        if job is None:
            continue
        ops = counts.get(job_id, [])
        total = job.rework_count + len(ops)
        if total > job.rework_limit:
            found.append(
                Finding(
                    lot_id=job_id,
                    tool_id=ops[-1].equipment_id if ops else "",
                    detail=(
                        f"{job_id} has {total} rework passes; the limit is {job.rework_limit}."
                    ),
                    fix_hint="Stop at the rework limit.",
                )
            )
        expected = f"{job.rework_of}-RW" if job.rework_of else ""
        for op in ops:
            if expected and op.step != expected:
                found.append(
                    Finding(
                        lot_id=job_id,
                        tool_id=op.equipment_id,
                        detail=(
                            f"{job_id} rework re-enters {op.step}; the return step is {expected}."
                        ),
                        fix_hint="Send the lot back to the failed step.",
                    )
                )
    return found


def _reticle_uses(plant: Plant, schedule: Schedule) -> list[tuple[str, str, str, int, int]]:
    uses: list[tuple[str, str, str, int, int]] = []
    for op in schedule.operations:
        reticle_id = reticle_for(plant, op.product_id, op.step)
        if reticle_id is None:
            continue
        uses.append((reticle_id, op.equipment_id, op.job_id, op.start_min, op.end_min))
    return uses


def _reticle(plant: Plant, schedule: Schedule) -> list[Finding]:
    uses = _reticle_uses(plant, schedule)
    found: list[Finding] = []
    for index, left in enumerate(uses):
        for right in uses[index + 1 :]:
            if left[0] != right[0] or left[1] == right[1]:
                continue
            if left[3] < right[4] and right[3] < left[4]:
                found.append(
                    Finding(
                        lot_id=right[2],
                        tool_id=right[1],
                        detail=(
                            f"Reticle {left[0]} is on {left[1]} for {left[2]} "
                            f"[{left[3]}, {left[4]}] and on {right[1]} for {right[2]} "
                            f"[{right[3]}, {right[4]}]."
                        ),
                        fix_hint="Keep the reticle on one lithography tool at a time.",
                    )
                )
    return found


def _inhibit(plant: Plant, schedule: Schedule) -> list[Finding]:
    found: list[Finding] = []
    for op in schedule.operations:
        recipe = recipe_for(plant, op.product_id, op.step)
        if not inhibited(plant, op.product_id, recipe, op.equipment_id):
            continue
        found.append(
            Finding(
                lot_id=op.job_id,
                tool_id=op.equipment_id,
                detail=(f"{op.job_id} cannot run {recipe or op.step} on {op.equipment_id}."),
                fix_hint="Use a tool that is not on the inhibit list.",
            )
        )
    return found


def _release_time(plant: Plant, schedule: Schedule) -> list[Finding]:
    jobs = plant.job_map()
    pinned = {op.job_id for op in schedule.operations if op.pinned}
    by_job: dict[str, list[ScheduledOp]] = {}
    for op in schedule.operations:
        by_job.setdefault(op.job_id, []).append(op)
    found: list[Finding] = []
    for job_id, ops in by_job.items():
        if job_id in pinned:
            continue
        job = jobs.get(job_id)
        if job is None or job.release_min <= 0:
            continue
        first = min(ops, key=lambda op: (op.start_min, op.step_index))
        if first.start_min < job.release_min:
            found.append(
                Finding(
                    lot_id=job_id,
                    tool_id=first.equipment_id,
                    detail=(
                        f"{job_id} starts at t={first.start_min} min, "
                        f"before its release at t={job.release_min} min."
                    ),
                    fix_hint="Wait until the lot is released.",
                )
            )
    return found


def _hold_release(_plant: Plant, schedule: Schedule) -> list[Finding]:
    return [
        Finding(
            lot_id=item.job_id,
            detail=item.reason,
            fix_hint="Release the lot when the hold clears.",
            severity="low",
        )
        for item in schedule.unscheduled
    ]


def _text(en: str, zh: str, ja: str) -> dict[str, str]:
    return {"en": en, "zh": zh, "ja": ja}


REGISTRY: tuple[Check, ...] = (
    Check(
        id="equipment_status",
        name=_text("Tool calendar", "设备日历", "装置カレンダー"),
        description=_text(
            "A lot cannot start while the tool is down or in maintenance.",
            "设备宕机或维护期间不能开工。",
            "停止中または保全中の装置では着手できない。",
        ),
        category="equipment",
        fields=("equipment.status", "equipment.available_at_min", "operation.start_min"),
        constraint="equipment_status",
        hard=True,
        run=_calendar,
    ),
    Check(
        id="capability",
        name=_text("Capability", "能力", "能力"),
        description=_text(
            "The tool must list the step's capability.",
            "设备必须具备该工序的能力。",
            "装置がその工程の能力を持つこと。",
        ),
        category="equipment",
        fields=("equipment.capability", "route_step.capability"),
        constraint="capability",
        hard=True,
        run=_capability,
    ),
    Check(
        id="overlap",
        name=_text("Overlap", "重叠", "重複"),
        description=_text(
            "A tool runs one lot at a time.",
            "一台设备同时只加工一个批次。",
            "装置は同時に一つのロットだけ加工する。",
        ),
        category="equipment",
        fields=("operation.equipment_id", "operation.start_min", "operation.end_min"),
        constraint="overlap",
        hard=True,
        run=_overlap,
    ),
    Check(
        id="wip",
        name=_text("WIP limit", "在制上限", "仕掛上限"),
        description=_text(
            "Simultaneous lots cannot exceed the tool's max WIP.",
            "同时在制不能超过设备上限。",
            "同時仕掛は装置の上限を超えない。",
        ),
        category="equipment",
        fields=("equipment.max_wip", "operation.start_min", "operation.end_min"),
        constraint="max_wip",
        hard=True,
        run=_wip,
    ),
    Check(
        id="operators",
        name=_text("Operators", "人员", "人員"),
        description=_text(
            "Overlapping steps cannot exceed the operator pool.",
            "重叠工序不能超过人员池。",
            "重なる工程は人員プールを超えない。",
        ),
        category="equipment",
        fields=("equipment.operators_required", "plant.operator_pool"),
        constraint="operator_capacity",
        hard=True,
        run=_operators,
    ),
    Check(
        id="material",
        name=_text("Material", "物料", "資材"),
        description=_text(
            "A new lot consumes its BOM only when stock covers it.",
            "新批次只有库存够用时才消耗物料。",
            "新規ロットは在庫が足りるときだけ部材を消費する。",
        ),
        category="material",
        fields=("material.on_hand", "bom.qty_per_lot"),
        constraint="material",
        hard=True,
        run=_material,
    ),
    Check(
        id="precedence",
        name=_text("Route order", "工艺顺序", "工程順"),
        description=_text(
            "A step cannot start before the previous step finishes.",
            "上道工序结束前不能开始下道。",
            "前工程が終わる前に次工程は始めない。",
        ),
        category="process",
        fields=("operation.step_index", "operation.start_min", "operation.end_min"),
        constraint="precedence",
        hard=True,
        run=_precedence,
    ),
    Check(
        id="preemption",
        name=_text("Preemption", "抢占", "割り込み"),
        description=_text(
            "A lot running on an up tool stays there.",
            "正在加工的批次留在可用设备上。",
            "加工中のロットは稼働中の装置に残す。",
        ),
        category="lot",
        fields=("job.status", "job.assigned_equipment"),
        constraint="preemption",
        hard=True,
        run=_preemption,
    ),
    Check(
        id="qtime",
        name=_text("Queue time", "队列时间", "待ち時間"),
        description=_text(
            "The next step must start within the queue-time limit.",
            "下道工序必须在队列时间内开始。",
            "次工程は待ち時間の制限内に始める。",
        ),
        category="time",
        fields=("qtime_rule.from_step", "qtime_rule.to_step", "qtime_rule.max_min"),
        constraint="qtime",
        hard=True,
        run=_qtime,
        applies=_has_qtime,
    ),
    Check(
        id="rework_limit",
        name=_text("Rework limit", "返工上限", "再加工上限"),
        description=_text(
            "A lot may re-enter the failed step only up to its rework limit.",
            "批次回到失败工序的次数不能超过返工上限。",
            "失敗工程への再入場は再加工上限まで。",
        ),
        category="lot",
        fields=("job.rework_count", "job.rework_limit", "operation.rework"),
        constraint="rework_limit",
        hard=True,
        run=_rework_limit,
    ),
    Check(
        id="reticle",
        name=_text("Reticle", "光罩", "レチクル"),
        description=_text(
            "A lithography reticle can be on only one tool at a time.",
            "一块光罩同一时间只能在一台光刻机上。",
            "レチクルは同時に一台のリソ装置にしか載せられない。",
        ),
        category="equipment",
        fields=("reticle.reticle_id", "reticle.step", "operation.equipment_id"),
        constraint="reticle",
        hard=True,
        run=_reticle,
        applies=_has_reticles,
    ),
    Check(
        id="inhibit",
        name=_text("Tool inhibit", "设备禁用", "装置禁止"),
        description=_text(
            "A lot or recipe cannot run on an excluded tool.",
            "批次或配方不能在被禁用的设备上跑。",
            "ロットまたはレシピは禁止装置では流せない。",
        ),
        category="lot",
        fields=("inhibit.product_id", "inhibit.recipe", "inhibit.equipment_id"),
        constraint="inhibit",
        hard=True,
        run=_inhibit,
        applies=_has_inhibits,
    ),
    Check(
        id="release_time",
        name=_text("Lot release", "批次放行", "ロット着手"),
        description=_text(
            "A lot cannot start before its release time.",
            "批次不能在放行时间之前开工。",
            "ロットは着手時刻より前に始めない。",
        ),
        category="time",
        fields=("job.release_min", "operation.start_min"),
        constraint="release_time",
        hard=True,
        run=_release_time,
    ),
    Check(
        id="hold_release",
        name=_text("Hold and release", "暂停与放行", "保留と解除"),
        description=_text(
            "Held lots stay out of the book and are listed here.",
            "暂停的批次不进账, 并在这里列出.",
            "保留ロットは帳票に載せずここに出す.",
        ),
        category="lot",
        fields=("schedule.unscheduled",),
        constraint="hold_release",
        hard=False,
        run=_hold_release,
    ),
)


def _applies(check: Check, plant: Plant, schedule: Schedule) -> bool:
    if check.applies is None:
        return True
    return check.applies(plant, schedule)


def hard_violations(plant: Plant, schedule: Schedule) -> list[Violation]:
    found: list[Violation] = []
    for check in REGISTRY:
        if not check.hard or not _applies(check, plant, schedule):
            continue
        for item in check.run(plant, schedule):
            found.append(item.violation(check.constraint))
    return found


def validate(plant: Plant, schedule: Schedule) -> dict[str, Any]:
    """Aggregate every registered check for the Verify tab."""
    details: list[dict[str, Any]] = []
    passed = failed = skipped = 0
    for check in REGISTRY:
        if not _applies(check, plant, schedule):
            status = "skipped"
            findings: list[Finding] = []
            skipped += 1
        else:
            findings = check.run(plant, schedule)
            if check.hard and any(item.severity == "high" for item in findings):
                status = "failed"
                failed += 1
            else:
                status = "passed"
                passed += 1
        details.append(
            {
                "id": check.id,
                "name": check.name,
                "description": check.description,
                "category": check.category,
                "fields": list(check.fields),
                "constraint": check.constraint,
                "status": status,
                "violations": [
                    {"lot_id": item.lot_id, "tool_id": item.tool_id, "detail": item.detail}
                    for item in findings
                ],
            }
        )
    overall = "failed" if failed else "passed"
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "overall": overall,
        "details": details,
    }


def _running_hold(plant: Plant, job_id: str) -> tuple[str, int] | None:
    """Tool and end minute for a lot that is still running at the horizon."""
    job = plant.job_map().get(job_id)
    if job is None or job.status != "RUNNING" or not job.assigned_equipment:
        return None
    elapsed = 0
    if job.started_at is not None:
        elapsed = max(0, minutes_between(job.started_at, plant.horizon))
    remaining = job.process_time_min - elapsed
    if remaining <= 0:
        return None
    return job.assigned_equipment, remaining


def extra_action_violations(plant: Plant, action: Action) -> list[Violation]:
    """Checks appended after the original action rules, so the first refusal stays put."""
    job = plant.job_map().get(action.job_id)
    if job is None or not action.step or not action.to_equipment:
        return []
    found: list[Violation] = []
    reticle_id = reticle_for(plant, job.product_id, action.step)
    if reticle_id is not None and action.start_min is not None:
        for holder in plant.jobs:
            if holder.job_id == action.job_id:
                continue
            held = _running_hold(plant, holder.job_id)
            if held is None:
                continue
            tool, end = held
            mask = reticle_for(plant, holder.product_id, holder.current_step)
            if mask != reticle_id or tool == action.to_equipment:
                continue
            if action.start_min < end:
                found.append(
                    Violation(
                        constraint="reticle",
                        severity="high",
                        detail=(
                            f"Reticle {reticle_id} is on {tool} with {holder.job_id} "
                            f"until t={end} min; {action.job_id} cannot start on "
                            f"{action.to_equipment} at t={action.start_min}."
                        ),
                        fix_hint="Use the tool that already has the reticle, or wait until it is free.",
                    )
                )
                break
    recipe = recipe_for(plant, job.product_id, action.step)
    if inhibited(plant, job.product_id, recipe, action.to_equipment):
        found.append(
            Violation(
                constraint="inhibit",
                severity="high",
                detail=f"{action.job_id} cannot run {recipe or action.step} on {action.to_equipment}.",
                fix_hint="Use a tool that is not on the inhibit list.",
            )
        )
    if (
        job.release_min > 0
        and action.start_min is not None
        and action.start_min < job.release_min
        and not (job.status == "RUNNING" and job.assigned_equipment == action.to_equipment)
    ):
        found.append(
            Violation(
                constraint="release_time",
                severity="high",
                detail=(
                    f"{action.job_id} cannot start at t={action.start_min} min; "
                    f"release is t={job.release_min} min."
                ),
                fix_hint="Wait until the lot is released.",
            )
        )
    if action.step.endswith("-RW") and job.rework_count + 1 > job.rework_limit:
        found.append(
            Violation(
                constraint="rework_limit",
                severity="high",
                detail=(f"{action.job_id} would exceed the rework limit of {job.rework_limit}."),
                fix_hint="Stop at the rework limit.",
            )
        )
    return found
