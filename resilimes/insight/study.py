"""AI eval studies: ``python -m resilimes.insight.study <study> [--provider ...]``.

Studies:
  cases         regenerate the 24 investigator cases (6 faults x 4 seeds)
  investigator  run every case through the investigator and the baseline
  all           every study in sequence (what scripts/run_ai_evals.* call)

``--provider mock`` (default in CI) uses the offline stand-ins and labels every
result ``mocked``; ``--provider nightshift`` requires Nightshift settings and
labels results with the model name. Secrets are never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from resilimes.config import ROOT, Settings, get_settings
from resilimes.evidence.toolkit import HOUR, RecordedRun, Toolkit, record_run
from resilimes.insight.injector import HORIZON_H, SEEDS, TAXONOMY, Case, make_case, rebuild
from resilimes.insight.progress import Progress, redact
from resilimes.llm.base import Completer
from resilimes.smt.fab import Fab, load_fab

CASES_PATH = ROOT / "eval" / "investigator_cases.json"
OUT_DIR = ROOT / "outputs" / "ai_eval"


def provider_for(name: str, settings: Settings) -> Completer | None:
    if name == "mock":
        return None
    if not settings.use_nightshift:
        raise SystemExit(
            "Nightshift is not configured (METERLESS_RUNTIME_TOKEN etc.); "
            "use --provider mock or set the env first."
        )
    from resilimes.llm.nightshift import NightshiftProvider

    return NightshiftProvider(settings)


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---- cases ---------------------------------------------------------------------------------
def make_cases(fab: Fab, seeds: tuple[int, ...] = SEEDS) -> list[Case]:
    progress = Progress("cases", len(seeds) * len(TAXONOMY))
    cases: list[Case] = []
    done = 0
    for seed in seeds:
        base = record_run(fab, seed=seed, horizon=HORIZON_H * HOUR)
        for fault in TAXONOMY:
            found = make_case(fab, fault, seed, base)
            done += 1
            status = f"{fault}/s{seed} " + (found[0].family if found else "NO CASE")
            if found:
                cases.append(found[0])
            progress.update(done, extra=status)
    progress.finish(extra=f"{len(cases)} cases")
    return cases


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Case.from_json(item) for item in payload["cases"]]


# ---- investigator --------------------------------------------------------------------------
def run_investigator(
    fab: Fab,
    cases: list[Case],
    provider: Completer | None,
    settings: Settings,
    out: Path,
    *,
    temperature: float = 0.2,
) -> dict[str, Any]:
    from resilimes.insight.investigator import baseline_rank, investigate, score

    label = "mock" if provider is None else f"real:{provider.model_for('investigator')}"
    progress = Progress("investigator", len(cases))
    rows: list[dict[str, Any]] = []
    bases: dict[int, RecordedRun] = {}
    for index, case in enumerate(cases):
        started = time.perf_counter()
        try:
            if case.seed not in bases:
                bases = {case.seed: record_run(fab, seed=case.seed, horizon=HORIZON_H * HOUR)}
            run = rebuild(fab, case, bases[case.seed])
            rank = baseline_rank(Toolkit(run), case.family, case.t1_h, case.t2_h)
            answer = investigate(
                Toolkit(run),
                case.question,
                case.family,
                case.t1_h,
                case.t2_h,
                provider,
                settings,
                temperature=temperature,
            )
            row: dict[str, Any] = {
                "case_id": case.case_id,
                "truth": case.fault,
                "baseline": rank[:2],
                "baseline_score": score(case.fault, rank[0], rank[1]),
                "stop_reason": answer.stop_reason,
                "degraded": answer.degraded,
                "degrade_reason": answer.degrade_reason,
                "ai": answer.to_json(),
                # The AI's own answer, scored as before (degraded cases are not rescued).
                "ai_score": score(case.fault, answer.primary_cause, answer.secondary_cause),
                # What the operator sees: the AI answer, or the rule answer when degraded.
                "system_score": score(
                    case.fault,
                    answer.system.get("primary_cause"),
                    answer.system.get("secondary_cause"),
                ),
                "seconds": round(time.perf_counter() - started, 1),
            }
        except Exception as exc:
            row = {
                "case_id": case.case_id,
                "truth": case.fault,
                "stop_reason": "error",
                "error": redact(repr(exc)),
            }
        rows.append(row)
        summary = summarize_investigator(rows, label)
        _write(out, {"summary": summary, "rows": rows})
        ai_part: dict[str, Any] = row.get("ai") or {}
        progress.update(
            index + 1,
            extra=(
                f"{case.case_id} ai={ai_part.get('primary_cause')} "
                f"| ai top1 {summary['ai_top1']}/{summary['n']} "
                f"base top1 {summary['baseline_top1']}/{summary['n']} "
                f"| non-nemotron {summary['model_audit']['non_nemotron_responses']}"
            ),
        )
    summary = summarize_investigator(rows, label)
    progress.finish(extra=f"ai top1 {summary['ai_top1']}/{summary['n']}")
    _write(out, {"summary": summary, "rows": rows})
    return summary


def summarize_investigator(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    ok = [row for row in rows if "error" not in row]
    by_fault: dict[str, dict[str, int]] = {}
    for row in ok:
        cell = by_fault.setdefault(row["truth"], {"n": 0, "ai_top1": 0, "base_top1": 0})
        cell["n"] += 1
        cell["ai_top1"] += int(row["ai_score"]["top1"])
        cell["base_top1"] += int(row["baseline_score"]["top1"])
    stop_reasons: dict[str, int] = {}
    degraded: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("stop_reason") or "")
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
        if row.get("degraded"):
            why = str(row.get("degrade_reason"))
            degraded[why] = degraded.get(why, 0) + 1
    return {
        "label": label,
        "model_audit": model_audit(rows),
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "ai_top1": sum(int(r["ai_score"]["top1"]) for r in ok),
        "ai_top2": sum(int(r["ai_score"]["top2"]) for r in ok),
        # Kept separate on purpose: ai_* is the AI's own answer, system_* is after the
        # degraded route to the rule answer. Never merge them.
        "system_top1": sum(int(r["system_score"]["top1"]) for r in ok if "system_score" in r),
        "system_top2": sum(int(r["system_score"]["top2"]) for r in ok if "system_score" in r),
        "degraded_count": sum(degraded.values()),
        "degraded_by_reason": degraded,
        "baseline_top1": sum(int(r["baseline_score"]["top1"]) for r in ok),
        "baseline_top2": sum(int(r["baseline_score"]["top2"]) for r in ok),
        "fact_ok": sum(int(r["ai"]["fact_ok"]) for r in ok),
        "repaired": sum(int(r["ai"]["repaired"]) for r in ok),
        "no_answer": sum(1 for r in ok if r["ai"]["primary_cause"] is None),
        "mean_tool_calls": round(sum(len(r["ai"]["calls"]) for r in ok) / max(1, len(ok)), 2),
        "by_fault": by_fault,
        "stop_reasons": stop_reasons,
    }


# ---- model audit ---------------------------------------------------------------------------
def is_nemotron(model: str) -> bool:
    """The model the response reported. A response that reported none is not confirmed."""
    model = model or ""
    return not model.startswith("unreported:") and "nemotron" in model.lower()


def model_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Which model actually answered each response; flags any that is not Nemotron."""
    counts: dict[str, int] = {}
    flagged: list[str] = []
    for row in rows:
        for model in (row.get("ai") or {}).get("response_models") or []:
            counts[model] = counts.get(model, 0) + 1
            if not is_nemotron(model):
                flagged.append(str(row.get("case_id") or row.get("lot") or row.get("id")))
    return {
        "responses": sum(counts.values()),
        "models": counts,
        "non_nemotron_responses": sum(n for m, n in counts.items() if not is_nemotron(m)),
        "non_nemotron_items": sorted(set(flagged)),
    }


# ---- late-lot explainer --------------------------------------------------------------------
def run_explainer(
    fab: Fab,
    provider: Completer | None,
    out: Path,
    *,
    seeds: tuple[int, ...] | None = None,
    limit: int = 0,
    temperature: float = 0.2,
) -> dict[str, Any]:
    from resilimes.evidence.lateness import late_lots
    from resilimes.insight import explainer as ex

    label = "mock" if provider is None else f"real:{provider.model_for(ex.LANE)}"
    seeds = seeds or ex.SEEDS
    bases = {seed: ex.base_run(fab, seed) for seed in seeds}
    work = [(seed, lot) for seed in seeds for lot in late_lots(bases[seed].timeline)]
    if limit:
        work = work[:limit]
    progress = Progress("explainer", len(work))
    rows: list[dict[str, Any]] = []
    for index, (seed, lot) in enumerate(work):
        base = bases[seed]
        lot_id = fab.lot_id[lot]
        row: dict[str, Any] = {"seed": seed, "lot": lot_id}
        try:
            row["split"] = ex.exact_split(base, lot)
            late = Toolkit(base).lot_lateness(lot_id)["while_late_min"]
            row["true_dominant"] = max(late, key=late.get) if late else None
            answer = ex.explain(Toolkit(base), lot_id, provider, temperature=temperature)
            row["ai"] = answer.to_json()
            row["cf"] = ex.verify(base, lot_id, answer) if answer.lever else {"verified": False}
        except Exception as exc:
            row["error"] = redact(repr(exc))
        rows.append(row)
        summary = summarize_explainer(rows, label)
        _write(out, {"summary": summary, "rows": rows})
        cf: dict[str, Any] = row.get("cf") or {}
        progress.update(
            index + 1,
            extra=(
                f"s{seed} {lot_id} saved={cf.get('saving_min')} "
                f"| exact {summary['exact_sum']}/{summary['n']} "
                f"cf hit {summary['cf_hit']}/{summary['cf_verified']} "
                f"| non-nemotron {summary['model_audit']['non_nemotron_responses']}"
            ),
        )
    summary = summarize_explainer(rows, label)
    progress.finish(extra=f"cf hit {summary['cf_hit']}/{summary['cf_verified']}")
    _write(out, {"summary": summary, "rows": rows})
    return summary


def summarize_explainer(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    ok = [row for row in rows if "error" not in row]
    answered = [row for row in ok if row["ai"]["lever"]]
    verified = [row for row in ok if row["cf"].get("verified")]
    levers: dict[str, int] = {}
    for row in answered:
        levers[row["ai"]["lever"]] = levers.get(row["ai"]["lever"], 0) + 1
    savings = [row["cf"]["saving_min"] for row in verified]
    return {
        "label": label,
        "model_audit": model_audit(rows),
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "exact_sum": sum(int(r["split"]["exact"]) for r in ok),
        "shown_sum_ok": sum(int(r["split"]["shown_sum_ok"]) for r in ok),
        "max_residual_sec": max((r["split"]["residual_sec"] for r in ok), default=0.0),
        "answered": len(answered),
        "fact_ok": sum(int(r["ai"]["fact_ok"]) for r in answered),
        "repaired": sum(int(r["ai"]["repaired"]) for r in answered),
        "dominant_match": sum(int(r["ai"]["dominant"] == r["true_dominant"]) for r in answered),
        "cf_verified": len(verified),
        "cf_hit": sum(int(r["cf"]["hit"]) for r in verified),
        "cf_helped": sum(1 for s in savings if s > 0),
        "mean_saving_min": round(sum(savings) / max(1, len(savings)), 1),
        "levers": levers,
    }


# ---- shift handover ------------------------------------------------------------------------
def run_handover(
    fab: Fab,
    provider: Completer | None,
    out: Path,
    *,
    limit: int = 0,
    temperature: float = 0.2,
) -> dict[str, Any]:
    from resilimes.insight import explainer as ex
    from resilimes.insight import handover as ho

    label = "mock" if provider is None else f"real:{provider.model_for(ho.LANE)}"
    work = [(seed, start, lang) for seed, start in ho.SHIFTS for lang in ho.LANGUAGES]
    if limit:
        work = work[:limit]
    bases = {seed: ex.base_run(fab, seed) for seed in sorted({seed for seed, _s, _l in work})}
    progress = Progress("handover", len(work))
    rows: list[dict[str, Any]] = []
    for index, (seed, start, lang) in enumerate(work):
        row: dict[str, Any] = {"id": f"s{seed}-{start:g}h-{lang}", "seed": seed, "lang": lang}
        try:
            result = ho.handover(
                bases[seed], start, provider, language=lang, temperature=temperature
            )
            row["ai"] = result
        except Exception as exc:
            row["error"] = redact(repr(exc))
        rows.append(row)
        summary = summarize_handover(rows, label)
        _write(out, {"summary": summary, "rows": rows})
        ai: dict[str, Any] = row.get("ai") or {}
        progress.update(
            index + 1,
            extra=(
                f"{row['id']} {ai.get('engine')} recall={ai.get('must_recall')} "
                f"| fact ok {summary['fact_ok']}/{summary['n']} "
                f"| non-nemotron {summary['model_audit']['non_nemotron_responses']}"
            ),
        )
    summary = summarize_handover(rows, label)
    progress.finish(extra=f"fact ok {summary['fact_ok']}/{summary['n']}")
    _write(out, {"summary": summary, "rows": rows})
    return summary


def summarize_handover(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    ok = [row["ai"] for row in rows if "error" not in row]
    reported = [ai for ai in ok if ai["report"]]
    recalls = [float(ai["must_recall"]) for ai in reported]
    engines: dict[str, int] = {}
    for ai in ok:
        engines[ai["engine"]] = engines.get(ai["engine"], 0) + 1
    return {
        "label": label,
        "model_audit": model_audit(rows),
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "reports": len(reported),
        "fact_ok": sum(int(ai["fact_ok"]) for ai in reported),
        "repaired": sum(int(ai["repaired"]) for ai in reported),
        "mean_must_recall": round(sum(recalls) / max(1, len(recalls)), 3),
        "min_must_recall": min(recalls, default=0.0),
        "engines": engines,
        "chunks_ok": sum(int(ai["chunks_ok"]) for ai in ok),
        "chunks": sum(len(ai["chunks"]) for ai in ok),
        "llm_calls": sum(int(ai["llm_calls"]) for ai in ok),
    }


# ---- CLI -----------------------------------------------------------------------------------
STUDIES: dict[str, Callable[..., Any]] = {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m resilimes.insight.study")
    parser.add_argument("study", choices=["cases", "investigator", "explainer", "handover", "all"])
    parser.add_argument("--provider", choices=["mock", "nightshift"], default="mock")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="first N cases only (0 = all)")
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args(argv)
    settings = get_settings()
    fab = load_fab()
    if args.study == "cases":
        cases = make_cases(fab)
        _write(args.cases, {"horizon_h": HORIZON_H, "cases": [c.to_json() for c in cases]})
        print(f"wrote {len(cases)} cases to {args.cases}")
        return 0
    provider = provider_for(args.provider, settings)
    tag = args.provider
    arms = ["investigator", "explainer", "handover"]
    studies = arms if args.study == "all" else [args.study]
    summaries: dict[str, Any] = {}
    for name in studies:
        if name == "investigator":
            cases = load_cases(args.cases)
            if args.limit:
                cases = cases[: args.limit]
            out = args.out_dir / f"investigator_{tag}.json"
            summary = run_investigator(
                fab, cases, provider, settings, out, temperature=args.temperature
            )
            print(json.dumps(summary, indent=1))
            print(f"wrote {out}")
            summaries[name] = summary
        if name == "explainer":
            out = args.out_dir / f"explainer_{tag}.json"
            summary = run_explainer(
                fab, provider, out, limit=args.limit, temperature=args.temperature
            )
            print(json.dumps(summary, indent=1))
            print(f"wrote {out}")
            summaries[name] = summary
        if name == "handover":
            out = args.out_dir / f"handover_{tag}.json"
            summary = run_handover(
                fab, provider, out, limit=args.limit, temperature=args.temperature
            )
            print(json.dumps(summary, indent=1))
            print(f"wrote {out}")
            summaries[name] = summary
    total = args.out_dir / f"summary_{tag}.json"
    flagged = sum(int(item["model_audit"]["non_nemotron_responses"]) for item in summaries.values())
    models: dict[str, int] = {}
    for item in summaries.values():
        for model, count in item["model_audit"]["models"].items():
            models[model] = models.get(model, 0) + count
    check = {
        "models": models,
        "non_nemotron_responses": flagged,
        "all_nemotron": provider is not None and bool(models) and flagged == 0,
    }
    _write(
        total,
        {"provider": tag, "mocked": provider is None, "model_check": check, "studies": summaries},
    )
    if provider is not None:
        verdict = "OK all Nemotron" if check["all_nemotron"] else "FLAG non-Nemotron responses"
        print(f"MODEL CHECK: {verdict}: {flagged} flagged; models {models}")
    print(f"wrote {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
