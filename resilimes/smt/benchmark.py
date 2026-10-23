"""Five-seed, 48-hour measurements on the full SMT2020 fab.

Writes ``data/smt2020/benchmark.json`` and ``docs/SMT2020_SCALE.md``.
The interactive console uses a 12-hour horizon so a click stays short.
"""

from __future__ import annotations

import json
from statistics import mean
from typing import Any

from resilimes.config import ROOT
from resilimes.smt.fab import LITHO_MTTR_MIN, load_fab
from resilimes.smt.scenarios import SEEDS, STUDY_HORIZON_SEC
from resilimes.smt.simulate import (
    RunResult,
    macro_aps_ms,
    pm_shift_to_open,
    pm_windows,
    run_policy,
    sample_downs,
)

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
)


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
    }
    json_path = ROOT / "data" / "smt2020" / "benchmark.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    doc = ROOT / "docs" / "SMT2020_SCALE.md"
    doc.write_text(_markdown(payload), encoding="utf-8")
    print(f"wrote {json_path}", flush=True)
    print(f"wrote {doc}", flush=True)


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


def _pack(rows: dict[str, list[RunResult]]) -> dict[str, Any]:
    packed: dict[str, Any] = {}
    for policy, runs in rows.items():
        packed[policy] = {
            "mean": {key: _mean(runs, key) for key in _KEYS},
            "seeds": [_public(item) for item in runs],
        }
    return packed


def _public(result: RunResult) -> dict[str, Any]:
    return {key: getattr(result, key) for key in ("seed", *_KEYS)}


def _mean(runs: list[RunResult], key: str) -> float | None:
    values = [getattr(item, key) for item in runs if getattr(item, key) is not None]
    if not values:
        return None
    return round(float(mean(values)), 3)


def _markdown(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    lines = [
        "# SMT2020 full-fab measurements",
        "",
        "Source: Kopp, Hassoun, Kalir, and Mönch, IEEE Trans. Semicond. Manuf. "
        "33(4), 2020, doi 10.1109/TSM.2020.3001933. PySCFabSim-release commit "
        "`0dbff6a`, directory `datasets/SMT2020_LVHM`.",
        "",
        f"Fab: {counts['groups']} station families, {counts['tools']} tools, "
        f"{counts['litho_tools']} `Litho_*` tools "
        f"({counts['scanner_tools']} expose scanners plus "
        f"{counts['litho_tools'] - counts['scanner_tools']} `Litho_REG`), "
        f"{counts['products']} products, {counts['lots']} initial WIP lots, "
        f"{counts['station_groups']} station groups. "
        "`Delay_32` is included (400 tools, 147 route steps).",
        "",
        f"Horizon: {payload['horizon_h']:.0f} hours from 2018-01-01 00:00 UTC. "
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
        "## Steady fab (seeded breakdowns, published PM calendar unshifted)",
        "",
        _table(payload["steady"]),
        "",
        "## Lithography breakdown",
        "",
        _table(payload["litho"]),
        "",
        _litho_note(payload),
        "",
        "## PM avoidance (calendar shifted, durations unchanged)",
        "",
        _table(payload["pm"]),
        "",
        "## Hot lot",
        "",
        _table(payload["hot"]),
        "",
        _hot_note(payload),
        "",
        "Per-seed rows are in `data/smt2020/benchmark.json`. Regenerate with `make smt-bench`.",
        "",
    ]
    return "\n".join(lines)


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
