"""One-command A/B/C run on the pre-registered generated stress set.

    python scripts/run_stress_live.py --mock            (dry wiring check)
    python scripts/run_stress_live.py                   (live, tonight's run)
    python scripts/run_stress_live.py --seeds 9,10,11 --out-dir study_stress_live

Scenario set: the scenarios that passed the no-AI gate validation
(``study_stress_gen/validation.json``, rule fixed in
docs/STRESS_GEN_PREREG.md before any run). Untriggered scenarios are
excluded there and counted in this report too; scenarios still pending
validation are NOT run (no hand-picking).

Arms (all K=3 proposer budget, twin fork 1 h, futures 2, serial):

* A ``sim``        - no-AI twin baseline: engine plans + Pareto.
* B ``sim_search`` - non-AI lever search (SearchCompleter) + Pareto.
* C ``sim_llm``    - Nemotron via the existing sim_llm path (propose +
                     select); ``--mock`` swaps in MockProvider and the
                     report is banner-marked MOCK.

Serial friendly: one run at a time, one request at a time; after every
run the script prints elapsed time and an ETA for the remaining runs
(average wall time x runs left). Resumable: finished runs are JSON
files under ``<out-dir>/<arm>/<book>_s<seed>.json`` and are skipped on
rerun. ``report.json`` / ``report.md`` are rewritten after every run.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARMS = {"A": "sim", "B": "sim_search", "C": "sim_llm"}
ARM_LABELS = {
    "A": "A - no-AI twin baseline (engine plans + Pareto)",
    "B": "B - non-AI lever search (SearchCompleter K=3 + Pareto)",
    "C": "C - Nemotron via sim_llm path (K=3, propose + select)",
}
MAX_PLANS = 3
HORIZON_H = 6.0


def scenario_set(validation_path: Path, override: list[str]) -> tuple[list[str], dict[str, Any]]:
    """The run set: validated-and-triggered scenarios, nothing else."""
    if override:
        return override, {"source": "--books override (flagged, not the registered set)"}
    if not validation_path.exists():
        raise SystemExit(
            f"validation summary not found: {validation_path}\n"
            "Run the gate validation first: "
            "python -m resilimes.smt.stress_gen_validate --out-dir study_stress_gen"
        )
    summary = json.loads(validation_path.read_text("utf-8"))
    return list(summary["triggered"]), summary


def run_args(llm_timeout: float) -> argparse.Namespace:
    return argparse.Namespace(
        fork_h=1.0,
        futures=2,
        workers=0,  # serial: one fork at a time on any machine
        llm_timeout=llm_timeout,
        budget=None,
        progress_s=3600.0,
        max_plans=MAX_PLANS,
    )


def degradation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fallback / timeout accounting over C-arm rows."""
    failures: dict[str, int] = {}
    calls = 0
    served: dict[str, int] = {}
    for row in rows:
        lead = row.get("shift_lead") or {}
        calls += int(lead.get("llm_calls", 0))
        for kind, count in (lead.get("llm_failures") or {}).items():
            failures[kind] = failures.get(kind, 0) + int(count)
        for model, count in (lead.get("served_models") or {}).items():
            served[model] = served.get(model, 0) + int(count)
    return {
        "llm_calls": calls,
        "failures_by_kind": failures,
        "timeouts": failures.get("timeout", 0),
        "fallbacks_total": sum(failures.values()),
        "served_models": served,
        "non_nemotron_replies": sum(
            int((row.get("shift_lead") or {}).get("non_nemotron_replies", 0)) for row in rows
        ),
    }


def wtl(rows_by_arm: dict[str, dict[tuple[str, int], dict[str, Any]]]) -> dict[str, Any]:
    """C vs A and C vs B, per (scenario, seed), pre-registered lexi_cmp."""
    from resilimes.smt.sim_select_study import lexi_cmp

    out: dict[str, Any] = {}
    for rival in ("A", "B"):
        wins = ties = losses = 0
        detail = []
        for key, crow in sorted(rows_by_arm.get("C", {}).items()):
            base = rows_by_arm.get(rival, {}).get(key)
            if base is None:
                continue
            cmp = lexi_cmp(crow, base)
            wins += cmp < 0
            ties += cmp == 0
            losses += cmp > 0
            detail.append({"book": key[0], "seed": key[1], "cmp": cmp})
        out[f"C_vs_{rival}"] = {"win": wins, "tie": ties, "loss": losses, "detail": detail}
    return out


def build_report(
    out_dir: Path,
    mode: str,
    validation: dict[str, Any],
    books: list[str],
    seeds: list[int],
) -> dict[str, Any]:
    rows_by_arm: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    for arm_key in ARMS:
        arm_dir = out_dir / arm_key
        found: dict[tuple[str, int], dict[str, Any]] = {}
        if arm_dir.exists():
            for path in sorted(arm_dir.glob("*_s*.json")):
                row = json.loads(path.read_text("utf-8"))
                found[(row["book"], int(row["seed"]))] = row
        rows_by_arm[arm_key] = found
    planned = len(books) * len(seeds)
    report: dict[str, Any] = {
        "manifest": {
            "environment": f"{platform.platform()} / python {platform.python_version()}",
            "ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "git_commit": subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "mode": mode,
            "mock": mode == "mock",
            "max_plans": MAX_PLANS,
            "horizon_h": HORIZON_H,
            "served_models": degradation(list(rows_by_arm["C"].values()))["served_models"],
        },
        "validation": {
            "generated": validation.get("generated"),
            "validated": validation.get("validated"),
            "triggered_count": len(validation.get("triggered", [])),
            "excluded_no_trigger": validation.get("excluded_no_trigger", []),
            "pending": validation.get("pending", []),
            "trigger_rate": (
                round(
                    len(validation.get("triggered", []))
                    / max(1, int(validation.get("validated", 0))),
                    3,
                )
                if validation.get("validated")
                else None
            ),
        },
        "runs_planned_per_arm": planned,
        "runs_done": {arm: len(rows) for arm, rows in rows_by_arm.items()},
        "wtl": wtl(rows_by_arm),
        "degradation_C": degradation(list(rows_by_arm["C"].values())),
        "rows": {
            arm: {f"{book}|{seed}": row for (book, seed), row in sorted(rows.items())}
            for arm, rows in rows_by_arm.items()
        },
    }
    return report


def render_md(report: dict[str, Any]) -> str:
    man, val = report["manifest"], report["validation"]
    lines = ["# 生成式压力集 A/B/C 对比报告", ""]
    if man["mock"]:
        lines += [
            "> **MOCK 模式**: C 臂为 MockProvider, 本报告所有数字仅验证管线, ",
            "> 不是 live 结果, 不得与 live 数字混排。",
            "",
        ]
    lines += [
        f"- 运行环境 (environment): {man['environment']}",
        f"- 运行时间 (ran_at): {man['ran_at']}",
        f"- 代码版本 (git_commit): {man['git_commit']}",
        f"- 模式 (mode): {man['mode']}; 模型 (served): {man['served_models']}",
        f"- 触发率 (trigger rate): 已验证 {val['validated']} 个场景中触发 "
        f"{val['triggered_count']} 个 (rate={val['trigger_rate']}); "
        f"未触发剔除 {len(val['excluded_no_trigger'])} 个: "
        f"{', '.join(val['excluded_no_trigger']) or '-'}; "
        f"待验证 {len(val['pending'])} 个 (不在运行集内)",
        "",
        "## 胜平负 (预注册词典序: 可避免 Q-time -> 热批迟到 -> 加权迟到)",
        "",
        "| 对比 | 胜 | 平 | 负 |",
        "|---|---|---|---|",
    ]
    for name, record in report["wtl"].items():
        lines.append(f"| {name} | {record['win']} | {record['tie']} | {record['loss']} |")
    deg = report["degradation_C"]
    lines += [
        "",
        "## C 臂降级 / 超时",
        "",
        f"- LLM 调用: {deg['llm_calls']}; 降级总计: {deg['fallbacks_total']} "
        f"(其中超时 timeout: {deg['timeouts']}); 非 Nemotron 回复: "
        f"{deg['non_nemotron_replies']}",
        f"- 失败分类: {deg['failures_by_kind']}",
        "",
        "## 各场景指标 (A / B / C)",
        "",
        "| 场景 | seed | 臂 | 可避免 Q-time | 热批迟到 | 加权迟到 (min) | 完成批数 | 升级 | LLM 调用 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    rows = report["rows"]
    keys = sorted({key for arm_rows in rows.values() for key in arm_rows})
    for key in keys:
        book, seed = key.rsplit("|", 1)
        for arm in ("A", "B", "C"):
            row = rows.get(arm, {}).get(key)
            if row is None:
                continue
            lead = row.get("shift_lead") or {}
            lines.append(
                f"| {book} | {seed} | {arm} | {row.get('qtime_avoidable')} | "
                f"{row.get('hot_late')} | {row.get('weighted_tardiness_min')} | "
                f"{row.get('completed_routes')} | {lead.get('escalated', 0)} | "
                f"{lead.get('llm_calls', 0)} |"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock", action="store_true", help="C arm = MockProvider (dry wiring check)"
    )
    parser.add_argument("--out-dir", default="study_stress_live")
    parser.add_argument("--validation", default="study_stress_gen/validation.json")
    parser.add_argument("--books", default="", help="comma-separated override (flagged in report)")
    parser.add_argument("--seeds", default="9")
    parser.add_argument("--llm-timeout", type=float, default=300.0)
    parser.add_argument(
        "--first", type=int, default=0, help="only the first N scenario x seed pairs"
    )
    args = parser.parse_args(argv)

    os.environ["RESILIMES_STUDY_HORIZON_H"] = f"{HORIZON_H:g}"
    os.environ.setdefault("RESILIMES_SEARCH_SEED", "20261026")
    out_dir = ROOT / args.out_dir if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    override = [name.strip() for name in args.books.split(",") if name.strip()]
    books, validation = scenario_set(ROOT / args.validation, override)
    seeds = [int(s) for s in args.seeds.split(",") if s]
    pairs = [(book, seed) for seed in seeds for book in books]
    if args.first:
        pairs = pairs[: args.first]
    mode = "mock" if args.mock else "live"

    if not args.mock:
        from resilimes.smt.sim_select_study import _completer

        try:
            _completer("sim_llm")  # same guard as the study: live config or stop
        except RuntimeError as exc:
            print(f"live mode unavailable: {exc}")
            print("Configure the Nightshift .env (RESILIMES_MODE=live) or run with --mock.")
            return 2

    from resilimes.smt.sim_select_study import run_one

    study_args = run_args(args.llm_timeout)
    jobs = [(arm_key, book, seed) for (book, seed) in pairs for arm_key in ("A", "B", "C")]
    done_walls: list[float] = []
    for index, (arm_key, book, seed) in enumerate(jobs, start=1):
        target = out_dir / arm_key / f"{book}_s{seed}.json"
        if target.exists():
            print(f"[skip] {arm_key} {book} s{seed}", flush=True)
            continue
        study_arm = "sim_mock" if (arm_key == "C" and args.mock) else ARMS[arm_key]
        print(f"[run {index}/{len(jobs)}] {arm_key} ({study_arm}) {book} s{seed} ...", flush=True)
        t0 = time.time()
        row = run_one(study_arm, book, seed, study_args)
        wall = time.time() - t0
        done_walls.append(wall)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding="utf-8")
        remaining = len(jobs) - index
        eta_min = (sum(done_walls) / len(done_walls)) * remaining / 60.0 if done_walls else 0.0
        print(
            f"[done] wall {wall:.0f} s; elapsed {sum(done_walls) / 60.0:.1f} min; "
            f"ETA remaining ~{eta_min:.1f} min ({remaining} runs)",
            flush=True,
        )
        report = build_report(out_dir, mode, validation, books, seeds)
        (out_dir / "report.json").write_text(
            json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "report.md").write_text(render_md(report), encoding="utf-8")
    print(f"report -> {out_dir}/report.md (mode={mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
