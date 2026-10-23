"""Acquire a machine lock, apply one tool call, re-dispatch.

This adapter uses the public ``schedule_plant`` and ``critique_schedule``
functions. It does not change how the scheduler places operations. Holds are
applied after dispatch by removing that lot from the returned book, which is
the same shape the critic already treats as conditional.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from resilimes.agents.toolcall import InsertHotLotCall, ToolCall, call_from_dump
from resilimes.domain.critique import critique_schedule
from resilimes.domain.kpis import evaluate
from resilimes.domain.models import (
    Action,
    Critique,
    Job,
    MaintenanceEvent,
    Plant,
    Schedule,
    Unscheduled,
)
from resilimes.domain.plant import enrich_availability
from resilimes.domain.schedule import POLICY_RECOVER, schedule_plant
from resilimes.txn.store import StateStore

_UNAVAILABLE = {"DOWN", "MAINTENANCE"}
_PLANT_KEY = "plant"


class LockError(RuntimeError):
    """The machine is already locked by another token."""


class MachineLock(BaseModel):
    lock_token: str
    equipment_ids: list[str]
    acquired_at: str


class TxnResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ok: bool
    committed: bool
    aborted: bool
    simulated: bool = False
    errors: list[str] = Field(default_factory=list)
    fix_hint: str = ""
    lock_token: str = ""
    kpis: dict[str, Any] | None = None
    affected_lots: list[dict[str, Any]] = Field(default_factory=list)
    critique: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    plant_id: str = ""
    book: Schedule | None = Field(default=None, exclude=True)
    draft: Plant | None = Field(default=None, exclude=True)
    critique_obj: Critique | None = Field(default=None, exclude=True)


class EngineTransaction(Protocol):
    """What the scheduling branch implements for real.

    ``apply`` runs inside the caller's lock. It persists a plant only when
    the change is committed. ``abort`` releases the lock and discards work
    that was not persisted.
    """

    def acquire_lock(self, equipment_ids: list[str]) -> MachineLock: ...

    def apply(self, lock: MachineLock, intent: dict[str, Any], plant: Plant) -> TxnResult: ...

    def abort(self, lock: MachineLock) -> None: ...


class InMemoryEngine:
    def __init__(self, store: StateStore) -> None:
        self.store = store

    def load_plant(self, fallback: Plant) -> Plant:
        raw = self.store.get(_PLANT_KEY)
        if raw is None:
            return fallback
        return Plant.model_validate_json(raw)

    def acquire_lock(self, equipment_ids: list[str]) -> MachineLock:
        ids = list(dict.fromkeys(equipment_ids)) or ["PLANT"]
        token = secrets.token_hex(16)
        held: list[str] = []
        try:
            for equipment_id in ids:
                key = f"lock:{equipment_id}"
                if not self.store.compare_and_set(key, None, token):
                    raise LockError(f"{equipment_id} is already locked.")
                held.append(equipment_id)
        except LockError:
            self._release_token(held, token)
            raise
        return MachineLock(
            lock_token=token,
            equipment_ids=ids,
            acquired_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def abort(self, lock: MachineLock) -> None:
        """Release the lock. A plant already committed by ``apply`` stays."""
        self._release_token(lock.equipment_ids, lock.lock_token)

    def apply(self, lock: MachineLock, intent: dict[str, Any], plant: Plant) -> TxnResult:
        call = call_from_dump(intent)
        self._require_lock(lock)
        trace = _notify_trace(call)
        base = TxnResult(
            ok=False,
            committed=False,
            aborted=True,
            lock_token=lock.lock_token,
            trace=trace,
            plant_id=plant.plant_id,
        )
        if call.validation_rules.check_inventory:
            short = _inventory_gaps(plant, _inventory_lots(plant, call))
            if short:
                base.errors = short
                base.fix_hint = "Replenish the material or clear check_inventory before retrying."
                return base
        original = plant.model_copy(deep=True)
        draft = plant.model_copy(deep=True)
        problem, hint = _mutate(draft, call)
        if problem:
            base.errors = [problem]
            base.fix_hint = hint
            return base
        enrich_availability(draft)
        simulated = call.intent == "what_if"
        before_book = _redispatch(original)
        after_book = _redispatch(draft)
        critique = critique_schedule(draft, after_book)
        before_kpi = evaluate(original, before_book)
        after_kpi = evaluate(draft, after_book)
        affected = _affected(original, draft, before_book, after_book)
        kpis = {
            "before": before_kpi.model_dump(),
            "after": after_kpi.model_dump(),
            "delta": _delta(before_kpi.model_dump(), after_kpi.model_dump()),
        }
        critique_dump = {"verdict": critique.verdict, "rationale": critique.rationale}
        if critique.verdict == "reject" and not simulated:
            base.errors = [critique.rationale or "Critic rejected the book."]
            base.fix_hint = critique.violations[0].fix_hint if critique.violations else ""
            base.kpis = kpis
            base.affected_lots = affected
            base.critique = critique_dump
            base.book = after_book
            base.draft = draft
            base.critique_obj = critique
            return base
        if not simulated:
            self.store.set(_PLANT_KEY, draft.model_dump_json())
        return TxnResult(
            ok=True,
            committed=not simulated,
            aborted=False,
            simulated=simulated,
            errors=[],
            lock_token=lock.lock_token,
            kpis=kpis,
            affected_lots=affected,
            critique=critique_dump,
            trace=trace,
            plant_id=draft.plant_id,
            book=after_book,
            draft=draft,
            critique_obj=critique,
        )

    def _require_lock(self, lock: MachineLock) -> None:
        for equipment_id in lock.equipment_ids:
            current = self.store.get(f"lock:{equipment_id}")
            if current != lock.lock_token:
                raise LockError(f"Lock token does not hold {equipment_id}.")

    def _release_token(self, equipment_ids: list[str], token: str) -> None:
        for equipment_id in equipment_ids:
            key = f"lock:{equipment_id}"
            if self.store.get(key) == token:
                self.store.delete(key)


def lock_targets(call: ToolCall, plant: Plant) -> list[str]:
    """Tools the change touches. The lock covers every one of them."""
    tools = plant.equipment_map()
    params = call.parameters
    equipment = str(getattr(params, "equipment_id", "") or "")
    if equipment and equipment in tools:
        return [equipment]
    target = str(getattr(params, "target_station_group", "") or "")
    if target and target in tools:
        return [target]
    if target:
        area = target.casefold()
        matched = [item.equipment_id for item in plant.equipment if item.area.casefold() == area]
        if matched:
            return matched
    lot_id = str(getattr(params, "lot_id", "") or "")
    job = plant.job_map().get(lot_id)
    if job is not None and job.assigned_equipment and job.assigned_equipment in tools:
        return [job.assigned_equipment]
    return ["PLANT"]


def _notify_trace(call: ToolCall) -> list[dict[str, Any]]:
    name = call.validation_rules.notify_pe.strip()
    if not name:
        return []
    return [
        {
            "type": "notify_pe",
            "to": name,
            "channel": "trace-only",
            "sent": False,
            "note": "Recorded for the trace and the UI. No email or message was sent.",
        }
    ]


def _inventory_lots(plant: Plant, call: ToolCall) -> list[str]:
    params = call.parameters
    lot_id = str(getattr(params, "lot_id", "") or "")
    if lot_id and lot_id in plant.job_map():
        return [lot_id]
    equipment = str(getattr(params, "equipment_id", "") or "")
    target = str(getattr(params, "target_station_group", "") or "")
    tool_id = equipment or (target if target in plant.equipment_map() else "")
    if not tool_id:
        return []
    return sorted(job.job_id for job in plant.jobs if job.assigned_equipment == tool_id)


def _inventory_gaps(plant: Plant, lot_ids: list[str]) -> list[str]:
    gaps: list[str] = []
    products = plant.product_map()
    stocks = plant.material_map()
    for lot_id in lot_ids:
        job = plant.job_map().get(lot_id)
        if job is None:
            continue
        product = products.get(job.product_id)
        if product is None:
            continue
        for need in product.materials:
            stock = stocks.get(need.material_id)
            on_hand = stock.on_hand if stock is not None else 0
            if on_hand < need.qty_per_lot:
                gaps.append(
                    f"{need.material_id} on hand is {on_hand}, {lot_id} needs {need.qty_per_lot}."
                )
    return gaps


def _mutate(plant: Plant, call: ToolCall) -> tuple[str, str]:
    if call.intent == "mark_tool_down":
        _mark_down(
            plant, call.parameters.equipment_id, call.parameters.eta_min, call.parameters.fault_code
        )
        return "", ""
    if call.intent == "move_pm":
        _move_pm(plant, call)
        return "", ""
    if call.intent == "insert_hot_lot":
        return _insert_hot_lot(plant, call), ""
    if call.intent == "hold_lot":
        return _hold(plant, call.parameters.lot_id)
    if call.intent == "release_lot":
        return _release(plant, call.parameters.lot_id)
    if call.intent == "what_if":
        return _what_if(plant, call), ""
    return f"Unsupported intent {call.intent}.", ""


def _mark_down(plant: Plant, equipment_id: str, eta_min: int, fault_code: str) -> None:
    tool = plant.equipment_map()[equipment_id]
    tool.status = "DOWN"
    tool.fault_code = fault_code or "UNPLANNED_DOWN"
    tool.repair_min = eta_min
    tool.eta_from_horizon = True
    tool.down_since = plant.horizon.strftime("%Y-%m-%dT%H:%M:%SZ")


def _move_pm(plant: Plant, call: ToolCall) -> None:
    params = call.parameters
    equipment_id = str(getattr(params, "equipment_id", "") or "")
    start = int(getattr(params, "new_start_min", 0) or 0)
    duration = int(getattr(params, "duration_min", 0) or 0)
    reason = str(getattr(params, "reason", "") or "")
    tool = plant.equipment_map()[equipment_id]
    plant.maintenance.append(
        MaintenanceEvent(
            log_id=f"PM-{equipment_id}-{start}",
            equipment_id=equipment_id,
            event_type="PM",
            occurred_at=plant.horizon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            severity_code="INFO",
            description=reason[:240],
            estimated_repair_min=duration,
            technician="",
        )
    )
    if start == 0:
        tool.status = "MAINTENANCE"
        tool.fault_code = None
        tool.repair_min = duration
        tool.eta_from_horizon = True


def _insert_hot_lot(plant: Plant, call: InsertHotLotCall) -> str:
    params = call.parameters
    lot_id = str(params.lot_id)
    target = str(params.target_station_group)
    job = plant.job_map()[lot_id]
    if bool(params.priority_override):
        job.priority = 1
    qualified = _tools_for_target(plant, job, target)
    if qualified:
        job.preferred_equipment = qualified
    return ""


def _hold(plant: Plant, lot_id: str) -> tuple[str, str]:
    job = plant.job_map()[lot_id]
    if job.status == "RUNNING" and job.assigned_equipment:
        tool = plant.equipment_map().get(job.assigned_equipment)
        if tool is not None and tool.status not in _UNAVAILABLE:
            return (
                f"Cannot hold {lot_id}: it is running on {job.assigned_equipment}.",
                "Leave the running lot in place and reschedule queued work.",
            )
    job.status = "HOLD"
    return "", ""


def _release(plant: Plant, lot_id: str) -> tuple[str, str]:
    job = plant.job_map()[lot_id]
    if job.status != "HOLD":
        return f"{lot_id} is not on hold.", "Hold the lot before releasing it."
    assigned = job.assigned_equipment
    tool = plant.equipment_map().get(assigned or "")
    if tool is not None and tool.status in _UNAVAILABLE:
        job.assigned_equipment = None
    job.status = "QUEUED"
    return "", ""


def _what_if(plant: Plant, call: ToolCall) -> str:
    params = call.parameters
    equipment_id = str(getattr(params, "equipment_id", "") or "")
    eta = getattr(params, "eta_min", None)
    if equipment_id and equipment_id in plant.equipment_map() and isinstance(eta, int):
        _mark_down(plant, equipment_id, eta, "UNPLANNED_DOWN")
    return ""


def _tools_for_target(plant: Plant, job: Job, target: str) -> list[str]:
    needed = _remaining_capabilities(plant, job)
    tools = plant.equipment_map()
    if target in tools:
        tool = tools[target]
        if needed.intersection(tool.capability):
            return [target]
        return []
    area = target.casefold()
    return [
        item.equipment_id
        for item in plant.equipment
        if item.area.casefold() == area and needed.intersection(item.capability)
    ]


def _remaining_capabilities(plant: Plant, job: Job) -> set[str]:
    route = plant.product_map()[job.product_id].route
    names = [step.step for step in route]
    index = names.index(job.current_step) if job.current_step in names else 0
    return {step.capability for step in route[index:]} or {step.capability for step in route}


def _redispatch(plant: Plant) -> Schedule:
    book = schedule_plant(plant, POLICY_RECOVER)
    held = {job.job_id for job in plant.jobs if job.status == "HOLD"}
    if not held:
        return book
    operations = [op for op in book.operations if op.job_id not in held]
    unscheduled = [item for item in book.unscheduled if item.job_id not in held]
    actions = [item for item in book.actions if item.job_id not in held]
    for lot_id in sorted(held):
        job = plant.job_map().get(lot_id)
        step = job.current_step if job is not None else ""
        reason = f"Held {lot_id} by dispatcher."
        unscheduled.append(Unscheduled(job_id=lot_id, step=step, reason=reason))
        actions.append(Action(type="hold", job_id=lot_id, step=step or None, reason=reason))
    return Schedule(
        policy=book.policy,
        operations=operations,
        unscheduled=unscheduled,
        actions=actions,
        bottleneck_area=book.bottleneck_area,
    )


def _affected(
    before: Plant,
    after: Plant,
    before_book: Schedule,
    after_book: Schedule,
) -> list[dict[str, Any]]:
    before_tool = _first_tool(before_book)
    after_tool = _first_tool(after_book)
    before_held = {item.job_id for item in before_book.unscheduled}
    after_held = {item.job_id for item in after_book.unscheduled}
    rows: list[dict[str, Any]] = []
    for lot_id in sorted(set(before.job_map()) | set(after.job_map())):
        left = before.job_map().get(lot_id)
        right = after.job_map().get(lot_id)
        changes: list[str] = []
        if left is not None and right is not None and left.priority != right.priority:
            changes.append("priority")
        if left is not None and right is not None and left.status != right.status:
            changes.append("status")
        if before_tool.get(lot_id) != after_tool.get(lot_id):
            changes.append("assignment")
        if lot_id in after_held and lot_id not in before_held:
            changes.append("hold")
        if lot_id in before_held and lot_id not in after_held:
            changes.append("release")
        if not changes:
            continue
        rows.append(
            {
                "lot_id": lot_id,
                "changes": changes,
                "before_equipment": before_tool.get(lot_id),
                "after_equipment": after_tool.get(lot_id),
                "before_priority": left.priority if left is not None else None,
                "after_priority": right.priority if right is not None else None,
                "before_status": left.status if left is not None else None,
                "after_status": right.status if right is not None else None,
            }
        )
    return rows


def _first_tool(book: Schedule) -> dict[str, str]:
    found: dict[str, str] = {}
    for op in sorted(
        book.operations, key=lambda item: (item.job_id, item.start_min, item.step_index)
    ):
        found.setdefault(op.job_id, op.equipment_id)
    return found


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    keys = (
        "on_time_delivery_pct",
        "weighted_tardiness_min",
        "makespan_min",
        "utilization_pct",
        "lots_at_risk",
        "setup_changes",
    )
    return {
        key: float(after[key]) - float(before[key])
        for key in keys
        if key in before and key in after
    }
