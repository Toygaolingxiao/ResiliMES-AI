#!/usr/bin/env python3
"""Context-investigation evaluation: template arm vs full arm.

Runs the fixed question set (``eval/context_questions.json``) through
``investigate_context`` twice:

- ``template`` — provider ``None``: the deterministic scripted answer
  (pure evidence assembly, no model).
- ``full`` — evidence chaining plus a model rewrite. In CI the model is
  ``EvalPolisher``, a deterministic mock that only compresses the
  scripted answer's own sentences, so the comparison is reproducible
  offline. Window questions are the exception: their answers come from
  the investigator's own loop, which has no context-layer rewrite, so
  both arms run the repo's canonical scripted investigator — the arms
  only differ under a live provider there. On the owner's machine the
  same script can be pointed at the live provider to fill the live
  numbers in the report.

Metrics per arm: fact-check pass rate, evidence-point coverage (the
fixture's pre-registered points), and the tier distribution. Outputs
``report.json`` + ``report.md`` under ``--out-dir``.

Usage: python scripts/run_context_eval.py [--limit N] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

os.environ.setdefault("RESILIMES_SCHED_MODE", "strict_qtime")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resilimes.evidence.toolkit import HOUR, Toolkit, record_run
from resilimes.insight.context_investigation import ContextQuery, investigate_context
from resilimes.llm.base import Completer, LlmResult

FIXTURE = Path(__file__).resolve().parents[1] / "eval" / "context_questions.json"


class EvalPolisher(Completer):
    """Deterministic stand-in for the live model: keeps the scripted
    answer's first two sentences verbatim (a faithful but lossy rewrite,
    which is exactly what the coverage metric is meant to catch)."""

    mocked = False
    name = "eval-polisher"

    def model_for(self, lane: str) -> str:
        return "nemotron-eval-mock"

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.2
    ) -> LlmResult:
        user = messages[-1]["content"]
        answer = user.split("ANSWER: ", 1)[1] if "ANSWER: " in user else user
        sentences = [s.strip() for s in answer.split(". ") if s.strip()]
        kept = ". ".join(sentences[:2])
        if kept and not kept.endswith("."):
            kept += "."
        return LlmResult(
            content=json.dumps({"answer": kept}),
            model="nemotron-eval-mock",
            provider=self.name,
            lane=lane,
            latency_ms=0.0,
            mocked=False,
            provider_model="nemotron-eval-mock",
        )


def build_kits(run_keys: set[str]) -> dict[str, Toolkit]:
    kits: dict[str, Toolkit] = {}
    if "smt24" in run_keys:
        from resilimes.smt.fab import load_fab

        kits["smt24"] = Toolkit(record_run(load_fab(), seed=1, horizon=24 * HOUR))
    if "starve" in run_keys:
        from resilimes.insight.injector import rebuild
        from resilimes.insight.study import load_cases
        from resilimes.smt.fab import load_fab

        fab = load_fab()
        case = next(c for c in load_cases() if c.case_id == "upstream_starvation-s1")
        base = record_run(fab, seed=case.seed, horizon=48 * HOUR)
        kits["starve"] = Toolkit(rebuild(fab, case, base))
    return kits


def check_point(answer: Any, point: dict[str, Any]) -> bool:
    if "answer_contains" in point:
        return str(point["answer_contains"]) in answer.answer
    if "tier" in point:
        return answer.tier == point["tier"]
    if "status" in point:
        return answer.status == point["status"]
    if "primary_cause" in point:
        return answer.primary_cause == point["primary_cause"]
    if "basis_kind" in point or "basis_source" in point:
        for entry in answer.basis:
            if "basis_kind" in point and entry["kind"] != point["basis_kind"]:
                continue
            if "basis_source" in point and entry["source"] != point["basis_source"]:
                continue
            if "contains" in point and str(point["contains"]) not in json.dumps(
                entry["facts"], ensure_ascii=False
            ):
                continue
            return True
        return False
    return False


def check_expect(answer: Any, expect: dict[str, Any]) -> bool:
    return check_point(answer, expect) if expect else True


def evaluate(
    fixture: dict[str, Any],
    kits: dict[str, Toolkit],
    *,
    limit: int | None = None,
    live_provider: Any = None,
) -> dict[str, Any]:
    """Run both arms over the fixture; returns the report dict.

    ``live_provider`` (a Completer) replaces the deterministic EvalPolisher
    in the full arm — the owner's live run (``--live``). None (default)
    keeps the CI behaviour byte-identical.
    """
    questions = fixture["questions"][:limit] if limit else fixture["questions"]
    arms: dict[str, Any] = {}
    for arm in ("template", "full"):
        rows = []
        for item in questions:
            # Window answers have no context-layer rewrite (see docstring):
            # the full arm's polisher applies to bar/gap/free only.
            if arm == "full" and item["query"]["type"] != "window":
                provider = live_provider if live_provider is not None else EvalPolisher()
            else:
                provider = None
            spec = item["query"]
            query = ContextQuery(
                type=spec["type"],
                tool=spec.get("tool"),
                family=spec.get("family"),
                lot=spec.get("lot"),
                step=spec.get("step"),
                t1_h=spec.get("t1_h"),
                t2_h=spec.get("t2_h"),
                question_preset=spec.get("question_preset"),
                question=spec.get("question"),
            )
            answer = investigate_context(kits[item["run"]], query, provider, None)
            points = [check_point(answer, point) for point in item["points"]]
            rows.append(
                {
                    "id": item["id"],
                    "type": item["query"]["type"],
                    "tier": answer.tier,
                    "status": answer.status,
                    "fact_ok": answer.fact_ok,
                    "fact_misses": list(answer.fact_misses),
                    "expect_ok": check_expect(answer, item.get("expect", {})),
                    "points_passed": sum(points),
                    "points_total": len(points),
                    "source": answer.source,
                    "degraded": answer.degraded,
                }
            )
        total_points = sum(r["points_total"] for r in rows)
        arms[arm] = {
            "fact_check_pass_rate": round(
                sum(1 for r in rows if r["fact_ok"]) / max(1, len(rows)), 3
            ),
            "evidence_point_coverage": round(
                sum(r["points_passed"] for r in rows) / max(1, total_points), 3
            ),
            "expect_pass_rate": round(
                sum(1 for r in rows if r["expect_ok"]) / max(1, len(rows)), 3
            ),
            "tier_distribution": dict(Counter(r["tier"] for r in rows)),
            "rows": rows,
        }
    return {
        "fixture_version": fixture.get("version"),
        "full_arm_provider": (
            f"{live_provider.name} (live)"
            if live_provider is not None
            else "EvalPolisher (deterministic mock)"
        ),
        "arms": arms,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Context investigation evaluation",
        "",
        "Fixed question set: `eval/context_questions.json` "
        f"(version {report['fixture_version']}). Arms: template = scripted "
        "evidence assembly (no model); full = evidence chaining + model "
        "rewrite (EvalPolisher mock in CI).",
        "",
        "| arm | fact-check pass rate | evidence-point coverage | expect pass rate | tiers |",
        "| --- | --- | --- | --- | --- |",
    ]
    for arm, data in report["arms"].items():
        tiers = ", ".join(f"{k}: {v}" for k, v in sorted(data["tier_distribution"].items()))
        lines.append(
            f"| {arm} | {data['fact_check_pass_rate']} | {data['evidence_point_coverage']} "
            f"| {data['expect_pass_rate']} | {tiers} |"
        )
    lines += [
        "",
        "## Live numbers (owner machine, Nightshift / Nemotron)",
        "",
        "Filled by the owner after a live run; the CI numbers above use the",
        "deterministic EvalPolisher mock and are not live-model results.",
        "",
        "| arm | fact-check pass rate | evidence-point coverage | expect pass rate | tiers | date | model |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| full (live) |  |  |  |  |  |  |",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/context_eval"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        help="full arm uses the live provider from settings (RESILIMES_MODE=live, "
        "Nightshift/Nemotron on the owner's machine) instead of the EvalPolisher mock",
    )
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    questions = fixture["questions"][: args.limit] if args.limit else fixture["questions"]
    kits = build_kits({item["run"] for item in questions})
    live_provider = None
    if args.live:
        from resilimes.config import Settings
        from resilimes.llm.factory import build_provider

        live_provider = build_provider(Settings())
        print(
            f"live provider: {live_provider.name} (mocked={getattr(live_provider, 'mocked', '?')})"
        )
    report = evaluate(fixture, kits, limit=args.limit, live_provider=live_provider)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (args.out_dir / "report.md").write_text(render_md(report), encoding="utf-8")
    for arm, data in report["arms"].items():
        print(
            f"{arm}: fact={data['fact_check_pass_rate']} "
            f"coverage={data['evidence_point_coverage']} expect={data['expect_pass_rate']} "
            f"tiers={data['tier_distribution']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
