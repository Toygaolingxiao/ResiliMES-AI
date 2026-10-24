"""Floor signals the console can show before the weighted dispatcher exists.

Queues and tool state come from the current book. Dispatch scores stay unset
until that dispatcher fills them. A WIP step warns only when a caller passes
a real limit. This module does not invent one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from resilimes.domain.models import Plant, Schedule, ScheduledOp

TriggerKind = Literal["breakdown", "hot_lot", "wip_threshold"]
QueueKind = Literal["litho", "furnace"]
BoardState = Literal["idle", "run", "down", "setup", "pm"]
LotRole = Literal["running", "next", "queued", "blocked"]

_LITHO_AREAS = {"lithography", "photo", "photolithography"}
_FURNACE_AREAS = {"furnace", "diffusion"}


class DispatchScore(BaseModel):
    """One dispatch decision. None means the weighted scorer has not run."""

    cr: float | None = None
    slack_min: float | None = None
    setup_cost_min: float | None = None
    qtime_risk: float | None = None


class QueueLot(BaseModel):
    lot: str
    step: str
    tool: str
    start_min: int
    end_min: int
    role: LotRole


class ToolQueue(BaseModel):
    tool: str
    area: str
    kind: QueueKind
    state: BoardState
    available_at_min: int
    running: QueueLot | None = None
    next: QueueLot | None = None
    queued: list[QueueLot] = Field(default_factory=list)
    blocked: QueueLot | None = None
    score: DispatchScore = Field(default_factory=DispatchScore)


class WipStep(BaseModel):
    step: str
    lots: int
    lot_ids: list[str]
    threshold: int | None = None
    warning: bool = False


class ReplanTrigger(BaseModel):
    kind: TriggerKind | None = None
    scenario_id: str = ""


def queue_kind(area: str, capability: list[str]) -> QueueKind | None:
    """Lithography and furnace bays are the queues the floor shows."""
    name = area.strip().lower()
    tokens = [item.lower() for item in capability]
    if name in _FURNACE_AREAS or any("furnace" in item or "diffusion" in item for item in tokens):
        return "furnace"
    if name in _LITHO_AREAS or any("litho" in item for item in tokens):
        return "litho"
    return None


def board_state(status: str, bars: list[dict[str, object]], now: int = 0) -> BoardState:
    """Map a tool and the bar under the shift clock to Idle, Run, Down, Setup, or PM."""
    key = status.upper()
    if key == "DOWN":
        return "down"
    if key == "MAINTENANCE":
        return "pm"
    if key == "SETUP":
        return "setup"
    for bar in bars:
        if bar.get("held"):
            continue
        start = _as_int(bar.get("start_min"))
        end = _as_int(bar.get("end_min"))
        setup = _as_int(bar.get("setup_min"))
        if setup > 0 and start <= now < start + setup:
            return "setup"
        if start <= now < end:
            return "run"
    if key == "RUNNING":
        return "run"
    return "idle"


def tool_queues(plant: Plant, schedule: Schedule) -> list[ToolQueue]:
    """Lots on litho and furnace tools. Other areas stay off this strip."""
    by_tool: dict[str, list[ScheduledOp]] = {}
    for op in schedule.operations:
        by_tool.setdefault(op.equipment_id, []).append(op)
    queues: list[ToolQueue] = []
    for equipment in plant.equipment:
        kind = queue_kind(equipment.area, list(equipment.capability))
        if kind is None:
            continue
        ops = sorted(
            by_tool.get(equipment.equipment_id, []), key=lambda op: (op.start_min, op.job_id)
        )
        bars = [_op_bar(op) for op in ops]
        state = board_state(equipment.status, bars)
        current = next((op for op in ops if op.start_min <= 0 < op.end_min), None)
        future = [op for op in ops if op.start_min > 0]
        if current is None and not future and state not in {"down", "pm"}:
            continue
        blocked = (
            _lot(current, "blocked") if current is not None and state in {"down", "pm"} else None
        )
        running = _lot(current, "running") if current is not None and blocked is None else None
        nxt = _lot(future[0], "next") if future else None
        waiting = [_lot(op, "queued") for op in future[1:]]
        queues.append(
            ToolQueue(
                tool=equipment.equipment_id,
                area=equipment.area,
                kind=kind,
                state=state,
                available_at_min=equipment.available_at_min,
                running=running,
                next=nxt,
                queued=waiting,
                blocked=blocked,
                score=DispatchScore(),
            )
        )
    queues.sort(key=lambda item: (0 if item.kind == "litho" else 1, item.tool))
    return queues


def wip_steps(plant: Plant, limits: dict[str, int] | None = None) -> list[WipStep]:
    """Lots at each current step. ``limits`` is the only way a step becomes a warning."""
    caps = limits or {}
    order: list[str] = []
    for product in plant.products:
        for route_step in product.route:
            if route_step.step not in order:
                order.append(route_step.step)
    grouped: dict[str, list[str]] = {}
    for job in plant.jobs:
        grouped.setdefault(job.current_step, []).append(job.job_id)
        if job.current_step not in order:
            order.append(job.current_step)
    rows: list[WipStep] = []
    for name in order:
        lots = grouped.get(name, [])
        if not lots:
            continue
        threshold = caps.get(name)
        rows.append(
            WipStep(
                step=name,
                lots=len(lots),
                lot_ids=lots,
                threshold=threshold,
                warning=threshold is not None and len(lots) >= threshold,
            )
        )
    return rows


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _op_bar(op: ScheduledOp) -> dict[str, object]:
    return {
        "start_min": op.start_min,
        "end_min": op.end_min,
        "setup_min": op.setup_min,
        "held": False,
    }


def _lot(op: ScheduledOp | None, role: LotRole) -> QueueLot | None:
    if op is None:
        return None
    return QueueLot(
        lot=op.job_id,
        step=op.step,
        tool=op.equipment_id,
        start_min=op.start_min,
        end_min=op.end_min,
        role=role,
    )
