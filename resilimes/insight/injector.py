"""Fault injection on the full SMT2020 fab: the investigator's ground truth.

Each case takes one seed's baseline run (16 h, policy ``resilimes``), picks a
target family, injects one fault in a window that starts at 6 h, and keeps the
case only when the symptom is visible in the faulted run's WIP and is not in
the baseline (pre-check). The injected fault is the answer key.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from resilimes.evidence.toolkit import HOUR, RecordedRun, Toolkit, record_run
from resilimes.smt.fab import Fab
from resilimes.smt.faults import FaultPlan

TAXONOMY: tuple[str, ...] = (
    "tool_down",
    "pm_in_peak",
    "release_burst",
    "setup_thrash",
    "batch_cap",
    "upstream_starvation",
)
CAUSE_TEXT = {
    "tool_down": "unplanned tool down at the family (capacity lost)",
    "pm_in_peak": "planned PM placed in the family's arrival peak (capacity lost to PM)",
    "release_burst": "a burst of lots released / arriving at once",
    "setup_thrash": "setup thrash: much more setup time per start (changeovers)",
    "batch_cap": "batch size cap lowered: fewer lots per batch start",
    "upstream_starvation": "the main upstream family stopped feeding (it is down), so WIP drains",
}
HORIZON_H = 16.0
T0_H = 6.0
T_END_H = 12.0
SEEDS = (1, 2, 3, 4)
SETUP_EXTRA_SEC = 2700.0
BATCH_CAP_WAFERS = 25
MAX_TRIES = 8


@dataclass
class Case:
    case_id: str
    fault: str
    seed: int
    family: str
    upstream: str | None
    t1_h: float
    t2_h: float
    direction: str
    wip_t1: int
    wip_t2: int
    base_wip_t2: int
    injection: dict[str, Any] = field(default_factory=dict)

    @property
    def question(self) -> str:
        if self.direction == "rise":
            verb = "double" if self.wip_t1 > 0 and self.wip_t2 >= 2 * self.wip_t1 else "rise"
            return (
                f"Why did {self.family} WIP {verb} between {self.t1_h:g} h and {self.t2_h:g} h "
                f"(waiting lots {self.wip_t1} -> {self.wip_t2})?"
            )
        return (
            f"Why did {self.family} WIP fall between {self.t1_h:g} h and {self.t2_h:g} h "
            f"(waiting lots {self.wip_t1} -> {self.wip_t2})?"
        )

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["question"] = self.question
        return out

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Case:
        keys = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in payload.items() if key in keys})


@dataclass
class Injection:
    faults: FaultPlan | None = None
    extra_downs: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    extra_pm: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    t1_h: float = T0_H
    t_end_h: float = T_END_H
    upstream: int = -1
    describe: dict[str, Any] = field(default_factory=dict)


def _half_tools(kit: Toolkit, fam: int) -> list[int]:
    tools = sorted(kit.tl.family_tools(fam))
    return tools[: max(1, math.ceil(len(tools) / 2))]


def _peak_start(kit: Toolkit, fam: int) -> float:
    """Start hour (4 h window inside [4 h, 10 h]) with the most baseline arrivals."""
    best, best_h = -1.0, T0_H
    for start_h in (4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
        stats = kit.window_stats(fam, start_h * HOUR, (start_h + 4.0) * HOUR)
        if stats["arrivals"] > best:
            best, best_h = stats["arrivals"], start_h
    return best_h


def main_upstream(kit: Toolkit, fam: int) -> int:
    for src, _n in kit.route_upstream(fam).most_common():
        if src != fam and src >= 0:
            return src
    return -1


def build_injection(fault: str, kit: Toolkit, fam: int) -> Injection | None:
    """Injection for ``fault`` at family ``fam``; None when the family is not eligible."""
    fab = kit.fab
    t0, t_end = T0_H * HOUR, T_END_H * HOUR
    name = fab.families[fam].name
    if fault == "tool_down":
        tools = _half_tools(kit, fam)
        return Injection(
            extra_downs={tool: [(t0, t_end)] for tool in tools},
            describe={"tools_down": [fab.tool_name[t] for t in tools], "window_h": [6, 12]},
        )
    if fault == "pm_in_peak":
        start_h = _peak_start(kit, fam)
        tools = _half_tools(kit, fam)
        span = (start_h * HOUR, (start_h + 4.0) * HOUR)
        return Injection(
            extra_pm={tool: [span] for tool in tools},
            t1_h=start_h,
            t_end_h=start_h + 4.0,
            describe={
                "tools_pm": [fab.tool_name[t] for t in tools],
                "window_h": [start_h, start_h + 4],
            },
        )
    if fault == "release_burst":
        held: dict[int, float] = {}
        for lot in range(len(fab.lot_id)):
            route = fab.routes[fab.lot_route[lot]]
            step = fab.lot_step[lot]
            ahead = route.family[step : step + 2]
            if fam in ahead:
                held[lot] = t0
        if len(held) < 8:
            return None
        return Injection(
            faults=FaultPlan(hold_until=held),
            describe={"lots_held_until_6h": len(held), "family": name},
        )
    if fault == "setup_thrash":
        base = kit.window_stats(fam, t0, t_end)
        if base["changeovers"] < 4:
            return None
        return Injection(
            faults=FaultPlan(
                setup_family=fam, setup_extra_sec=SETUP_EXTRA_SEC, setup_window=(t0, t_end)
            ),
            describe={"extra_setup_min_per_changeover": SETUP_EXTRA_SEC / 60, "window_h": [6, 12]},
        )
    if fault == "batch_cap":
        if not kit._is_batch(fam):
            return None
        base = kit.window_stats(fam, t0, t_end)
        if base["lots_per_start"] < 2.0:
            return None
        return Injection(
            faults=FaultPlan(
                batch_family=fam, batch_cap_wafers=BATCH_CAP_WAFERS, batch_window=(t0, t_end)
            ),
            describe={"batch_cap_wafers": BATCH_CAP_WAFERS, "window_h": [6, 12]},
        )
    if fault == "upstream_starvation":
        up = main_upstream(kit, fam)
        if up < 0:
            return None
        tools = sorted(kit.tl.family_tools(up))
        return Injection(
            extra_downs={tool: [(t0, t_end)] for tool in tools},
            upstream=up,
            describe={"upstream_family_down": fab.families[up].name, "window_h": [6, 12]},
        )
    raise ValueError(f"unknown fault {fault!r}")


def faulted_run(fab: Fab, seed: int, injection: Injection, label: str) -> RecordedRun:
    return record_run(
        fab,
        seed=seed,
        horizon=HORIZON_H * HOUR,
        faults=injection.faults,
        extra_downs=injection.extra_downs,
        extra_pm=injection.extra_pm,
        label=label,
    )


def _symptom(
    fault: str, kit: Toolkit, base: Toolkit, fam: int, t1_h: float, t_end_h: float
) -> tuple[str, float, int, int, int] | None:
    rise = fault != "upstream_starvation"
    w1 = kit.tl.waiting_at(fam, t1_h * HOUR)
    best: tuple[float, int] | None = None
    hour = t1_h + 2.0
    while hour <= min(t_end_h + 2.0, HORIZON_H) + 1e-9:
        wait = kit.tl.waiting_at(fam, hour * HOUR)
        if best is None or (wait > best[1] if rise else wait < best[1]):
            best = (hour, wait)
        hour += 1.0
    if best is None:
        return None
    t2_h, w2 = best
    b2 = base.tl.waiting_at(fam, t2_h * HOUR)
    if rise:
        ok = w2 >= max(1.5 * w1, w1 + 6) and w2 - b2 >= max(4, 0.3 * w2)
    else:
        ok = w1 >= 6 and w2 <= 0.5 * w1 and b2 - w2 >= 3
    if not ok:
        return None
    return ("rise" if rise else "fall", t2_h, w1, w2, b2)


def candidates(fault: str, base: Toolkit, rng: random.Random) -> list[int]:
    fab = base.fab
    t0, t_end = T0_H * HOUR, T_END_H * HOUR
    pool = []
    for fam in range(len(fab.families)):
        stats = base.window_stats(fam, t0, t_end)
        if stats["arrivals"] < 10 or stats["tools"] < 1:
            continue
        if fault == "batch_cap" and not base._is_batch(fam):
            continue
        if fault in ("tool_down", "pm_in_peak") and stats["tools"] < 2:
            continue
        pool.append(fam)
    rng.shuffle(pool)
    return pool


def make_case(
    fab: Fab, fault: str, seed: int, base_run: RecordedRun, *, max_tries: int = MAX_TRIES
) -> tuple[Case, RecordedRun] | None:
    base = Toolkit(base_run)
    rng = random.Random(seed * 1000 + TAXONOMY.index(fault))
    tries = 0
    for fam in candidates(fault, base, rng):
        injection = build_injection(fault, base, fam)
        if injection is None:
            continue
        tries += 1
        if tries > max_tries:
            break
        run = faulted_run(fab, seed, injection, label=f"{fault}/s{seed}")
        kit = Toolkit(run)
        found = _symptom(fault, kit, base, fam, injection.t1_h, injection.t_end_h)
        if found is None:
            continue
        direction, t2_h, w1, w2, b2 = found
        case = Case(
            case_id=f"{fault}-s{seed}",
            fault=fault,
            seed=seed,
            family=fab.families[fam].name,
            upstream=fab.families[injection.upstream].name if injection.upstream >= 0 else None,
            t1_h=injection.t1_h,
            t2_h=t2_h,
            direction=direction,
            wip_t1=w1,
            wip_t2=w2,
            base_wip_t2=b2,
            injection=injection.describe,
        )
        return case, run
    return None


def rebuild(fab: Fab, case: Case, base_run: RecordedRun | None = None) -> RecordedRun:
    """Re-run the faulted simulation of a stored case (deterministic)."""
    base = base_run or record_run(fab, seed=case.seed, horizon=HORIZON_H * HOUR)
    kit = Toolkit(base)
    injection = build_injection(case.fault, kit, fab.family_index[case.family])
    if injection is None:
        raise ValueError(f"case {case.case_id} no longer eligible")
    return faulted_run(fab, case.seed, injection, label=case.case_id)
