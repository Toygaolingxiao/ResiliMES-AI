"""Pre-registered stress book of the AI shift lead (docs/AI_SHIFT_LEAD_STRESS.md).

Five realistic incidents on the full SMT2020 fab, each a study book
``stress_<id>``. ``--book stress`` expands to all of them in the fixed
pre-registered order. Parameters are fixed here and in the doc (pre-registration
commit 59ca1e0); they are not tuned on results.

Every incident starts at the snapshot (t = 0) or is part of the simulator
state (PM windows, holds, batch cap), so the twin's forks keep it (forks only
resample breakdowns that start after the fork moment).
"""

from __future__ import annotations

import math
from typing import Any

from resilimes.smt.fab import Fab
from resilimes.smt.faults import FaultPlan

HOUR = 3600.0
STRESS_SEEDS = (9, 10, 11)
# Fixed order (S1..S5), used for any live subset (seed-major, then this order).
SCENARIOS = (
    "stress_furnace_down",
    "stress_hot_cqt",
    "stress_release_burst",
    "stress_pm_peak",
    "stress_batch_cap",
)
# Second, clearly labelled pre-registration (commit 99e85bc), harsher.
SCENARIOS2 = (
    "stress2_furnace_crisis",
    "stress2_rush_hot",
    "stress2_fe_furnace_crisis",
)
BOOKS = {"stress": SCENARIOS, "stress2": SCENARIOS2}
RUSH_X_FACTOR = 1.25
FURNACE_BE = "Diffusion_BE_123"
FURNACE_FE = "Diffusion_FE_94"
BURST_FAMILIES = ("DE_BE_69", "WE_BE_17", "Dielectric_BE_28")
DOWN_SPAN = (0.0, 4 * HOUR)
BURST_RELEASE = 1 * HOUR
PM_SPAN = (1 * HOUR, 5 * HOUR)
BATCH_CAP_WAFERS = 25
BATCH_SPAN = (0.0, 6 * HOUR)
HOT_X_FACTOR = 2.0
HOT_REMAIN = (2 * HOUR, 4 * HOUR)


def is_stress(book: str) -> bool:
    return book in SCENARIOS or book in SCENARIOS2


def expand(book: str) -> list[str]:
    """``stress`` / ``stress2`` -> its scenarios in order; else the book."""
    return list(BOOKS[book]) if book in BOOKS else [book]


def ordered_pairs(
    seeds: list[int] | tuple[int, ...] = STRESS_SEEDS, book: str = "stress"
) -> list[tuple[str, int]]:
    """The pre-registered run order: seed-major, then the scenario order."""
    return [(name, seed) for seed in seeds for name in BOOKS[book]]


def half_tools(fab: Fab, name: str) -> list[int]:
    family = fab.families[fab.family_index[name]]
    return list(range(family.tool0, family.tool0 + math.ceil(family.tools / 2)))


def hot_candidate(fab: Fab) -> tuple[int, float]:
    """S2 lot: normal WIP lot with remaining raw process time in [2 h, 4 h]
    whose remaining route has a CQT origin; the least remaining time first.
    Returns (lot index, remaining seconds)."""
    best: tuple[float, int] | None = None
    for lot in range(len(fab.lot_id)):
        if fab.lot_class[lot] != "normal":
            continue
        route = fab.routes[fab.lot_route[lot]]
        step = fab.lot_step[lot]
        remain = route.remain[step]
        if not HOT_REMAIN[0] <= remain <= HOT_REMAIN[1]:
            continue
        if not any(route.cqt_limit[s] > 0 for s in range(step, len(route.family))):
            continue
        if best is None or (remain, lot) < best:
            best = (remain, lot)
    if best is None:
        raise LookupError("no S2 hot-lot candidate")
    return best[1], best[0]


def burst_lots(fab: Fab) -> list[int]:
    """S3 lots: WIP whose current or next step is at a burst family."""
    fams = {fab.family_index[name] for name in BURST_FAMILIES}
    lots = []
    for lot in range(len(fab.lot_id)):
        route = fab.routes[fab.lot_route[lot]]
        step = fab.lot_step[lot]
        if fams & set(route.family[step : step + 2]):
            lots.append(lot)
    return lots


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def apply(
    fab: Fab,
    book: str,
    policy: str,
    downs: list[list[tuple[float, float]]],
    pm: list[list[tuple[float, float]]],
    kwargs: dict[str, Any],
) -> None:
    """Add the incident of ``book`` to ``downs`` / ``pm`` / ``kwargs`` in place."""
    horizon = float(kwargs.get("horizon", 0.0) or math.inf)
    if book == "stress2_furnace_crisis":
        apply(fab, "stress_furnace_down", policy, downs, pm, kwargs)
        kwargs["faults"] = FaultPlan(
            hold_until={lot: BURST_RELEASE for lot in burst_lots(fab)},
            batch_family=fab.family_index[FURNACE_BE],
            batch_cap_wafers=BATCH_CAP_WAFERS,
            batch_window=BATCH_SPAN,
        )
    elif book == "stress2_rush_hot":
        lot, remain = hot_candidate(fab)
        kwargs["hot_lot"] = lot
        if policy == "resilimes":
            kwargs["hot_due"] = RUSH_X_FACTOR * remain
            kwargs["promote_hot"] = True
    elif book == "stress2_fe_furnace_crisis":
        for tool in half_tools(fab, FURNACE_FE):
            downs[tool] = _merge([*downs[tool], (DOWN_SPAN[0], min(DOWN_SPAN[1], horizon))])
        kwargs["faults"] = FaultPlan(
            batch_family=fab.family_index[FURNACE_FE],
            batch_cap_wafers=BATCH_CAP_WAFERS,
            batch_window=BATCH_SPAN,
        )
    elif book == "stress_furnace_down":
        for tool in half_tools(fab, FURNACE_BE):
            downs[tool] = _merge([*downs[tool], (DOWN_SPAN[0], min(DOWN_SPAN[1], horizon))])
    elif book == "stress_hot_cqt":
        lot, remain = hot_candidate(fab)
        kwargs["hot_lot"] = lot
        if policy == "resilimes":
            kwargs["hot_due"] = HOT_X_FACTOR * remain
            kwargs["promote_hot"] = True
    elif book == "stress_release_burst":
        kwargs["faults"] = FaultPlan(hold_until={lot: BURST_RELEASE for lot in burst_lots(fab)})
    elif book == "stress_pm_peak":
        for tool in half_tools(fab, FURNACE_FE):
            pm[tool] = _merge([*pm[tool], PM_SPAN])
    elif book == "stress_batch_cap":
        kwargs["faults"] = FaultPlan(
            batch_family=fab.family_index[FURNACE_BE],
            batch_cap_wafers=BATCH_CAP_WAFERS,
            batch_window=BATCH_SPAN,
        )
    else:
        raise KeyError(book)
