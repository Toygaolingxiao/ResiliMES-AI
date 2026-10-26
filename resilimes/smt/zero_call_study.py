"""Zero-call table for the normal (non-stress) book.

    python -m resilimes.smt.zero_call_study [--out-dir study_zero_call]

Runs the existing ``sim_llm`` wiring on a normal book/seed with the
provider swapped for ``MockProvider`` (a dry run of the exact live
path: same gate, same prompts, same selection), and the pure ``rules``
arm on the same book/seed. On a normal book the shipped gate is
expected to escalate nothing, so the AI is never called and the two
arms must agree KPI by KPI. The table reports exactly that — counts
and any difference, as measured, never assumed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

BOOK = "heldout_published"
SEED = 9
COMPARE_FIELDS = (
    "weighted_tardiness_min",
    "on_time_pct",
    "qtime_violations",
    "qtime_avoidable",
    "hot_late",
    "hot_due",
    "completed_routes",
)


def _manifest() -> dict[str, Any]:
    return {
        "environment": f"{platform.platform()} / python {platform.python_version()}",
        "ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "note": "sim_llm wiring run dry with MockProvider; no live model is called.",
    }


def compare_rules_vs_mock_wiring(
    row_rules: dict[str, Any], row_mock: dict[str, Any]
) -> dict[str, Any]:
    """Field-by-field deltas plus the AI-call accounting of the mock run."""
    fields: dict[str, Any] = {}
    identical = True
    for field in COMPARE_FIELDS:
        rules_value = row_rules.get(field)
        mock_value = row_mock.get(field)
        same = rules_value == mock_value
        identical = identical and same
        fields[field] = {"rules": rules_value, "sim_llm_mock": mock_value, "same": same}
    lead = row_mock.get("shift_lead") or {}
    return {
        "fields": fields,
        "identical": identical,
        "exceptions": lead.get("exceptions", len(row_mock.get("decisions") or [])),
        "escalations": lead.get("escalated"),
        "llm_calls": lead.get("llm_calls"),
    }


def run_zero_call_study(
    book: str = BOOK,
    seed: int = SEED,
    horizon_h: float = 5.0,
    fork_h: float = 1.0,
    futures: int = 2,
    workers: int = 0,
) -> dict[str, Any]:
    from resilimes.llm.mock import MockProvider
    from resilimes.smt import sim_select_study

    os.environ["RESILIMES_STUDY_HORIZON_H"] = f"{horizon_h:g}"
    args = argparse.Namespace(
        fork_h=fork_h,
        futures=futures,
        workers=workers,
        llm_timeout=30.0,
        budget=None,
        progress_s=3600.0,
    )
    row_rules = sim_select_study.run_one("rules", book, seed, args)
    with mock.patch.object(sim_select_study, "_completer", lambda arm: MockProvider()):
        row_mock = sim_select_study.run_one("sim_llm", book, seed, args)
    return {
        "manifest": _manifest(),
        "config": {
            "book": book,
            "seed": seed,
            "horizon_h": horizon_h,
            "fork_h": fork_h,
            "futures": futures,
            "mock_provider": "MockProvider (sim_llm wiring, dry)",
        },
        "comparison": compare_rules_vs_mock_wiring(row_rules, row_mock),
        "rows": {"rules": row_rules, "sim_llm_mock": row_mock},
    }


def render_md(result: dict[str, Any]) -> str:
    man, cfg, cmp_ = result["manifest"], result["config"], result["comparison"]
    lines = [
        "# 常态账本零调用表 (zero-call table)",
        "",
        f"- 运行环境 (environment): {man['environment']}",
        f"- 运行时间 (ran_at): {man['ran_at']}",
        f"- 代码版本 (git_commit): {man['git_commit']}",
        f"- 注记 (note): {man['note']}",
        f"- book {cfg['book']}, seed {cfg['seed']}, horizon {cfg['horizon_h']} h, "
        f"fork {cfg['fork_h']} h, futures {cfg['futures']}",
        "",
        f"异常 {cmp_['exceptions']} 个, 升级 {cmp_['escalations']} 次, "
        f"AI 调用 {cmp_['llm_calls']} 次。",
        "",
        "| 指标 | 纯规则 (rules) | sim_llm 接线 (mock 干跑) | 一致 |",
        "|---|---|---|---|",
    ]
    for field, record in cmp_["fields"].items():
        lines.append(
            f"| {field} | {record['rules']} | {record['sim_llm_mock']} | "
            f"{'是' if record['same'] else '否'} |"
        )
    lines += [
        "",
        "结论: "
        + (
            "常态账本上 gate 不升级, AI 零调用, 两臂逐项一致。"
            if cmp_["identical"] and cmp_["llm_calls"] == 0
            else "见上表差异 (如实记录, 不做粉饰)。"
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", default=BOOK)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--horizon-h", type=float, default=5.0)
    parser.add_argument("--fork-h", type=float, default=1.0)
    parser.add_argument("--futures", type=int, default=2)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--out-dir", default="study_zero_call")
    args = parser.parse_args(argv)
    result = run_zero_call_study(
        book=args.book,
        seed=args.seed,
        horizon_h=args.horizon_h,
        fork_h=args.fork_h,
        futures=args.futures,
        workers=args.workers,
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "zero_call.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (out / "zero_call.md").write_text(render_md(result), encoding="utf-8")
    cmp_ = result["comparison"]
    print(
        f"exceptions={cmp_['exceptions']} escalations={cmp_['escalations']} "
        f"llm_calls={cmp_['llm_calls']} identical={cmp_['identical']} -> {out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
