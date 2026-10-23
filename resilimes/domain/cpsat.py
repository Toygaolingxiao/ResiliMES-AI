"""Optional CP-SAT reference for the list scheduler.

The committed book stays the heuristic in ``schedule.py``. This module scores
that book against a constraint program of the same rules and, on the scale
fab, spends a short time trying to improve a small neighborhood. If OR-Tools
is not installed, the recovery path is unchanged.
"""

from __future__ import annotations

import importlib
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, cast

from resilimes.domain.checks import inhibited, reticle_copies, validate
from resilimes.domain.checks import recipe_for as recipe_of
from resilimes.domain.kpis import evaluate
from resilimes.domain.models import (
    Equipment,
    Plant,
    Schedule,
    ScheduledOp,
    StepWork,
    Unscheduled,
    priority_weight,
)
from resilimes.domain.plant import minutes_between
from resilimes.domain.schedule import RETICLE_LOAD_MIN, _expand

_UNAVAILABLE = {"DOWN", "MAINTENANCE"}
_EXACT_LIMIT_S = 5.0
_LNS_LIMIT_S = 2.0
_LNS_JOBS = 6


def ortools_available() -> bool:
    try:
        importlib.import_module("ortools.sat.python.cp_model")
    except ImportError:
        return False
    return True


def optimality_reference(
    plant: Plant,
    heuristic: Schedule,
    *,
    mode: str,
    limit_s: float | None = None,
    include_book: bool | None = None,
) -> dict[str, Any]:
    """Compare ``heuristic`` with CP-SAT. The returned schedule is a reference."""
    heuristic_kpi = evaluate(plant, heuristic)
    base = _empty(
        heuristic_kpi.weighted_tardiness_min,
        heuristic_kpi.makespan_min,
        mode=mode,
    )
    if not ortools_available():
        base["status"] = "UNAVAILABLE"
        return base
    started = time.perf_counter()
    try:
        if mode == "lns":
            solved = _solve_lns(
                plant,
                heuristic,
                limit_s if limit_s is not None else _LNS_LIMIT_S,
                include_book=include_book,
            )
        else:
            solved = _solve_exact(
                plant,
                heuristic,
                limit_s if limit_s is not None else _EXACT_LIMIT_S,
                include_book=include_book,
            )
    except Exception as exc:
        base["status"] = "ERROR"
        base["detail"] = f"{type(exc).__name__}: {exc}"
        base["runtime_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return base
    solved["runtime_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return solved


def _empty(tardiness: float, makespan: int, *, mode: str) -> dict[str, Any]:
    return {
        "available": False,
        "status": "UNAVAILABLE",
        "proved": False,
        "mode": mode,
        "heuristic_tardiness_min": tardiness,
        "best_tardiness_min": None,
        "bound_tardiness_min": None,
        "heuristic_makespan_min": makespan,
        "best_makespan_min": None,
        "runtime_ms": 0.0,
        "improved": False,
        "delta_min": 0.0,
        "makespan_delta_min": 0,
        "reference": None,
    }


@dataclass
class _StepVar:
    step: StepWork
    present: Any
    start: Any
    end: Any
    setup: Any
    size: Any
    load: Any
    assign: dict[str, Any] = field(default_factory=dict)
    copies: dict[str, Any] = field(default_factory=dict)


def _solve_exact(
    plant: Plant, heuristic: Schedule, limit_s: float, *, include_book: bool | None
) -> dict[str, Any]:
    expanded = _expand(plant)
    return _solve(
        plant,
        heuristic,
        expanded,
        free_jobs=None,
        limit_s=limit_s,
        mode="exact",
        sequence_setup=True,
        include_book=include_book,
    )


def _solve_lns(
    plant: Plant, heuristic: Schedule, limit_s: float, *, include_book: bool | None
) -> dict[str, Any]:
    expanded = _expand(plant)
    jobs = _lns_jobs(plant, heuristic, expanded)
    if not jobs:
        kpi = evaluate(plant, heuristic)
        payload = _empty(kpi.weighted_tardiness_min, kpi.makespan_min, mode="lns")
        payload["available"] = True
        payload["status"] = "SKIPPED"
        payload["best_tardiness_min"] = kpi.weighted_tardiness_min
        payload["bound_tardiness_min"] = kpi.weighted_tardiness_min
        payload["best_makespan_min"] = kpi.makespan_min
        payload["proved"] = False
        return payload
    return _solve(
        plant,
        heuristic,
        expanded,
        free_jobs=jobs,
        limit_s=limit_s,
        mode="lns",
        sequence_setup=False,
        include_book=include_book,
    )


def _lns_jobs(plant: Plant, heuristic: Schedule, expanded: dict[str, list[StepWork]]) -> set[str]:
    """Late lots, the lot that sets the makespan, then the next priority-1 lots."""
    kpi_jobs = {job.job_id: job for job in plant.jobs}
    chosen: list[str] = []
    for job_id in evaluate(plant, heuristic).late_lots:
        if job_id in kpi_jobs and expanded.get(job_id) and job_id not in chosen:
            chosen.append(job_id)
    if heuristic.operations:
        tail = max(heuristic.operations, key=lambda op: (op.end_min, op.job_id))
        if expanded.get(tail.job_id) and tail.job_id not in chosen:
            chosen.append(tail.job_id)
    rest = sorted(
        (job for job in plant.jobs if job.job_id not in chosen and expanded.get(job.job_id)),
        key=lambda job: (job.priority, job.job_id),
    )
    for job in rest:
        if len(chosen) >= _LNS_JOBS:
            break
        chosen.append(job.job_id)
    return set(chosen[:_LNS_JOBS])


def _solve(
    plant: Plant,
    heuristic: Schedule,
    expanded: dict[str, list[StepWork]],
    *,
    free_jobs: set[str] | None,
    limit_s: float,
    mode: str,
    sequence_setup: bool,
    include_book: bool | None,
) -> dict[str, Any]:
    cp_model = cast(Any, importlib.import_module("ortools.sat.python.cp_model"))
    model = cp_model.CpModel()
    heuristic_kpi = evaluate(plant, heuristic)
    steps = _selected_steps(expanded, free_jobs)
    blocks = _blocks(heuristic, free_jobs)
    horizon = _horizon(plant, steps, heuristic)
    made: dict[tuple[str, str], _StepVar] = {}
    order: dict[str, list[_StepVar]] = {}
    for step in steps:
        machines = _eligible(step, plant)
        made[(step.job_id, step.step)] = _add_step(model, step, machines, horizon)
        order.setdefault(step.job_id, []).append(made[(step.job_id, step.step)])

    _precedence(model, order)
    _materials(model, plant, order)
    _queue_times(model, plant, made, expanded)
    _machines(model, plant, made, blocks, sequence_setup=sequence_setup)
    if not sequence_setup:
        _freeze_setup(model, made, heuristic)
    _reticles(model, plant, made, blocks)
    _operators(model, plant, made, blocks)
    penalty, scale = _objective(model, plant, order, horizon)
    _hint(model, made, heuristic)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = limit_s
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 1
    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)
    payload = _empty(
        heuristic_kpi.weighted_tardiness_min,
        heuristic_kpi.makespan_min,
        mode=mode,
    )
    payload["status"] = status
    if status not in {"OPTIMAL", "FEASIBLE"}:
        payload["available"] = True
        payload["best_tardiness_min"] = heuristic_kpi.weighted_tardiness_min
        payload["best_makespan_min"] = heuristic_kpi.makespan_min
        return payload
    schedule = _read_schedule(solver, made, heuristic)
    if mode == "lns" and not _setups_match(plant, schedule):
        schedule = _repair_setups(plant, schedule)
    if validate(plant, schedule)["failed"] != 0 or not _setups_match(plant, schedule):
        payload["available"] = mode == "lns"
        payload["status"] = "REJECTED" if mode == "exact" else "KEPT"
        payload["best_tardiness_min"] = heuristic_kpi.weighted_tardiness_min
        payload["best_makespan_min"] = heuristic_kpi.makespan_min
        return payload
    best = evaluate(plant, schedule)
    proved = status == "OPTIMAL"
    bound = _tardiness_bound(
        solver,
        proved=proved,
        best=best.weighted_tardiness_min,
        penalty=penalty,
        scale=scale,
        order=order,
    )
    delta = heuristic_kpi.weighted_tardiness_min - best.weighted_tardiness_min
    makespan_delta = heuristic_kpi.makespan_min - best.makespan_min
    improved = delta > 0 or (delta == 0 and makespan_delta > 0)
    if mode == "lns" and not improved:
        payload["available"] = True
        payload["status"] = "KEPT"
        payload["best_tardiness_min"] = heuristic_kpi.weighted_tardiness_min
        payload["best_makespan_min"] = heuristic_kpi.makespan_min
        return payload
    payload.update(
        {
            "available": True,
            "proved": proved and mode == "exact",
            "best_tardiness_min": best.weighted_tardiness_min,
            "bound_tardiness_min": bound,
            "best_makespan_min": best.makespan_min,
            "improved": improved,
            "delta_min": delta,
            "makespan_delta_min": makespan_delta,
            "reference": _reference_payload(
                heuristic,
                schedule,
                best,
                include_book=mode == "exact" if include_book is None else include_book,
            ),
        }
    )
    return payload


def _selected_steps(
    expanded: dict[str, list[StepWork]], free_jobs: set[str] | None
) -> list[StepWork]:
    chosen: list[StepWork] = []
    for job_id, job_steps in expanded.items():
        if free_jobs is not None and job_id not in free_jobs:
            continue
        chosen.extend(job_steps)
    return chosen


def _blocks(heuristic: Schedule, free_jobs: set[str] | None) -> list[ScheduledOp]:
    if free_jobs is None:
        return []
    return [op for op in heuristic.operations if op.job_id not in free_jobs]


def _horizon(plant: Plant, steps: list[StepWork], heuristic: Schedule) -> int:
    hint_end = max((op.end_min for op in heuristic.operations), default=0)
    work = sum(step.process_min for step in steps)
    setup = sum(machine.setup_time_min for machine in plant.equipment)
    due = max((step.due_min for step in steps), default=0)
    return max(hint_end, due, 1) + work + setup + 1


def _eligible(step: StepWork, plant: Plant) -> list[Equipment]:
    equipment = plant.equipment_map()
    if step.in_progress:
        machine = equipment.get(step.assigned_equipment or "")
        if machine is None or machine.status in _UNAVAILABLE:
            return []
        return [machine]
    recipe = step.recipe or recipe_of(plant, step.product_id, step.step)
    chosen: list[Equipment] = []
    for machine in plant.equipment:
        if step.capability not in machine.capability or machine.max_wip < 1:
            continue
        if inhibited(plant, step.product_id, recipe, machine.equipment_id):
            continue
        chosen.append(machine)
    return chosen


def _add_step(model: Any, step: StepWork, machines: list[Equipment], horizon: int) -> _StepVar:
    name = f"{step.job_id}_{step.step}"
    present = model.NewBoolVar(f"on_{name}")
    setup_cap = max((machine.setup_time_min for machine in machines), default=0)
    start = model.NewIntVar(0, horizon, f"s_{name}")
    setup = model.NewIntVar(0, setup_cap, f"u_{name}")
    load = model.NewIntVar(0, RETICLE_LOAD_MIN, f"ld_{name}")
    size = model.NewIntVar(
        step.process_min,
        step.process_min + setup_cap + RETICLE_LOAD_MIN,
        f"z_{name}",
    )
    end = model.NewIntVar(0, horizon + setup_cap + RETICLE_LOAD_MIN, f"e_{name}")
    model.Add(size == step.process_min + setup + load)
    model.Add(end == start + size)
    assign = {
        machine.equipment_id: model.NewBoolVar(f"m_{name}_{machine.equipment_id}")
        for machine in machines
    }
    if machines:
        model.Add(sum(assign.values()) == present)
    else:
        model.Add(present == 0)
    if step.in_progress and machines:
        model.Add(present == 1)
        model.Add(start == 0)
        model.Add(setup == 0)
        model.Add(load == 0)
        model.Add(assign[machines[0].equipment_id] == 1)
    else:
        model.Add(start >= step.ready_at).OnlyEnforceIf(present)
    for machine in machines:
        if machine.available_at_min > 0 and not step.in_progress:
            model.Add(start >= machine.available_at_min).OnlyEnforceIf(assign[machine.equipment_id])
    return _StepVar(
        step=step,
        present=present,
        start=start,
        end=end,
        setup=setup,
        size=size,
        load=load,
        assign=assign,
    )


def _precedence(model: Any, order: dict[str, list[_StepVar]]) -> None:
    for job_steps in order.values():
        for left, right in itertools.pairwise(job_steps):
            model.Add(right.start >= left.end).OnlyEnforceIf(right.present)
            model.AddImplication(right.present, left.present)


def _materials(model: Any, plant: Plant, order: dict[str, list[_StepVar]]) -> None:
    stock = {item.material_id: item.on_hand for item in plant.materials}
    usage: dict[str, list[tuple[Any, int]]] = {}
    products = plant.product_map()
    for job_steps in order.values():
        if not job_steps or not job_steps[0].step.consumes_material:
            continue
        product = products[job_steps[0].step.product_id]
        for need in product.materials:
            usage.setdefault(need.material_id, []).append((job_steps[0].present, need.qty_per_lot))
    for material_id, terms in usage.items():
        have = stock.get(material_id, 0)
        model.Add(sum(present * qty for present, qty in terms) <= have)


def _queue_times(
    model: Any,
    plant: Plant,
    made: dict[tuple[str, str], _StepVar],
    expanded: dict[str, list[StepWork]],
) -> None:
    jobs = plant.job_map()
    for rule in plant.qtime_rules:
        for job in plant.jobs:
            if job.product_id != rule.product_id:
                continue
            left = made.get((job.job_id, rule.from_step))
            right = made.get((job.job_id, rule.to_step))
            if right is None:
                continue
            if left is not None:
                model.Add(right.start <= left.end + rule.max_min).OnlyEnforceIf(
                    [left.present, right.present]
                )
                continue
            if (job.job_id, rule.from_step) in {
                (job.job_id, step.step) for step in expanded.get(job.job_id, [])
            }:
                continue
            anchor = _anchor_before_clock(jobs[job.job_id], rule.from_step, plant)
            if anchor is None:
                continue
            model.Add(right.start <= anchor + rule.max_min).OnlyEnforceIf(right.present)


def _anchor_before_clock(job: Any, from_step: str, plant: Plant) -> int | None:
    if job.current_step != from_step or job.started_at is None or job.status != "RUNNING":
        return None
    elapsed = minutes_between(job.started_at, plant.horizon)
    if elapsed < job.process_time_min:
        return None
    return job.process_time_min - elapsed


def _freeze_setup(model: Any, made: dict[tuple[str, str], _StepVar], heuristic: Schedule) -> None:
    """Keep the heuristic setup inside each interval so the warm start stays feasible."""
    placed = {(op.job_id, op.step): op for op in heuristic.operations}
    for key, var in made.items():
        op = placed.get(key)
        model.Add(var.setup == (op.setup_min if op is not None else 0))


def _machines(
    model: Any,
    plant: Plant,
    made: dict[tuple[str, str], _StepVar],
    blocks: list[ScheduledOp],
    *,
    sequence_setup: bool,
) -> None:
    by_machine: dict[str, list[tuple[_StepVar, str]]] = {}
    for var in made.values():
        for equipment_id in var.assign:
            by_machine.setdefault(equipment_id, []).append((var, equipment_id))
    blocked: dict[str, list[ScheduledOp]] = {}
    for op in blocks:
        blocked.setdefault(op.equipment_id, []).append(op)
    equipment = plant.equipment_map()
    for equipment_id, group in by_machine.items():
        machine = equipment[equipment_id]
        intervals = []
        for var, _machine_id in group:
            intervals.append(
                model.NewOptionalIntervalVar(
                    var.start,
                    var.size,
                    var.end,
                    var.assign[equipment_id],
                    f"iv_{var.step.job_id}_{var.step.step}_{equipment_id}",
                )
            )
        for op in blocked.get(equipment_id, []):
            intervals.append(
                model.NewFixedSizeIntervalVar(
                    op.start_min,
                    op.end_min - op.start_min,
                    f"blk_{op.job_id}_{op.step}_{equipment_id}",
                )
            )
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)
        if sequence_setup:
            _circuit(model, machine, group, blocked.get(equipment_id, []))


def _circuit(
    model: Any,
    machine: Equipment,
    group: list[tuple[_StepVar, str]],
    blocks: list[ScheduledOp],
) -> None:
    """Sequence-dependent setup: a family change inserts the tool's setup time."""
    nodes: list[dict[str, Any]] = []
    for var, equipment_id in group:
        nodes.append(
            {
                "kind": "free",
                "var": var,
                "on": var.assign[equipment_id],
                "family": var.step.setup_family,
                "start": var.start,
                "end": var.end,
                "setup": var.setup,
            }
        )
    # Keep the circuit small. Extra blocks still reserve the tool via NoOverlap.
    for op in blocks[:40]:
        stay = model.NewBoolVar(f"stay_{machine.equipment_id}_{op.job_id}_{op.step}")
        model.Add(stay == 1)
        nodes.append(
            {
                "kind": "block",
                "on": stay,
                "family": op.setup_family,
                "start": model.NewConstant(op.start_min),
                "end": model.NewConstant(op.end_min),
                "setup_value": op.setup_min,
                "key": (op.job_id, op.step),
            }
        )
    if not nodes:
        return
    arcs: list[tuple[int, int, Any]] = []
    count = len(nodes)
    empty = model.NewBoolVar(f"empty_{machine.equipment_id}")
    arcs.append((0, 0, empty))
    for index, node in enumerate(nodes, start=1):
        arcs.append((index, index, node["on"].Not()))
    for left in range(count):
        for right in range(count):
            if left == right:
                continue
            lit = model.NewBoolVar(f"arc_{machine.equipment_id}_{left}_{right}")
            arcs.append((left + 1, right + 1, lit))
            _arc_time(model, nodes[left], nodes[right], lit, machine.setup_time_min)
    for index, node in enumerate(nodes, start=1):
        first = model.NewBoolVar(f"first_{machine.equipment_id}_{index}")
        last = model.NewBoolVar(f"last_{machine.equipment_id}_{index}")
        arcs.append((0, index, first))
        arcs.append((index, 0, last))
        if node["kind"] == "free":
            model.Add(node["start"] >= machine.available_at_min).OnlyEnforceIf(first)
            model.Add(node["setup"] == 0).OnlyEnforceIf(first)
        elif node["setup_value"] != 0:
            model.Add(first == 0)
    model.AddCircuit(arcs)


def _arc_time(
    model: Any, left: dict[str, Any], right: dict[str, Any], lit: Any, setup_time: int
) -> None:
    model.Add(right["start"] >= left["end"]).OnlyEnforceIf(lit)
    needed = 0 if left["family"] == right["family"] else setup_time
    if right["kind"] == "free":
        model.Add(right["setup"] == needed).OnlyEnforceIf(lit)
        return
    if right["setup_value"] != needed:
        model.Add(lit == 0)


def _reticles(
    model: Any,
    plant: Plant,
    made: dict[tuple[str, str], _StepVar],
    blocks: list[ScheduledOp],
) -> None:
    """One physical copy per lithography step, with the same mount time as the list scheduler."""
    users: dict[str, list[_StepVar]] = {}
    for var in made.values():
        copies = reticle_copies(plant, var.step.product_id, var.step.step)
        if not copies:
            model.Add(var.load == 0)
            continue
        flags = {
            copy.reticle_id: model.NewBoolVar(
                f"c_{var.step.job_id}_{var.step.step}_{copy.reticle_id}"
            )
            for copy in copies
        }
        var.copies = flags
        model.Add(sum(flags.values()) == var.present)
        model.Add(var.load == 0).OnlyEnforceIf(var.present.Not())
        for reticle_id in flags:
            users.setdefault(reticle_id, []).append(var)
    held: dict[str, list[ScheduledOp]] = {}
    for op in blocks:
        if not op.reticle_id:
            continue
        held.setdefault(op.reticle_id, []).append(op)
    for reticle_id in set(users) | set(held):
        _one_copy(model, reticle_id, users.get(reticle_id, []), held.get(reticle_id, []))


def _one_copy(
    model: Any,
    reticle_id: str,
    free: list[_StepVar],
    blocks: list[ScheduledOp],
) -> None:
    intervals: list[Any] = []
    for var in free:
        intervals.append(
            model.NewOptionalIntervalVar(
                var.start,
                var.size,
                var.end,
                var.copies[reticle_id],
                f"mask_{reticle_id}_{var.step.job_id}_{var.step.step}",
            )
        )
    for op in blocks:
        intervals.append(
            model.NewFixedSizeIntervalVar(
                op.start_min,
                max(1, op.end_min - op.start_min),
                f"maskblk_{reticle_id}_{op.job_id}_{op.step}",
            )
        )
    if len(intervals) > 1:
        model.AddNoOverlap(intervals)
    if not free:
        return
    nodes: list[dict[str, Any]] = [
        {"kind": "free", "var": var, "on": var.copies[reticle_id]} for var in free
    ]
    nodes.extend(
        {
            "kind": "block",
            "op": op,
            "tool": op.equipment_id,
            "start": op.start_min,
            "end": op.end_min,
        }
        for op in blocks
    )
    arcs: list[tuple[int, int, Any]] = []
    for index, node in enumerate(nodes, start=1):
        if node["kind"] == "free":
            arcs.append((index, index, node["on"].Not()))
    for left_i, left in enumerate(nodes):
        for right_i, right in enumerate(nodes):
            if left_i == right_i:
                continue
            lit = model.NewBoolVar(f"rarc_{reticle_id}_{left_i}_{right_i}")
            arcs.append((left_i + 1, right_i + 1, lit))
            _copy_follows(model, left, right, lit)
    for index, node in enumerate(nodes, start=1):
        first = model.NewBoolVar(f"rfirst_{reticle_id}_{index}")
        last = model.NewBoolVar(f"rlast_{reticle_id}_{index}")
        arcs.append((0, index, first))
        arcs.append((index, 0, last))
        if node["kind"] == "free" and not node["var"].step.in_progress:
            model.Add(node["var"].load == RETICLE_LOAD_MIN).OnlyEnforceIf(first)
    if not blocks:
        # A copy that no free step picks still needs a closed circuit.
        inactive = model.NewBoolVar(f"rempty_{reticle_id}")
        ons = [node["on"] for node in nodes]
        model.Add(sum(ons) == 0).OnlyEnforceIf(inactive)
        model.Add(sum(ons) >= 1).OnlyEnforceIf(inactive.Not())
        arcs.append((0, 0, inactive))
    model.AddCircuit(arcs)


def _copy_follows(model: Any, left: dict[str, Any], right: dict[str, Any], lit: Any) -> None:
    if left["kind"] == "block" and right["kind"] == "block":
        if int(left["end"]) > int(right["start"]):
            model.Add(lit == 0)
        return
    if right["kind"] == "free":
        if left["kind"] == "free":
            model.Add(right["var"].start >= left["var"].end).OnlyEnforceIf(lit)
        else:
            model.Add(right["var"].start >= int(left["end"])).OnlyEnforceIf(lit)
        if right["var"].step.in_progress:
            return
        _mount_load(model, right["var"], lit, _node_tools(left))
        return
    if left["kind"] == "free":
        model.Add(left["var"].end <= int(right["start"])).OnlyEnforceIf(lit)


def _node_tools(node: dict[str, Any]) -> list[tuple[str, Any | None]]:
    if node["kind"] == "block":
        return [(str(node["tool"]), None)]
    return [(tool, choice) for tool, choice in node["var"].assign.items()]


def _mount_load(
    model: Any,
    right: _StepVar,
    lit: Any,
    previous: list[tuple[str, Any | None]],
) -> None:
    """Five minutes unless the previous use of this copy was already on this scanner."""
    boths: list[Any] = []
    tag = f"{right.step.job_id}_{right.step.step}_{id(lit)}"
    for tool, on_tool in previous:
        choice = right.assign.get(tool)
        if choice is None:
            continue
        if on_tool is None:
            boths.append(choice)
            continue
        both = model.NewBoolVar(f"stay_{tag}_{tool}")
        model.AddMultiplicationEquality(both, [on_tool, choice])
        boths.append(both)
    if not boths:
        model.Add(right.load == RETICLE_LOAD_MIN).OnlyEnforceIf(lit)
        return
    same = model.NewBoolVar(f"same_{tag}")
    model.AddBoolOr(boths).OnlyEnforceIf(same)
    model.AddBoolAnd([item.Not() for item in boths]).OnlyEnforceIf(same.Not())
    model.Add(right.load == 0).OnlyEnforceIf([lit, same])
    model.Add(right.load == RETICLE_LOAD_MIN).OnlyEnforceIf([lit, same.Not()])


def _operators(
    model: Any,
    plant: Plant,
    made: dict[tuple[str, str], _StepVar],
    blocks: list[ScheduledOp],
) -> None:
    equipment = plant.equipment_map()
    intervals: list[Any] = []
    demands: list[int] = []
    for var in made.values():
        for equipment_id, present in var.assign.items():
            machine = equipment[equipment_id]
            intervals.append(
                model.NewOptionalIntervalVar(
                    var.start,
                    var.size,
                    var.end,
                    present,
                    f"staff_{var.step.job_id}_{var.step.step}_{equipment_id}",
                )
            )
            demands.append(machine.operators_required)
    for op in blocks:
        tool = equipment.get(op.equipment_id)
        need = tool.operators_required if tool is not None else 1
        span = max(0, op.end_min - op.start_min)
        if span == 0:
            continue
        intervals.append(
            model.NewFixedSizeIntervalVar(op.start_min, span, f"staffblk_{op.job_id}_{op.step}")
        )
        demands.append(need)
    if intervals:
        model.AddCumulative(intervals, demands, plant.operator_pool)


def _objective(
    model: Any,
    plant: Plant,
    order: dict[str, list[_StepVar]],
    horizon: int,
) -> tuple[int, int]:
    """Lexicographic: complete every feasible lot, then weighted tardiness, then makespan.

    A held lot adds no tardiness, matching ``evaluate``. The completion penalty is
    larger than any tardiness, so a lot is held only when completing it is infeasible.
    """
    weights = {job.job_id: priority_weight(job.priority) for job in plant.jobs}
    due = {job_id: next((var.step.due_min for var in steps), 0) for job_id, steps in order.items()}
    scale = horizon + 1
    max_tardiness = sum(weights.get(job_id, 1) * horizon for job_id in order) + 1
    penalty = scale * max_tardiness
    incomplete: list[Any] = []
    tardy_terms: list[Any] = []
    makespan = model.NewIntVar(0, horizon + 100, "makespan")
    for job_id, job_steps in order.items():
        if not job_steps:
            continue
        last = job_steps[-1]
        missing = model.NewBoolVar(f"miss_{job_id}")
        model.Add(missing + last.present == 1)
        incomplete.append(missing)
        tardy = model.NewIntVar(0, horizon + max(0, -due[job_id]), f"tardy_{job_id}")
        model.Add(tardy >= last.end - due[job_id]).OnlyEnforceIf(last.present)
        model.Add(tardy == 0).OnlyEnforceIf(missing)
        tardy_terms.append(tardy * weights.get(job_id, 1))
        for var in job_steps:
            model.Add(makespan >= var.end).OnlyEnforceIf(var.present)
    model.Minimize(sum(incomplete) * penalty + sum(tardy_terms) * scale + makespan)
    return penalty, scale


def _hint(model: Any, made: dict[tuple[str, str], _StepVar], heuristic: Schedule) -> None:
    placed = {(op.job_id, op.step): op for op in heuristic.operations}
    for key, var in made.items():
        op = placed.get(key)
        if op is None:
            model.AddHint(var.present, 0)
            for choice in var.assign.values():
                model.AddHint(choice, 0)
            continue
        if op.equipment_id not in var.assign:
            continue
        model.AddHint(var.present, 1)
        model.AddHint(var.start, op.start_min)
        model.AddHint(var.setup, op.setup_min)
        model.AddHint(var.load, op.reticle_load_min)
        model.AddHint(var.end, op.end_min)
        for equipment_id, choice in var.assign.items():
            model.AddHint(choice, 1 if equipment_id == op.equipment_id else 0)
        for reticle_id, choice in var.copies.items():
            model.AddHint(choice, 1 if reticle_id == op.reticle_id else 0)


def _read_schedule(
    solver: Any,
    made: dict[tuple[str, str], _StepVar],
    heuristic: Schedule,
) -> Schedule:
    operations: list[ScheduledOp] = []
    absent: list[Unscheduled] = []
    for var in made.values():
        if solver.Value(var.present) == 0:
            absent.append(
                Unscheduled(
                    job_id=var.step.job_id,
                    step=var.step.step,
                    reason=_hold_reason(var.step),
                )
            )
            continue
        equipment_id = next(
            tool for tool, choice in var.assign.items() if solver.Value(choice) == 1
        )
        reticle_id = next(
            (mask for mask, choice in var.copies.items() if solver.Value(choice) == 1),
            "",
        )
        operations.append(
            ScheduledOp(
                job_id=var.step.job_id,
                product_id=var.step.product_id,
                step=var.step.step,
                step_index=var.step.step_index,
                equipment_id=equipment_id,
                start_min=int(solver.Value(var.start)),
                end_min=int(solver.Value(var.end)),
                setup_min=int(solver.Value(var.setup)),
                process_min=var.step.process_min,
                setup_family=var.step.setup_family,
                priority=var.step.priority,
                pinned=var.step.in_progress,
                rework=var.step.rework,
                reticle_id=reticle_id,
                reticle_load_min=int(solver.Value(var.load)),
            )
        )
    kept = {(op.job_id, op.step) for op in operations}
    for op in heuristic.operations:
        if (op.job_id, op.step) in made or (op.job_id, op.step) in kept:
            continue
        if any(item.job_id == op.job_id for item in absent):
            continue
        operations.append(op)
    operations.sort(key=lambda op: (op.start_min, op.equipment_id, op.job_id, op.step_index))
    return Schedule(
        policy="cpsat",
        operations=operations,
        unscheduled=absent,
        bottleneck_area=heuristic.bottleneck_area,
    )


def _hold_reason(step: StepWork) -> str:
    if (
        step.qtime_latest is not None
        and step.qtime_anchor is not None
        and step.ready_at > step.qtime_latest
    ):
        return (
            f"Q-time would break for {step.job_id}: {step.qtime_from} ended at "
            f"t={step.qtime_anchor} min; {step.step} must start by t={step.qtime_latest} min."
        )
    if step.consumes_material:
        return f"Material short for {step.job_id}: the reference model holds this lot."
    return f"Held {step.job_id} {step.step}: completing it breaks a hard constraint."


def _setups_match(plant: Plant, schedule: Schedule) -> bool:
    equipment = plant.equipment_map()
    grouped: dict[str, list[ScheduledOp]] = {}
    for op in schedule.operations:
        grouped.setdefault(op.equipment_id, []).append(op)
    for tool, ops in grouped.items():
        machine = equipment.get(tool)
        if machine is None:
            return False
        ops.sort(key=lambda op: (op.start_min, op.end_min, op.job_id))
        previous: ScheduledOp | None = None
        for op in ops:
            expected = 0
            if previous is not None and previous.setup_family != op.setup_family:
                expected = machine.setup_time_min
            if op.pinned:
                expected = 0
            if op.setup_min != expected:
                return False
            if previous is not None and op.start_min < previous.end_min:
                return False
            previous = op
    return True


def _repair_setups(plant: Plant, schedule: Schedule) -> Schedule:
    """Rewrite family-change setups, pushing a step later when the gap is short."""
    equipment = plant.equipment_map()
    grouped: dict[str, list[ScheduledOp]] = {}
    for op in schedule.operations:
        grouped.setdefault(op.equipment_id, []).append(op)
    updated: dict[tuple[str, str], ScheduledOp] = {}
    for tool, ops in grouped.items():
        machine = equipment.get(tool)
        if machine is None:
            return schedule
        previous: ScheduledOp | None = None
        for op in sorted(ops, key=lambda item: (item.start_min, item.end_min, item.job_id)):
            if op.pinned:
                current = op
            else:
                expected = 0
                if previous is not None and previous.setup_family != op.setup_family:
                    expected = machine.setup_time_min
                start = op.start_min
                if previous is not None:
                    start = max(start, previous.end_min)
                start = max(start, machine.available_at_min)
                current = op.model_copy(
                    update={
                        "start_min": start,
                        "setup_min": expected,
                        "end_min": start + op.process_min + expected + op.reticle_load_min,
                    }
                )
            updated[(current.job_id, current.step)] = current
            previous = current
    operations = [updated[(op.job_id, op.step)] for op in schedule.operations]
    operations.sort(key=lambda op: (op.start_min, op.equipment_id, op.job_id, op.step_index))
    return schedule.model_copy(update={"operations": operations})


def _tardiness_bound(
    solver: Any,
    *,
    proved: bool,
    best: float,
    penalty: int,
    scale: int,
    order: dict[str, list[_StepVar]],
) -> float:
    if proved:
        return best
    held = 0
    for job_steps in order.values():
        if job_steps and solver.Value(job_steps[-1].present) == 0:
            held += 1
    raw = round(solver.BestObjectiveBound())
    held_lb = raw // penalty if penalty else 0
    if held_lb != held:
        return 0.0
    remainder = raw - held_lb * penalty
    return float(remainder // scale if scale else 0)


def _reference_payload(
    heuristic: Schedule,
    schedule: Schedule,
    best: Any,
    *,
    include_book: bool,
) -> dict[str, Any]:
    heuristic_ops = {(op.job_id, op.step): op for op in heuristic.operations}
    changed = []
    for op in schedule.operations:
        prior = heuristic_ops.get((op.job_id, op.step))
        if (
            prior is None
            or prior.equipment_id != op.equipment_id
            or prior.start_min != op.start_min
        ):
            changed.append(
                {
                    "job_id": op.job_id,
                    "step": op.step,
                    "equipment_id": op.equipment_id,
                    "start_min": op.start_min,
                    "end_min": op.end_min,
                    "from_equipment": prior.equipment_id if prior else "",
                }
            )
    payload: dict[str, Any] = {
        "tardiness_min": best.weighted_tardiness_min,
        "makespan_min": best.makespan_min,
        "holds": len({item.job_id for item in schedule.unscheduled}),
        "changed": changed[:40],
    }
    if include_book:
        payload["operations"] = [op.model_dump() for op in schedule.operations]
        payload["unscheduled"] = [item.model_dump() for item in schedule.unscheduled]
    return payload
