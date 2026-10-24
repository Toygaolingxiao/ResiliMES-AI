"""Load the public SMT2020 LV/HM extract into one in-memory fab.

Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020,
doi 10.1109/TSM.2020.3001933. Files from PySCFabSim-release commit 0dbff6a,
``datasets/SMT2020_LVHM``. The paper says the dataset is open to public use.

Counts on this extract: 106 station families, 1,313 tools, 10 products,
2,156 initial WIP lots, 4,013 route steps. ``Litho_*`` is 102 tools: 82 expose
scanners plus 20 ``Litho_REG`` tools. Track and metrology families do not use
that prefix. ``Delay_32`` is in the route files (147 steps, 400 tools) and is
simulated as a station with its published process time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from resilimes.config import ROOT
from resilimes.data.smt2020_kernel import (
    SNAPSHOT,
    _cycle_sec,
    _is_scanner,
    _rows,
    _stamp,
    _to_sec,
)
from resilimes.kernel.score import lot_value, order_class_from_priority

# Published BREAK_Litho MTTR. Used when a scenario holds one scanner down.
LITHO_MTTR_MIN = 705.59
LOOKAHEAD = 24
BATCH_MAX_WAIT_SEC = 1800.0
# ResiliMES parameter. Not an SMT2020 column.
WIP_PER_TOOL = 2
WIP_FLOOR = 8

DATA_SOURCE = "smt2020"
READ_QUERY = (
    "Local extract data/smt2020: tool.txt.1l, WIP.txt, part.txt, route_1.txt "
    "through route_10.txt, setup.txt, pmcal.txt, attach.txt, downcal.txt. "
    "The simulator does not issue a Zetaris round-trip per dispatch. "
    "scripts/zetaris_setup.sh loads the same kernel tables into Postgres "
    "datasources resilimes, fab_cmms, and fab_erp."
)


@dataclass
class Family:
    name: str
    group: str
    tools: int
    tool0: int
    litho: bool
    scanner: bool
    # tool.txt.1l RULE. HotLotFIRST everywhere except Implant_128/132/91 (LSSU).
    rule: str = "rule_HotLotFIRST"


@dataclass
class Route:
    route_id: str
    family: list[int]
    cycle: list[float]
    recipe: list[int]
    batch_min: list[int]
    batch_max: list[int]
    cqt_limit: list[float]
    cqt_target: list[int]
    remain: list[float]
    step_index: dict[int, int]
    # Step index of the first litho layer that chose the scanner, or -1.
    # SVESTN/FORSTEP. Same station family, and the pointer is forward.
    dedicate_root: list[int]


@dataclass
class Fab:
    families: list[Family]
    family_index: dict[str, int]
    tool_family: list[int]
    tool_name: list[str]
    routes: list[Route]
    route_index: dict[str, int]
    lot_id: list[str]
    lot_product: list[str]
    lot_route: list[int]
    lot_step: list[int]
    lot_due: list[float]
    lot_value: list[float]
    lot_class: list[str]
    lot_priority: list[int]
    recipe_name: list[str]
    setup: dict[tuple[int, int, int], float]
    down_mttf: dict[str, float]
    down_mttr: dict[str, float]
    # family index, first start, interval, duration, calendar name. Seconds.
    pm: list[tuple[int, float, float, float, str]]
    focus_family: int
    focus_tool: int
    hot_lot: int
    pm_calendar: str
    snapshot: str = "2018-01-01T00:00:00Z"
    products: int = 10
    group_names: list[str] = field(default_factory=list)

    @property
    def litho_tools(self) -> int:
        return sum(item.tools for item in self.families if item.litho)

    @property
    def scanner_tools(self) -> int:
        return sum(item.tools for item in self.families if item.scanner)


def load_fab() -> Fab:
    return _load(str(ROOT / "data" / "smt2020"))


@lru_cache(maxsize=1)
def _load(root: str) -> Fab:
    path = Path(root)
    families, tool_family, tool_name, family_index = _tools(path / "tool.txt.1l")
    recipes: dict[str, int] = {"": 0}
    recipe_name = [""]
    routes, route_index = _routes(path, family_index, recipes, recipe_name)
    setup = _setups(path, family_index, recipes, recipe_name)
    lots = _lots(path, route_index, routes)
    down_mttf, down_mttr = _downs(path)
    pm = _pm(path, family_index)
    focus_family = _largest_scanner(families)
    focus = families[focus_family]
    focus_tool = focus.tool0  # {family}-1
    hot_lot = _hot_lot(lots, routes, families)
    pm_name = _pm_name(pm, focus_family)
    groups = sorted({item.group for item in families})
    return Fab(
        families=families,
        family_index=family_index,
        tool_family=tool_family,
        tool_name=tool_name,
        routes=routes,
        route_index=route_index,
        lot_id=[item[0] for item in lots],
        lot_product=[item[1] for item in lots],
        lot_route=[item[2] for item in lots],
        lot_step=[item[3] for item in lots],
        lot_due=[item[4] for item in lots],
        lot_value=[item[5] for item in lots],
        lot_class=[item[6] for item in lots],
        lot_priority=[item[7] for item in lots],
        recipe_name=recipe_name,
        setup=setup,
        down_mttf=down_mttf,
        down_mttr=down_mttr,
        pm=pm,
        focus_family=focus_family,
        focus_tool=focus_tool,
        hot_lot=hot_lot,
        pm_calendar=pm_name,
        products=10,
        group_names=groups,
    )


def _tools(path: Path) -> tuple[list[Family], list[int], list[str], dict[str, int]]:
    families: list[Family] = []
    tool_family: list[int] = []
    tool_name: list[str] = []
    index: dict[str, int] = {}
    for row in _rows(path):
        name = row["STNFAM"].strip()
        if name in index:
            raise ValueError(f"Duplicate station family {name}")
        qty = int(float(row["STNQTY"]))
        fam_index = len(families)
        index[name] = fam_index
        families.append(
            Family(
                name=name,
                group=row["STNGRP"].strip(),
                tools=qty,
                tool0=len(tool_name),
                litho=name.startswith("Litho_"),
                scanner=_is_scanner(name),
                rule=row["RULE"].strip() or "rule_HotLotFIRST",
            )
        )
        for number in range(1, qty + 1):
            tool_family.append(fam_index)
            tool_name.append(f"{name}-{number}")
    return families, tool_family, tool_name, index


def _recipe(name: str, recipes: dict[str, int], recipe_name: list[str]) -> int:
    key = name.strip()
    found = recipes.get(key)
    if found is not None:
        return found
    recipes[key] = len(recipe_name)
    recipe_name.append(key)
    return recipes[key]


def _routes(
    path: Path,
    family_index: dict[str, int],
    recipes: dict[str, int],
    recipe_name: list[str],
) -> tuple[list[Route], dict[str, int]]:
    routes: list[Route] = []
    index: dict[str, int] = {}
    for part in _rows(path / "part.txt"):
        route_id = part["ROUTE"].strip()
        steps = list(_rows(path / part["ROUTEFILE"]))
        by_number = {int(step["STEP"]): pos for pos, step in enumerate(steps)}
        dedicate_root = _dedicate_root(steps, by_number)
        family: list[int] = []
        cycle: list[float] = []
        recipe: list[int] = []
        batch_min: list[int] = []
        batch_max: list[int] = []
        cqt_limit: list[float] = []
        cqt_target: list[int] = []
        for step in steps:
            fam_name = step["STNFAM"].strip()
            if fam_name not in family_index:
                raise ValueError(f"Route {route_id} uses unknown family {fam_name}")
            family.append(family_index[fam_name])
            cycle.append(_cycle_sec(step))
            recipe.append(
                _recipe(step["SETUP"].strip() or step["DESC"].strip(), recipes, recipe_name)
            )
            if step["PTPER"].strip() == "per_batch":
                cap = int(float(step["BATCHMX"])) if step["BATCHMX"].strip() else 0
                floor = int(float(step["BATCHMN"])) if step["BATCHMN"].strip() else cap
                batch_max.append(cap)
                batch_min.append(floor or cap)
            else:
                batch_max.append(0)
                batch_min.append(0)
            if step["CQT"].strip():
                cqt_limit.append(_to_sec(float(step["CQT"]), step["CQTUNITS"] or "hr"))
                target_no = step["STEP_CQT"].strip()
                target = -1
                if target_no and int(float(target_no)) in by_number:
                    target = by_number[int(float(target_no))]
                cqt_target.append(target)
            else:
                cqt_limit.append(0.0)
                cqt_target.append(-1)
        remain = [0.0] * len(cycle)
        total = 0.0
        for pos in range(len(cycle) - 1, -1, -1):
            total += cycle[pos]
            remain[pos] = total
        index[route_id] = len(routes)
        routes.append(
            Route(
                route_id=route_id,
                family=family,
                cycle=cycle,
                recipe=recipe,
                batch_min=batch_min,
                batch_max=batch_max,
                cqt_limit=cqt_limit,
                cqt_target=cqt_target,
                remain=remain,
                step_index={int(step["STEP"]): pos for pos, step in enumerate(steps)},
                dedicate_root=dedicate_root,
            )
        )
    return routes, index


def _dedicate_root(steps: list[dict[str, str]], by_number: dict[int, int]) -> list[int]:
    """First step that chose the scanner for this layer.

    ``SVESTN=yes`` and ``FORSTEP`` point forward, inside one station family.
    A later layer has to use that scanner. The extract has no reticle id,
    no stocker, and no per-scanner qualification beyond the station family.
    """
    count = len(steps)
    nxt = [-1] * count
    for pos, step in enumerate(steps):
        if step["SVESTN"].strip().lower() != "yes" or not step["FORSTEP"].strip():
            continue
        target = by_number.get(int(float(step["FORSTEP"])))
        if target is None or target <= pos:
            continue
        if steps[target]["STNFAM"].strip() != step["STNFAM"].strip():
            continue
        nxt[pos] = target
    prev = [-1] * count
    for pos, target in enumerate(nxt):
        if target >= 0 and prev[target] < 0:
            prev[target] = pos
    root = [-1] * count
    for pos in range(count):
        if nxt[pos] < 0 and prev[pos] < 0:
            continue
        cursor = pos
        guard = 0
        while prev[cursor] >= 0 and guard < count:
            cursor = prev[cursor]
            guard += 1
        root[pos] = cursor
    return root


def _setups(
    path: Path,
    family_index: dict[str, int],
    recipes: dict[str, int],
    recipe_name: list[str],
) -> dict[tuple[int, int, int], float]:
    matrix: dict[tuple[int, int, int], float] = {}
    for row in _rows(path / "setup.txt"):
        fam_name = row["IGNORE"].strip()
        fam = family_index.get(fam_name)
        if fam is None:
            continue
        src = _recipe(row["CURSETUP"].strip(), recipes, recipe_name)
        dst = _recipe(row["NEWSETUP"].strip(), recipes, recipe_name)
        matrix[(fam, src, dst)] = _to_sec(float(row["STIME"]), row["STUNITS"] or "min")
    for part in _rows(path / "part.txt"):
        for step in _rows(path / part["ROUTEFILE"]):
            setup = step["SETUP"].strip()
            stime = step["STIME"].strip()
            if not setup or not stime:
                continue
            fam = family_index.get(step["STNFAM"].strip())
            if fam is None:
                continue
            dst = _recipe(setup, recipes, recipe_name)
            matrix.setdefault((fam, 0, dst), _to_sec(float(stime), step["STUNITS"] or "min"))
    return matrix


def _lots(
    path: Path,
    route_index: dict[str, int],
    routes: list[Route],
) -> list[tuple[str, str, int, int, float, float, str, int]]:
    parts = {row["PART"].strip(): row["ROUTE"].strip() for row in _rows(path / "part.txt")}
    lots: list[tuple[str, str, int, int, float, float, str, int]] = []
    for row in _rows(path / "WIP.txt"):
        route_id = parts[row["PART"].strip()]
        route_i = route_index[route_id]
        step_no = int(float(row["CURSTEP"]))
        step = routes[route_i].step_index.get(step_no)
        if step is None:
            raise ValueError(f"{row['LOT']} step {step_no} is not on {route_id}")
        priority = int(float(row["PRIOR"]))
        kind = order_class_from_priority(priority)
        due = (_stamp(row["DUE"]) - SNAPSHOT).total_seconds()
        lots.append(
            (
                row["LOT"].strip(),
                row["PART"].strip(),
                route_i,
                step,
                due,
                lot_value(kind),
                kind,
                priority,
            )
        )
    return lots


def _downs(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    mttf: dict[str, float] = {}
    mttr: dict[str, float] = {}
    for row in _rows(path / "downcal.txt"):
        group = row["IGNORE"].strip()
        mttf[group] = _to_sec(float(row["MTTF"]), row["MTTFUNITS"] or "min")
        mttr[group] = _to_sec(float(row["MTTR"]), row["MTTRUNITS"] or "min")
    return mttf, mttr


def _pm(path: Path, family_index: dict[str, int]) -> list[tuple[int, float, float, float, str]]:
    attach = {row["CALNAME"]: row for row in _rows(path / "attach.txt")}
    rows: list[tuple[int, float, float, float, str]] = []
    for row in _rows(path / "pmcal.txt"):
        linked = attach.get(row["PMCALNAME"])
        if linked is None or linked["CALTYPE"].strip() != "pm":
            continue
        if row["MTBPMUNITS"].strip().lower() in {"piece", "pieces"}:
            continue
        fam = family_index.get(linked["RESNAME"].strip())
        if fam is None:
            continue
        foa_units = linked["FOAUNITS"].strip() or "min"
        rows.append(
            (
                fam,
                _to_sec(float(linked["FOA"]), foa_units),
                _to_sec(float(row["MTBPM"]), row["MTBPMUNITS"]),
                _to_sec(float(row["MTTR"]), row["MTTRUNITS"]),
                row["PMCALNAME"].strip(),
            )
        )
    return rows


def _largest_scanner(families: list[Family]) -> int:
    scanners = [item for item in families if item.scanner]
    if not scanners:
        raise ValueError("SMT2020 extract has no expose scanner family")
    chosen = max(scanners, key=lambda item: (item.tools, item.name))
    return families.index(chosen)


def _hot_lot(
    lots: list[tuple[str, str, int, int, float, float, str, int]],
    routes: list[Route],
    families: list[Family],
) -> int:
    """Normal lot four steps before an expose scanner. Lowest lot id wins.

    Distance 0 is already on a scanner, so promoting it does not show a pull-in.
    Four steps is close enough to reach lithography inside a multi-shift window.
    """
    best: tuple[str, int] | None = None
    for index, lot in enumerate(lots):
        if lot[7] != 10:
            continue
        route = routes[lot[2]]
        distance: int | None = None
        for offset, fam in enumerate(route.family[lot[3] :]):
            if families[fam].scanner:
                distance = offset
                break
        if distance != 4:
            continue
        if best is None or lot[0] < best[0]:
            best = (lot[0], index)
    if best is None:
        raise ValueError("No normal-priority lot sits four steps before a scanner")
    return best[1]


def _pm_name(pm: list[tuple[int, float, float, float, str]], family: int) -> str:
    weekly = [item for item in pm if item[0] == family and item[4].endswith("_WK")]
    if weekly:
        return min(weekly, key=lambda item: item[1])[4]
    named = [item for item in pm if item[0] == family]
    if not named:
        raise ValueError("Focus scanner family has no day-based PM calendar")
    return min(named, key=lambda item: item[1])[4]


def initial_queues(fab: Fab) -> dict[str, int]:
    """Lots waiting at t=0, keyed by station group."""
    counts = {name: 0 for name in fab.group_names}
    for route_i, step in zip(fab.lot_route, fab.lot_step, strict=True):
        fam = fab.families[fab.routes[route_i].family[step]]
        counts[fam.group] += 1
    return counts
