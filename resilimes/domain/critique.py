"""Deterministic constraint critic.

Hard violations reject a proposal. A feasible schedule with held lots is
conditional: the holds are visible, and nothing impossible was committed.
The checks themselves live in the registry. This module keeps the verdict.
"""

from __future__ import annotations

from .checks import extra_action_violations, hard_violations
from .models import Action, Critique, Plant, Schedule, Violation

UNAVAILABLE = {"DOWN", "MAINTENANCE"}

_CHECK_ORDER = (
    "equipment_status",
    "capability",
    "overlap",
    "wip",
    "operators",
    "material",
    "precedence",
    "preemption",
    "qtime",
    "rework_limit",
    "reticle",
    "inhibit",
    "release_time",
)


def critique_schedule(plant: Plant, schedule: Schedule) -> Critique:
    return _summarize(hard_violations(plant, schedule), held=bool(schedule.unscheduled))


def constraint_checks(committed: Critique, rejected: Critique) -> list[dict[str, str]]:
    """One row per constraint family for the committed book and the refused alternative.

    ``pass`` means the committed schedule cleared it. ``fail`` means the
    committed schedule did not. ``rejected`` means the committed schedule
    cleared it and the alternative the critic refused did not.
    """
    names = list(_CHECK_ORDER)
    for critique in (committed, rejected):
        for item in critique.violations:
            if item.constraint not in names:
                names.append(item.constraint)
    rows: list[dict[str, str]] = []
    for name in names:
        committed_hit = next(
            (item for item in committed.violations if item.constraint == name), None
        )
        rejected_hit = next((item for item in rejected.violations if item.constraint == name), None)
        if committed_hit is not None:
            rows.append({"constraint": name, "result": "fail", "reason": committed_hit.detail})
        elif rejected_hit is not None:
            rows.append({"constraint": name, "result": "rejected", "reason": rejected_hit.detail})
        else:
            rows.append({"constraint": name, "result": "pass", "reason": ""})
    return rows


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
                    code="unknown_dest",
                    params={"tool": target or ""},
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
                    code="equipment_maint" if machine.status == "MAINTENANCE" else "equipment_down",
                    params={
                        "tool": target,
                        "until_at": machine.available_at_min,
                        "lot": action.job_id,
                        "start_at": action.start_min,
                    },
                )
            )
        elif machine.status in UNAVAILABLE and action.start_min is None:
            violations.append(
                Violation(
                    constraint="equipment_status",
                    severity="high",
                    detail=f"{target} is {machine.status}; cannot accept {action.job_id} now.",
                    fix_hint="Choose an IDLE or RUNNING tool with the same capability.",
                    code="equipment_blocked_maint"
                    if machine.status == "MAINTENANCE"
                    else "equipment_blocked_down",
                    params={"tool": target, "lot": action.job_id},
                )
            )
        if (
            job is not None
            and action.step
            and action.start_min is not None
            and action.anchor_end_min is not None
        ):
            rule = next(
                (
                    item
                    for item in plant.qtime_rules
                    if item.product_id == job.product_id and item.to_step == action.step
                ),
                None,
            )
            gap = action.start_min - action.anchor_end_min
            if rule is not None and gap > rule.max_min:
                violations.append(
                    Violation(
                        constraint="qtime",
                        severity="high",
                        detail=(
                            f"{rule.from_step} ended at t={action.anchor_end_min} min; "
                            f"{action.job_id} {action.step} cannot start at t={action.start_min} min "
                            f"(limit {rule.max_min} min)."
                        ),
                        fix_hint="Start the next step inside the queue-time window, or hold the lot.",
                        code="qtime_block",
                        params={
                            "from_step": rule.from_step,
                            "anchor_at": action.anchor_end_min,
                            "lot": action.job_id,
                            "step": action.step,
                            "start_at": action.start_min,
                            "limit_min": rule.max_min,
                        },
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
                        code="cannot_run",
                        params={
                            "tool": target,
                            "step": action.step,
                            "capability": needed.capability,
                        },
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
                        code="already_running",
                        params={"lot": job.job_id, "tool": job.assigned_equipment},
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
                            code="material_need",
                            params={
                                "material": need.material_id,
                                "have": on_hand,
                                "lot": job.job_id,
                                "qty": need.qty_per_lot,
                            },
                        )
                    )
        violations.extend(extra_action_violations(plant, action))
    return _summarize(violations, held=False)


def _summarize(violations: list[Violation], *, held: bool) -> Critique:
    high = [item for item in violations if item.severity == "high"]
    if high:
        return Critique(
            verdict="reject",
            score=0.25,
            violations=violations,
            rationale="Hard constraints failed. The proposal is not safe to commit.",
            rationale_code="rationale_hard",
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
            rationale_code="rationale_conditional",
            confidence=0.9,
        )
    return Critique(
        verdict="accept",
        score=0.93,
        violations=[],
        rationale="Due dates, capability, setup, staffing, WIP, and tool status all hold.",
        rationale_code="rationale_accept",
        confidence=0.95,
    )
