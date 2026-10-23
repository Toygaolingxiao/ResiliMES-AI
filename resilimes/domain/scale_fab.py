"""Deterministic synthetic fab. The hero bay stays the sample plant.

One seed builds the same tools, routes, lots, reticles, inhibits, and
queue-time rules every time. A smaller ``lots`` count is the CI smoke.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from .models import (
    Equipment,
    Inhibit,
    Job,
    MaintenanceEvent,
    MaterialNeed,
    MaterialStock,
    Operator,
    Plant,
    Product,
    QTimeRule,
    Reticle,
    RouteStep,
)
from .plant import enrich_availability

SCALE_SEED = 20261022
SCALE_LOTS = 1000
SCALE_DOWN_TOOL = "LITHO-03"
SCALE_REPAIR_MIN = 600
SCALE_AREAS = ("Deposition", "Lithography", "Metrology", "Etch", "Clean", "CMP")

_LAYER = (
    ("DEP", "cvd_oxide", 28, "CVD_OX", "Deposition", "Deposition"),
    ("LITHO", "litho_193nm", 75, "LITHO", "Lithography", "Lithography"),
    ("MEAS", "overlay_cd", 20, "OCD", "Metrology", "Metrology"),
    ("ETCH", "etch_dielectric", 40, "ETCH_D", "Etch", "Etch"),
    ("CLEAN", "wet_clean", 16, "WET", "Clean", "Clean"),
    ("CMP", "cmp_oxide", 32, "CMP_OX", "CMP", "CMP"),
)


def build_scale_plant(
    horizon: datetime,
    *,
    lots: int = SCALE_LOTS,
    seed: int = SCALE_SEED,
) -> Plant:
    """Fab-scale plant with one scanner already down.

    ``lots`` defaults to 1000. Tools stay at the full fleet either way, so a
    smoke run still schedules every area.
    """
    if lots < 8:
        raise ValueError("scale fab needs at least 8 lots")
    rng = random.Random(seed)
    equipment = _equipment()
    products = _products()
    by_id = {item.product_id: item for item in products}
    jobs = _jobs(horizon, products, rng, lots)
    plant = Plant(
        plant_id="FAB-SCALE",
        horizon=horizon,
        operator_pool=len(equipment),
        equipment=equipment,
        jobs=jobs,
        products=products,
        materials=[
            MaterialStock(
                material_id="RESIST-UV", name="193nm photoresist", on_hand=4000, unit="L"
            ),
            MaterialStock(material_id="WAFER-300", name="300mm wafer", on_hand=40000, unit="wafer"),
            MaterialStock(material_id="GAS-CF4", name="CF4 etch gas", on_hand=20000, unit="L"),
            MaterialStock(material_id="SLURRY-OX", name="Oxide slurry", on_hand=8000, unit="L"),
        ],
        operators=_operators(equipment),
        maintenance=[
            MaintenanceEvent(
                log_id="M-SCALE-03",
                equipment_id=SCALE_DOWN_TOOL,
                event_type="FAULT",
                occurred_at="2026-10-22T06:12:00Z",
                severity_code="LASER_FAULT",
                description=(
                    "Machine Litho-03 Down — laser source interlock tripped. "
                    "Repair ETA 600 minutes."
                ),
                estimated_repair_min=SCALE_REPAIR_MIN,
                technician="tech.nguyen",
            )
        ],
        qtime_rules=_qtime_rules(products),
        reticles=_reticles(products),
        inhibits=[
            Inhibit(
                inhibit_id="INH-F20-LITHO01",
                equipment_id="LITHO-01",
                product_id="PROD-F20",
                recipe="LITHO_L1",
            ),
            Inhibit(
                inhibit_id="INH-S04-LITHO02",
                equipment_id="LITHO-02",
                product_id="PROD-S04",
                recipe="LITHO_S",
            ),
        ],
        source="scale",
    )
    _pin_down_scanner(plant, by_id, lots)
    return enrich_availability(plant)


def _equipment() -> list[Equipment]:
    specs = (
        ("DEP", 6, "Deposition", ["cvd_oxide"], 18, "CVD"),
        ("LITHO", 8, "Lithography", ["litho_193nm"], 20, "Scanner"),
        ("MEAS", 4, "Metrology", ["overlay_cd"], 8, "Metrology"),
        ("ETCH", 6, "Etch", ["etch_dielectric"], 15, "Etcher"),
        ("ETCH", 2, "Etch", ["etch_dielectric", "etch_metal"], 15, "Etcher"),
        ("WET", 4, "Clean", ["wet_clean"], 10, "Wet bench"),
        ("CMP", 6, "CMP", ["cmp_oxide"], 12, "Polisher"),
    )
    rows: list[Equipment] = []
    etch_index = 0
    for prefix, count, area, capability, setup, label in specs:
        for offset in range(count):
            if prefix == "ETCH":
                etch_index += 1
                number = etch_index
            else:
                number = offset + 1
            equipment_id = f"{prefix}-{number:02d}"
            down = equipment_id == SCALE_DOWN_TOOL
            rows.append(
                Equipment(
                    equipment_id=equipment_id,
                    name=f"{label} {number:02d}",
                    area=area,
                    status="DOWN" if down else "IDLE",
                    capability=list(capability),
                    setup_time_min=setup,
                    operators_required=1,
                    max_wip=1,
                    mtbf_hours=160,
                    last_pm_at="2026-10-20T08:00:00Z",
                    fault_code="LASER_FAULT" if down else None,
                    down_since="2026-10-22T06:12:00Z" if down else None,
                    repair_min=SCALE_REPAIR_MIN if down else None,
                    eta_from_horizon=down,
                )
            )
    return rows


def _products() -> list[Product]:
    products: list[Product] = []
    for index in range(1, 21):
        product_id = f"PROD-F{index:02d}"
        products.append(
            Product(
                product_id=product_id,
                name=f"Logic {index:02d}",
                route_id=f"RT-F{index:02d}",
                route=_loop(product_id),
                materials=[
                    MaterialNeed(material_id="WAFER-300", qty_per_lot=25),
                    MaterialNeed(material_id="RESIST-UV", qty_per_lot=1),
                    MaterialNeed(material_id="GAS-CF4", qty_per_lot=2),
                    MaterialNeed(material_id="SLURRY-OX", qty_per_lot=1),
                ],
            )
        )
    for index in range(1, 7):
        product_id = f"PROD-D{index:02d}"
        products.append(
            Product(
                product_id=product_id,
                name=f"Film cap {index:02d}",
                route_id=f"RT-D{index:02d}",
                route=_cap(product_id, metal=False),
                materials=[
                    MaterialNeed(material_id="WAFER-300", qty_per_lot=25),
                    MaterialNeed(material_id="GAS-CF4", qty_per_lot=2),
                ],
            )
        )
    for index in range(1, 3):
        product_id = f"PROD-M{index:02d}"
        products.append(
            Product(
                product_id=product_id,
                name=f"Metal cap {index:02d}",
                route_id=f"RT-M{index:02d}",
                route=_cap(product_id, metal=True),
                materials=[
                    MaterialNeed(material_id="WAFER-300", qty_per_lot=25),
                    MaterialNeed(material_id="GAS-CF4", qty_per_lot=3),
                ],
            )
        )
    for index in range(1, 5):
        product_id = f"PROD-S{index:02d}"
        products.append(
            Product(
                product_id=product_id,
                name=f"Short flow {index:02d}",
                route_id=f"RT-S{index:02d}",
                route=_short(product_id),
                materials=[
                    MaterialNeed(material_id="WAFER-300", qty_per_lot=25),
                    MaterialNeed(material_id="RESIST-UV", qty_per_lot=1),
                ],
            )
        )
    return products


def _loop(product_id: str) -> list[RouteStep]:
    steps: list[RouteStep] = []
    for layer, suffix in (("L1", ""), ("L2", "-L2")):
        for name, capability, minutes, recipe, area, operation in _LAYER:
            if name == "LITHO":
                step_name = "LITHO" if layer == "L1" else "LITHO-L2"
                recipe_name = f"{recipe}_{layer}"
            else:
                step_name = f"{name}{suffix}"
                recipe_name = recipe
            steps.append(
                _step(
                    product_id,
                    step_name,
                    capability,
                    minutes,
                    recipe_name,
                    area,
                    operation,
                    layer,
                    len(steps) + 1,
                )
            )
    return steps


def _cap(product_id: str, *, metal: bool) -> list[RouteStep]:
    etch_capability = "etch_metal" if metal else "etch_dielectric"
    etch_recipe = "ETCH_M" if metal else "ETCH_D"
    rows = (
        ("DEP", "cvd_oxide", 20, "CVD_OX", "Deposition", "Deposition"),
        ("ETCH", etch_capability, 30, etch_recipe, "Etch", "Etch"),
        ("CLEAN", "wet_clean", 12, "WET", "Clean", "Clean"),
        ("DEP-2", "cvd_oxide", 20, "CVD_OX", "Deposition", "Deposition"),
    )
    return [
        _step(product_id, name, capability, minutes, recipe, area, operation, "L1", index + 1)
        for index, (name, capability, minutes, recipe, area, operation) in enumerate(rows)
    ]


def _short(product_id: str) -> list[RouteStep]:
    rows = (
        ("LITHO", "litho_193nm", 40, "LITHO_S", "Lithography", "Lithography"),
        ("ETCH", "etch_dielectric", 24, "ETCH_D", "Etch", "Etch"),
        ("CMP", "cmp_oxide", 45, "CMP_OX", "CMP", "CMP"),
    )
    return [
        _step(product_id, name, capability, minutes, recipe, area, operation, "L1", index + 1)
        for index, (name, capability, minutes, recipe, area, operation) in enumerate(rows)
    ]


def _step(
    product_id: str,
    name: str,
    capability: str,
    minutes: int,
    recipe: str,
    area: str,
    operation: str,
    layer: str,
    step_no: int,
) -> RouteStep:
    return RouteStep(
        step=name,
        capability=capability,
        process_time_min=minutes,
        setup_family=recipe,
        step_no=step_no,
        operation=operation,
        area=area,
        recipe=recipe,
        layer=layer,
    )


def _jobs(
    horizon: datetime,
    products: list[Product],
    rng: random.Random,
    lots: int,
) -> list[Job]:
    weights = _mix(products, lots)
    jobs: list[Job] = []
    for index, product in enumerate(weights, start=1):
        route = product.route
        litho_at = [step for step in route if step.capability == "litho_193nm"]
        if litho_at and rng.random() < 0.22:
            current = rng.choice(litho_at)
        else:
            current = route[rng.randrange(len(route))]
        released = _release_through(route, current)
        priority = _priority(rng)
        remaining = _remaining_minutes(route, current, released)
        # Two weeks of slack. The scanner fault is the lateness in this book.
        slack = 14 * 24 * 60
        jobs.append(
            Job(
                job_id=f"SL-{index:04d}",
                product_id=product.product_id,
                priority=priority,
                qty=25,
                current_step=current.step,
                assigned_equipment=None,
                status="QUEUED",
                due_at=horizon + timedelta(minutes=remaining + slack),
                started_at=None,
                process_time_min=current.process_time_min,
                remaining_steps=[
                    step.step for step in route[route.index(current) : route.index(released) + 1]
                ],
                preferred_equipment=[],
                released_through=released.step,
                release_min=0,
            )
        )
    _mark_running(jobs, products, horizon)
    return jobs


def _mix(products: list[Product], lots: int) -> list[Product]:
    """700 logic, 180 dielectric cap, 40 metal, 80 short, scaled to ``lots``."""
    full = [item for item in products if item.product_id.startswith("PROD-F")]
    dielectric = [item for item in products if item.product_id.startswith("PROD-D")]
    metal = [item for item in products if item.product_id.startswith("PROD-M")]
    short = [item for item in products if item.product_id.startswith("PROD-S")]
    plan = (
        (full, 700),
        (dielectric, 180),
        (metal, 40),
        (short, 80),
    )
    chosen: list[Product] = []
    for group, count in plan:
        share = max(len(group), round(lots * count / SCALE_LOTS))
        for index in range(share):
            chosen.append(group[index % len(group)])
    return chosen[:lots]


def _release_through(route: list[RouteStep], current: RouteStep) -> RouteStep:
    """Today's release stops at the end of the current layer.

    Clean-to-film rules still sit on the product for the next layer. They arm
    when a lot is released through that film.
    """
    layer_steps = [step for step in route if step.layer == current.layer]
    return layer_steps[-1]


def _after(route: list[RouteStep], current: RouteStep, step: RouteStep) -> bool:
    return route.index(step) > route.index(current)


def _remaining_minutes(route: list[RouteStep], current: RouteStep, released: RouteStep) -> int:
    start = route.index(current)
    end = route.index(released)
    return sum(step.process_time_min for step in route[start : end + 1])


def _priority(rng: random.Random) -> int:
    roll = rng.random()
    if roll < 0.08:
        return 1
    if roll < 0.28:
        return 2
    if roll < 0.72:
        return 3
    return 4


def _mark_running(jobs: list[Job], products: list[Product], horizon: datetime) -> None:
    """One running lot per up tool, so pinned work does not stack at t=0."""
    by_id = {item.product_id: item for item in products}
    used: set[str] = set()
    for job in jobs:
        route = by_id[job.product_id].route
        step = next(item for item in route if item.step == job.current_step)
        if step.capability == "litho_193nm":
            continue
        tool = _tool_for(step.capability, used)
        if tool is None or tool == SCALE_DOWN_TOOL:
            continue
        if len(used) >= 18:
            break
        elapsed = max(1, step.process_time_min // 5)
        job.status = "RUNNING"
        job.assigned_equipment = tool
        job.started_at = horizon - timedelta(minutes=elapsed)
        used.add(tool)


def _tool_for(capability: str, used: set[str]) -> str | None:
    for equipment in _equipment():
        if equipment.equipment_id in used or equipment.equipment_id == SCALE_DOWN_TOOL:
            continue
        if capability in equipment.capability:
            return equipment.equipment_id
    return None


def _pin_down_scanner(plant: Plant, products: dict[str, Product], lots: int) -> None:
    """Park one lot per product on the down scanner.

    Each product has its own reticle, so the up scanners can run those lots
    together. Waiting for the repair queues them on one tool. Slack is shorter
    than the repair and longer than one pass across the up scanners.
    """
    per_product = 1
    cap = 24 if lots >= 200 else max(4, lots // 10)
    grouped: dict[str, list[Job]] = {}
    for job in plant.jobs:
        if job.status == "RUNNING" or not _on_litho(job, products):
            continue
        grouped.setdefault(job.product_id, []).append(job)
    pinned: list[Job] = []
    for product_id in sorted(grouped):
        grouped[product_id].sort(key=lambda job: job.job_id)
        pinned.extend(grouped[product_id][:per_product])
        if len(pinned) >= cap:
            pinned = pinned[:cap]
            break
    pinned_ids = {job.job_id for job in pinned}
    products_hit = {job.product_id for job in pinned}
    for job in plant.jobs:
        if (
            job.product_id in products_hit
            and job.job_id not in pinned_ids
            and _on_litho(job, products)
        ):
            job.priority = 4
    for job in pinned:
        job.status = "BLOCKED"
        job.assigned_equipment = SCALE_DOWN_TOOL
        job.preferred_equipment = [SCALE_DOWN_TOOL]
        job.priority = 1
        route = products[job.product_id].route
        current = next(step for step in route if step.step == job.current_step)
        released = next(step for step in route if step.step == job.released_through)
        remaining = _remaining_minutes(route, current, released)
        job.due_at = plant.horizon + timedelta(minutes=remaining + 360)


def _on_litho(job: Job, products: dict[str, Product]) -> bool:
    route = products[job.product_id].route
    current = next((step for step in route if step.step == job.current_step), None)
    return current is not None and current.capability == "litho_193nm"


def _qtime_rules(products: list[Product]) -> list[QTimeRule]:
    rules: list[QTimeRule] = []
    for product in products:
        names = {step.step for step in product.route}
        if "CLEAN" in names and "DEP-L2" in names:
            rules.append(
                QTimeRule(
                    rule_id=f"QT-{product.product_id}-CLEAN-DEP",
                    product_id=product.product_id,
                    from_step="CLEAN",
                    to_step="DEP-L2",
                    max_min=480,
                )
            )
        if "CLEAN" in names and "DEP-2" in names:
            rules.append(
                QTimeRule(
                    rule_id=f"QT-{product.product_id}-CLEAN-DEP",
                    product_id=product.product_id,
                    from_step="CLEAN",
                    to_step="DEP-2",
                    max_min=480,
                )
            )
    return rules


def _reticles(products: list[Product]) -> list[Reticle]:
    rows: list[Reticle] = []
    for product in products:
        for step in product.route:
            if step.capability != "litho_193nm":
                continue
            layer = step.layer or "L1"
            rows.append(
                Reticle(
                    reticle_id=f"RET-{product.product_id}-{layer}",
                    product_id=product.product_id,
                    layer=layer,
                    step=step.step,
                )
            )
    return rows


def _operators(equipment: list[Equipment]) -> list[Operator]:
    return [
        Operator(
            operator_id=f"OP-{index:02d}",
            name=f"Operator {index:02d}",
            certified=list(tool.capability),
            shift="A" if index % 2 == 0 else "B",
        )
        for index, tool in enumerate(equipment, start=1)
    ]
