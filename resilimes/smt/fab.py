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

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from resilimes.config import ROOT, ConfigError, Settings, get_settings
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
# Batch wait rule (ResiliMES defaults, not SMT2020 columns; the extract has no
# max-wait field). A batch under BATCHMN waits only while more same-recipe lots
# are expected within the window, never longer than BATCH_MAX_WAIT_SEC after the
# oldest member was ready, and never longer than HOT_BATCH_WAIT_SEC once a hot or
# VIP lot has been ready in the batch.
BATCH_MAX_WAIT_SEC = 1800.0
HOT_BATCH_WAIT_SEC = 600.0
# A lot that was in process when its tool broke goes to rework: a fixed hold for
# disposition and strip/clean, then it redoes the whole operation on any
# qualified tool of the family. ResiliMES default, not an SMT2020 column.
REWORK_SEC = 1800.0
# Q-time-urgent override (ResiliMES dispatch only). A waiting lot inside an
# open dataset CQT window is urgent when the time left before its target step
# must start is at least the process time it still needs before that step and
# at most that plus this margin. Pre-registered at 900 s (15 min) before any
# run of the rule: about three times the mean VIP queue wait (5.7 min on the
# published book), so an urgent lot sees at least one dispatch on its family,
# and a quarter of the shortest SMT2020 CQT limit (1 h). Not tuned across seeds.
QTIME_URGENT_MARGIN_SEC = 900.0
# Bounded tool reservation (ResiliMES dispatch only). A tool may be held idle
# for a Q-time-critical lot that is about to arrive for at most this long, and
# at most one tool per family at a time. Set at 15 min by the owner's brief
# before any run, the same value as the urgent margin. Not tuned.
RESERVE_MAX_SEC = 900.0
# Fixed lot transport between steps, the same for every policy. ResiliMES
# assumption, not the SMT2020 value: fromto.txt has a single Fab-to-Fab row
# (uniform 7.5 +/- 2.5 min) and every tool family's STNFAMLOC is "Fab", so the
# dataset names no bays. The bay of a family is its STNGRP station group
# (Dry_Etch, Litho, Wet_Etch, Delay, ...; 13 groups). Same group 1 min, other
# group 3 min. No AMHS, no vehicle limit. Q-time windows keep running.
# An optional multi-building layout (resilimes.smt.layout, default off) adds a
# fixed cross-building tier; that is a fab rule, not SMT2020 data.
TRANSPORT_SAME_BAY_SEC = 60.0
TRANSPORT_OTHER_BAY_SEC = 180.0
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
# Where the master data came from. RESILIMES_SMT_SOURCE picks file, zetaris,
# or auto (Zetaris when settings.use_zetaris, else the files). The fab is read
# once at load; the simulator never queries per dispatch.
FILE_LABEL = "SMT2020 local extract (data/smt2020)"
ZETARIS_LABEL = "SMT2020 via Zetaris"
FALLBACK_LABEL = "SMT2020 local extract (Zetaris read failed, file fallback)"

Rows = Callable[[str], list[dict[str, str]]]
logger = logging.getLogger(__name__)


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
    # StepPercent: share of lots measured at a sampled metrology step (100 = all).
    sample_pct: list[float] = field(default_factory=list)
    # Published STEP number per step index, used by the sampling rule.
    step_no: list[int] = field(default_factory=list)


def transport_seconds(
    fab: Fab,
    origin: int,
    target: int,
    buildings: list[str] | None = None,
    cross_building_sec: float = 900.0,
) -> float:
    """Fixed move time from a family to the next: same STNGRP bay 1 min, else 3 min.

    ``buildings`` (family -> building, ``resilimes.smt.layout``; None = one
    building, as on main) adds a third tier: a move between buildings takes
    ``cross_building_sec``. A bay is then a STNGRP group inside one building.
    """
    if buildings is not None and buildings[origin] != buildings[target]:
        return cross_building_sec
    if fab.families[origin].group == fab.families[target].group:
        return TRANSPORT_SAME_BAY_SEC
    return TRANSPORT_OTHER_BAY_SEC


def lot_number(lot_id: str, fallback: int) -> int:
    """Numeric suffix of a lot id (``Init_Lot_3_17`` -> 17)."""
    tail = lot_id.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else fallback


def release_at(fab: Fab, lot: int) -> float:
    """When ``lot`` enters the fab: 0 for snapshot WIP."""
    return fab.lot_release[lot] if lot < len(fab.lot_release) else 0.0


def measured(route: Route, index: int, number: int) -> bool:
    """Deterministic sampling: does this lot visit this metrology step?

    StepPercent ``p`` < 100 marks a sampled step. With ``n = lot number + STEP``
    the lot is measured when ``floor((n + 1) * p / 100) > floor(n * p / 100)``.
    That picks exactly ``p`` of every 100 consecutive lot numbers, evenly spaced
    (``p = 10`` is every tenth lot, ``p = 50`` every other one), and the STEP
    offset spreads the measured lots differently on each layer.
    """
    if index >= len(route.sample_pct):
        return True
    pct = route.sample_pct[index]
    if pct >= 100.0:
        return True
    n = number + route.step_no[index]
    return int((n + 1) * pct // 100) > int(n * pct // 100)


def inherited_windows(fab: Fab) -> list[tuple[int, int, int, float]]:
    """(lot, origin, target, limit) for every snapshot lot inside a CQT span.

    A lot whose snapshot step lies after a dataset CQT origin step and at or
    before that window's target (``origin < step <= target``) is already inside
    an open window at t=0. WIP.txt gives no time for the end of the origin step
    (every START is the snapshot), so the window is taken to open at t=0: its
    deadline is the full limit. That is the most lenient reading, and these
    windows are reported apart from the windows the dispatcher opens.
    """
    found: list[tuple[int, int, int, float]] = []
    for lot, (route_i, step) in enumerate(zip(fab.lot_route, fab.lot_step, strict=True)):
        route = fab.routes[route_i]
        for origin in range(step - 1, -1, -1):
            target = route.cqt_target[origin]
            if route.cqt_limit[origin] > 0 and target >= step:
                found.append((lot, origin, target, route.cqt_limit[origin]))
                break
    return found


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
    # Release moment (sim seconds) per lot. Empty: every lot is WIP at t=0.
    # ``resilimes.smt.planning.with_releases`` appends the order.txt lots.
    lot_release: list[float] = field(default_factory=list)
    # Provenance of the master data (file, zetaris, or file after a failed
    # Zetaris read). Not part of equality: both sources build the same fab.
    origin: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def litho_tools(self) -> int:
        return sum(item.tools for item in self.families if item.litho)

    @property
    def scanner_tools(self) -> int:
        return sum(item.tools for item in self.families if item.scanner)


def load_fab(settings: Settings | None = None) -> Fab:
    """The SMT2020 fab, from data/smt2020 or from the Zetaris smt_* tables.

    ``file`` (and ``auto`` without Zetaris) is the cached local extract, the
    same object as before this switch. ``zetaris`` raises on a failed read.
    ``auto`` with Zetaris configured falls back to the files on a failed read
    and says so in ``fab.origin``.
    """
    root = str(ROOT / "data" / "smt2020")
    if settings is None:
        try:
            settings = get_settings()
        except ConfigError:
            return _load(root)
    active = settings
    requested = active.smt_source
    if requested == "file":
        return _load(root)
    if requested == "auto":
        try:
            wanted = active.use_zetaris
        except ConfigError:
            wanted = False
        if not wanted:
            return _load(root)
    key = _zetaris_key(active)
    failed = _ZETARIS_FAILED.get(key)
    if requested == "auto" and failed and time.monotonic() - failed[0] < RETRY_AFTER_SEC:
        error = failed[1]
    else:
        try:
            fab = load_fab_zetaris(active)
        except Exception as exc:
            if requested == "zetaris":
                raise
            error = str(exc)[:300]
            _ZETARIS_FAILED[key] = (time.monotonic(), error)
            logger.warning(
                "SMT2020 Zetaris read failed, using data/smt2020",
                extra={"fields": {"error": error}},
            )
        else:
            _ZETARIS_FAILED.pop(key, None)
            return fab
    fab = replace(_load(root))
    fab.origin = {
        "source": "file",
        "requested": requested,
        "label": FALLBACK_LABEL,
        "fallback": True,
        "error": error,
        "queries": [],
    }
    return fab


_ZETARIS_CACHE: dict[tuple[Any, ...], Fab] = {}
# auto mode: after a failed read, serve the files for this long before retrying,
# so /api/health polling does not wait on a dead Zetaris every call.
RETRY_AFTER_SEC = 60.0
_ZETARIS_FAILED: dict[tuple[Any, ...], tuple[float, str]] = {}


def _zetaris_key(settings: Settings) -> tuple[Any, ...]:
    return (
        settings.zetaris_schema,
        tuple(sorted(settings.zetaris_table_sources.items())),
        settings.zetaris_rest_url,
    )


def load_fab_zetaris(settings: Settings, run: Any = None, *, cache: bool = True) -> Fab:
    """Build the fab from the smt_* tables through Zetaris. Successes are cached."""
    from resilimes.data.smt2020_sql import ZetarisRows

    key = _zetaris_key(settings)
    if cache and run is None and key in _ZETARIS_CACHE:
        return _ZETARIS_CACHE[key]
    reader = ZetarisRows(
        run,
        schema=settings.zetaris_schema,
        sources=settings.zetaris_table_sources,
        timeout_s=settings.zetaris_timeout_s,
    )
    fab = _build(reader)
    fab.origin = {
        "source": "zetaris",
        "requested": settings.smt_source,
        "label": ZETARIS_LABEL,
        "fallback": False,
        "error": "",
        "queries": [record.model_dump() for record in reader.records],
    }
    if cache and run is None:
        _ZETARIS_CACHE[key] = fab
    return fab


def fab_digest(fab: Fab) -> str:
    """SHA-256 over every compared field, for parity between file and Zetaris loads."""
    import hashlib
    from dataclasses import fields

    parts = [f"{item.name}={getattr(fab, item.name)!r}" for item in fields(fab) if item.compare]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def fab_source(fab: Fab) -> dict[str, Any]:
    """Public provenance block for API payloads. Never holds credentials."""
    origin = fab.origin or {"source": "file", "label": FILE_LABEL, "fallback": False}
    return {
        "source": origin.get("source", "file"),
        "requested": origin.get("requested", "file"),
        "label": origin.get("label", FILE_LABEL),
        "fallback": bool(origin.get("fallback")),
        "error": origin.get("error", ""),
        "tables": [
            {"table": item["name"], "rows": item["row_count"]} for item in origin.get("queries", [])
        ],
    }


@lru_cache(maxsize=1)
def _load(root: str) -> Fab:
    path = Path(root)
    fab = _build(lambda name: _rows(path / name))
    fab.origin = {
        "source": "file",
        "requested": "file",
        "label": FILE_LABEL,
        "fallback": False,
        "error": "",
        "queries": [],
    }
    return fab


def _build(read: Rows) -> Fab:
    """Assemble the fab from rows keyed by SMT2020 file name (files or Zetaris)."""
    families, tool_family, tool_name, family_index = _tools(read)
    recipes: dict[str, int] = {"": 0}
    recipe_name = [""]
    routes, route_index = _routes(read, family_index, recipes, recipe_name)
    setup = _setups(read, family_index, recipes, recipe_name)
    lots = _lots(read, route_index, routes)
    down_mttf, down_mttr = _downs(read)
    pm = _pm(read, family_index)
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


def _tools(read: Rows) -> tuple[list[Family], list[int], list[str], dict[str, int]]:
    families: list[Family] = []
    tool_family: list[int] = []
    tool_name: list[str] = []
    index: dict[str, int] = {}
    for row in read("tool.txt.1l"):
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
    read: Rows,
    family_index: dict[str, int],
    recipes: dict[str, int],
    recipe_name: list[str],
) -> tuple[list[Route], dict[str, int]]:
    routes: list[Route] = []
    index: dict[str, int] = {}
    for part in read("part.txt"):
        route_id = part["ROUTE"].strip()
        steps = list(read(part["ROUTEFILE"]))
        by_number = {int(step["STEP"]): pos for pos, step in enumerate(steps)}
        dedicate_root = _dedicate_root(steps, by_number)
        family: list[int] = []
        cycle: list[float] = []
        recipe: list[int] = []
        batch_min: list[int] = []
        batch_max: list[int] = []
        cqt_limit: list[float] = []
        cqt_target: list[int] = []
        sample_pct: list[float] = []
        for step in steps:
            pct = (step.get("StepPercent") or "").strip()
            sample_pct.append(float(pct) if pct else 100.0)
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
                sample_pct=sample_pct,
                step_no=[int(step["STEP"]) for step in steps],
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
    read: Rows,
    family_index: dict[str, int],
    recipes: dict[str, int],
    recipe_name: list[str],
) -> dict[tuple[int, int, int], float]:
    matrix: dict[tuple[int, int, int], float] = {}
    for row in read("setup.txt"):
        fam_name = row["IGNORE"].strip()
        fam = family_index.get(fam_name)
        if fam is None:
            continue
        src = _recipe(row["CURSETUP"].strip(), recipes, recipe_name)
        dst = _recipe(row["NEWSETUP"].strip(), recipes, recipe_name)
        matrix[(fam, src, dst)] = _to_sec(float(row["STIME"]), row["STUNITS"] or "min")
    for part in read("part.txt"):
        for step in read(part["ROUTEFILE"]):
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
    read: Rows,
    route_index: dict[str, int],
    routes: list[Route],
) -> list[tuple[str, str, int, int, float, float, str, int]]:
    parts = {row["PART"].strip(): row["ROUTE"].strip() for row in read("part.txt")}
    lots: list[tuple[str, str, int, int, float, float, str, int]] = []
    for row in read("WIP.txt"):
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


def _downs(read: Rows) -> tuple[dict[str, float], dict[str, float]]:
    mttf: dict[str, float] = {}
    mttr: dict[str, float] = {}
    for row in read("downcal.txt"):
        group = row["IGNORE"].strip()
        mttf[group] = _to_sec(float(row["MTTF"]), row["MTTFUNITS"] or "min")
        mttr[group] = _to_sec(float(row["MTTR"]), row["MTTRUNITS"] or "min")
    return mttf, mttr


def _pm(read: Rows, family_index: dict[str, int]) -> list[tuple[int, float, float, float, str]]:
    attach = {row["CALNAME"]: row for row in read("attach.txt")}
    rows: list[tuple[int, float, float, float, str]] = []
    for row in read("pmcal.txt"):
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
