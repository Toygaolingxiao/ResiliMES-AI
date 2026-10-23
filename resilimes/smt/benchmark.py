"""Five-seed, 48-hour measurements on the full SMT2020 fab.

Writes ``data/smt2020/benchmark.json`` and ``docs/SMT2020_SCALE.md``.
The interactive console uses a 12-hour horizon so a click stays short.
"""

from __future__ import annotations

import json
import random
from statistics import mean, pstdev
from typing import Any

from resilimes.config import ROOT
from resilimes.smt.fab import LITHO_MTTR_MIN, Fab, load_fab
from resilimes.smt.scenarios import SCENARIOS, SEEDS, STUDY_HORIZON_SEC, simulate_pair
from resilimes.smt.simulate import (
    DISPOSITION_SEC,
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
    "sim_s",
    "sibling_starts",
    "focus_queue_max",
    "downstream_queue_max",
    "hot_steps",
    "mean_x_factor",
    "qtime_gates",
    "recleans",
)

_X_ETAS = (180.0, 300.0, 600.0, LITHO_MTTR_MIN)


def main() -> None:
    fab = load_fab()
    aps_ms, scanner_steps = macro_aps_ms(fab)
    horizon = STUDY_HORIZON_SEC
    print(f"APS {aps_ms:.1f} ms, {scanner_steps} scanner steps", flush=True)
    steady = _matrix(fab, horizon, ("resilimes", "edd", "fifo", "cr"), kind="steady")
    litho = _matrix(fab, horizon, ("resilimes", "edd"), kind="litho")
    pm = _matrix(fab, horizon, ("resilimes", "edd"), kind="pm")
    hot = _matrix(fab, horizon, ("resilimes", "fifo"), kind="hot")
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
        "tight": _pack(_tight_matrix(fab)),
        "xfactor": _xfactor(fab),
        "repair_mc": _repair_mc(),
        "price": _prices(fab),
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
    for seed in SEEDS:
        book = apply_tight(fab, horizon=horizon)
        downs = sample_downs(book.fab, seed, horizon)
        downs[book.down_tool].append((0.0, min(book.down_until, horizon)))
        pm = pm_windows(book.fab, horizon)
        for policy in found:
            print(f"tight {policy} seed {seed}", flush=True)
            found[policy].append(
                run_policy(
                    book.fab,
                    policy=policy,
                    seed=seed,
                    horizon=horizon,
                    downs=downs,
                    pm=pm,
                    trace=False,
                    watch=book.watch,
                )
            )
    return found


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
            print(f"{kind} {policy} seed {seed}", flush=True)
            found[policy].append(
                run_policy(
                    fab,
                    policy=policy,
                    seed=seed,
                    horizon=horizon,
                    downs=downs,
                    pm=pm,
                    hot_lot=fab.hot_lot if kind == "hot" else None,
                    hot_due=12 * 3600.0 if kind == "hot" and policy == "resilimes" else None,
                    promote_hot=kind == "hot" and policy == "resilimes",
                    trace=False,
                    focus_down_until=forced_until,
                )
            )
    return found


def _xfactor(fab: Fab) -> dict[str, Any]:
    """Dues at 2.75 x remaining process. One scanner held for a fixed ETA."""
    plant = apply_xfactor(fab)
    horizon = STUDY_HORIZON_SEC
    due = sum(1 for due_at in plant.lot_due if due_at <= horizon)
    found: dict[str, Any] = {
        "factor": X_FACTOR,
        "horizon_h": horizon / 3600.0,
        "due_in_horizon": due,
        "disposition_min": DISPOSITION_SEC / 60.0,
        "etas": {},
    }
    for eta in _X_ETAS:
        policies = ("resilimes", "edd", "fifo", "cr") if eta == 600.0 else ("resilimes", "edd")
        rows: dict[str, list[RunResult]] = {policy: [] for policy in policies}
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
                print(f"xfactor eta {eta} {policy} seed {seed}", flush=True)
                rows[policy].append(
                    run_policy(
                        plant,
                        policy=policy,
                        seed=seed,
                        horizon=horizon,
                        downs=downs,
                        pm=pm,
                        trace=False,
                        focus_down_until=eta * 60.0,
                    )
                )
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
    return {key: getattr(result, key) for key in ("seed", *_KEYS)}


def _mean(runs: list[RunResult], key: str) -> float | None:
    values = [getattr(item, key) for item in runs if getattr(item, key) is not None]
    if not values:
        return None
    digits = 4 if key in {"dispatch_p50_ms", "dispatch_p95_ms"} else 3
    return round(float(mean(values)), digits)


def _std(runs: list[RunResult], key: str) -> float | None:
    values = [getattr(item, key) for item in runs if getattr(item, key) is not None]
    if len(values) < 2:
        return None
    digits = 4 if key in {"dispatch_p50_ms", "dispatch_p95_ms"} else 3
    return round(float(pstdev(values)), digits)


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
        "The tight VIP table is 24 hours. The appendix is "
        f"{payload['horizon_h']:.0f} hours from 2018-01-01 00:00 UTC. "
        f"Seeds: {', '.join(str(item) for item in payload['seeds'])}. "
        "Each seed draws exponential MTTF/MTTR from `downcal.txt`, one clock per tool. "
        "The same draw is shared across policies.",
        "",
        f"Macro APS (backward due, then earliest free expose scanner, "
        f"{payload['scanner_steps']} scanner steps): **{payload['aps_ms']} ms**.",
        "",
        "Dispatch latency is the time to choose the next lot for one idle tool, "
        "look-ahead 24 (8 when that family's queue exceeds two lots per tool). "
        "It is not the full simulation time. Simulation time is the whole 48-hour run.",
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
        "PM avoided is a ResiliMES decision that refused at least one lot "
        "because the process would cross a PM. "
        "PM overlaps are baseline starts that run across a PM.",
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
        _tight_price(payload),
        "",
        "## X-factor dues (48 hours)",
        "",
        _xfactor_prose(payload),
        "",
        _xfactor_table(payload),
        "",
        _xfactor_price(payload),
        "",
        "## Appendix: published order book (performance)",
        "",
        _published_lead(payload),
        "",
        "### Steady fab (seeded breakdowns, published PM calendar unshifted)",
        "",
        _table(payload["steady"]),
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
        "Per-seed rows are in `data/smt2020/benchmark.json`. Regenerate with `make smt-bench`.",
        "What the extract contains, and what this simulator leaves out, is "
        "[SMT2020_PROVENANCE.md](SMT2020_PROVENANCE.md).",
        "",
    ]
    return "\n".join(lines)


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
        f"of which {res['already_late']} are already late at the snapshot."
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
    worst = ", ".join(
        f"{item['lot_id']} +{item['extra_h']} h" for item in price["worst"]
    )
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
        "until then. There is no reticle id, stocker, or transfer time in the "
        "extract, and none is invented. "
        f"A lot in process at a breakdown keeps the remaining process, waits "
        f"{block['disposition_min']:.0f} minutes, and resumes on that tool. "
        "The 15 minutes are not an SMT2020 column. "
        "An adjacent Wet_Etch queue-time step is held back when the next tool "
        "cannot start inside the window. A miss sends the lot through that "
        "wet step once. That is not the published rework probability. "
        f"Ten thousand exponential draws of the lithography MTTR "
        f"({LITHO_MTTR_MIN} minutes) have mean {repair['mean_min']} minutes, "
        f"sample std {repair['std_min']}, p50 {repair['p50_min']}, "
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
            "Seed 1, who paid: no scored non-hot lot finishes later under "
            "ResiliMES than under EDD."
        )
    else:
        worst = ", ".join(
            f"{item['lot_id']} +{item['extra_h']} h" for item in price["worst"]
        )
        paid = (
            f"Seed 1, who paid: {price['lots']} non-hot lots, "
            f"{price['extra_h']} extra hours ({worst})."
        )
    xf = price.get("xfactor") or {}
    return (
        f"{paid} Mean X-factor on this seed is {xf.get('mean_x_before')} under "
        f"EDD and {xf.get('mean_x_after')} under ResiliMES. "
        f"Upstream gates {xf.get('gates')}. Re-cleans {xf.get('recleans')}. "
        "Spread across seeds is the sample standard deviation, n=5."
    )


def _table(block: dict[str, Any]) -> str:
    header = (
        "| Policy | OTD % | Weighted tardiness min | Cycle h | "
        "Litho util % | Scanner util % | Q-time | PM avoided | PM overlaps | "
        "WIP replans | Dispatch p50 ms | Dispatch p95 ms | Sim s |"
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
