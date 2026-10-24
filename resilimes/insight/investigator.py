"""AI investigator: "why did <family> WIP double between t1 and t2?".

A model (Nemotron through Nightshift; a scripted stand-in offline) runs a
bounded tool loop (at most ``MAX_CALLS`` evidence calls) over the toolkit and
guarded SQL, then answers with a causal chain, one primary cause from
``TAXONOMY``, an advisory lever, and citations to its calls. Every number and
ID in the answer must appear in a tool result (``factcheck.check``); one
repair turn is allowed, after that the answer is flagged, never silently
accepted. The lever is advice only: nothing is executed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from resilimes.agents.jsonutil import extract_json_object
from resilimes.config import Settings
from resilimes.evidence.factcheck import FactRegistry, check
from resilimes.evidence.sqlrun import run_guarded
from resilimes.evidence.toolkit import HOUR, Toolkit
from resilimes.insight.injector import CAUSE_TEXT, TAXONOMY, main_upstream
from resilimes.llm.base import Completer, LlmResult

MAX_CALLS = 6
MAX_TURNS = 10
RESULT_CHARS = 3500
LANE = "investigator"

TOOLS_DOC = """Tools (call one per turn):
- family_wip {"family": str, "start_h": num, "end_h": num}: waiting / in-process lots each hour.
- family_window {"family": str, "start_h": num, "end_h": num}: arrivals, starts, tool-hours down/pm/busy/idle, setup minutes per start, lots per batch start, mean wait.
- tool_states {"family": str, "start_h": num, "end_h": num}: per tool hours down/pm/busy/idle and the down / PM windows.
- upstream {"family": str, "start_h": num, "end_h": num}: which families the arrivals in the window came from.
- maintenance {"family": str}: downtime model (MTTF/MTTR) and PM calendars.
- sql {"sql": str}: one read-only SELECT on fab_ops.ops_events / fab_ops.ops_kpi_hourly / fab_ops.ops_ai_decisions, resilimes.smt_tool, fab_cmms.smt_downcal and the other allowlisted tables (LIMIT <= 200). fab_ops holds a reference run (seed 1, 12 h), not this run."""

SYSTEM = (
    "You are a senior semiconductor fab engineer investigating a WIP change in a "
    "simulated fab. Use the tools to gather evidence, then answer. Reply with ONE JSON "
    "object and nothing else. To call a tool: "
    '{"tool": "<name>", "args": {...}}. To answer: {"final": {"primary_cause": "<one of '
    'the causes>", "secondary_cause": "<another cause or null>", "causal_chain": ["step", '
    '...], "lever": "<one advisory action>", "citations": [<result numbers>]}}. '
    "Every number and tool or family name you write must be copied from a tool result "
    "or the question. Do not invent numbers. The lever is advice only."
)


@dataclass
class Investigation:
    question: str
    family: str
    t1_h: float
    t2_h: float
    primary_cause: str | None = None
    secondary_cause: str | None = None
    causal_chain: list[str] = field(default_factory=list)
    lever: str = ""
    citations: list[int] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    fact_misses: list[str] = field(default_factory=list)
    fact_ok: bool = False
    repaired: bool = False
    turns: int = 0
    llm_calls: int = 0
    latency_ms: float = 0.0
    provider: str = ""
    model: str = ""
    mocked: bool = True
    # The model each response actually came from (LlmResult.model), one per LLM call.
    response_models: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


# ---- evidence calls -----------------------------------------------------------------------
def execute(
    kit: Toolkit, name: str, args: dict[str, Any], settings: Settings | None
) -> dict[str, Any]:
    """Run one tool call. Errors come back as ``{"error": ...}``; nothing raises."""
    try:
        if name == "sql":
            out = run_guarded(str(args.get("sql", "")), settings)
            kit.registry.add(out)
            kit.calls.append({"tool": "sql", "args": {"sql": out.get("sql")}})
            return out
        family = args.get("family")
        if name == "maintenance":
            return kit.maintenance(str(family))
        if name in ("family_wip", "family_window", "tool_states", "upstream"):
            start_h = float(args.get("start_h", 0.0))
            end_h = float(args.get("end_h", kit.run.horizon / HOUR))
            start_h = max(0.0, min(start_h, kit.run.horizon / HOUR))
            end_h = max(start_h, min(end_h, kit.run.horizon / HOUR))
            return getattr(kit, name)(str(family), start_h, end_h)
        if name == "lot_trace":
            return kit.lot_trace(str(args.get("lot_id", "")))
        return {"error": f"unknown tool {name!r}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


# ---- baseline: biggest anomaly ------------------------------------------------------------
def anomaly_scores(kit: Toolkit, family: str, t1_h: float, t2_h: float) -> dict[str, float]:
    """Relative change of each cause's metric, window [t1, t2) vs the 4 h before t1."""
    fam = kit.family_id(family)
    lo = max(1.0, t1_h - 4.0)
    win = kit.window_stats(fam, t1_h * HOUR, max(t2_h, t1_h + 1.0) * HOUR)
    ref = kit.window_stats(fam, lo * HOUR, t1_h * HOUR)

    def frac(stats: dict[str, float], key: str) -> float:
        return stats[key] / max(1e-9, stats["tools"] * stats["hours"])

    def rel(new: float, old: float, floor: float) -> float:
        return max(0.0, min(5.0, (new - old) / max(old, floor)))

    scores = {
        "tool_down": rel(frac(win, "down_tool_h"), frac(ref, "down_tool_h"), 0.1),
        "pm_in_peak": rel(frac(win, "pm_tool_h"), frac(ref, "pm_tool_h"), 0.1),
        "release_burst": rel(win["arrivals_per_h"], ref["arrivals_per_h"], 1.0),
        "setup_thrash": rel(win["setup_min_per_start"], ref["setup_min_per_start"], 1.0),
        "batch_cap": 0.0,
        "upstream_starvation": 0.0,
    }
    if kit._is_batch(fam) and ref["lots_per_start"] > 0 and win["lots_per_start"] > 0:
        scores["batch_cap"] = max(
            0.0, min(5.0, (ref["lots_per_start"] - win["lots_per_start"]) / ref["lots_per_start"])
        )
    up = main_upstream(kit, fam)
    if up >= 0:
        uw = kit.window_stats(up, t1_h * HOUR, max(t2_h, t1_h + 1.0) * HOUR)
        ur = kit.window_stats(up, lo * HOUR, t1_h * HOUR)
        lost_w = frac(uw, "down_tool_h") + frac(uw, "pm_tool_h")
        lost_r = frac(ur, "down_tool_h") + frac(ur, "pm_tool_h")
        scores["upstream_starvation"] = rel(lost_w, lost_r, 0.1)
    return scores


def baseline_rank(kit: Toolkit, family: str, t1_h: float, t2_h: float) -> list[str]:
    scores = anomaly_scores(kit, family, t1_h, t2_h)
    return sorted(TAXONOMY, key=lambda cause: (-scores[cause], TAXONOMY.index(cause)))


# ---- offline stand-in for the model -------------------------------------------------------
class ScriptedCompleter:
    """Offline stand-in: fixed evidence plan, then the biggest-anomaly answer.

    It goes through the same loop, parser and fact check as the model, so CI
    exercises the plumbing. Its accuracy equals the baseline by construction.
    """

    name = "scripted-mock"
    mocked = True

    def __init__(self, kit: Toolkit, family: str, t1_h: float, t2_h: float) -> None:
        self.kit = kit
        self.family = family
        self.t1_h = t1_h
        self.t2_h = t2_h
        fam = kit.family_id(family)
        up = main_upstream(kit, fam)
        self.upstream = kit.fab.families[up].name if up >= 0 else family
        self.lo = max(1.0, t1_h - 4.0)

    def model_for(self, lane: str) -> str:
        return "scripted-mock"

    def plan(self) -> list[dict[str, Any]]:
        f, lo, t1, t2 = self.family, self.lo, self.t1_h, self.t2_h
        return [
            {"tool": "family_wip", "args": {"family": f, "start_h": lo, "end_h": t2}},
            {"tool": "family_window", "args": {"family": f, "start_h": lo, "end_h": t1}},
            {"tool": "family_window", "args": {"family": f, "start_h": t1, "end_h": t2}},
            {"tool": "tool_states", "args": {"family": f, "start_h": t1, "end_h": t2}},
            {"tool": "upstream", "args": {"family": f, "start_h": t1, "end_h": t2}},
            {
                "tool": "family_window",
                "args": {"family": self.upstream, "start_h": t1, "end_h": t2},
            },
        ]

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.0
    ) -> LlmResult:
        del lane, temperature
        results = [m["content"] for m in messages if m["content"].startswith("RESULT ")]
        plan = self.plan()
        if len(results) < len(plan) and not any(
            "budget used" in m["content"] for m in messages if m["role"] == "user"
        ):
            content = json.dumps(plan[len(results)])
        else:
            content = json.dumps({"final": self._final(results)})
        return LlmResult(
            content=content,
            model="scripted-mock",
            provider=self.name,
            lane=LANE,
            latency_ms=0.1,
            mocked=True,
        )

    def _final(self, results: list[str]) -> dict[str, Any]:
        def body(index: int) -> dict[str, Any]:
            try:
                text = results[index].split(":", 1)[1].strip()
                return dict(json.JSONDecoder().raw_decode(text)[0])
            except (IndexError, ValueError):
                return {}

        rank = baseline_rank(self.kit, self.family, self.t1_h, self.t2_h)
        ref, win, up = body(1), body(2), body(5)
        series = body(0).get("series", [])
        first = next((p for p in series if p.get("hour") == round(self.t1_h, 2)), None)
        last = series[-1] if series else None
        chain = []
        if first and last:
            chain.append(
                f"{self.family} waiting lots went from {first['waiting']} at {first['hour']} h "
                f"to {last['waiting']} at {last['hour']} h."
            )
        metric = {
            "tool_down": ("down_tool_h", "tool-hours down", win, ref),
            "pm_in_peak": ("pm_tool_h", "tool-hours in PM", win, ref),
            "release_burst": ("arrivals", "arrivals", win, ref),
            "setup_thrash": ("setup_min_per_start", "setup minutes per start", win, ref),
            "batch_cap": ("lots_per_start", "lots per batch start", win, ref),
            "upstream_starvation": ("down_tool_h", f"tool-hours down at {self.upstream}", up, {}),
        }[rank[0]]
        key, label, now, before = metric
        if key in now:
            text = f"In the window the family had {now[key]} {label}"
            if key in before:
                text += f", against {before[key]} in the hours before"
            chain.append(text + ".")
        chain.append(f"That points to: {CAUSE_TEXT[rank[0]]}.")
        levers = {
            "tool_down": "Escalate the repair of the down tools and route urgent lots first.",
            "pm_in_peak": "Move the PM out of the arrival peak to a low-WIP hour.",
            "release_burst": "Smooth releases upstream instead of letting lots arrive at once.",
            "setup_thrash": "Group lots by recipe to cut changeovers on this family.",
            "batch_cap": "Restore the batch size limit and fill batches before starting.",
            "upstream_starvation": "Recover the upstream family first; this family is starved.",
        }
        return {
            "primary_cause": rank[0],
            "secondary_cause": rank[1],
            "causal_chain": chain,
            "lever": levers[rank[0]],
            "citations": [1, 2, 3, 6] if rank[0] == "upstream_starvation" else [1, 2, 3, 4],
        }


# ---- the loop -----------------------------------------------------------------------------
def _intro(question: str, family: str, t1_h: float, t2_h: float) -> str:
    causes = "\n".join(f"- {key}: {text}" for key, text in CAUSE_TEXT.items())
    return (
        f"Question: {question}\nFamily: {family}. Window: {t1_h:g} h to {t2_h:g} h "
        f"(simulated hours since the start of the run).\n"
        f"Possible primary causes (pick exactly one; secondary is optional):\n{causes}\n\n"
        f"{TOOLS_DOC}\n\nYou may make at most {MAX_CALLS} tool calls. Start."
    )


def _validate(final: Any, ncalls: int) -> list[str]:
    errors = []
    if not isinstance(final, dict):
        return ["final must be an object"]
    if final.get("primary_cause") not in TAXONOMY:
        errors.append(f"primary_cause must be one of {list(TAXONOMY)}")
    second = final.get("secondary_cause")
    if second not in (None, "", "null") and second not in TAXONOMY:
        errors.append("secondary_cause must be one of the causes or null")
    chain = final.get("causal_chain")
    if not isinstance(chain, list) or not chain or not all(isinstance(s, str) for s in chain):
        errors.append("causal_chain must be a non-empty list of strings")
    if not isinstance(final.get("lever"), str):
        errors.append("lever must be a string")
    cites = final.get("citations", [])
    if not isinstance(cites, list) or any(
        not isinstance(c, int) or c < 1 or c > ncalls for c in cites
    ):
        errors.append(f"citations must be result numbers 1..{ncalls}")
    return errors


def investigate(
    kit: Toolkit,
    question: str,
    family: str,
    t1_h: float,
    t2_h: float,
    provider: Completer | None = None,
    settings: Settings | None = None,
    *,
    max_calls: int = MAX_CALLS,
    temperature: float = 0.2,
) -> Investigation:
    """Bounded tool loop. ``provider`` None or mocked -> the scripted stand-in."""
    if provider is None or provider.mocked:
        provider = ScriptedCompleter(kit, family, t1_h, t2_h)
    kit.registry = kit.registry or FactRegistry()
    kit.registry.add_text(question)
    kit.registry.add_text(f"{family} {t1_h:g} {t2_h:g} {max_calls}")
    out = Investigation(
        question=question,
        family=family,
        t1_h=t1_h,
        t2_h=t2_h,
        provider=provider.name,
        model=provider.model_for(LANE),
        mocked=provider.mocked,
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _intro(question, family, t1_h, t2_h)},
    ]
    ncalls = 0
    repairs = 0
    started = time.perf_counter()
    final: dict[str, Any] | None = None
    while out.turns < MAX_TURNS:
        out.turns += 1
        try:
            reply = provider.complete(messages, lane=LANE, temperature=temperature)
        except Exception as exc:
            out.error = f"provider: {type(exc).__name__}"
            break
        out.llm_calls += 1
        out.response_models.append(reply.provider_model or f"unreported:{reply.model}")
        messages.append({"role": "assistant", "content": reply.content})
        try:
            payload = extract_json_object(reply.content)
        except (ValueError, json.JSONDecodeError):
            messages.append(
                {"role": "user", "content": "Reply with one JSON object only (tool or final)."}
            )
            continue
        if "final" in payload:
            errors = _validate(payload["final"], ncalls)
            if errors and repairs < 2:
                repairs += 1
                messages.append(
                    {"role": "user", "content": "Fix the final answer: " + "; ".join(errors)}
                )
                continue
            final = payload["final"] if not errors else None
            if errors:
                out.error = "invalid final: " + "; ".join(errors)
            if final is not None:
                text = " ".join([*final.get("causal_chain", []), str(final.get("lever", ""))])
                misses = check(text, kit.registry)
                if misses and not out.repaired:
                    out.repaired = True
                    messages.append(
                        {
                            "role": "user",
                            "content": "These numbers/names are not in any tool result: "
                            + ", ".join(misses[:12])
                            + ". Rewrite the final answer using only values from the results.",
                        }
                    )
                    final = None
                    continue
                out.fact_misses = misses
            break
        name = str(payload.get("tool", ""))
        if ncalls >= max_calls:
            messages.append(
                {"role": "user", "content": "Tool budget used. Give the final answer now."}
            )
            continue
        args = payload.get("args") or {}
        result = execute(kit, name, args if isinstance(args, dict) else {}, settings)
        ncalls += 1
        out.calls.append({"n": ncalls, "tool": name, "args": args})
        text = json.dumps(result, ensure_ascii=False, default=str)[:RESULT_CHARS]
        note = "" if ncalls < max_calls else " Tool budget used. Give the final answer now."
        messages.append({"role": "user", "content": f"RESULT {ncalls}: {text}{note}"})
    out.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if final is not None:
        out.primary_cause = final.get("primary_cause")
        second = final.get("secondary_cause")
        out.secondary_cause = second if second in TAXONOMY else None
        out.causal_chain = [str(s) for s in final.get("causal_chain", [])]
        out.lever = str(final.get("lever", ""))
        out.citations = [int(c) for c in final.get("citations", [])]
        out.fact_ok = not out.fact_misses
    elif out.error is None:
        out.error = "no final answer within the turn limit"
    return out


def score(truth: str, primary: str | None, secondary: str | None) -> dict[str, bool]:
    return {"top1": primary == truth, "top2": truth in (primary, secondary)}
