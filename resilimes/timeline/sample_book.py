"""Timeline book from the sample plant. Read-only: the frozen book is not a reschedule."""

from __future__ import annotations

from typing import cast

from resilimes.config import Settings
from resilimes.data.factory import build_source
from resilimes.domain.kpis import completion_of, qtime_report
from resilimes.domain.models import Plant
from resilimes.domain.plant import minutes_between
from resilimes.domain.schedule import POLICY_FROZEN, schedule_plant
from resilimes.timeline.model import Bar, Block, Book, LotInfo, Machine


def load_sample_book(settings: Settings) -> Book:
    plant, _records = build_source(settings).load_plant(settings.horizon)
    schedule = schedule_plant(plant, POLICY_FROZEN)
    jobs = plant.job_map()
    products = plant.product_map()
    equipment = plant.equipment_map()
    qtime = _qtime_flags(plant, schedule)
    lots: list[LotInfo] = []
    for job in plant.jobs:
        due = float(minutes_between(plant.horizon, job.due_at))
        finished = completion_of(schedule, job.job_id)
        lots.append(
            LotInfo(
                id=job.job_id,
                product=job.product_id,
                priority=job.priority,
                due_min=due,
                late=finished is None or finished > due,
                qty=job.qty,
            )
        )
    lot_by_id = {item.id: item for item in lots}
    bars: list[Bar] = []
    for op in schedule.operations:
        lot = lot_by_id[op.job_id]
        recipe = ""
        product = products.get(op.product_id)
        if product is not None:
            for step in product.route:
                if step.step == op.step:
                    recipe = step.recipe or step.setup_family
                    break
        tool = equipment.get(op.equipment_id)
        bars.append(
            Bar(
                id=f"{op.job_id}|{op.step}|{op.start_min}|{op.equipment_id}",
                lot=op.job_id,
                product=op.product_id,
                machine=op.equipment_id,
                group=tool.area if tool is not None else "",
                step=op.step,
                recipe=recipe,
                start_min=float(op.start_min),
                end_min=float(op.end_min),
                setup_min=float(op.setup_min),
                priority=op.priority,
                due_min=lot.due_min,
                late=lot.late,
                qtime=qtime.get((op.job_id, op.step), ""),
                rework=op.rework,
                pinned=op.pinned,
                qty=jobs[op.job_id].qty,
            )
        )
    blocks: list[Block] = []
    machines: list[Machine] = []
    for tool in plant.equipment:
        machines.append(
            Machine(
                id=tool.equipment_id,
                name=tool.name,
                group=tool.area,
                family=", ".join(tool.capability),
            )
        )
        if tool.available_at_min > 0 and tool.status in {"DOWN", "MAINTENANCE"}:
            blocks.append(
                Block(
                    machine=tool.equipment_id,
                    kind="pm" if tool.status == "MAINTENANCE" else "down",
                    start_min=0.0,
                    end_min=float(tool.available_at_min),
                )
            )
    end = max([bar.end_min for bar in bars] + [block.end_min for block in blocks] + [60.0])
    return Book(
        source="sample",
        seed=1,
        horizon_h=round(end / 60.0, 2),
        origin=plant.horizon.isoformat().replace("+00:00", "Z"),
        horizon_min=end,
        shift_min=8 * 60.0,
        machines=machines,
        lots=lots,
        bars=bars,
        blocks=blocks,
        skips=0,
        lot_index=lot_by_id,
    )


def _qtime_flags(plant: Plant, schedule: object) -> dict[tuple[str, str], str]:
    from resilimes.domain.models import Schedule

    if not isinstance(schedule, Schedule):
        return {}
    report = qtime_report(plant, schedule)
    rows = cast(list[object], report.get("rows", []))
    flags: dict[tuple[str, str], str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = str(row.get("state", ""))
        if state == "violation":
            flag = "breach"
        elif state == "risk":
            flag = "risk"
        else:
            flag = ""
        if flag:
            flags[(str(row.get("job_id", "")), str(row.get("to_step", "")))] = flag
    return flags
