"""Hard Q-time study: dispatcher as is vs the same dispatcher with hard Q-time.

``python -m resilimes.smt.hard_qtime_study OUT.json`` runs the published book,
seeds 1-3, 168 h (``RESILIMES_STUDY_HORIZON_H``), for each policy in
``RESILIMES_HQ_POLICIES`` (default ``planning,edd``; ``planning`` is ResiliMES
in main's default mode: the auto planning layer, r2 fixes 2+3, closed fab),
arms ``H0`` (hard Q-time off) and ``H1`` (``hard_qtime=True``, the default with
the planning layer). Plant,
downs and PM as ``qtime_study._setup``. True Q-time is the event
replay of ``qtime_study``; ``q_steady_pct`` scores only windows opened after
the first 24 h (the snapshot WIP start-up wave is over by then). Miss causes
come from ``resilimes.smt.hard_qtime.classify`` and the avoidable /
unavoidable split from ``miss_class``. The report keeps a configuration as a
candidate only with zero avoidable Q-time violations; Q-time-blind rules
(EDD) appear only as an industry reference row. No weights, due dates or
seeds are tuned. ``RESILIMES_STUDY_WORKERS`` (default 2) sets the pool.
``python -m resilimes.smt.hard_qtime_study --report OUT.json`` prints the
tables of docs/HARD_QTIME.md.
"""

from __future__ import annotations

import json
import os
import sys
from multiprocessing import get_context
from typing import Any

from resilimes.smt import qtime_study
from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.hard_qtime import AVOIDABLE, CAUSES, DISRUPTION
from resilimes.smt.simulate import run_policy

BOOK = "published"
SEEDS = (1, 2, 3)
ARMS = (("H0", False), ("H1", True))
WARMUP_SEC = 24 * 3600.0
_FAB: list[Fab] = []


def policies() -> tuple[str, ...]:
    raw = os.environ.get("RESILIMES_HQ_POLICIES", "planning,edd")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def configs() -> list[tuple[str, str]]:
    """(policy, arm) pairs: every arm of ``policies()``, or RESILIMES_HQ_CONFIGS.

    ``RESILIMES_HQ_CONFIGS=planning:H0,planning:H1,edd:H0`` skips EDD + hard.
    """
    raw = os.environ.get("RESILIMES_HQ_CONFIGS", "").strip()
    if raw:
        return [tuple(part.strip().split(":", 1)) for part in raw.split(",")]  # type: ignore[misc]
    return [(policy, arm) for policy in policies() for arm, _ in ARMS]


def steady(fab: Fab, events: list[tuple[Any, ...]], horizon: float) -> dict[str, int]:
    """Met / missed of windows opened after the warm-up (event replay)."""
    window: dict[int, tuple[int, float]] = {}
    met = missed = 0
    for event in events:
        kind = event[0]
        if kind == "end":
            moment, lot, index = event[1:4]
            route = fab.routes[fab.lot_route[lot]]
            if route.cqt_limit[index] > 0 and route.cqt_target[index] >= 0:
                window.pop(lot, None)
                if moment >= WARMUP_SEC:
                    window[lot] = (route.cqt_target[index], moment + route.cqt_limit[index])
        elif kind == "start":
            moment, lots, steps = event[1], event[3], event[4]
            for lot, index in zip(lots, steps, strict=True):
                if lot in window and window[lot][0] == index:
                    if moment > window.pop(lot)[1] + 1e-6:
                        missed += 1
                    else:
                        met += 1
        elif kind in ("reclean", "qhold"):
            if window.pop(event[2], None) is not None:
                missed += 1
        elif kind == "skip":
            lot = event[2]
            if lot in window and window[lot][0] == event[3]:
                window.pop(lot)
    missed += sum(1 for _target, deadline in window.values() if deadline <= horizon)
    return {"q_steady_met": met, "q_steady_missed": missed}


def _one(item: tuple[int, str, str]) -> dict[str, Any]:
    seed, policy, arm = item
    hard = dict(ARMS)[arm]
    sim_policy = "resilimes" if policy == "planning" else policy
    plant, kwargs = qtime_study._setup(_FAB[0], BOOK, seed, sim_policy)
    result = run_policy(plant, hard_qtime=hard, **kwargs)
    horizon = kwargs["horizon"]
    row: dict[str, Any] = {"book": BOOK, "seed": seed, "policy": policy, "arm": arm}
    row["horizon_h"] = horizon / 3600.0
    for key in (
        "on_time_pct",
        "due_in_horizon",
        "completed_routes",
        "weighted_tardiness_min",
        "qtime_violations",
        "qtime_causes",
        "qtime_miss_class",
        "hard_qtime",
        "sim_s",
    ):
        row[key] = getattr(result, key)
    row["on_time"] = round(result.on_time_pct * result.due_in_horizon / 100.0)
    row.update(qtime_study.replay(plant, result.events, horizon))
    row.update(steady(plant, result.events, horizon))
    return row


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 2) if den else None


def _cls(rows: list[dict[str, Any]], key: str) -> int:
    return sum(row.get("qtime_miss_class", {}).get(key, 0) for row in rows)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pooled KPIs of one policy and arm over its seeds."""
    due = sum(row["due_in_horizon"] for row in rows)
    causes = {key: sum(row["qtime_causes"].get(key, 0) for row in rows) for key in CAUSES}
    hq = [row["hard_qtime"] for row in rows if row["hard_qtime"]]
    st_met = sum(row["q_steady_met"] for row in rows)
    st_all = st_met + sum(row["q_steady_missed"] for row in rows)
    out: dict[str, Any] = {
        "runs": len(rows),
        "on_time_pct": _pct(sum(row["on_time"] for row in rows), due),
        "completed_per_run": round(sum(row["completed_routes"] for row in rows) / len(rows), 1),
        "q_true_pct": _pct(sum(row["q_met"] for row in rows), sum(row["q_scored"] for row in rows)),
        "q_steady_pct": _pct(st_met, st_all),
        "weighted_tardiness_min": round(sum(row["weighted_tardiness_min"] for row in rows), 1),
        "missed_avoidable": _cls(rows, "avoidable"),
        "missed_unavoidable": _cls(rows, "unavoidable_breakdown")
        + _cls(rows, "unavoidable_disruption")
        + _cls(rows, "unavoidable_pre_gate"),
        "unavoidable_breakdown": _cls(rows, "unavoidable_breakdown"),
        "unavoidable_disruption": _cls(rows, "unavoidable_disruption"),
        "unavoidable_pre_gate": _cls(rows, "unavoidable_pre_gate"),
        "cause_avoidable": sum(causes[key] for key in AVOIDABLE),
        "cause_disruption": sum(causes[key] for key in DISRUPTION),
        "missed_inherited": sum(row["q_inherited_missed"] for row in rows),
        **{f"cause_{key}": causes[key] for key in CAUSES if key != "unclassified"},
    }
    if hq:
        rec = [h["recover_mean_min"] for h in hq if h["recover_mean_min"] is not None]
        out |= {
            "gate_blocks": sum(h["gate_blocks"] for h in hq),
            "expedited_lots": sum(h["expedited_lots"] for h in hq),
            "recovered": sum(h["recovered"] for h in hq),
            "recover_mean_min": round(sum(rec) / len(rec), 1) if rec else None,
            "recover_p90_min": max((h["recover_p90_min"] or 0.0) for h in hq),
        }
    return out


KEYS = (
    ("status", "Q-time feasibility"),
    ("missed_avoidable", "avoidable Q-time violations (3 seeds)"),
    ("missed_unavoidable", "unavoidable exceptions (3 seeds)"),
    ("unavoidable_breakdown", "  breakdown after the origin start"),
    ("unavoidable_disruption", "  target down / PM, rework, transport"),
    ("unavoidable_pre_gate", "  in a window before any gate decision (t=0 WIP chain)"),
    ("missed_inherited", "inherited windows missed (t=0 WIP)"),
    ("expedited_lots", "expedited exception lots"),
    ("recovered", "  recovered (target started)"),
    ("recover_mean_min", "  time to recover, mean (min)"),
    ("recover_p90_min", "  time to recover, p90 max (min)"),
    ("on_time_pct", "on-time %"),
    ("completed_per_run", "completed / run"),
    ("weighted_tardiness_min", "weighted tardiness (min, 3 seeds)"),
    ("q_true_pct", "true Q-time %"),
    ("q_steady_pct", "true Q-time % after 24 h"),
    ("cause_upstream", "misses by cause: upstream (still before target)"),
    ("cause_queueing", "  queueing at target"),
    ("cause_batch_fill", "  batch fill at target"),
    ("cause_tool_down_pm", "  target down / PM"),
    ("cause_breakdown_rework", "  breakdown / rework after start"),
    ("cause_transport", "  transport"),
    ("gate_blocks", "origin gate blocks (dispatch checks)"),
)


def label(policy: str, arm: str) -> str:
    gate = "hard" if dict(ARMS)[arm] else "off"
    return f"{policy} + {gate}" if policy == "planning" else f"{policy} ({gate})"


def feasibility(pooled: dict[str, Any]) -> str:
    """Candidate only with zero avoidable violations; else an infeasible reference."""
    n = pooled["missed_avoidable"]
    if n == 0:
        return "feasible"
    return f"infeasible: {n} avoidable Q-time violations"


def report(rows: list[dict[str, Any]]) -> str:
    """KPI table; Q-time-feasible configurations first, the rest as references.

    A configuration is a candidate only with zero avoidable Q-time
    violations. Q-time-blind rules (EDD and the others) are shown only as an
    industry reference with their avoidable-violation count, never as the
    winner or the comparison target.
    """
    pols = tuple(dict.fromkeys(row["policy"] for row in rows))
    pooled: dict[tuple[str, str], dict[str, Any]] = {}
    for p in pols:
        for a, _ in ARMS:
            chosen = [r for r in rows if r["policy"] == p and r["arm"] == a]
            if chosen:
                pooled[(p, a)] = aggregate(chosen)
                pooled[(p, a)]["status"] = feasibility(pooled[(p, a)])
    configs = sorted(pooled, key=lambda c: (pooled[c]["missed_avoidable"], c))
    heads = []
    for p, a in configs:
        name = label(p, a)
        if p != "planning":
            n = pooled[(p, a)]["missed_avoidable"]
            status = f"infeasible: {n} avoidable Q-time violations" if n else "feasible"
            name = f"{name}: industry reference ({status})"
        elif not dict(ARMS)[a]:
            name = f"{name} (experiment switch)"
        heads.append(name)
    lines = ["| KPI | " + " | ".join(heads) + " |"]
    lines.append("|---|" + "---:|" * len(configs))
    for key, text in KEYS:
        cells = [str(pooled[c].get(key, "-")) for c in configs]
        lines.append(f"| {text} | " + " | ".join(cells) + " |")
    best = [c for c in configs if pooled[c]["missed_avoidable"] == 0]
    if best:
        top = max(best, key=lambda c: pooled[c]["on_time_pct"] or 0.0)
        lines.append(
            f"\nAmong Q-time-feasible configurations, {label(*top)} gives the best on-time."
        )
    else:
        top = configs[0]
        lines.append(
            f"\nNo configuration is Q-time-feasible yet; the fewest avoidable violations: "
            f"{label(*top)} ({pooled[top]['missed_avoidable']})."
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    if sys.argv[1] == "--report":
        with open(sys.argv[2], encoding="utf-8") as handle:
            data = json.load(handle)
        print(report(data["rows"] if isinstance(data, dict) else data))
        return
    out = sys.argv[1]
    hours = float(os.environ.get("RESILIMES_STUDY_HORIZON_H", "168"))
    qtime_study.STUDY_HORIZON_SEC = hours * 3600.0
    _FAB.append(load_fab())
    items = [(seed, policy, arm) for seed in SEEDS for policy, arm in configs()]
    workers = max(1, int(os.environ.get("RESILIMES_STUDY_WORKERS", "2")))
    rows: list[dict[str, Any]] = []
    with (
        get_context("fork").Pool(workers, maxtasksperchild=3) as pool,
        open(f"{out}.partial.jsonl", "w", encoding="utf-8") as partial,
    ):
        for row in pool.imap_unordered(_one, items, chunksize=1):
            rows.append(row)
            partial.write(json.dumps(row) + "\n")
            partial.flush()
            print(
                f"{len(rows)}/{len(items)} s{row['seed']} {row['policy']} {row['arm']}", flush=True
            )
    rows.sort(key=lambda row: (row["seed"], row["policy"], row["arm"]))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"horizon_h": hours, "rows": rows}, handle, indent=1)
    print(f"hard Q-time study: {len(rows)} runs -> {out}")


if __name__ == "__main__":
    main()
