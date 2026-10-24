"""Five-seed, 48-hour measurements on the full SMT2020 fab.

Writes ``data/smt2020/benchmark.json`` and ``docs/SMT2020_SCALE.md``.
The interactive console uses a 12-hour horizon so a click stays short.
"""

from __future__ import annotations

import json
import os
import random
from multiprocessing import get_context
from statistics import mean, pstdev
from typing import Any

from resilimes.config import ROOT
from resilimes.smt.fab import LITHO_MTTR_MIN, REWORK_SEC, Fab, load_fab
from resilimes.smt.scenarios import SCENARIOS, SEEDS, STUDY_HORIZON_SEC, simulate_pair
from resilimes.smt.simulate import (
    X_FACTOR,
    RunResult,
    macro_aps_ms,
    pm_shift_to_open,
    pm_windows,
    run_policy,
    sample_downs,
)
from resilimes.smt.tight import DIELECTRIC_MTTR_MIN, TIGHT_HORIZON_SEC, apply_tight, apply_xfactor

_KEYS = (
    "on_time_pct",
    "weighted_tardiness_min",
    "due_in_horizon",
    "already_late",
    "completed_routes",
    "cycle_time_h",
    "mean_step_cycle_min",
    "litho_util_pct",
    "scanner_util_pct",
    "qtime_violations",
    "pm_avoided",
    "pm_overlaps",
    "wip_replans",
    "dispatch_p50_ms",
    "dispatch_p95_ms",
    "dispatch_busy_p50_ms",
    "dispatch_busy_p95_ms",
    "sim_s",
    "sibling_starts",
    "focus_queue_max",
    "downstream_queue_max",
    "hot_steps",
    "mean_x_factor",
    "qtime_gates",
    "recleans",
    "setup_min",
    "batch_starts",
    "batch_lots",
    "batch_dropped",
    "reworks",
    "rework_lot_min",
    "repins",
    "skipped",
    "qtime_skipped",
    "qtime_overrides",
    "qtime_met",
    "qtime_late",
    "qtime_held",
    "qtime_recleaned",
    "qtime_expired",
    "qtime_rate_pct",
    "qtime_inherited_windows",
    "qtime_inherited_missed",
    "qtime_hold_lot_min",
)

_X_ETAS = (180.0, 300.0, 600.0, LITHO_MTTR_MIN)

# Runs are independent, so seeds and policies go to a process pool. One
# full-scale run peaks near 90 MB RSS and ~3 s; 6 workers on the 8-core,
# ~4 GB box ran 25 runs in 14 s with no swap. Set RESILIMES_BENCH_WORKERS=1
# for a serial run. Wall-clock fields (sim_s, dispatch ms) are measured
# inside each run and can read a little higher under a busy pool.
_WORKERS = max(1, int(os.environ.get("RESILIMES_BENCH_WORKERS", "6")))
_FABS: dict[str, Fab] = {}


def _job(item: tuple[str, dict[str, Any]]) -> RunResult:
    book, kwargs = item
    return run_policy(_FABS[book], **kwargs)


def _run_all(items: list[tuple[str, dict[str, Any]]]) -> list[RunResult]:
    """Run jobs in order. Workers fork after ``_FABS`` is filled."""
    if _WORKERS <= 1 or len(items) <= 1:
        return [_job(item) for item in items]
    with get_context("fork").Pool(min(_WORKERS, len(items))) as pool:
        return pool.map(_job, items, chunksize=1)


def _collect(
    keys: list[str], results: list[RunResult], found: dict[str, list[RunResult]]
) -> dict[str, list[RunResult]]:
    for key, result in zip(keys, results, strict=True):
        found[key].append(result)
    return found


# One pre-registered run. Seeds 9-13. Not retuned after the numbers.
_HELDOUT: dict[str, Any] = {
    "seeds": [9, 10, 11, 12, 13],
    "slack_sec": 7200,
    "rule": (
        "Keep a ResiliMES arm only when, on both books, on-time lots are not "
        "fewer and re-cleans and Q-time violations are not higher than the control."
    ),
    "xfactor": {
        "due_per_seed": 87,
        "control": {"on_time": 407, "qtime": 2223, "recleans": 223, "decision": "baseline"},
        "expose_due_in_dpi": {
            "on_time": 420,
            "qtime": 2148,
            "recleans": 208,
            "decision": "revert",
        },
        "dry_etch_queue_gate": {
            "on_time": 407,
            "qtime": 2198,
            "recleans": 213,
            "decision": "revert",
        },
        "slack_7200": {"on_time": 407, "qtime": 2223, "recleans": 223, "decision": "keep"},
    },
    "published": {
        "due_per_seed": 56,
        "control": {"on_time": 156, "qtime": 1821, "recleans": 131, "decision": "baseline"},
        "expose_due_in_dpi": {
            "on_time": 155,
            "qtime": 1862,
            "recleans": 147,
            "decision": "revert",
        },
        "dry_etch_queue_gate": {
            "on_time": 156,
            "qtime": 1850,
            "recleans": 131,
            "decision": "revert",
        },
        "slack_7200": {"on_time": 156, "qtime": 1821, "recleans": 131, "decision": "keep"},
    },
}


def main() -> None:
    fab = load_fab()
    _FABS["base"] = fab
    _FABS["xfactor"] = apply_xfactor(fab)
    _FABS["tight"] = apply_tight(fab, horizon=TIGHT_HORIZON_SEC).fab
    print(f"{_WORKERS} workers", flush=True)
    aps_ms, scanner_steps = macro_aps_ms(fab)
    horizon = STUDY_HORIZON_SEC
    print(f"APS {aps_ms:.1f} ms, {scanner_steps} scanner steps", flush=True)
    steady = _matrix(fab, horizon, ("resilimes", "edd", "fifo", "cr", "smt_rule"), kind="steady")
    litho = _matrix(fab, horizon, ("resilimes", "edd"), kind="litho")
    pm = _matrix(fab, horizon, ("resilimes", "edd"), kind="pm")
    hot = _matrix(fab, horizon, ("resilimes", "fifo"), kind="hot")
    still = _matrix(
        fab, horizon, ("resilimes", "edd", "fifo", "cr", "smt_rule"), kind="no_transport"
    )
    payload = {
        "horizon_h": horizon / 3600.0,
        "seeds": list(SEEDS),
        "counts": {
            "groups": len(fab.families),
            "tools": len(fab.tool_name),
            "litho_tools": fab.litho_tools,
            "scanner_tools": fab.scanner_tools,
            "products": fab.products,
            "lots": len(fab.lot_id),
            "station_groups": len(fab.group_names),
        },
        "focus_tool": fab.tool_name[fab.focus_tool],
        "focus_family": fab.families[fab.focus_family].name,
        "hot_lot": fab.lot_id[fab.hot_lot],
        "pm_calendar": fab.pm_calendar,
        "aps_ms": round(aps_ms, 1),
        "scanner_steps": scanner_steps,
        "steady": _pack(steady),
        "litho": _pack(litho),
        "pm": _pack(pm),
        "hot": _pack(hot),
        "steady_no_transport": _pack(still),
        "tight": _pack(_tight_matrix(fab)),
        "xfactor": _xfactor(fab),
        "repair_mc": _repair_mc(),
        "price": _prices(fab),
        "heldout_seeds_9_13": _heldout_control(fab),
    }
    json_path = ROOT / "data" / "smt2020" / "benchmark.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    doc = ROOT / "docs" / "SMT2020_SCALE.md"
    doc.write_text(_markdown(payload), encoding="utf-8")
    print(f"wrote {json_path}", flush=True)
    print(f"wrote {doc}", flush=True)


def _tight_matrix(fab: Any) -> dict[str, list[RunResult]]:
    """24-hour constructed dues. Not the published order book."""
    found: dict[str, list[RunResult]] = {
        policy: [] for policy in ("resilimes", "edd", "fifo", "cr")
    }
    horizon = TIGHT_HORIZON_SEC
    book = apply_tight(fab, horizon=horizon)
    _FABS.setdefault("tight", book.fab)
    keys: list[str] = []
    items: list[tuple[str, dict[str, Any]]] = []
    for seed in SEEDS:
        downs = sample_downs(book.fab, seed, horizon)
        downs[book.down_tool].append((0.0, min(book.down_until, horizon)))
        pm = pm_windows(book.fab, horizon)
        for policy in found:
            keys.append(policy)
            items.append(
                (
                    "tight",
                    {
                        "policy": policy,
                        "seed": seed,
                        "horizon": horizon,
                        "downs": downs,
                        "pm": pm,
                        "trace": False,
                        "watch": book.watch,
                    },
                )
            )
    print(f"tight: {len(items)} runs", flush=True)
    return _collect(keys, _run_all(items), found)


def _matrix(
    fab: Any,
    horizon: float,
    policies: tuple[str, ...],
    *,
    kind: str,
) -> dict[str, list[RunResult]]:
    found: dict[str, list[RunResult]] = {policy: [] for policy in policies}
    forced_until = LITHO_MTTR_MIN * 60.0 if kind == "litho" else 0.0
    shift = pm_shift_to_open(fab, fab.pm_calendar, 2 * 3600.0) if kind == "pm" else 0.0
    _FABS.setdefault("base", fab)
    keys: list[str] = []
    items: list[tuple[str, dict[str, Any]]] = []
    for seed in SEEDS:
        downs = sample_downs(
            fab,
            seed,
            horizon,
            forced_tool=fab.focus_tool if kind == "litho" else None,
            forced_until=forced_until,
        )
        pm = pm_windows(fab, horizon, shift_sec=shift)
        for policy in policies:
            keys.append(policy)
            items.append(
                (
                    "base",
                    {
                        "policy": policy,
                        "seed": seed,
                        "horizon": horizon,
                        "downs": downs,
                        "pm": pm,
                        "hot_lot": fab.hot_lot if kind == "hot" else None,
                        "hot_due": 12 * 3600.0 if kind == "hot" and policy == "resilimes" else None,
                        "promote_hot": kind == "hot" and policy == "resilimes",
                        "trace": False,
                        "focus_down_until": forced_until,
                        "transport": kind != "no_transport",
                    },
                )
            )
    print(f"{kind}: {len(items)} runs", flush=True)
    return _collect(keys, _run_all(items), found)


def _xfactor(fab: Fab) -> dict[str, Any]:
    """Dues at 2.75 x remaining process. One scanner held for a fixed ETA."""
    plant = apply_xfactor(fab)
    _FABS.setdefault("xfactor", plant)
    horizon = STUDY_HORIZON_SEC
    due = sum(1 for due_at in plant.lot_due if due_at <= horizon)
    found: dict[str, Any] = {
        "factor": X_FACTOR,
        "horizon_h": horizon / 3600.0,
        "due_in_horizon": due,
        "rework_min": REWORK_SEC / 60.0,
        "etas": {},
    }
    for eta in _X_ETAS:
        policies = (
            ("resilimes", "edd", "fifo", "cr", "smt_rule")
            if eta == 600.0
            else ("resilimes", "edd", "smt_rule")
        )
        rows: dict[str, list[RunResult]] = {policy: [] for policy in policies}
        keys: list[str] = []
        items: list[tuple[str, dict[str, Any]]] = []
        for seed in SEEDS:
            downs = sample_downs(
                plant,
                seed,
                horizon,
                forced_tool=plant.focus_tool,
                forced_until=eta * 60.0,
            )
            pm = pm_windows(plant, horizon)
            for policy in policies:
                keys.append(policy)
                items.append(
                    (
                        "xfactor",
                        {
                            "policy": policy,
                            "seed": seed,
                            "horizon": horizon,
                            "downs": downs,
                            "pm": pm,
                            "trace": False,
                            "focus_down_until": eta * 60.0,
                        },
                    )
                )
        print(f"xfactor eta {eta}: {len(items)} runs", flush=True)
        _collect(keys, _run_all(items), rows)
        found["etas"][str(eta)] = _pack(rows, spread=True)
    found["scanner_family_util_edd_seed1"] = _scanner_family_util(fab, plant, horizon)
    return found


def _scanner_family_util(fab: Fab, plant: Fab, horizon: float) -> list[dict[str, Any]]:
    eta = 600.0 * 60.0
    downs = sample_downs(plant, 1, horizon, forced_tool=plant.focus_tool, forced_until=eta)
    result = run_policy(
        plant,
        policy="edd",
        seed=1,
        horizon=horizon,
        downs=downs,
        pm=pm_windows(plant, horizon),
        trace=True,
        focus_down_until=eta,
    )
    rows: list[dict[str, Any]] = []
    for fam, family in enumerate(fab.families):
        if not family.scanner:
            continue
        busy = sum(result.occupancy[fam]) if result.occupancy else 0.0
        rows.append(
            {
                "family": family.name,
                "tools": family.tools,
                "util_pct": round(100.0 * busy / (family.tools * horizon), 1),
            }
        )
    rows.sort(key=lambda item: float(item["util_pct"]), reverse=True)
    return rows


def _repair_mc() -> dict[str, float]:
    """10,000 exponential draws of the published lithography MTTR. Minutes."""
    rng = random.Random(1)
    draws = sorted(rng.expovariate(1.0 / LITHO_MTTR_MIN) for _ in range(10_000))

    def quantile(fraction: float) -> float:
        return round(draws[min(len(draws) - 1, int(fraction * len(draws)))], 1)

    return {
        "draws": 10000,
        "mean_min": round(mean(draws), 1),
        "std_min": round(pstdev(draws), 1),
        "p50_min": quantile(0.50),
        "p90_min": quantile(0.90),
        "p_le_180": round(sum(item <= 180 for item in draws) / len(draws), 3),
        "p_le_300": round(sum(item <= 300 for item in draws) / len(draws), 3),
        "p_le_600": round(sum(item <= 600 for item in draws) / len(draws), 3),
    }


def _prices(fab: Fab) -> dict[str, Any]:
    print("price tight seed 1", flush=True)
    tight = simulate_pair(fab, SCENARIOS["tight_p1"], seed=1, horizon=TIGHT_HORIZON_SEC)
    print("price xfactor seed 1", flush=True)
    xf = simulate_pair(fab, SCENARIOS["xfactor"], seed=1, horizon=STUDY_HORIZON_SEC)
    return {"tight_seed1": _price_public(tight), "xfactor_seed1": _price_public(xf)}


def _price_public(report: dict[str, Any]) -> dict[str, Any]:
    price = report["price"]
    return {
        "lots": price["lots"],
        "extra_h": price["extra_h"],
        "worst": price["worst"],
        "otd_before": report["kpis"]["before"]["on_time_pct"],
        "otd_after": report["kpis"]["after"]["on_time_pct"],
        "q_before": report["kpis"]["before"]["qtime_violations"],
        "q_after": report["kpis"]["after"]["qtime_violations"],
        "spotlight_lot": (report.get("tight") or {}).get("spotlight_lot"),
        "spotlight_late_h_before": (report.get("tight") or {}).get("spotlight_late_h_before"),
        "spotlight_late_h_after": (report.get("tight") or {}).get("spotlight_late_h_after"),
        "xfactor": report.get("xfactor"),
    }


def _pack(rows: dict[str, list[RunResult]], *, spread: bool = False) -> dict[str, Any]:
    packed: dict[str, Any] = {}
    for policy, runs in rows.items():
        body: dict[str, Any] = {
            "mean": {key: _mean(runs, key) for key in _KEYS},
            "seeds": [_public(item) for item in runs],
        }
        if spread:
            body["std"] = {key: _std(runs, key) for key in _KEYS}
        packed[policy] = body
    return packed


def _public(result: RunResult) -> dict[str, Any]:
    row = {key: getattr(result, key) for key in ("seed", *_KEYS)}
    row["batch_reasons"] = dict(result.batch_reasons)
    row["class_wait_min"] = dict(result.class_wait_min)
    row["qtime_override_displaced"] = dict(result.qtime_override_displaced)
    return row


_LATENCY = {"dispatch_p50_ms", "dispatch_p95_ms", "dispatch_busy_p50_ms", "dispatch_busy_p95_ms"}


def _mean(runs: list[RunResult], key: str) -> float | None:
    values = [getattr(item, key) for item in runs if getattr(item, key) is not None]
    if not values:
        return None
    digits = 4 if key in _LATENCY else 3
    return round(float(mean(values)), digits)


def _std(runs: list[RunResult], key: str) -> float | None:
    values = [getattr(item, key) for item in runs if getattr(item, key) is not None]
    if len(values) < 2:
        return None
    digits = 4 if key in _LATENCY else 3
    return round(float(pstdev(values)), digits)


def _count(pct: float, denom: int) -> int:
    return round(pct / 100.0 * denom)


def _seed_otd(block: dict[str, Any]) -> str:
    lines = [
        "Per seed, on time / lots due. Re-cleans, Q-time, and weighted tardiness are that seed.",
        "",
        "| Policy | Seed | On time | Q-time | Re-cleans | Weighted tardiness min |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for policy, body in block.items():
        for item in body.get("seeds") or []:
            denom = int(item["due_in_horizon"])
            num = _count(float(item["on_time_pct"]), denom)
            lines.append(
                f"| {policy} | {item['seed']} | {num}/{denom} | "
                f"{item['qtime_violations']} | {item['recleans']} | "
                f"{item['weighted_tardiness_min']} |"
            )
    return "\n".join(lines)


def _pooled(block: dict[str, Any], policy: str) -> str:
    seeds = block[policy]["seeds"]
    num = sum(_count(float(item["on_time_pct"]), int(item["due_in_horizon"])) for item in seeds)
    den = sum(int(item["due_in_horizon"]) for item in seeds)
    rendered = ", ".join(
        f"{_count(float(item['on_time_pct']), int(item['due_in_horizon']))}/{item['due_in_horizon']}"
        for item in seeds
    )
    return f"{rendered} ({num}/{den} pooled)"


def _trade(payload: dict[str, Any]) -> str:
    """First screen. X-factor, then published dues, then the rewritten tight book."""
    xf = payload["xfactor"]["etas"]["600.0"]
    due = payload["xfactor"]["due_in_horizon"]
    res = xf["resilimes"]["mean"]
    edd = xf["edd"]["mean"]
    fifo = xf["fifo"]["mean"]
    cr = xf["cr"]["mean"]
    tight_res = payload["tight"]["resilimes"]["seeds"][0]
    tight_edd = payload["tight"]["edd"]["seeds"][0]
    published = payload["steady"]
    gap = _pooled_count(xf, "edd") - _pooled_count(xf, "resilimes")
    seeds = len(xf["resilimes"]["seeds"])
    if gap > 0:
        versus = f"Versus EDD it gives up {gap} of {due * seeds} pooled lots"
    elif gap < 0:
        versus = f"Versus EDD it gains {-gap} of {due * seeds} pooled lots"
    else:
        versus = "Versus EDD it ties on pooled on-time lots"
    return (
        "## The trade\n\n"
        f"X-factor dues, 48 hours, {due} lots. {_eta_sameness(payload)} "
        f"ResiliMES {_pooled(xf, 'resilimes')}, mean {res['on_time_pct']}%. "
        f"EDD {_pooled(xf, 'edd')}, mean {edd['on_time_pct']}%. "
        f"FIFO mean {fifo['on_time_pct']}%. CR mean {cr['on_time_pct']}%. "
        "ResiliMES beats FIFO and CR by a wide margin. "
        f"{versus}, with re-cleans {res['recleans']} against {edd['recleans']} "
        f"and Q-time violations {res['qtime_violations']} against "
        f"{edd['qtime_violations']} (five-seed means).\n\n"
        "Published dues, 48 hours, 56 lots. "
        f"ResiliMES {_pooled(published, 'resilimes')}, "
        f"mean {published['resilimes']['mean']['on_time_pct']}%. "
        f"EDD {_pooled(published, 'edd')}, "
        f"mean {published['edd']['mean']['on_time_pct']}%. "
        f"{_published_order(published)}\n\n"
        "Tight VIP dues rewrites the dues for the stress test. It is not the "
        "published order book. Denominator 21 lots. "
        f"ResiliMES {_pooled(payload['tight'], 'resilimes')}. "
        f"EDD {_pooled(payload['tight'], 'edd')}. "
        f"FIFO {_pooled(payload['tight'], 'fifo')}. "
        f"CR {_pooled(payload['tight'], 'cr')}. "
        f"Seed 1 weighted tardiness is {tight_edd['weighted_tardiness_min']} "
        f"under EDD and {tight_res['weighted_tardiness_min']} under ResiliMES. "
        "The 12-hour lithography click is one seed. "
        "It is not the 48-hour lithography study in the appendix.\n\n"
        "Every number in this file comes from the simulator after the stale-queue "
        "fix. Before it, a lot that had already started could stay in its old "
        "family queue and start its next step on a tool of the wrong family. "
        "The trace checker and the pre-fix numbers are in [invariants.md](invariants.md). "
        "It also includes the fab-logic-r1 operation logic: every lot chosen for a "
        "batch starts, same-recipe lots batch across operation numbers under a wait "
        "rule, setup time is charged, a breakdown sends the lot in process to rework, "
        "sampled metrology is skipped by a lot-ID rule, and ResiliMES ranks by class "
        "tier first. Old against new numbers are in [FAB_LOGIC_R1.md](FAB_LOGIC_R1.md)."
    )


def _pooled_count(block: dict[str, Any], policy: str) -> int:
    return sum(
        _count(float(item["on_time_pct"]), int(item["due_in_horizon"]))
        for item in block[policy]["seeds"]
    )


def _published_order(block: dict[str, Any]) -> str:
    res = _pooled_count(block, "resilimes")
    edd = _pooled_count(block, "edd")
    if res == edd:
        return "ResiliMES and EDD tie on pooled on-time lots."
    if edd > res:
        return f"EDD is ahead by {edd - res} pooled lots."
    return f"ResiliMES is ahead by {res - edd} pooled lots."


def _eta_sameness(payload: dict[str, Any]) -> str:
    """Say whether the on-time row moves with the repair time, from the rows."""
    etas = payload["xfactor"]["etas"]
    same: list[str] = []
    moved: list[str] = []
    for policy in ("resilimes", "edd"):
        rows = {
            tuple(
                _count(float(item["on_time_pct"]), int(item["due_in_horizon"]))
                for item in block[policy]["seeds"]
            )
            for block in etas.values()
            if policy in block
        }
        (same if len(rows) == 1 else moved).append("ResiliMES" if policy == "resilimes" else "EDD")
    minutes = ", ".join(str(eta).removesuffix(".0") for eta in etas)
    if not moved:
        return f"On-time for ResiliMES and EDD is the same at a {minutes} minute repair."
    if not same:
        return f"On-time moves with the repair time ({minutes} minutes) for both policies."
    return (
        f"On-time is the same at a {minutes} minute repair for {same[0]} and moves for {moved[0]}."
    )


def _busy_latency(payload: dict[str, Any]) -> str:
    seeds = payload["xfactor"]["etas"]["600.0"]["resilimes"]["seeds"]
    p50 = [item.get("dispatch_busy_p50_ms") for item in seeds]
    p95 = [item.get("dispatch_busy_p95_ms") for item in seeds]
    if any(value is None for value in p50 + p95):
        return ""
    return (
        "Nonempty-queue decisions on the X-factor ResiliMES runs, seeds 1-5, "
        f"were p50 {min(p50)}-{max(p50)} ms and p95 {min(p95)}-{max(p95)} ms on this run. "
    )


def _transport_note(payload: dict[str, Any]) -> str:
    """Published book with and without the fixed lot transport, seeds 1-5."""
    off = payload.get("steady_no_transport")
    if not off:
        return ""
    lines = [
        "### Lot transport (published book, with and without)",
        "",
        "Every table above moves a lot 1 min to a family in the same STNGRP bay "
        "and 3 min to another bay, for every policy. This ablation turns the move "
        "off and changes nothing else.",
        "",
        "| Policy | On-time with | On-time without | Q-time with | Q-time without "
        "| Re-cleans with | Re-cleans without | Cycle h with | Cycle h without |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for policy, body in payload["steady"].items():
        if policy not in off:
            continue
        on, no = body["mean"], off[policy]["mean"]
        lines.append(
            f"| {policy} | {on['on_time_pct']:.1f}% | {no['on_time_pct']:.1f}% "
            f"| {on['qtime_violations']:.1f} | {no['qtime_violations']:.1f} "
            f"| {on['recleans']:.1f} | {no['recleans']:.1f} "
            f"| {on['cycle_time_h']:.2f} | {no['cycle_time_h']:.2f} |"
        )
    return "\n".join(lines)


def _markdown(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    lines = [
        "# SMT2020 full-fab measurements",
        "",
        "Public industry benchmark (SMT2020). Source: Kopp, Hassoun, Kalir, and "
        "Mönch, IEEE Trans. Semicond. Manuf. 33(4), 2020, doi "
        "10.1109/TSM.2020.3001933. PySCFabSim-release commit `0dbff6a`, "
        "directory `datasets/SMT2020_LVHM`. This is not a recording from a "
        "production fab.",
        "",
        f"Fab: {counts['groups']} station families, {counts['tools']} tools, "
        f"{counts['litho_tools']} `Litho_*` tools "
        f"({counts['scanner_tools']} expose scanners plus "
        f"{counts['litho_tools'] - counts['scanner_tools']} `Litho_REG`), "
        f"{counts['products']} products, {counts['lots']} initial WIP lots, "
        f"{counts['station_groups']} station groups. "
        "`Delay_32` is included (400 tools, 147 route steps).",
        "",
        _trade(payload),
        "",
        "The tight VIP table is 24 hours. The appendix is "
        f"{payload['horizon_h']:.0f} hours from 2018-01-01 00:00 UTC. "
        f"Seeds: {', '.join(str(item) for item in payload['seeds'])}. "
        "Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. "
        "The same draw is shared across policies.",
        "",
        f"Macro APS places {payload['scanner_steps']} scanner steps. "
        "That step count is the stable spec. "
        f"The timer is about 0.3 s on the CI VM (this run recorded {payload['aps_ms']} ms).",
        "",
        "Dispatch latency is the time to choose the next lot for one idle tool, "
        "look-ahead 24 (8 when that family's queue exceeds two lots per tool). "
        "The headline p50/p95 includes empty wakes. "
        f"{_busy_latency(payload)}"
        "It is not the full simulation time. Simulation time is the whole 48-hour run.",
        "",
        "The WIP column is a candidate cap, not a replan. "
        "`choose()` keeps 8 lots instead of 24 after a family exceeds "
        "max(8, two lots per tool), and also keeps a lot whose slack is at or "
        "under 7200 seconds. "
        "The adjacent Wet_Etch look-ahead fired 0 times on these books. "
        "`macro_aps_ms` does not feed `dpi()`. "
        "`rank()` for resilimes uses `tiered_key`: class tier, late band, "
        "Q-time risk, setup, then slack. `dispatch_score` is no longer used there. "
        "A down tool queues the end of every covering window, so a forced outage "
        "that overlaps an MTTF draw still releases at the later end. "
        "Seeds 1-5 on-time on the books below match the figures in this file.",
        "",
        "On-time percent uses lots whose due is at or before the horizon. "
        "A lot is on time only if its route finishes at or before the due. "
        "Lots already due at the snapshot stay in the denominator. "
        "Weighted tardiness is lot value times minutes late. "
        "An open lot is censored at the horizon. "
        "Cycle time is the mean completion time of lots that finish the route. "
        "X-factor is that completion time divided by the lot's remaining raw "
        "process time at the snapshot. "
        "Litho utilization is busy time on the 102 `Litho_*` tools divided by "
        "tools times horizon. Scanner utilization uses the 82 expose tools. "
        "Q-time violations are published CQT misses. "
        "PM avoided counts decisions, on every policy, that refused at least one "
        "lot because the process would cross a PM. "
        "PM overlaps are starts that still run across a PM.",
        "",
        "The weekly PM FOA on the focus family is outside a 48-hour window "
        "(about 7 days). The steady and litho studies therefore show zero PM "
        "events. The PM study subtracts one offset from every day-based calendar "
        "so `Litho_FE_92_WK` opens at 2 hours. Duration and interval stay published. "
        "One FOA is stored per family, so every tool in the family shares that window.",
        "",
        f"Lithography breakdown holds `{payload['focus_tool']}` "
        f"(`{payload['focus_family']}`, largest expose family) "
        f"for the published lithography MTTR of {LITHO_MTTR_MIN} minutes, "
        "on top of the seeded breakdowns.",
        "",
        f"Hot lot `{payload['hot_lot']}` is the lowest lot id among normal-priority "
        "lots sitting four steps before an expose scanner. The ResiliMES book "
        "raises it to VIP with a due 12 hours from the snapshot. FIFO keeps "
        "the published priority.",
        "",
        "## Tight VIP dues (constructed, 24 hours)",
        "",
        "The published dues do not make earliest-due lose on on-time delivery. "
        "This book keeps the routes, process times, setups, and CQT limits, and "
        "replaces the dues used for scoring. Eight lots waiting at "
        f"`Dielectric_BE_28` with a later CQT become VIP and are due at 8 hours. "
        "The other lots in that queue stay normal and are due at 7.2 hours, so "
        "earliest-due serves them first. Every other lot still moves through the "
        "fab and is outside the scored horizon. `Dielectric_BE_28-1` is down for "
        f"the published dielectric MTTR of {DIELECTRIC_MTTR_MIN} minutes. "
        "The family has three tools. Horizon is 24 hours, five seeds.",
        "",
        _table(payload["tight"]) if payload.get("tight") else "_Not measured._",
        "",
        _seed_otd(payload["tight"]) if payload.get("tight") else "",
        "",
        _tight_price(payload),
        "",
        "## X-factor dues (48 hours)",
        "",
        _xfactor_prose(payload),
        "",
        _xfactor_table(payload),
        "",
        _seed_otd(payload["xfactor"]["etas"]["600.0"]),
        "",
        _eta_sameness(payload),
        "",
        _xfactor_price(payload),
        "",
        "## Appendix: published order book (performance)",
        "",
        _published_lead(payload),
        "",
        _seed_otd(payload["steady"]) if payload.get("steady") else "",
        "",
        "### Steady fab (seeded breakdowns, published PM calendar unshifted)",
        "",
        _table(payload["steady"]),
        "",
        _smt_rule_note(payload),
        "",
        "### Lithography breakdown",
        "",
        _table(payload["litho"]),
        "",
        _litho_note(payload),
        "",
        "### PM avoidance (calendar shifted, durations unchanged)",
        "",
        _table(payload["pm"]),
        "",
        "### Hot lot",
        "",
        _table(payload["hot"]),
        "",
        _hot_note(payload),
        "",
        _transport_note(payload),
        "",
        _heldout(payload),
        "",
        "Per-seed rows are in `data/smt2020/benchmark.json`. Regenerate with `make smt-bench`.",
        "What the extract contains, and what this simulator leaves out, is "
        "[SMT2020_PROVENANCE.md](SMT2020_PROVENANCE.md).",
        "",
    ]
    return "\n".join(lines)


_HELDOUT_SEEDS = (9, 10, 11, 12, 13)


def _heldout_control(fab: Fab) -> dict[str, Any]:
    """Recompute the shipped score on seeds 9-13. The arm table stays a lab note.

    Policies are resilimes, edd, fifo, and cr. The expose-due and dry-etch arms
    are not in this code, so they are not recomputed.
    """
    policies = ("resilimes", "edd", "fifo", "cr")
    books: dict[str, Any] = {}
    horizon = STUDY_HORIZON_SEC
    for name in ("xfactor", "published"):
        plant = apply_xfactor(fab) if name == "xfactor" else fab
        rows: dict[str, dict[str, Any]] = {
            policy: {"on_time": 0, "due": 0, "qtime": 0, "recleans": 0, "per_seed": []}
            for policy in policies
        }
        _FABS.setdefault(name if name == "xfactor" else "base", plant)
        keys: list[str] = []
        items: list[tuple[str, dict[str, Any]]] = []
        for seed in _HELDOUT_SEEDS:
            downs = sample_downs(
                plant,
                seed,
                horizon,
                forced_tool=plant.focus_tool if name == "xfactor" else None,
                forced_until=600.0 * 60.0 if name == "xfactor" else 0.0,
            )
            pm = pm_windows(plant, horizon)
            for policy in policies:
                keys.append(policy)
                items.append(
                    (
                        name if name == "xfactor" else "base",
                        {
                            "policy": policy,
                            "seed": seed,
                            "horizon": horizon,
                            "downs": downs,
                            "pm": pm,
                            "trace": False,
                            "focus_down_until": 600.0 * 60.0 if name == "xfactor" else 0.0,
                        },
                    )
                )
        print(f"heldout {name}: {len(items)} runs", flush=True)
        for policy, result in zip(keys, _run_all(items), strict=True):
            num = _count(result.on_time_pct, result.due_in_horizon)
            rows[policy]["on_time"] += num
            rows[policy]["due"] += result.due_in_horizon
            rows[policy]["qtime"] += result.qtime_violations
            rows[policy]["recleans"] += result.recleans
            rows[policy]["per_seed"].append(f"{num}/{result.due_in_horizon}")
        books[name] = rows
    return {
        "seeds": list(_HELDOUT_SEEDS),
        "regenerated_by": "make smt-bench",
        "books": books,
        "lab_note": _HELDOUT,
    }


def _heldout(payload: dict[str, Any]) -> str:
    """Seeds 9-13. The control is regenerated. The arm table is a lab note."""
    fresh = _heldout_fresh(payload.get("heldout_seeds_9_13") or {})
    lab = """## Seeds 9-13 arm decisions (pre-fix lab note, not regenerated by make smt-bench)

The rows below are the one-shot recorded before `make smt-bench` regenerated the control, and before the stale-queue fix in [invariants.md](invariants.md). They were measured on the simulator that let a lot start a step on a tool of the wrong family. The expose-due and dry-etch arms are not in the code, so this command does not recompute them. Do not read the lab-note control as the current score. The current score is the regenerated table above.

Registered before that one-shot. Seeds 9, 10, 11, 12, 13. X-factor book: due = remaining process times 2.75, 48 hours, 87 lots due, `Litho_FE_92-1` down 600 minutes. Published-due book: 48 hours, 56 lots due. Policies: ResiliMES, EDD, FIFO, CR. Slack threshold 7200 seconds. Keep a ResiliMES arm only when, on both books, the on-time lot count is not lower and re-cleans are not higher and Q-time violations are not higher than the control. EDD, FIFO, and CR matched the control on every arm.

Control in this lab note is the score shipped at that one-shot: lot due inside `dpi()`, the Wet_Etch gate, and the candidate cap. Sums are five seeds.

| Book | Arm | Decision | On time | Q-time | Re-cleans |
| --- | --- | --- | ---: | ---: | ---: |
| X-factor | control |  | 407/435 | 2223 | 223 |
| X-factor | expose due inside dpi() | revert | 420/435 | 2148 | 208 |
| X-factor | dry-etch queue gate | revert | 407/435 | 2198 | 213 |
| X-factor | slack at or under 7200 s stays | keep | 407/435 | 2223 | 223 |
| Published | control |  | 156/280 | 1821 | 131 |
| Published | expose due inside dpi() | revert | 155/280 | 1862 | 147 |
| Published | dry-etch queue gate | revert | 156/280 | 1850 | 131 |
| Published | slack at or under 7200 s stays | keep | 156/280 | 1821 | 131 |

The expose-step due raised X-factor on-time and cut re-cleans and Q-time, and lost one published-due lot (156 to 155) while raising that book's Q-time and re-cleans. Reverted. `dpi()` still uses the lot due. At that one-shot `rank()` called `dispatch_score`; since fab-logic-r1 it uses `tiered_key`.

The dry-etch gate, aimed at the 44 adjacent 1-hour Dry_Etch to Wet_Etch pairs and counting lots already queued downstream, held X-factor on-time and cut that book's Q-time (2223 to 2198) and re-cleans (223 to 213). Published-due on-time stayed 156/280 and Q-time rose from 1821 to 1850. Reverted. The Wet_Etch gate remains, and it fired 0 times on the books above.

The slack exception matched the control on every seed of both books. It stays in `choose()`.

Per seed, ResiliMES on time, X-factor control: 82/87, 74/87, 87/87, 87/87, 77/87. Expose due: 82/87, 87/87, 87/87, 87/87, 77/87. Dry-etch: 82/87, 74/87, 87/87, 87/87, 77/87. Slack: same as control.

Per seed, ResiliMES on time, published control: 32/56, 31/56, 32/56, 32/56, 29/56. Expose due: 32/56, 31/56, 32/56, 32/56, 28/56. Dry-etch and slack: same as control."""
    if not fresh:
        return lab
    return fresh + "\n\n" + lab


def _heldout_fresh(block: dict[str, Any]) -> str:
    if block.get("regenerated_by") != "make smt-bench":
        return ""
    lines = [
        "## Seeds 9-13 control (regenerated by make smt-bench)",
        "",
        "Shipped score only. Seeds 9, 10, 11, 12, 13. "
        "X-factor book: due = remaining process times 2.75, 48 hours, "
        "`Litho_FE_92-1` down 600 minutes. "
        "Published-due book: 48 hours, published dues. "
        "PM refusal applies to every policy. "
        "This table is recomputed by `make smt-bench`.",
        "",
        "| Book | Policy | On time | Q-time | Re-cleans | Per seed |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    books = block.get("books") or {}
    for book, rows in books.items():
        for policy, item in rows.items():
            per_seed = ", ".join(item.get("per_seed") or [])
            lines.append(
                f"| {book} | {policy} | {item['on_time']}/{item['due']} | "
                f"{item['qtime']} | {item['recleans']} | {per_seed} |"
            )
    return "\n".join(lines)


def _smt_rule_note(payload: dict[str, Any]) -> str:
    """Report smt_rule against ResiliMES from the rows this run wrote."""
    steady = payload.get("steady") or {}
    if "smt_rule" not in steady or "resilimes" not in steady:
        return ""
    res = steady["resilimes"]["mean"]
    rule = steady["smt_rule"]["mean"]
    published = _rule_vs(res, rule, "published dues")
    xf_block = ((payload.get("xfactor") or {}).get("etas") or {}).get("600.0") or {}
    xf = ""
    if "smt_rule" in xf_block and "resilimes" in xf_block:
        xf = " " + _rule_vs(
            xf_block["resilimes"]["mean"],
            xf_block["smt_rule"]["mean"],
            "X-factor dues at a 600-minute repair",
        )
    return (
        "`smt_rule` is `rule_HotLotFIRST` with `rank_HP;rank_RSETUP;rank_CR` "
        "(PRIOR at least 20 first, then higher PRIOR, then shorter setup, then lower CR). "
        "Implant_128, Implant_132, and Implant_91 use `rule_LSSU` (setup first, then that cascade). "
        "The idle-tool loop still picks the tool. `wake_LeastSetupTime` is not implemented. "
        f"{published}{xf} "
        "These rows were not tuned after the run."
    )


def _rule_vs(res: dict[str, Any], rule: dict[str, Any], book: str) -> str:
    res_otd = res["on_time_pct"]
    rule_otd = rule["on_time_pct"]
    if rule_otd > res_otd:
        delivery = f"On {book}, smt_rule on-time {rule_otd}% beats ResiliMES {res_otd}%."
    elif rule_otd < res_otd:
        delivery = f"On {book}, ResiliMES on-time {res_otd}% beats smt_rule {rule_otd}%."
    else:
        delivery = f"On {book}, smt_rule and ResiliMES tie on on-time at {res_otd}%."
    return (
        f"{delivery} Weighted tardiness is {rule['weighted_tardiness_min']} minutes "
        f"under smt_rule and {res['weighted_tardiness_min']} under ResiliMES. "
        f"Q-time is {rule['qtime_violations']} against {res['qtime_violations']}. "
        f"Re-cleans are {rule['recleans']} against {res['recleans']}."
    )


def _published_lead(payload: dict[str, Any]) -> str:
    res = payload["steady"]["resilimes"]["mean"]
    edd = payload["steady"]["edd"]["mean"]
    if res["on_time_pct"] == edd["on_time_pct"]:
        delivery = "ResiliMES and EDD tie on on-time delivery."
    elif edd["on_time_pct"] > res["on_time_pct"]:
        delivery = (
            f"EDD is slightly ahead of ResiliMES on on-time delivery "
            f"({edd['on_time_pct']}% against {res['on_time_pct']}%)."
        )
    else:
        delivery = (
            f"ResiliMES is ahead of EDD on on-time delivery "
            f"({res['on_time_pct']}% against {edd['on_time_pct']}%)."
        )
    if edd["weighted_tardiness_min"] < res["weighted_tardiness_min"]:
        tardiness = (
            f"EDD weighted tardiness is {edd['weighted_tardiness_min']} minutes "
            f"against {res['weighted_tardiness_min']}."
        )
    else:
        tardiness = (
            f"ResiliMES weighted tardiness is {res['weighted_tardiness_min']} minutes "
            f"against {edd['weighted_tardiness_min']}."
        )
    return (
        "On the published dues, a 48-hour horizon, "
        f"{delivery} {tardiness} "
        "These tables are runtime and knock-on measurements. "
        "They are not the claim that earliest-due loses."
    )


def _litho_note(payload: dict[str, Any]) -> str:
    block = payload["litho"]
    res = block["resilimes"]["mean"]
    edd = block["edd"]["mean"]
    return (
        f"While `{payload['focus_tool']}` is down, other tools in "
        f"`{payload['focus_family']}` start {res['sibling_starts']} lots under "
        f"ResiliMES and {edd['sibling_starts']} under EDD (five-seed mean). "
        f"The family queue peaks at {res['focus_queue_max']} lots. "
        f"The downstream queue peaks at {res['downstream_queue_max']} under "
        f"ResiliMES and {edd['downstream_queue_max']} under EDD. "
        f"On-time uses {res['due_in_horizon']} lots due inside the horizon, "
        f"of which {res['already_late']} are already late at the snapshot. "
        "The interactive lithography click is 12 hours and seed 1, and the two "
        "policies tie there at 2/19. That click is not this 48-hour table."
    )


def _hot_note(payload: dict[str, Any]) -> str:
    block = payload["hot"]
    res = block["resilimes"]["mean"]
    fifo = block["fifo"]["mean"]
    return (
        f"`{payload['hot_lot']}` completes {res['hot_steps']} steps under "
        f"ResiliMES and {fifo['hot_steps']} under FIFO. "
        f"Promoting it moves the on-time denominator to {res['due_in_horizon']} "
        f"lots ({fifo['due_in_horizon']} on the FIFO book)."
    )


def _tight_price(payload: dict[str, Any]) -> str:
    price = (payload.get("price") or {}).get("tight_seed1")
    if not price:
        return ""
    worst = ", ".join(f"{item['lot_id']} +{item['extra_h']} h" for item in price["worst"])
    spot = price.get("spotlight_lot") or "the spotlight lot"
    return (
        f"Seed 1, who paid: {price['lots']} non-hot lots in that queue finish "
        f"{price['extra_h']} hours later under ResiliMES than under EDD"
        f"{f' ({worst})' if worst else ''}. "
        f"{spot} is {price['spotlight_late_h_before']} h late under EDD and "
        f"{price['spotlight_late_h_after']} h late under ResiliMES. "
        f"On-time on this seed is {price['otd_before']}% under EDD and "
        f"{price['otd_after']}% under ResiliMES. "
        f"Queue-time violations are {price['q_before']} and {price['q_after']}."
    )


def _xfactor_prose(payload: dict[str, Any]) -> str:
    block = payload["xfactor"]
    repair = payload["repair_mc"]
    families = block["scanner_family_util_edd_seed1"]
    busiest = families[0]
    res = block["etas"]["600.0"]["resilimes"]["mean"]
    edd = block["etas"]["600.0"]["edd"]["mean"]
    if res["on_time_pct"] == edd["on_time_pct"]:
        tie = (
            f"At a 600-minute repair, ResiliMES and EDD tie on on-time delivery "
            f"at {res['on_time_pct']}%. "
        )
    elif res["on_time_pct"] > edd["on_time_pct"]:
        tie = (
            f"At a 600-minute repair, ResiliMES on-time is {res['on_time_pct']}% "
            f"and EDD is {edd['on_time_pct']}%. "
        )
    else:
        tie = (
            f"At a 600-minute repair, EDD on-time is {edd['on_time_pct']}% and "
            f"ResiliMES is {res['on_time_pct']}%. "
        )
    return (
        "This book keeps the published routes, priorities, and CQT limits. "
        f"Each due is the remaining raw process time times {block['factor']}. "
        f"Horizon is {block['horizon_h']:.0f} hours. "
        f"{block['due_in_horizon']} lots are due inside it. "
        f"`{payload['focus_tool']}` is held down for a fixed repair on top of "
        "the seeded breakdowns. The baseline is EDD. FIFO and CR are on the "
        "600-minute row only. "
        f"{tie}"
        "Scanner station families have no row in `setup.txt` and no route "
        "`STIME`, so a scanner change does not add setup. "
        "A later litho layer stays on the scanner that ran the first layer of "
        "its `SVESTN` / `FORSTEP` chain, once this run has chosen that scanner. "
        "WIP does not name a tool, so a lot that starts mid-chain is not pinned "
        "until then. If that scanner is down, the lot may run on another "
        "scanner of the family and is re-pinned there. There is no reticle id, "
        "stocker, or transfer time in the extract, and none is invented. "
        "A lot in process at a breakdown goes to rework: the work is lost, it "
        f"waits {block['rework_min']:.0f} minutes, and then redoes the whole "
        "operation from the family queue on any qualified tool. "
        "The rework hold is a ResiliMES default, not an SMT2020 column. "
        "An adjacent Wet_Etch queue-time step is held back when the next tool "
        "cannot start inside the window. A miss sends the lot through that "
        "wet step once. That is not the published rework probability. "
        f"Ten thousand exponential draws of the lithography MTTR "
        f"({LITHO_MTTR_MIN} minutes) have mean {repair['mean_min']} minutes, "
        f"population standard deviation {repair['std_min']}, p50 {repair['p50_min']}, "
        f"p90 {repair['p90_min']}. "
        f"The share at or under 180 / 300 / 600 minutes is "
        f"{repair['p_le_180']} / {repair['p_le_300']} / {repair['p_le_600']}. "
        f"Litho utilization at 600 minutes is {res['litho_util_pct']}% under "
        f"ResiliMES and {edd['litho_util_pct']}% under EDD, over all 102 "
        f"`Litho_*` tools. The busiest expose family on the EDD seed-1 run is "
        f"`{busiest['family']}` at {busiest['util_pct']}% "
        f"({busiest['tools']} tools). "
        "Tools were not removed to push that number to 90%."
    )


def _xfactor_table(payload: dict[str, Any]) -> str:
    header = (
        "| ETA min | Policy | OTD % | OTD std | Q-time | Q std | X-factor | X std | "
        "Cycle h | Cycle std | Litho util % | Litho std | Re-cleans | Gates |"
    )
    rule = "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines = [header, rule]
    for eta, block in payload["xfactor"]["etas"].items():
        for policy, body in block.items():
            item = body["mean"]
            spread = body["std"]
            lines.append(
                f"| {eta} | {policy} | {item['on_time_pct']} | {spread['on_time_pct']} | "
                f"{item['qtime_violations']} | {spread['qtime_violations']} | "
                f"{item['mean_x_factor']} | {spread['mean_x_factor']} | "
                f"{item['cycle_time_h']} | {spread['cycle_time_h']} | "
                f"{item['litho_util_pct']} | {spread['litho_util_pct']} | "
                f"{item['recleans']} | {item['qtime_gates']} |"
            )
    return "\n".join(lines)


def _xfactor_price(payload: dict[str, Any]) -> str:
    price = (payload.get("price") or {}).get("xfactor_seed1")
    if not price:
        return ""
    if price["lots"] == 0:
        paid = (
            "Seed 1, who paid: no scored non-hot lot finishes later under ResiliMES than under EDD."
        )
    else:
        worst = ", ".join(f"{item['lot_id']} +{item['extra_h']} h" for item in price["worst"])
        paid = (
            f"Seed 1, who paid: {price['lots']} non-hot "
            f"{'lot' if price['lots'] == 1 else 'lots'}, "
            f"{price['extra_h']} extra hours ({worst})."
        )
    xf = price.get("xfactor") or {}
    return (
        f"{paid} Mean X-factor on this seed is {xf.get('mean_x_before')} under "
        f"EDD and {xf.get('mean_x_after')} under ResiliMES. "
        f"Upstream gates {xf.get('gates')}. Re-cleans {xf.get('recleans')}. "
        "Spread across seeds is the population standard deviation, n=5."
    )


def _table(block: dict[str, Any]) -> str:
    header = (
        "| Policy | OTD % | Weighted tardiness min | Cycle h | "
        "Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | "
        "Candidate cap | Dispatch p50 ms | Dispatch p95 ms | Sim s |"
    )
    rule = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines = [header, rule]
    for policy, body in block.items():
        item = body["mean"]
        lines.append(
            "| {policy} | {on_time_pct} | {weighted_tardiness_min} | {cycle_time_h} | "
            "{litho_util_pct} | {scanner_util_pct} | {qtime_violations} | "
            "{pm_avoided} | {pm_overlaps} | {wip_replans} | {dispatch_p50_ms} | "
            "{dispatch_p95_ms} | {sim_s} |".format(policy=policy, **item)
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
