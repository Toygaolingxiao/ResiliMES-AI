#!/usr/bin/env python3
"""Gap counterfactual (Plan 4 v1.5): fill the deliberate gaps, count the damage.

Method (pure simulation, no LLM):

1. Baseline run with the dispatch-time gap recorder on
   (``resilimes.smt.dispatch_log``). The deliberate gaps are the recorded
   ``qtime_gate`` and ``batch_wait`` decisions -- not post-hoc guesses.
2. Twin run of the same seed / horizon / downs / PM with every recorded
   gap "filled": each held lot gets a research-arm override
   (``force_start_at``) releasing it at the moment the gate / batch rule
   first held it. The override never exists on the default path.
3. Compare: how many *new avoidable* Q-time violations appeared
   (``qtime_miss_class["avoidable"]``, filled minus baseline), and for each
   filled gap whether filling it hurt -- for a gate gap, the held lot's
   Q-time window missed in the twin; for a batch gap, the twin started
   that tool's batch under the BATCHMN floor. A gap whose filling hurt is
   *protective*: the idle time was doing work.

Honesty limits, stated rather than hidden:

* All gaps are filled in ONE twin run, so per-gap attribution is
  indicative, not an isolated causal effect: fills interact (one released
  lot can jam another's segment). The aggregate delta (new avoidable
  violations) is the hard number; the protective share is the estimate.
* "Filled" means released at the next dispatch evaluation of a free,
  eligible tool of the family -- the earliest the dispatcher could have
  started the lot -- not at the exact refusal instant.
* PM-avoidance gaps are recorded but never filled: filling one means
  running into scheduled maintenance, a different intervention than
  releasing a scheduling hold.
* Every number below is a simulator result on the SMT2020 extract at the
  stated seed and horizon. Nothing here is measured on a real fab and no
  LLM is involved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from resilimes.evidence.timeline import Timeline, build_timeline  # noqa: E402
from resilimes.smt.dispatch_log import REASON_BATCH_WAIT, REASON_QTIME_GATE, GapRecorder  # noqa: E402
from resilimes.smt.fab import Fab, load_fab  # noqa: E402
from resilimes.smt.simulate import RunResult, make_sim, pm_windows, sample_downs  # noqa: E402

FILL_REASONS = (REASON_QTIME_GATE, REASON_BATCH_WAIT)
_WAFERS = 25


def _run(
    fab: Fab,
    *,
    seed: int,
    horizon: float,
    policy: str,
    recorder: GapRecorder | None = None,
    force_start_at: dict[tuple[int, int], float] | None = None,
) -> RunResult:
    sim = make_sim(
        fab,
        policy=policy,
        seed=seed,
        horizon=horizon,
        downs=sample_downs(fab, seed, horizon),
        pm=pm_windows(fab, horizon),
        hard_qtime=True,
        gap_recorder=recorder,
        force_start_at=force_start_at,
        record=True,
        lot_log=True,
    )
    return sim.run()


def _window_missed(timeline: Timeline, fab: Fab, lot: int, origin_step: int) -> bool | None:
    """Did ``lot``'s Q-time window from ``origin_step`` miss in this timeline?

    ``None`` = the lot never started the target step inside the horizon, so
    the twin cannot judge this gap (inconclusive, not protective).
    """
    route = fab.routes[fab.lot_route[lot]]
    target = route.cqt_target[origin_step]
    if target < 0:
        return None
    visits = [visit for visit in timeline.visits.get(lot, []) if visit.step == target]
    if not visits:
        return None
    if any(visit.outcome in ("qhold", "reclean") for visit in visits):
        return True
    origin_starts = [
        visit.start
        for visit in timeline.visits.get(lot, [])
        if visit.step == origin_step and visit.start is not None
    ]
    if origin_starts:
        first = min(origin_starts)
        if any(
            gap.kind == "qtime_hold" and gap.start >= first for gap in timeline.gaps.get(lot, [])
        ):
            return True
    return False


def analyse(
    fab: Fab, *, seed: int = 1, horizon_h: float = 12.0, policy: str = "resilimes"
) -> dict[str, Any]:
    horizon = horizon_h * 3600.0
    recorder = GapRecorder()
    base = _run(fab, seed=seed, horizon=horizon, policy=policy, recorder=recorder)
    gaps = [rec for rec in recorder.records if rec.reason in FILL_REASONS]
    force: dict[tuple[int, int], float] = {}
    for rec in gaps:
        for lot in rec.lots:
            key = (lot, rec.step)
            force[key] = min(force.get(key, float("inf")), rec.t)
    filled = _run(fab, seed=seed, horizon=horizon, policy=policy, force_start_at=force)
    timeline = build_timeline(
        fab,
        filled,
        downs=sample_downs(fab, seed, horizon),
        pm=pm_windows(fab, horizon),
    )

    per_reason: dict[str, dict[str, int]] = {}
    protective_total = 0
    filled_total = 0
    for rec in gaps:
        bucket = per_reason.setdefault(
            rec.reason, {"gaps": 0, "protective": 0, "not_protective": 0, "inconclusive": 0}
        )
        bucket["gaps"] += 1
        filled_total += 1
        if rec.reason == REASON_QTIME_GATE and rec.lot is not None:
            missed = _window_missed(timeline, fab, rec.lot, rec.step)
            verdict = (
                "inconclusive" if missed is None else ("protective" if missed else "not_protective")
            )
        elif rec.reason == REASON_BATCH_WAIT:
            floor_lots = int(rec.evidence.get("floor_wafers", 0)) // _WAFERS
            underfilled = any(
                t >= rec.t and tool == rec.tool and lots < floor_lots
                for t, tool, lots in timeline.starts
            )
            verdict = "protective" if underfilled else "not_protective"
        else:
            verdict = "inconclusive"
        bucket[verdict] += 1
        if verdict == "protective":
            protective_total += 1

    judged = sum(bucket["protective"] + bucket["not_protective"] for bucket in per_reason.values())
    base_avoidable = int(base.qtime_miss_class.get("avoidable", 0))
    filled_avoidable = int(filled.qtime_miss_class.get("avoidable", 0))
    return {
        "scenario": {
            "fab": "SMT2020 extract (simulated, not a real fab)",
            "policy": policy,
            "seed": seed,
            "horizon_h": horizon_h,
            "hard_qtime": True,
            "llm": False,
            "synthetic_scenario": False,
        },
        "gaps_recorded_total": len(recorder.records),
        "gaps_filled": filled_total,
        "gaps_by_reason": {
            reason: len(recorder.by_reason(reason))
            for reason in {r.reason for r in recorder.records}
        },
        "new_avoidable_qtime_violations": filled_avoidable - base_avoidable,
        "base_avoidable_qtime_violations": base_avoidable,
        "filled_avoidable_qtime_violations": filled_avoidable,
        "protective_share": round(protective_total / filled_total, 4) if filled_total else None,
        # Same share over judgeable gaps only (the twin reached a verdict);
        # inconclusive gaps are mostly a horizon artifact (target not
        # reached within the window), not evidence either way.
        "protective_share_judged": round(protective_total / judged, 4) if judged else None,
        "protective_total": protective_total,
        "per_reason": per_reason,
        "base_kpi": {
            "completed_routes": base.completed_routes,
            "qtime_violations": base.qtime_violations,
            "batch_reasons": base.batch_reasons,
        },
        "filled_kpi": {
            "completed_routes": filled.completed_routes,
            "qtime_violations": filled.qtime_violations,
            "batch_reasons": filled.batch_reasons,
        },
        "notes": [
            "All gaps filled in one twin run: per-gap attribution is indicative, fills interact.",
            "PM-avoidance gaps are recorded but never filled (different intervention).",
            "Simulator results on the SMT2020 extract; no LLM involved.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    sc = report["scenario"]
    lines = [
        "# Gap counterfactual: fill the deliberate gaps",
        "",
        f"Scenario: policy `{sc['policy']}`, seed {sc['seed']}, horizon {sc['horizon_h']} h, "
        f"fab = {sc['fab']}. Pure simulation, no LLM.",
        "",
        f"- Deliberate gaps recorded at dispatch time: **{report['gaps_recorded_total']}** "
        f"({report['gaps_by_reason']})",
        f"- Gaps filled in the twin run: **{report['gaps_filled']}**",
        f"- New avoidable Q-time violations after filling: **{report['new_avoidable_qtime_violations']}** "
        f"(baseline {report['base_avoidable_qtime_violations']} -> filled "
        f"{report['filled_avoidable_qtime_violations']})",
        f"- Protective gaps (filling them hurt): **{report['protective_total']}** "
        f"= share **{report['protective_share']}** of filled, "
        f"**{report.get('protective_share_judged')}** of judgeable gaps",
        "",
        "| reason | gaps | protective | not protective | inconclusive |",
        "|---|---|---|---|---|",
    ]
    for reason, bucket in sorted(report["per_reason"].items()):
        lines.append(
            f"| {reason} | {bucket['gaps']} | {bucket['protective']} | "
            f"{bucket['not_protective']} | {bucket['inconclusive']} |"
        )
    lines += ["", "## Limits", ""]
    lines += [f"- {note}" for note in report["notes"]]
    lines.append(
        "- Per-gap attribution comes from one twin run with all gaps filled at once; "
        "fills interact, so treat the share as an estimate and the violation delta as the hard number."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--hours", type=float, default=12.0)
    parser.add_argument("--policy", default="resilimes")
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args()
    report = analyse(load_fab(), seed=args.seed, horizon_h=args.hours, policy=args.policy)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.out_json:
        args.out_json.write_text(text + "\n", encoding="utf-8")
    if args.out_md:
        args.out_md.write_text(render_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
