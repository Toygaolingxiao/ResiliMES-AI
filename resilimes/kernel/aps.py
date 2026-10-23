"""Stage 2 finite-capacity plan. The litho scanner group is the one constraint.

Backward pass: each operation due is the order due minus the process time of
every later step. Those dues are what RemainingSlack uses when DPI is
recomputed; the dispatcher does not also add CR.

Forward pass: scanner steps are placed on the earliest free scanner, in
operation-due order. A step before the scanner is pulled earlier so it finishes
when the scanner starts. A step after the scanner starts when the scanner ends.
That is the WIP smoothing rule: non-bottleneck work moves, the scanner does not.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepLoad:
    lot_id: str
    op_id: str
    cycle_sec: float
    scanner: bool


@dataclass(frozen=True)
class BaselineRow:
    lot_id: str
    op_id: str
    start_sec: float
    end_sec: float
    op_due_sec: float
    scanner: bool


def backward_dues(cycles_sec: list[float], order_due_sec: float) -> list[float]:
    """Per-operation due, aligned with ``cycles_sec`` from the current step on."""
    due = order_due_sec
    reversed_dues: list[float] = []
    for cycle in reversed(cycles_sec):
        reversed_dues.append(due)
        due -= cycle
    reversed_dues.reverse()
    return reversed_dues


def schedule_bottleneck(
    lots: list[list[StepLoad]],
    dues: list[list[float]],
    *,
    scanners: int,
) -> list[BaselineRow]:
    """Forward-load scanner steps, then shift the other steps around them."""
    if scanners < 1:
        raise ValueError("scanner count must be positive")
    free = [0.0] * scanners
    scanner_jobs: list[tuple[float, int, int]] = []
    for lot_index, steps in enumerate(lots):
        for step_index, step in enumerate(steps):
            if step.scanner:
                scanner_jobs.append((dues[lot_index][step_index], lot_index, step_index))
    scanner_jobs.sort()
    placed: dict[tuple[int, int], tuple[float, float]] = {}
    for _due, lot_index, step_index in scanner_jobs:
        tool = min(range(scanners), key=lambda index: (free[index], index))
        start = free[tool]
        end = start + lots[lot_index][step_index].cycle_sec
        free[tool] = end
        placed[(lot_index, step_index)] = (start, end)
    rows: list[BaselineRow] = []
    for lot_index, steps in enumerate(lots):
        times: list[tuple[float, float] | None] = [None] * len(steps)
        for step_index, step in enumerate(steps):
            if step.scanner:
                times[step_index] = placed[(lot_index, step_index)]
        for step_index, step in enumerate(steps):
            window = times[step_index]
            if not step.scanner or window is None:
                continue
            cursor = window[0]
            earlier = step_index - 1
            while earlier >= 0 and times[earlier] is None:
                end = cursor
                start = end - steps[earlier].cycle_sec
                times[earlier] = (start, end)
                cursor = start
                earlier -= 1
        cursor = 0.0
        for step_index, step in enumerate(steps):
            window = times[step_index]
            if window is not None:
                cursor = window[1]
                continue
            start = cursor
            end = start + step.cycle_sec
            times[step_index] = (start, end)
            cursor = end
        for step_index, step in enumerate(steps):
            start, end = times[step_index] or (0.0, step.cycle_sec)
            rows.append(
                BaselineRow(
                    lot_id=step.lot_id,
                    op_id=step.op_id,
                    start_sec=start,
                    end_sec=end,
                    op_due_sec=dues[lot_index][step_index],
                    scanner=step.scanner,
                )
            )
    return rows
