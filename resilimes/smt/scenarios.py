"""Headline scenarios on the full SMT2020 fab.

The six-lot sample bay stays in ``resilimes.domain.scenarios`` for unit tests.
It is not what this module returns.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from resilimes.config import ROOT, Settings
from resilimes.engines.scout.engine import default_scout
from resilimes.llm.factory import build_provider
from resilimes.smt.fab import DATA_SOURCE, LITHO_MTTR_MIN, READ_QUERY, Fab, initial_queues, load_fab
from resilimes.smt.simulate import (
    X_FACTOR,
    RunResult,
    macro_aps_ms,
    pm_shift_to_open,
    pm_windows,
    price_paid,
    run_policy,
    sample_downs,
)
from resilimes.smt.tight import (
    DIELECTRIC_FAMILY,
    DIELECTRIC_MTTR_MIN,
    TIGHT_HORIZON_SEC,
    apply_setup_rows,
    apply_tight,
    apply_xfactor,
    read_benchmark,
    refusal_from_trace,
)

logger = logging.getLogger(__name__)

# One shift on a click. The multi-shift study uses 48h and five seeds.
INTERACTIVE_HORIZON_SEC = 12 * 3600.0
STUDY_HORIZON_SEC = 48 * 3600.0
HOT_DUE_SEC = 12 * 3600.0
PM_OPEN_SEC = 2 * 3600.0
SEEDS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class SmtScenario:
    id: str
    title: str
    summary: str
    incident: str
    before_policy: str
    after_policy: str
    kind: str


SCENARIOS: dict[str, SmtScenario] = {
    "litho_down": SmtScenario(
        id="litho_down",
        title="Lithography breakdown",
        summary=(
            "Litho_FE_92-1, an expose scanner in the largest Litho_* family, "
            "is down for the published lithography MTTR."
        ),
        incident=(
            "Machine Litho_FE_92-1 down. Breakdown on expose family Litho_FE_92. "
            "Repair uses the published lithography MTTR of 705.59 minutes."
        ),
        before_policy="edd",
        after_policy="resilimes",
        kind="litho",
    ),
    "hot_lot": SmtScenario(
        id="hot_lot",
        title="Hot lot",
        summary=(
            "A normal lot four steps before an expose scanner is raised to VIP "
            "with a due 12 hours from the snapshot."
        ),
        incident="Hot lot: promote one normal WIP lot to VIP, due in 12 hours.",
        before_policy="fifo",
        after_policy="resilimes",
        kind="hot",
    ),
    "pm_avoid": SmtScenario(
        id="pm_avoid",
        title="PM avoidance",
        summary=(
            "The published weekly PM on Litho_FE_92 is shifted so it opens two "
            "hours into the window. Duration and interval stay as published."
        ),
        incident=(
            "Preventive maintenance on Litho_FE_92. Lots that would run across "
            "the PM window stay off the tool."
        ),
        before_policy="edd",
        after_policy="resilimes",
        kind="pm",
    ),
    "wip_threshold": SmtScenario(
        id="wip_threshold",
        title="WIP threshold",
        summary=(
            "When a station family holds more than two lots per tool, choose() "
            "keeps eight candidates instead of twenty-four, and also keeps a lot "
            "whose slack is at or under 7200 seconds. That counter is not a replan."
        ),
        incident=(
            "WIP over the station-family cap. The candidate list shortens. "
            "Lots with slack at or under 7200 seconds stay on the list. The book is not replanned."
        ),
        before_policy="fifo",
        after_policy="resilimes",
        kind="wip",
    ),
    "qtime": SmtScenario(
        id="qtime",
        title="Queue time",
        summary=(
            "Published CQT limits. ResiliMES adds PED risk and holds an adjacent "
            "Wet_Etch step when the next tool cannot start inside the window. "
            "That gate fired 0 times on the stored seeds. FIFO does not use the gate."
        ),
        incident=(
            "Q-time: published CQT limits are active. ResiliMES adds PED risk and "
            "the Wet_Etch gate. The gate fired 0 times on the stored seeds."
        ),
        before_policy="fifo",
        after_policy="resilimes",
        kind="qtime",
    ),
    "tight_p1": SmtScenario(
        id="tight_p1",
        title="Tight VIP dues",
        summary=(
            "Dues rewritten for this stress test. Not the published book. "
            "21 lots, 24 h, five seeds: ResiliMES 4/21 on every seed (20/105), "
            "EDD 3/21, 3/21, 2/21, 2/21, 3/21 (13/105). "
            "Seed 1 weighted tardiness is 7,679.4 under EDD and 4,043.8 under ResiliMES. "
            "Init_Lot_2_23 is the save here and an X-factor loss on seeds 5 and 6. "
            "Published dues, 48 h, 56 lots: ResiliMES 31/56, 31/56, 32/56, 32/56, 32/56 "
            "(mean 56.43%). EDD 31/56, 32/56, 32/56, 32/56, 32/56 (mean 56.78%). "
            "EDD is slightly ahead on that book."
        ),
        incident=(
            "Stress test with dues rewritten. Dielectric_BE_28-1 is down. "
            "Eight VIP lots are due in 8 hours. Thirteen normal lots in that queue "
            "are due 48 minutes sooner, so earliest-due serves them first."
        ),
        before_policy="edd",
        after_policy="resilimes",
        kind="tight",
    ),
    "xfactor": SmtScenario(
        id="xfactor",
        title="X-factor dues",
        summary=(
            "This run is seed 1, 48 h, 87 lots due. Both policies are 87/87 on time. "
            "Re-cleans are 24 under EDD and 31 under ResiliMES. "
            "Q-time violations are 428 under EDD and 418 under ResiliMES. "
            "Five-seed mean, not this click: re-cleans 38 vs 55.6, Q-time 430 vs 451.6. "
            "That mean is ResiliMES 97.47% and EDD 99.54% on time, FIFO 20.7%, CR 71.7%. "
            "Versus EDD the five-seed mean gives up about 2 of 87 lots."
        ),
        incident=(
            "Litho_FE_92-1 down for 600 minutes. This click is seed 1: both policies "
            "87/87 on time, re-cleans 24 to 31, Q-time 428 to 418. "
            "The five-seed mean is a separate study."
        ),
        before_policy="edd",
        after_policy="resilimes",
        kind="xfactor",
    ),
}


def list_smt_scenarios() -> list[SmtScenario]:
    return list(SCENARIOS.values())


def scenario_payload(fab: Fab | None = None) -> dict[str, Any]:
    plant = fab or load_fab()
    queues = initial_queues(plant)
    grouped: dict[str, dict[str, Any]] = {}
    for family in plant.families:
        row = grouped.setdefault(
            family.group,
            {
                "id": family.group,
                "kind": "group",
                "status": "IDLE",
                "tools": 0,
                "families": 0,
                "queue": queues.get(family.group, 0),
                "litho": family.group == "Litho",
            },
        )
        row["tools"] += family.tools
        row["families"] += 1
    return {
        "fab": DATA_SOURCE,
        "scenarios": [item.__dict__ for item in SCENARIOS.values()],
        "bay": list(grouped.values()),
        "counts": _counts(plant),
        "query": READ_QUERY,
        "data_source": DATA_SOURCE,
    }


def scout_provider_mode(settings: Settings) -> str:
    """Nightshift when live mode or a configured token says so. Mock otherwise.

    ``RESILIMES_MODE=live`` without a token raises ``ConfigError`` from
    ``use_nightshift``. Mock mode never selects Nightshift.
    """
    return "nightshift" if settings.use_nightshift else "mock"


def run_smt(
    settings: Settings,
    scenario_id: str,
    *,
    actor_role: str = "planner",
    actor_id: str = "planner.ops",
    seed: int = 1,
    horizon_sec: float | None = None,
    on_event: Any = None,
) -> dict[str, Any]:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise KeyError(scenario_id)
    fab = load_fab()
    if horizon_sec is None:
        horizon = (
            TIGHT_HORIZON_SEC
            if scenario.kind == "tight"
            else STUDY_HORIZON_SEC
            if scenario.kind == "xfactor"
            else INTERACTIVE_HORIZON_SEC
        )
    else:
        horizon = horizon_sec
    scout = default_scout(
        signing_secret=settings.scout_signing_secret,
        provider_mode=scout_provider_mode(settings),
        ttl_seconds=settings.scout_ttl_seconds,
    )
    decision = scout.decide(
        {
            "prompt": scenario.incident,
            "surface": "mes_console",
            "user": {"id": actor_id, "role": actor_role},
        }
    )
    _emit(
        on_event,
        "scout",
        "scout",
        "Scout Intent",
        f"Intent {decision.intent.get('primary')}.",
        {"intent": decision.intent.get("primary"), "confidence": decision.intent.get("confidence")},
    )
    if decision.risk.get("level") == "block" or decision.execution_contract is None:
        logger.info(
            "data source: smt2020",
            extra={"fields": {"query": READ_QUERY, "scenario": scenario_id, "blocked": "true"}},
        )
        return {
            "fab": DATA_SOURCE,
            "blocked": True,
            "scenario_id": scenario_id,
            "incident": scenario.incident,
            "narrative": decision.risk.get("reason") or "Scout refused the request.",
            "scout": _scout_public(decision),
            "verdict": {"verdict": "reject"},
            "mode": {"label": "SMT2020", "data": DATA_SOURCE},
            "data_source": DATA_SOURCE,
            "query": READ_QUERY,
        }
    benchmark = read_benchmark(settings, fab)
    setup_rows = list(benchmark.pop("setup_rows", []) or [])
    applied = 0
    if setup_rows and not benchmark.get("error"):
        fab, applied = apply_setup_rows(fab, setup_rows)
    benchmark["setup_rows_applied"] = applied
    benchmark["dispatcher_input"] = "resilimes.setup_matrix" if applied else ""
    _emit(
        on_event,
        "query",
        "specialist",
        "Zetaris read",
        _benchmark_summary(benchmark),
        {
            "source": benchmark["mode"],
            "reads": len(benchmark["queries"]),
            "sources": benchmark["sources"],
            "queries": benchmark["queries"],
            "row_counts": benchmark["row_counts"],
            "mode": benchmark["mode"],
            "error": benchmark["error"],
        },
        evidence=[item["sql"] for item in benchmark["queries"]],
    )
    _emit(on_event, "sim", "dispatcher", "Full fab", _count_line(fab), {"lots": len(fab.lot_id)})
    report = simulate_pair(fab, scenario, seed=seed, horizon=horizon)
    refusal = refusal_from_trace(list(report.get("down_starts") or []))
    report["refusal"] = refusal
    _emit(
        on_event,
        "critique",
        "evaluator",
        "Critic",
        refusal["detail"] if refusal else "No start on a down tool was proposed.",
        {
            "verdict": "reject" if refusal else "accept",
            "lot_id": refusal.get("lot_id") if refusal else "",
            "tool": refusal.get("tool") if refusal else "",
        },
        evidence=[refusal["detail"]] if refusal else [],
    )
    note = _explain(settings, scenario.incident, report)
    report["explain"] = note
    _emit(
        on_event,
        "explain",
        "narrator",
        "Nightshift",
        note.get("text") or note.get("error") or "",
        {
            "provider": note.get("provider"),
            "model": note.get("model"),
            "mocked": note.get("mocked"),
            "meterless_request_id": note.get("meterless_request_id"),
            "completion_id": note.get("completion_id"),
        },
    )
    report["scout"] = _scout_public(decision)
    report["zetaris"] = benchmark
    report["query"] = benchmark["queries"][0]["sql"] if benchmark["queries"] else READ_QUERY
    report["blocked"] = False
    report["verdict"] = {"verdict": "reject" if refusal else "accept"}
    provider_name = str(note.get("provider") or "mock")
    report["mode"] = {
        "label": "NIGHTSHIFT" if provider_name == "nightshift" else "SMT2020",
        "data": DATA_SOURCE,
        "llm": provider_name,
    }
    logger.info(
        "data source: smt2020",
        extra={
            "fields": {
                "query": report["query"],
                "zetaris": benchmark["mode"],
                "sources": ",".join(benchmark["sources"]),
                "scenario": scenario_id,
                "seed": str(seed),
                "horizon_h": str(horizon / 3600.0),
            }
        },
    )
    return report


def simulate_pair(
    fab: Fab,
    scenario: SmtScenario,
    *,
    seed: int,
    horizon: float,
) -> dict[str, Any]:
    book = apply_tight(fab, horizon=horizon) if scenario.kind == "tight" else None
    plant = book.fab if book is not None else fab
    if scenario.kind == "xfactor":
        plant = apply_xfactor(fab)
    forced_tool = fab.focus_tool if scenario.kind in {"litho", "xfactor"} else None
    if scenario.kind == "litho":
        forced_until = LITHO_MTTR_MIN * 60.0
    elif scenario.kind == "xfactor":
        forced_until = 600.0 * 60.0
    else:
        forced_until = 0.0
    shift = pm_shift_to_open(fab, fab.pm_calendar, PM_OPEN_SEC) if scenario.kind == "pm" else 0.0
    downs = sample_downs(
        plant,
        seed,
        horizon,
        forced_tool=forced_tool,
        forced_until=forced_until,
    )
    if book is not None:
        downs[book.down_tool].append((0.0, min(book.down_until, horizon)))
    pm = pm_windows(plant, horizon, shift_sec=shift)
    hot = fab.hot_lot if scenario.kind == "hot" else None
    if book is not None:
        watch: tuple[int, ...] = book.watch
    elif scenario.kind == "xfactor":
        watch = tuple(
            index
            for index, due in enumerate(plant.lot_due)
            if due <= horizon and fab.lot_class[index] != "VIP"
        )
    else:
        watch = ()
    bar_family = None
    bar_until = None
    if book is not None:
        bar_family = fab.family_index[DIELECTRIC_FAMILY]
        bar_until = horizon
    # The before book keeps the lot at its published priority.
    before = run_policy(
        plant,
        policy=scenario.before_policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        hot_lot=hot,
        trace=True,
        focus_down_until=forced_until,
        watch=watch,
        bar_family=bar_family,
        bar_until=bar_until,
    )
    after = run_policy(
        plant,
        policy=scenario.after_policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        hot_lot=hot,
        hot_due=HOT_DUE_SEC if hot is not None else None,
        promote_hot=hot is not None,
        trace=True,
        focus_down_until=forced_until,
        watch=watch,
        bar_family=bar_family,
        bar_until=bar_until,
    )
    aps_ms, scanner_steps = macro_aps_ms(fab)
    report = _report(fab, scenario, before, after, seed, horizon, aps_ms, scanner_steps, shift)
    if book is not None:
        report["tight"] = _tight_public(fab, book, before, after)
        report["price"] = price_paid(before, after, [fab.lot_id[index] for index in book.decoy])
    if scenario.kind == "xfactor":
        report["xfactor"] = {
            "factor": X_FACTOR,
            "down_min": 600,
            "tool": fab.tool_name[fab.focus_tool],
            "mean_x_before": before.mean_x_factor,
            "mean_x_after": after.mean_x_factor,
            "gates": after.qtime_gates,
            "recleans": after.recleans,
        }
        report["price"] = price_paid(before, after, [fab.lot_id[index] for index in watch])
    return report


def _report(
    fab: Fab,
    scenario: SmtScenario,
    before: RunResult,
    after: RunResult,
    seed: int,
    horizon: float,
    aps_ms: float,
    scanner_steps: int,
    shift: float,
) -> dict[str, Any]:
    family = fab.families[fab.focus_family]
    if scenario.kind == "tight":
        family = fab.families[fab.family_index[DIELECTRIC_FAMILY]]
    report = {
        "fab": DATA_SOURCE,
        "data_source": DATA_SOURCE,
        "query": READ_QUERY,
        "scenario_id": scenario.id,
        "incident": scenario.incident,
        "horizon": "2018-01-01T00:00:00Z",
        "horizon_h": horizon / 3600.0,
        "seed": seed,
        "counts": _counts(fab),
        "policies": {"before": before.policy, "after": after.policy},
        "focus": {
            "family": family.name,
            "group": family.group,
            "tool": (
                fab.tool_name[fab.families[fab.family_index[DIELECTRIC_FAMILY]].tool0]
                if scenario.kind == "tight"
                else fab.tool_name[fab.focus_tool]
            ),
            "tools_in_family": family.tools,
            "down_min": (
                round(DIELECTRIC_MTTR_MIN, 2)
                if scenario.kind == "tight"
                else round(LITHO_MTTR_MIN, 2)
                if scenario.kind == "litho"
                else 0
            ),
            "sibling_starts_before": before.sibling_starts,
            "sibling_starts_after": after.sibling_starts,
            "queue_max_before": before.focus_queue_max,
            "queue_max_after": after.focus_queue_max,
            "downstream_queue_max_before": before.downstream_queue_max,
            "downstream_queue_max_after": after.downstream_queue_max,
        },
        "hot_lot": {
            "lot_id": fab.lot_id[fab.hot_lot],
            "product": fab.lot_product[fab.hot_lot],
            "rule": "priority 10, four steps before an expose scanner, lowest lot id",
            "steps_before": before.hot_steps,
            "steps_after": after.hot_steps,
            "scanner_start_min_before": before.hot_scanner_start_min,
            "scanner_start_min_after": after.hot_scanner_start_min,
        },
        "pm": {
            "calendar": fab.pm_calendar,
            "shift_h": round(shift / 3600.0, 2),
            "note": (
                "FOA is one published constant per family, so every tool in the "
                "family shares the window. The PM scenario subtracts the same "
                "offset from every day-based calendar."
            ),
        },
        "kpis": {"before": _kpi(before), "after": _kpi(after), "delta": _delta(before, after)},
        "timing": {
            "dispatch_p50_ms": after.dispatch_p50_ms,
            "dispatch_p95_ms": after.dispatch_p95_ms,
            "dispatch_decisions": after.dispatch_decisions,
            "dispatch_busy_p50_ms": after.dispatch_busy_p50_ms,
            "dispatch_busy_p95_ms": after.dispatch_busy_p95_ms,
            "dispatch_busy_decisions": after.dispatch_busy_decisions,
            "latency_note": (
                "Headline p50/p95 include empty wakes. "
                "Nonempty-queue p50/p95 count only decisions with a ready lot."
            ),
            "aps_ms": round(aps_ms, 1),
            "scanner_steps": scanner_steps,
            "sim_before_s": before.sim_s,
            "sim_after_s": after.sim_s,
        },
        "board": _board(fab, after),
        "down_starts": list(before.down_starts) + list(after.down_starts),
        "gantt": {
            "bin_min": 15,
            "before": _bars(fab, before),
            "after": _bars(fab, after),
            "focus_bars": after.focus_bars,
        },
        "definitions": {
            "on_time_pct": (
                "Lots whose due is at or before the horizon. On time only if the "
                "route finishes at or before the due. Lots already due at the "
                "snapshot stay in the denominator."
            ),
            "weighted_tardiness_min": (
                "Lot value times minutes late. An open lot is censored at the horizon."
            ),
            "cycle_time_h": "Mean completion time of lots that finish the route inside the horizon.",
            "litho_util_pct": "Busy time on the 102 Litho_* tools divided by tools times horizon.",
            "qtime_violations": "CQT target started after the limit, or the limit expired inside the horizon.",
            "recleans": (
                "One return through the wet step that opened the missed window. "
                "Not the published rework probability."
            ),
            "mean_x_factor": (
                "Completion time divided by remaining raw process time at the snapshot, "
                "for lots that finish inside the horizon."
            ),
            "candidate_cap": (
                "The WIP counter in enqueue records that a family exceeded "
                "max(8, two lots per tool). choose() then keeps 8 candidates "
                "instead of 24, and also keeps a lot whose slack is at or under "
                "7200 seconds. It does not replan the family. On seeds 9-13 that "
                "slack exception matched the shipped score."
            ),
            "qtime_gate": (
                "The adjacent Wet_Etch look-ahead is a hold, not a replan. "
                "On the measured books that gate fired 0 times. Retargeting it "
                "at the 44 adjacent 1-hour Dry_Etch to Wet_Etch pairs, and counting "
                "lots already queued downstream, was reverted after seeds 9-13."
            ),
            "macro_aps": (
                "macro_aps_ms times a backward due and an earliest-free scanner "
                "placement. Those operation dues are not an input to dpi(). "
                "Feeding the expose-step due into dpi() was reverted after seeds 9-13."
            ),
            "pm_avoided": (
                "Decisions, on every policy, that refused at least one lot because "
                "it would cross a PM."
            ),
            "pm_overlaps": "Starts whose process overlaps a PM window.",
            "down_tool_refusal": (
                "Set only when the event trace contains a start on a tool that is down. "
                "Otherwise null."
            ),
        },
    }
    if scenario.kind == "litho":
        report["study_note"] = _litho_study_note(before, after, seed, horizon)
    if scenario.kind == "xfactor":
        report["study_note"] = _xfactor_study_note(before, after, seed, horizon)
    return report


def _otd_count(pct: float, denom: int) -> int:
    return round(pct / 100.0 * denom)


def _litho_study_note(before: RunResult, after: RunResult, seed: int, horizon: float) -> str:
    """The 12 h click is one seed. The five-seed lithography row is the study."""
    click = (
        f"This click is seed {seed} and {horizon / 3600:.0f} h: "
        f"{before.policy} {_otd_count(before.on_time_pct, before.due_in_horizon)}/"
        f"{before.due_in_horizon} ({before.on_time_pct}%), "
        f"{after.policy} {_otd_count(after.on_time_pct, after.due_in_horizon)}/"
        f"{after.due_in_horizon} ({after.on_time_pct}%)."
    )
    if before.on_time_pct == after.on_time_pct:
        click += " The two policies tie on this seed."
    path = ROOT / "data" / "smt2020" / "benchmark.json"
    if not path.is_file():
        return click + " The five-seed lithography study is in docs/SMT2020_SCALE.md."
    payload = json.loads(path.read_text(encoding="utf-8"))
    litho = payload.get("litho") or {}
    parts: list[str] = []
    denom = None
    for policy in ("resilimes", "edd"):
        block = litho.get(policy) or {}
        seeds = block.get("seeds") or []
        if not seeds:
            continue
        denom = seeds[0].get("due_in_horizon")
        rendered = ", ".join(
            f"seed {item['seed']} "
            f"{_otd_count(float(item['on_time_pct']), int(item['due_in_horizon']))}/"
            f"{item['due_in_horizon']}"
            for item in seeds
        )
        mean = (block.get("mean") or {}).get("on_time_pct")
        parts.append(f"{policy} {rendered} (mean {mean}%)")
    if not parts:
        return click
    return (
        f"{click} Five-seed lithography study, 48 h, {denom} lots due: "
        + "; ".join(parts)
        + ". That study is not this click."
    )


def _xfactor_study_note(before: RunResult, after: RunResult, seed: int, horizon: float) -> str:
    """The click is one seed. The five-seed means are the study."""
    click = (
        f"This run (seed {seed}, {horizon / 3600:.0f} h): "
        f"{before.policy} {_otd_count(before.on_time_pct, before.due_in_horizon)}/"
        f"{before.due_in_horizon} on time, re-cleans {before.recleans}, "
        f"Q-time {before.qtime_violations}. "
        f"{after.policy} {_otd_count(after.on_time_pct, after.due_in_horizon)}/"
        f"{after.due_in_horizon} on time, re-cleans {after.recleans}, "
        f"Q-time {after.qtime_violations}."
    )
    path = ROOT / "data" / "smt2020" / "benchmark.json"
    if not path.is_file():
        return click + " The five-seed mean is in docs/SMT2020_SCALE.md. It is not this run."
    payload = json.loads(path.read_text(encoding="utf-8"))
    block = ((payload.get("xfactor") or {}).get("etas") or {}).get("600.0") or {}
    parts: list[str] = []
    for policy in ("edd", "resilimes"):
        mean = (block.get(policy) or {}).get("mean") or {}
        if not mean:
            continue
        parts.append(
            f"{policy} on-time {mean.get('on_time_pct')}%, "
            f"re-cleans {mean.get('recleans')}, Q-time {mean.get('qtime_violations')}"
        )
    if not parts:
        return click
    return f"{click} Five-seed mean at a 600-minute repair, not this run: " + "; ".join(parts) + "."


def _counts(fab: Fab) -> dict[str, int]:
    return {
        "groups": len(fab.families),
        "tools": len(fab.tool_name),
        "litho_tools": fab.litho_tools,
        "scanner_tools": fab.scanner_tools,
        "products": fab.products,
        "lots": len(fab.lot_id),
        "station_groups": len(fab.group_names),
    }


def _kpi(result: RunResult) -> dict[str, Any]:
    return {
        "policy": result.policy,
        "on_time_pct": result.on_time_pct,
        "weighted_tardiness_min": result.weighted_tardiness_min,
        "due_in_horizon": result.due_in_horizon,
        "already_late": result.already_late,
        "completed_routes": result.completed_routes,
        "cycle_time_h": result.cycle_time_h,
        "mean_step_cycle_min": result.mean_step_cycle_min,
        "litho_util_pct": result.litho_util_pct,
        "scanner_util_pct": result.scanner_util_pct,
        "qtime_violations": result.qtime_violations,
        "recleans": result.recleans,
        "mean_x_factor": result.mean_x_factor,
        "qtime_gates": result.qtime_gates,
        "pm_avoided": result.pm_avoided,
        "pm_overlaps": result.pm_overlaps,
        "wip_replans": result.wip_replans,
    }


def _delta(before: RunResult, after: RunResult) -> dict[str, Any]:
    def sub(left: float | None, right: float | None) -> float | None:
        if left is None or right is None:
            return None
        return round(right - left, 2)

    return {
        "on_time_pct": round(after.on_time_pct - before.on_time_pct, 2),
        "weighted_tardiness_min": round(
            after.weighted_tardiness_min - before.weighted_tardiness_min, 1
        ),
        "qtime_violations": after.qtime_violations - before.qtime_violations,
        "litho_util_pct": round(after.litho_util_pct - before.litho_util_pct, 2),
        "cycle_time_h": sub(before.cycle_time_h, after.cycle_time_h),
        "pm_avoided": after.pm_avoided - before.pm_avoided,
    }


def _board(fab: Fab, result: RunResult) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for family in fab.families:
        row = rows.setdefault(
            family.group,
            {
                "id": family.group,
                "kind": "group",
                "tools": 0,
                "families": 0,
                "queue": result.queue_end.get(family.group, 0),
                "down": result.down_tools.get(family.group, 0),
                "status": "IDLE",
            },
        )
        row["tools"] += family.tools
        row["families"] += 1
    for row in rows.values():
        if row["down"]:
            row["status"] = "DOWN"
    return list(rows.values())


def _bars(fab: Fab, result: RunResult) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    if not result.occupancy:
        return bars
    for fam, row in enumerate(result.occupancy):
        family = fab.families[fam]
        segments: list[dict[str, float]] = []
        start: int | None = None
        peak = 0.0
        for index, value in enumerate(row):
            if value > 0:
                peak = max(peak, value)
                if start is None:
                    start = index
            elif start is not None:
                segments.append(
                    {
                        "s": start * 15,
                        "e": index * 15,
                        "n": round(peak / _bin_seconds(), 2),
                    }
                )
                start = None
                peak = 0.0
        if start is not None:
            segments.append(
                {"s": start * 15, "e": len(row) * 15, "n": round(peak / _bin_seconds(), 2)}
            )
        if not segments:
            continue
        bars.append(
            {
                "id": family.name,
                "group": family.group,
                "scanner": family.scanner,
                "litho": family.litho,
                "bars": segments,
            }
        )
    return bars


def _bin_seconds() -> float:
    return 900.0


def _scout_public(decision: Any) -> dict[str, Any]:
    contract = decision.execution_contract or {}
    return {
        "engine": "scout-intent",
        "intent": decision.intent.get("primary"),
        "confidence": decision.intent.get("confidence"),
        "risk": decision.risk.get("level"),
        "contract": bool(contract),
        "test": "tests/test_scout_engine.py",
    }


def _count_line(fab: Fab) -> str:
    return (
        f"{len(fab.families)} families, {len(fab.tool_name)} tools, "
        f"{fab.litho_tools} litho, {len(fab.lot_id)} lots."
    )


def _emit(
    on_event: Any,
    phase: str,
    agent: str,
    title: str,
    summary: str,
    slots: dict[str, Any],
    evidence: list[str] | None = None,
) -> None:
    if on_event is None:
        return
    shown = evidence if evidence is not None else ([READ_QUERY] if phase == "sim" else [])
    on_event(
        {
            "type": "step",
            "phase": phase,
            "agent": agent,
            "title": title,
            "summary": summary,
            "evidence": shown,
            "slots": slots,
            "elapsed_ms": 0,
        }
    )


def _benchmark_summary(benchmark: dict[str, Any]) -> str:
    counts = benchmark.get("row_counts") or {}
    rendered = ", ".join(f"{name} {value}" for name, value in counts.items())
    sources = ", ".join(benchmark.get("sources") or [])
    if benchmark.get("mode") == "zetaris" and not benchmark.get("error"):
        fed = benchmark.get("setup_rows_applied") or 0
        return (
            f"Zetaris sources {sources}. Rows: {rendered}. "
            f"Setup matrix rows applied to the dispatcher: {fed}."
        )
    if benchmark.get("error"):
        return f"Zetaris query failed. Sources {sources}."
    return f"Local extract. Zetaris was not called. Sources {sources}. Rows: {rendered}."


def _explain(settings: Settings, incident: str, report: dict[str, Any]) -> dict[str, Any]:
    """One Nightshift completion. The schedule is already fixed."""
    after = (report.get("kpis") or {}).get("after") or {}
    try:
        provider = build_provider(settings)
        result = provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Write one sentence a fab supervisor can read. "
                        "The schedule is already fixed. Do not invent numbers or lot ids."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Incident: {incident}\n"
                        f"On-time percent after recovery: {after.get('on_time_pct')}. "
                        f"Weighted tardiness minutes after recovery: "
                        f"{after.get('weighted_tardiness_min')}."
                    ),
                },
            ],
            lane="explain",
            temperature=0.2,
        )
    except Exception as exc:
        return {"provider": "nightshift", "mocked": False, "error": str(exc)[:240], "text": ""}
    return {
        "provider": result.provider,
        "model": result.model,
        "mocked": result.mocked,
        "meterless_request_id": result.meterless_request_id,
        "completion_id": result.completion_id,
        "text": result.content[:500],
        "error": "",
    }


def _tight_public(
    fab: Fab,
    book: Any,
    before: RunResult,
    after: RunResult,
) -> dict[str, Any]:
    family = fab.families[fab.family_index["Dielectric_BE_28"]]
    gap = 0.0
    spot_id = fab.lot_id[book.p1[0]]
    for index in book.p1:
        lot_id = fab.lot_id[index]
        delta = before.watched_late_h.get(lot_id, 0.0) - after.watched_late_h.get(lot_id, 0.0)
        if delta >= gap:
            gap = delta
            spot_id = lot_id
    return {
        "family": family.name,
        "group": family.group,
        "tool": fab.tool_name[book.down_tool],
        "tools_in_family": family.tools,
        "down_min": DIELECTRIC_MTTR_MIN,
        "p1_due_h": 8,
        "decoy_due_h": 7.2,
        "p1_lots": [fab.lot_id[index] for index in book.p1],
        "decoy_lots": [fab.lot_id[index] for index in book.decoy],
        "spotlight_lot": spot_id,
        "spotlight_late_h_before": before.watched_late_h.get(spot_id),
        "spotlight_late_h_after": after.watched_late_h.get(spot_id),
        "note": (
            "Constructed dues on the public industry benchmark (SMT2020). "
            "Routes, process times, setups, and CQT limits stay published. "
            "Lots outside this queue stay in the fab and are outside the scored horizon."
        ),
    }
