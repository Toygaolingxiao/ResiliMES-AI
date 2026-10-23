"""Named disruptions the console can run without typing an incident."""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from .models import Job, Plant
from .plant import enrich_availability
from .schedule import POLICY_FROZEN, schedule_plant

LITHO_REPAIR_MIN = 600
RUSH_DUE_MIN = 180
QTIME_TIGHT_MIN = 15
QTIME_TIGHT_RULE = "QT-B14-CLEAN-DEP"


class Scenario(BaseModel):
    id: str
    title: str
    incident: str
    summary: str
    before_label: str
    after_label: str
    kind: str


SCENARIOS: dict[str, Scenario] = {
    "litho_down": Scenario(
        id="litho_down",
        title="Machine breakdown",
        incident=(
            "Machine Litho-02 Down — laser source interlock tripped. "
            "Maintenance revises the repair ETA to 600 minutes."
        ),
        summary=(
            "LITHO-02 is down for 10 hours and priority-1 LOT-1001 is blocked on it, due 18:00 UTC."
        ),
        before_label="Wait for repair",
        after_label="Rescheduled",
        kind="frozen_vs_recover",
    ),
    "rush_order": Scenario(
        id="rush_order",
        title="Rush order",
        incident=(
            "Rush order: accept hot lot LOT-2001, product PROD-A28, priority 1, "
            "25 wafers, due in 3 hours."
        ),
        summary=(
            "A customer wants a hot lot in three hours. The book is re-sequenced "
            "without preempting lots that are already running."
        ),
        before_label="Book without the rush lot",
        after_label="Book with LOT-2001",
        kind="insert_lot",
    ),
    "material_shortage": Scenario(
        id="material_shortage",
        title="Material shortage",
        incident="Material shortage: RESIST-UV photoresist is out of stock.",
        summary=(
            "193nm resist is at zero. Lots that still need lithography cannot start; "
            "lots already running keep their resist."
        ),
        before_label="Resist available",
        after_label="RESIST-UV stockout",
        kind="stockout",
    ),
    "rework": Scenario(
        id="rework",
        title="Overlay rework",
        incident=(
            "Rework: LOT-1004 overlay failed at metrology. "
            "Strip, re-expose, and re-measure once. Rework limit is 1."
        ),
        summary=(
            "Overlay failed on LOT-1004 at measure. Strip the resist, "
            "re-expose once, and measure again."
        ),
        before_label="No rework",
        after_label="Strip, expose, measure",
        kind="rework",
    ),
    "qtime": Scenario(
        id="qtime",
        title="Queue time",
        incident=(
            "Q-time: clean to deposition must start within 15 minutes. "
            "The naive plan starts deposition after the window."
        ),
        summary=(
            "Clean on LOT-1003 finished before the clock. The next film must start within 15 min."
        ),
        before_label="8 h queue time",
        after_label="15 min queue time",
        kind="qtime",
    ),
}


def list_scenarios() -> list[Scenario]:
    return list(SCENARIOS.values())


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        known = ", ".join(SCENARIOS)
        raise KeyError(f"Unknown scenario {scenario_id!r}. Known: {known}") from exc


class ScenarioPlants(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    before: Plant
    after: Plant
    incident: str
    scenario: Scenario | None = None


def plants_for_scenario(base: Plant, scenario_id: str) -> ScenarioPlants:
    scenario = get_scenario(scenario_id)
    if scenario.kind == "frozen_vs_recover":
        disrupted = _litho_down(base)
        return ScenarioPlants(
            before=disrupted,
            after=disrupted.model_copy(deep=True),
            incident=scenario.incident,
            scenario=scenario,
        )
    if scenario.kind == "insert_lot":
        healthy = _restore_litho(base)
        with_lot = _add_rush(healthy)
        return ScenarioPlants(
            before=healthy,
            after=with_lot,
            incident=scenario.incident,
            scenario=scenario,
        )
    if scenario.kind == "stockout":
        healthy = _restore_litho(base)
        short = healthy.model_copy(deep=True)
        for material in short.materials:
            if material.material_id == "RESIST-UV":
                material.on_hand = 0
        return ScenarioPlants(
            before=healthy,
            after=short,
            incident=scenario.incident,
            scenario=scenario,
        )
    if scenario.kind == "rework":
        healthy = _restore_litho(base)
        return ScenarioPlants(
            before=healthy,
            after=_mark_rework(healthy),
            incident=scenario.incident,
            scenario=scenario,
        )
    if scenario.kind == "qtime":
        healthy = _restore_litho(base)
        return ScenarioPlants(
            before=healthy,
            after=_tighten_qtime(healthy),
            incident=scenario.incident,
            scenario=scenario,
        )
    raise KeyError(scenario.kind)


def apply_free_text(
    base: Plant, incident: str, intent_id: str, parameters: dict[str, object]
) -> ScenarioPlants:
    """Turn a classified free-text incident into a before/after pair."""
    if intent_id == "plant.rush_order":
        healthy = (
            _restore_litho(base) if _mentions_only_rush(incident) else base.model_copy(deep=True)
        )
        # A free-text rush keeps the current plant and inserts a lot, so a
        # breakdown mentioned in the same sentence is not silently cleared.
        host = base.model_copy(deep=True)
        if "litho-02" not in incident.lower() and "down" not in incident.lower():
            host = healthy
        with_lot = _add_rush(host)
        return ScenarioPlants(
            before=host,
            after=with_lot,
            incident=incident,
            scenario=None,
        )
    if intent_id == "plant.material_shortage":
        host = base.model_copy(deep=True)
        if "down" not in incident.lower():
            host = _restore_litho(base)
        short = host.model_copy(deep=True)
        material_id = str(parameters.get("material_id") or "RESIST-UV")
        known = {item.material_id for item in short.materials}
        target = material_id if material_id in known else "RESIST-UV"
        for material in short.materials:
            if material.material_id == target:
                material.on_hand = 0
        return ScenarioPlants(before=host, after=short, incident=incident, scenario=None)
    if intent_id == "plant.rework":
        host = base.model_copy(deep=True)
        if "down" not in incident.lower():
            host = _restore_litho(base)
        return ScenarioPlants(
            before=host,
            after=_mark_rework(host),
            incident=incident,
            scenario=None,
        )
    if intent_id == "plant.qtime":
        host = base.model_copy(deep=True)
        if "down" not in incident.lower():
            host = _restore_litho(base)
        return ScenarioPlants(
            before=host,
            after=_tighten_qtime(host),
            incident=incident,
            scenario=None,
        )
    return _machine_down(base, incident, parameters)


def _mentions_only_rush(incident: str) -> bool:
    text = incident.lower()
    return "down" not in text and "fault" not in text


def _litho_down(base: Plant) -> Plant:
    plant = base.model_copy(deep=True)
    for equipment in plant.equipment:
        if equipment.equipment_id == "LITHO-02":
            equipment.status = "DOWN"
            equipment.fault_code = "LASER_FAULT"
            equipment.repair_min = LITHO_REPAIR_MIN
            equipment.eta_from_horizon = True
    for job in plant.jobs:
        if job.job_id == "LOT-1001":
            job.status = "BLOCKED"
            job.assigned_equipment = "LITHO-02"
            job.current_step = "LITHO"
    return enrich_availability(plant)


def _restore_litho(base: Plant) -> Plant:
    plant = base.model_copy(deep=True)
    for equipment in plant.equipment:
        if equipment.equipment_id == "LITHO-02":
            equipment.status = "IDLE"
            equipment.fault_code = None
            equipment.down_since = None
            equipment.repair_min = None
            equipment.eta_from_horizon = False
    for job in plant.jobs:
        if job.job_id == "LOT-1001":
            job.status = "QUEUED"
            job.assigned_equipment = None
            job.current_step = "QUEUED"
            job.started_at = None
            job.preferred_equipment = ["LITHO-01", "LITHO-02"]
    return enrich_availability(plant)


def _add_rush(plant: Plant) -> Plant:
    copied = plant.model_copy(deep=True)
    due = copied.horizon + timedelta(minutes=RUSH_DUE_MIN)
    copied.jobs.append(
        Job(
            job_id="LOT-2001",
            product_id="PROD-A28",
            priority=1,
            qty=25,
            current_step="QUEUED",
            assigned_equipment=None,
            status="QUEUED",
            due_at=due,
            started_at=None,
            process_time_min=90,
            remaining_steps=["DEP", "LITHO", "MEAS", "ETCH", "CLEAN", "CMP"],
            preferred_equipment=["LITHO-01", "LITHO-02"],
            released_through="CMP",
        )
    )
    return copied


def _mark_rework(plant: Plant) -> Plant:
    copied = plant.model_copy(deep=True)
    for job in copied.jobs:
        if job.job_id == "LOT-1004":
            job.rework_of = "MEAS"
            job.rework_count = 0
            job.rework_limit = 1
    return copied


def _tighten_qtime(plant: Plant) -> Plant:
    """Close the clean-to-film window that LOT-1003 already missed."""
    copied = plant.model_copy(deep=True)
    for rule in copied.qtime_rules:
        if rule.rule_id == QTIME_TIGHT_RULE:
            rule.max_min = QTIME_TIGHT_MIN
    return copied


def _machine_down(base: Plant, incident: str, parameters: dict[str, object]) -> ScenarioPlants:
    """A named tool-down is that tool's story.

    The sample fab is already a lithography fault. A sentence that names
    another tool starts from a lithography bay that is up, then puts the
    named tool down for the stated repair. The before book waits on the
    lots a healthy book had placed there. The after book may move them.
    """
    equipment_id = str(parameters.get("equipment_id") or "")
    known = {item.equipment_id for item in base.equipment}
    if equipment_id not in known:
        equipment_id = "LITHO-02"
    if equipment_id == "LITHO-02":
        disrupted = _litho_down(base)
        repair = parameters.get("repair_min")
        if isinstance(repair, (int, float)):
            for equipment in disrupted.equipment:
                if equipment.equipment_id == "LITHO-02":
                    equipment.repair_min = int(repair)
                    equipment.eta_from_horizon = True
            disrupted = enrich_availability(disrupted)
        return ScenarioPlants(
            before=disrupted,
            after=disrupted.model_copy(deep=True),
            incident=incident,
            scenario=None,
        )
    host = _restore_litho(base)
    healthy = schedule_plant(host, POLICY_FROZEN)
    stick = [
        f"{op.job_id}:{op.step}:{op.equipment_id}"
        for op in healthy.operations
        if op.equipment_id == equipment_id
    ]
    bound = dict(parameters)
    bound["equipment_id"] = equipment_id
    disrupted = _apply_down(host, bound)
    before = disrupted.model_copy(deep=True)
    before.frozen_stick = stick
    after = disrupted.model_copy(deep=True)
    after.frozen_stick = []
    return ScenarioPlants(before=before, after=after, incident=incident, scenario=None)


def _apply_down(base: Plant, parameters: dict[str, object]) -> Plant:
    plant = base.model_copy(deep=True)
    equipment_id = str(parameters.get("equipment_id") or "LITHO-02")
    repair = parameters.get("repair_min")
    repair_min = int(repair) if isinstance(repair, (int, float)) else LITHO_REPAIR_MIN
    known = {item.equipment_id for item in plant.equipment}
    if equipment_id not in known:
        equipment_id = "LITHO-02"
    for equipment in plant.equipment:
        if equipment.equipment_id == equipment_id:
            equipment.status = "DOWN"
            equipment.fault_code = str(parameters.get("fault_code") or "UNPLANNED_DOWN")
            equipment.repair_min = repair_min
            equipment.eta_from_horizon = True
    for job in plant.jobs:
        if job.assigned_equipment == equipment_id and job.status == "RUNNING":
            job.status = "BLOCKED"
    return enrich_availability(plant)
