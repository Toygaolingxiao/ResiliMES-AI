"""Constructed due-date stress on the public SMT2020 benchmark.

The published order book does not make earliest-due lose. This book keeps the
routes, process times, setups, and CQT limits, and replaces only the dues used
for scoring. Eight lots waiting at Dielectric_BE_28, each with a later CQT,
become VIP and are due at 8 hours. The other lots in that same queue stay
normal and are due at 7.2 hours, so earliest-due serves them first. Every
other lot keeps moving through the fab and is left outside the scored horizon.

Dielectric_BE_28-1 is held down for the published BREAK_Dielectric MTTR
(604.8 minutes in downcal.txt). The family has three tools.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from resilimes.config import ROOT, Settings
from resilimes.smt.fab import Fab
from resilimes.smt.simulate import X_FACTOR

DIELECTRIC_FAMILY = "Dielectric_BE_28"
# BREAK_Dielectric in data/smt2020/downcal.txt. Minutes.
DIELECTRIC_MTTR_MIN = 604.8
P1_DUE_SEC = 8 * 3600.0
DECOY_DUE_SEC = 7.2 * 3600.0
TIGHT_HORIZON_SEC = 24 * 3600.0
P1_COUNT = 8
# Remain under this, and a CQT on a later step. Both are properties of the extract.
REMAIN_MAX_SEC = 8 * 3600.0

COUNT_SQL: tuple[tuple[str, str, str], ...] = (
    ("resilimes", "lots", "SELECT COUNT(*) AS n FROM resilimes.lots"),
    ("resilimes", "operations", "SELECT COUNT(*) AS n FROM resilimes.operations"),
    ("resilimes", "setup_matrix", "SELECT COUNT(*) AS n FROM resilimes.setup_matrix"),
    ("fab_cmms", "pm_calendar", "SELECT COUNT(*) AS n FROM fab_cmms.pm_calendar"),
    ("fab_erp", "orders", "SELECT COUNT(*) AS n FROM fab_erp.orders"),
)
SOURCES = ("resilimes", "fab_cmms", "fab_erp")


@dataclass(frozen=True)
class TightBook:
    fab: Fab
    p1: tuple[int, ...]
    decoy: tuple[int, ...]
    down_tool: int
    down_until: float

    @property
    def watch(self) -> tuple[int, ...]:
        return self.p1 + self.decoy


def apply_xfactor(fab: Fab, factor: float = X_FACTOR) -> Fab:
    """Due = remaining process times factor. Routes and priorities stay published."""
    plant = copy.copy(fab)
    plant.lot_due = [
        fab.routes[route_i].remain[step] * factor
        for route_i, step in zip(fab.lot_route, fab.lot_step, strict=True)
    ]
    return plant


def cohort(fab: Fab) -> tuple[list[int], list[int]]:
    fam = fab.family_index[DIELECTRIC_FAMILY]
    found: list[int] = []
    for index, (route_i, step) in enumerate(zip(fab.lot_route, fab.lot_step, strict=True)):
        route = fab.routes[route_i]
        if route.family[step] != fam or route.remain[step] >= REMAIN_MAX_SEC:
            continue
        if any(limit > 0 for limit in route.cqt_limit[step:]):
            found.append(index)
    if len(found) <= P1_COUNT:
        raise RuntimeError("Dielectric_BE_28 does not have the expected CQT queue")
    return found[:P1_COUNT], found[P1_COUNT:]


def apply_tight(fab: Fab, *, horizon: float = TIGHT_HORIZON_SEC) -> TightBook:
    """Shallow copy. The cached fab's due lists are not mutated."""
    p1, decoy = cohort(fab)
    plant = copy.copy(fab)
    outside = horizon + 30 * 24 * 3600.0
    plant.lot_due = [outside] * len(fab.lot_due)
    plant.lot_class = list(fab.lot_class)
    plant.lot_value = list(fab.lot_value)
    for index in p1:
        plant.lot_due[index] = P1_DUE_SEC
        plant.lot_class[index] = "VIP"
        plant.lot_value[index] = 3.0
    for index in decoy:
        plant.lot_due[index] = DECOY_DUE_SEC
        plant.lot_class[index] = "normal"
        plant.lot_value[index] = 1.0
    family = fab.families[fab.family_index[DIELECTRIC_FAMILY]]
    return TightBook(
        fab=plant,
        p1=tuple(p1),
        decoy=tuple(decoy),
        down_tool=family.tool0,
        down_until=DIELECTRIC_MTTR_MIN * 60.0,
    )


def refuse_down_start(tool: str, lot_id: str, down_min: float) -> dict[str, Any]:
    """The critic blocks a start on a tool that is down. It does not move the lot."""
    return {
        "verdict": "reject",
        "constraint": "tool_down",
        "lot_id": lot_id,
        "tool": tool,
        "down_min": round(down_min, 2),
        "detail": (
            f"{lot_id} is not started on {tool}. That tool is down for {down_min:.1f} minutes."
        ),
    }


def first_lot_at(fab: Fab, family: int) -> str | None:
    for index, (route_i, step) in enumerate(zip(fab.lot_route, fab.lot_step, strict=True)):
        if fab.routes[route_i].family[step] == family:
            return fab.lot_id[index]
    return None


def local_counts(fab: Fab) -> dict[str, int]:
    orders = (ROOT / "data" / "smt2020" / "order.txt").read_text(encoding="utf-8").splitlines()
    return {
        "lots": len(fab.lot_id),
        "operations": sum(len(route.family) for route in fab.routes),
        "setup_matrix": len(fab.setup),
        "pm_calendar": len(fab.pm),
        "orders": max(0, len(orders) - 1),
    }


def _count_of(payload: dict[str, Any]) -> int:
    from agent.tools_zetaris import rows_as_dicts

    rows = rows_as_dicts(payload)
    if rows:
        row = rows[0]
        for key, value in row.items():
            if str(key).lower() in {"n", "count", "count(*)"} or str(key).startswith("count"):
                return int(value)
        for value in row.values():
            if isinstance(value, int | float) and not isinstance(value, bool):
                return int(value)
    data = payload.get("data") or []
    if data and isinstance(data[0], list) and data[0]:
        return int(data[0][0])
    raise ValueError("Zetaris count query returned no numeric column")


def read_benchmark(
    settings: Settings,
    fab: Fab,
    *,
    runner: Any = None,
) -> dict[str, Any]:
    """Count rows in the three datasources.

    Mock and auto-without-credentials report the local extract and say Zetaris
    was not called. A configured Zetaris client runs the SELECT COUNT statements.
    """
    queries = [{"source": source, "table": table, "sql": sql} for source, table, sql in COUNT_SQL]
    if not settings.use_zetaris:
        return {
            "mode": "extract",
            "called": False,
            "sources": list(SOURCES),
            "queries": queries,
            "row_counts": local_counts(fab),
            "error": "",
        }
    run = runner
    if run is None:
        from agent.tools_zetaris import run_sql

        run = run_sql
    counts: dict[str, int] = {}
    try:
        for _source, table, sql in COUNT_SQL:
            counts[table] = _count_of(run(sql))
    except Exception as exc:
        return {
            "mode": "zetaris",
            "called": True,
            "sources": list(SOURCES),
            "queries": queries,
            "row_counts": counts,
            "error": str(exc)[:240],
        }
    return {
        "mode": "zetaris",
        "called": True,
        "sources": list(SOURCES),
        "queries": queries,
        "row_counts": counts,
        "error": "",
    }
