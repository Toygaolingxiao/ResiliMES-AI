"""Gate validation of the pre-registered generated stress set.

    python -m resilimes.smt.stress_gen_validate [--out-dir DIR] [--books a,b]

The inclusion rule was fixed in docs/STRESS_GEN_PREREG.md before this
module existed: each generated scenario is run once through the REAL
gate with no AI attached (``SimShiftLead`` without a completer, the
shipped ``exception`` escalation mode, twin fork 1 h, futures 2,
horizon 6 h, book seed 9). A scenario counts as triggered when at
least one exception passed ``rule_trigger`` and escalated
(``escalations >= 1`` in the lead summary). Untriggered scenarios are
excluded from the A/B/C run set and counted here, by name — the set is
never hand-picked after seeing results.

Runs are resumable: one JSON per scenario under the out dir; existing
files are skipped. Serial twin forks (workers=0) for shared boxes.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resilimes.smt import stress_gen
from resilimes.smt.fab import load_fab
from resilimes.smt.qtime_study import _setup

HOUR = 3600.0
SEED = 9
HORIZON_H = 6.0


def verdict(lead_summary: dict[str, Any]) -> bool:
    """The pre-registered trigger test: >= 1 gate escalation."""
    return int(lead_summary.get("escalated", 0)) >= 1


def _mode(rows: list[dict[str, Any]]) -> str:
    """Escalation mode for the header: what the rows recorded, else the environment."""
    from resilimes.agents.sim_select import escalation_mode

    modes = sorted({str(row["escalation_mode"]) for row in rows if row.get("escalation_mode")})
    return "/".join(modes) if modes else escalation_mode()


def validate_one(book: str) -> dict[str, Any]:
    """One no-AI gate run, wired exactly like sim_select_study.run_one."""
    import os

    os.environ.setdefault("RESILIMES_STUDY_HORIZON_H", str(HORIZON_H))
    from resilimes.agents.sim_select import SimShiftLead, escalation_mode
    from resilimes.smt.sim_select_study import hot_late
    from resilimes.smt.simulate import make_sim
    from resilimes.smt.twin import Twin, TwinConfig

    plant, kwargs = _setup(load_fab(), book, SEED, "resilimes")
    twin = Twin(
        plant,
        TwinConfig(horizon_sec=1 * HOUR, futures=2, workers=0),
    )
    lead = SimShiftLead(twin, completer=None, selector="pareto")
    t0 = time.time()
    try:
        sim = make_sim(plant, shift_lead=lead, **kwargs)
        result = sim.run()
    finally:
        twin.close()
    lead_summary = lead.summary()
    hot, _due = hot_late(sim, kwargs["horizon"])
    return {
        "book": book,
        "escalation_mode": escalation_mode(),
        "archetype": stress_gen.spec_for(book)["archetype"],
        "seed": SEED,
        "horizon_h": HORIZON_H,
        "wall_s": round(time.time() - t0, 1),
        "exceptions": lead_summary.get("exceptions", 0),
        "gate_checks": lead_summary.get("gate_checks", 0),
        "escalated": lead_summary.get("escalated", 0),
        "triggers": lead_summary.get("escalation_triggers", {}),
        "rule_handled": lead_summary.get("rule_handled", 0),
        "triggered": verdict(lead_summary),
        "kpi": {
            "qtime_avoidable": int(
                (getattr(result, "qtime_miss_class", None) or {}).get("avoidable", 0)
            ),
            "hot_late": hot,
            "weighted_tardiness_min": round(result.weighted_tardiness_min, 1),
            "completed_routes": result.completed_routes,
        },
    }


def aggregate(out_dir: Path) -> dict[str, Any]:
    specs = stress_gen.load_specs()
    rows: list[dict[str, Any]] = []
    for spec in specs:
        path = out_dir / f"validation_{spec['id']}.json"
        if path.exists():
            rows.append(json.loads(path.read_text("utf-8")))
    done = {row["book"] for row in rows}
    triggered = [row["book"] for row in rows if row["triggered"]]
    excluded = [row["book"] for row in rows if not row["triggered"]]
    pending = [spec["id"] for spec in specs if spec["id"] not in done]
    return {
        "environment": f"{platform.platform()} / python {platform.python_version()}",
        "ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "rule": "triggered := escalations >= 1 in the no-AI gate run "
        f"({_mode(rows)} mode, fork 1 h, futures 2, horizon {HORIZON_H:g} h, seed {SEED})",
        "generated": len(specs),
        "validated": len(rows),
        "triggered": triggered,
        "excluded_no_trigger": excluded,
        "pending": pending,
        "rows": rows,
    }


def render_md(summary: dict[str, Any]) -> str:
    lines = [
        "# 生成式压力场景 - gate 验证 (预注册规则)",
        "",
        f"- 运行环境 (environment): {summary['environment']}",
        f"- 运行时间 (ran_at): {summary['ran_at']}",
        f"- 代码版本 (git_commit): {summary['git_commit']}",
        f"- 规则 (rule): {summary['rule']}",
        "",
        f"生成 {summary['generated']} 个, 已验证 {summary['validated']} 个, "
        f"触发 {len(summary['triggered'])} 个, "
        f"未触发剔除 {len(summary['excluded_no_trigger'])} 个, "
        f"待验证 {len(summary['pending'])} 个。",
        "",
        "| 场景 | 原型 | 异常 | gate 检查 | 升级 (rule_trigger) | 触发 |",
        "|---|---|---|---|---|---|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['book']} | {row['archetype']} | {row['exceptions']} | "
            f"{row['gate_checks']} | {row['escalated']} | "
            f"{'是' if row['triggered'] else '否 (剔除)'} |"
        )
    if summary["pending"]:
        lines += ["", f"待验证 (未跑, 不在运行集内): {', '.join(summary['pending'])}"]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="study_stress_gen")
    parser.add_argument("--books", default="", help="comma-separated subset (default: all)")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    books = (
        [name.strip() for name in args.books.split(",") if name.strip()]
        if args.books
        else [spec["id"] for spec in stress_gen.load_specs()]
    )
    for book in books:
        path = out_dir / f"validation_{book}.json"
        if path.exists():
            print(f"[skip] {book} (done)", flush=True)
            continue
        print(f"[run] {book} ...", flush=True)
        row = validate_one(book)
        path.write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding="utf-8")
        print(
            f"[done] {book}: escalated={row['escalated']} triggered={row['triggered']} "
            f"({row['wall_s']} s)",
            flush=True,
        )
    summary = aggregate(out_dir)
    (out_dir / "validation.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "validation.md").write_text(render_md(summary), encoding="utf-8")
    print(
        f"validated {summary['validated']}/{summary['generated']}, "
        f"triggered {len(summary['triggered'])}, excluded {len(summary['excluded_no_trigger'])}, "
        f"pending {len(summary['pending'])} -> {out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
