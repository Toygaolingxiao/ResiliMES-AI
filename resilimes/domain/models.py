"""Typed factory objects shared by the scheduler, agents, and API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MaterialNeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    material_id: str
    qty_per_lot: int


class RouteStep(BaseModel):
    """One operation on a product route. The same area can return on a later layer."""

    model_config = ConfigDict(extra="ignore")

    step: str
    capability: str
    process_time_min: int
    setup_family: str
    step_no: int = 0
    operation: str = ""
    area: str = ""
    recipe: str = ""
    layer: str = ""
    rework: bool = False


class QTimeRule(BaseModel):
    """Queue time from the end of one step to the start of a later step."""

    model_config = ConfigDict(extra="ignore")

    rule_id: str
    product_id: str
    from_step: str
    to_step: str
    max_min: int


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_id: str
    name: str
    route: list[RouteStep]
    route_id: str = ""
    materials: list[MaterialNeed] = Field(default_factory=list)


class MaterialStock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    material_id: str
    name: str
    on_hand: int
    unit: str


class Operator(BaseModel):
    model_config = ConfigDict(extra="ignore")

    operator_id: str
    name: str
    certified: list[str] = Field(default_factory=list)
    shift: str = "A"


class MaintenanceEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    log_id: str
    equipment_id: str
    event_type: str
    occurred_at: str
    severity_code: str
    description: str
    estimated_repair_min: int = 0
    technician: str = ""


class Equipment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    equipment_id: str
    name: str
    area: str
    status: str
    capability: list[str]
    setup_time_min: int = 0
    operators_required: int = 1
    max_wip: int = 1
    mtbf_hours: float | None = None
    last_pm_at: str | None = None
    fault_code: str | None = None
    down_since: str | None = None
    repair_min: int | None = None
    eta_from_horizon: bool = False
    available_at_min: int = 0


class Job(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    product_id: str
    priority: int
    qty: int
    current_step: str
    assigned_equipment: str | None = None
    status: str
    due_at: datetime
    started_at: datetime | None = None
    process_time_min: int
    remaining_steps: list[str] = Field(default_factory=list)
    preferred_equipment: list[str] = Field(default_factory=list)
    released_through: str | None = None
    rework_of: str | None = None
    rework_count: int = 0
    rework_limit: int = 1


class Plant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    plant_id: str
    horizon: datetime
    operator_pool: int = 4
    equipment: list[Equipment]
    jobs: list[Job]
    products: list[Product]
    materials: list[MaterialStock] = Field(default_factory=list)
    operators: list[Operator] = Field(default_factory=list)
    maintenance: list[MaintenanceEvent] = Field(default_factory=list)
    qtime_rules: list[QTimeRule] = Field(default_factory=list)
    source: str = "sample"

    def equipment_map(self) -> dict[str, Equipment]:
        return {item.equipment_id: item for item in self.equipment}

    def job_map(self) -> dict[str, Job]:
        return {item.job_id: item for item in self.jobs}

    def product_map(self) -> dict[str, Product]:
        return {item.product_id: item for item in self.products}

    def material_map(self) -> dict[str, MaterialStock]:
        return {item.material_id: item for item in self.materials}


class StepWork(BaseModel):
    """One remaining route step expanded for the scheduler."""

    job_id: str
    product_id: str
    priority: int
    due_min: int
    step: str
    step_index: int
    capability: str
    setup_family: str
    process_min: int
    ready_at: int = 0
    in_progress: bool = False
    assigned_equipment: str | None = None
    preferred_equipment: list[str] = Field(default_factory=list)
    is_first: bool = False
    consumes_material: bool = False
    area: str = ""
    feeds: str = ""
    rework: bool = False
    qtime_from: str = ""
    qtime_anchor: int | None = None
    qtime_latest: int | None = None


class ScheduledOp(BaseModel):
    job_id: str
    product_id: str
    step: str
    step_index: int
    equipment_id: str
    start_min: int
    end_min: int
    setup_min: int
    process_min: int
    setup_family: str
    priority: int
    pinned: bool = False
    rework: bool = False


class Unscheduled(BaseModel):
    job_id: str
    step: str
    reason: str


class Action(BaseModel):
    type: str
    job_id: str
    step: str | None = None
    from_equipment: str | None = None
    to_equipment: str | None = None
    start_min: int | None = None
    end_min: int | None = None
    reason: str
    evidence: list[str] = Field(default_factory=list)
    anchor_end_min: int | None = None


class Schedule(BaseModel):
    policy: str
    operations: list[ScheduledOp] = Field(default_factory=list)
    unscheduled: list[Unscheduled] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    bottleneck_area: str = ""


class KpiReport(BaseModel):
    on_time_delivery_pct: float
    weighted_tardiness_min: float
    makespan_min: int
    utilization_pct: float
    lots_at_risk: int
    setup_changes: int
    mean_remaining_flow_min: float
    late_lots: list[str]
    unscheduled_lots: list[str]


class JobOutcome(BaseModel):
    job_id: str
    product_id: str
    priority: int
    due_min: int
    before_completion_min: int | None
    after_completion_min: int | None
    before_tardiness_min: int
    after_tardiness_min: int
    before_equipment: str | None = None
    after_equipment: str | None = None
    moved_step: str | None = None
    moved_from: str | None = None
    moved_to: str | None = None


class Violation(BaseModel):
    constraint: str
    severity: str
    detail: str
    fix_hint: str


class Critique(BaseModel):
    verdict: str
    score: float
    violations: list[Violation] = Field(default_factory=list)
    rationale: str
    confidence: float = 0.9
    source: str = "deterministic"


def priority_weight(priority: int) -> int:
    return {1: 8, 2: 4, 3: 2, 4: 1}.get(priority, 1)
