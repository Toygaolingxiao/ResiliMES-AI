"""Proposals. The committed plan is the solver. A naive alternative is what the critic rejects."""

from __future__ import annotations

from resilimes.domain.critique import critique_actions
from resilimes.domain.models import Action, Critique, Plant
from resilimes.domain.plant import minutes_between

UNAVAILABLE = {"DOWN", "MAINTENANCE"}


def naive_alternative(plant: Plant, kind: str) -> list[Action]:
    if kind == "stockout":
        return _expedite_without_material(plant)
    if kind == "insert_lot":
        return _preempt_running(plant)
    if kind == "qtime":
        return _start_after_qtime(plant)
    return _start_on_down_tool(plant)


def _start_on_down_tool(plant: Plant) -> list[Action]:
    actions: list[Action] = []
    equipment = plant.equipment_map()
    for job in plant.jobs:
        target = job.assigned_equipment
        machine = equipment.get(target or "")
        if machine is None or machine.status not in UNAVAILABLE:
            continue
        if job.status not in {"BLOCKED", "QUEUED", "RUNNING"}:
            continue
        actions.append(
            Action(
                type="reassign",
                job_id=job.job_id,
                step=job.current_step,
                from_equipment=target,
                to_equipment=target,
                start_min=0,
                reason=(
                    f"Naive plan: start {job.job_id} on {target} immediately and ignore the repair."
                ),
                evidence=[f"equipment:{target} status={machine.status}"],
            )
        )
    return actions


def _preempt_running(plant: Plant) -> list[Action]:
    running = next(
        (job for job in plant.jobs if job.status == "RUNNING" and job.assigned_equipment),
        None,
    )
    if running is None or not running.assigned_equipment:
        return []
    others = [
        item.equipment_id
        for item in plant.equipment
        if item.equipment_id != running.assigned_equipment and item.status not in UNAVAILABLE
    ]
    destination = others[0] if others else running.assigned_equipment
    return [
        Action(
            type="reassign",
            job_id=running.job_id,
            step=running.current_step,
            from_equipment=running.assigned_equipment,
            to_equipment=destination,
            start_min=0,
            reason=(
                f"Naive plan: preempt {running.job_id} so a hot lot can take "
                f"{running.assigned_equipment} immediately."
            ),
            evidence=[f"job:{running.job_id} status=RUNNING"],
        )
    ]


def _expedite_without_material(plant: Plant) -> list[Action]:
    held = next((job for job in plant.jobs if job.priority == 1), None)
    if held is None:
        return []
    return [
        Action(
            type="expedite",
            job_id=held.job_id,
            step="LITHO",
            from_equipment=held.assigned_equipment,
            to_equipment="LITHO-01",
            start_min=0,
            reason=f"Naive plan: start {held.job_id} and consume resist that is not on hand.",
            evidence=["material:RESIST-UV"],
        )
    ]


def _start_after_qtime(plant: Plant) -> list[Action]:
    """Start CMP long after etch ended. The committed book holds the lot instead."""
    job = plant.job_map().get("LOT-1003")
    if job is None or job.started_at is None:
        return []
    elapsed = minutes_between(job.started_at, plant.horizon)
    anchor = job.process_time_min - elapsed
    return [
        Action(
            type="expedite",
            job_id=job.job_id,
            step="CMP",
            from_equipment=job.assigned_equipment,
            to_equipment="CMP-01",
            start_min=120,
            anchor_end_min=anchor,
            reason="Naive plan: start CMP after the etch queue-time window.",
            evidence=["qtime:ETCH->CMP"],
        )
    ]


def reject_alternative(plant: Plant, actions: list[Action]) -> Critique:
    if not actions:
        return Critique(
            verdict="accept",
            score=0.5,
            violations=[],
            rationale="No naive alternative was proposed.",
            confidence=0.5,
        )
    return critique_actions(plant, actions)
