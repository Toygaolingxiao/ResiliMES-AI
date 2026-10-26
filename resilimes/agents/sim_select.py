"""Propose -> fork -> simulate -> select at escalated shift-lead exceptions.

Off by default: only ``SimShiftLead`` (attached explicitly, e.g. by the
study's ``sim-*`` arms) uses it; ``ShiftLead`` and the dispatcher are
unchanged.

Rules first. At every exception the rule default plan is what runs. A
no-AI gate (``rule_trigger``) forks the twin for the rule default alone and
escalates only if that plan is projected (mean over the sampled futures) to
cause at least one avoidable Q-time violation (``hard_qtime.miss_class``) or
at least one late hot/VIP lot inside the fork horizon. Otherwise the rule
default stands, no model is called, and the exception is logged as
``rule_ok``. ``SHIFT_LEAD_ESCALATE=always`` restores the old kind-based
filter (``escalate``) for experiments only.

At an exception that is escalated:

1. Candidates: the engine's options (``resilimes.smt.exceptions``), plus, with
   a proposer, up to ``MAX_PLANS`` typed plans from the model in a small JSON
   DSL (``keep_pin``, ``reroute``, ``boost``, ``defer_pm``, ``start_batch``).
2. Guardrails validate every plan (scope, flex-PM rule, frozen lots).
3. The digital twin (``resilimes.smt.twin``) forks the simulator and runs the
   rule default and each valid plan ``horizon`` hours ahead over ``futures``
   resampled futures (no oracle: breakdowns after now are redrawn).
4. Selection. ``pareto`` (sim-only, no model): a plan replaces the default only
   if its mean is no worse on Q-time violations, hot/VIP late and weighted
   tardiness and strictly better on one. ``llm``: the model picks from the
   numbers table and must cite them; a number checker rejects any cited
   number that is not in the table. Timeout, bad output, a failed number
   check or a plan worse on hot/VIP late than the default fall back to the
   rule default.

Every decision is logged with a counterfactual receipt (chosen vs default
means on the same futures). Non-escalated exceptions keep the rule default
and are logged with ``escalation_reason`` (``rule_ok`` or ``filter``).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from resilimes.agents.jsonutil import extract_json_object
from resilimes.agents.shift_lead import DecisionError, RuleDefault, ShiftLead
from resilimes.llm.base import Completer, LlmResult
from resilimes.smt.exceptions import (
    _BOOST,
    LOOKAHEAD_SEC,
    FabException,
    Lever,
    Option,
    _covering,
    _due_base,
    _latest_waiting,
    inbound_lots,
    waiting_lots,
)
from resilimes.smt.twin import PlanScore, Twin

PLAN_LANE = "shift_lead_plan"
SELECT_LANE = "shift_lead_select"
REQUIRED_MODEL = "nemotron"  # live replies must be served by a Nemotron model
MAX_PLANS = 4
MAX_LEVERS = 4
BOOST_MAX_MIN = 60.0
KEEP_PIN_MAX_H = 8.0
PM_FLEX_SEC = 24 * 3600.0
QTIME_ESCALATE_MIN = 2  # legacy filter: default projects >= this many more misses
ALWAYS_ESCALATE = ("breakdown", "pm_conflict", "hot_insertion", "batch_underfill")  # legacy
ESCALATE_ENV = "SHIFT_LEAD_ESCALATE"
ESCALATE_MODES = ("exception", "always")  # exception: rules first (default)
# Pre-registered gate (not tuned): the rule default's mean over the fork's
# sampled futures must reach this many avoidable Q-time misses or late
# hot/VIP lots for the shift lead to be asked.
GATE_QAVOID_MIN = 1.0
GATE_HOT_LATE_MIN = 1.0
METRICS = ("wt_min", "qviol", "hot_late", "late_lots", "on_time")
PROMPT_LOTS = 30


# ------------------------------------------------------------------ escalation
def escalation_mode(value: str | None = None) -> str:
    """``exception`` (default, rules first) or ``always`` (legacy experiment)."""
    raw = os.environ.get(ESCALATE_ENV, "") if value is None else value
    mode = (raw or "exception").strip().lower()
    if mode not in ESCALATE_MODES:
        raise ValueError(f"{ESCALATE_ENV} must be one of {', '.join(ESCALATE_MODES)}")
    return mode


def rule_trigger(default: PlanScore) -> str | None:
    """The exception-only gate on the rule default's twin score.

    Returns the trigger (``avoidable_qtime`` or ``hot_late``) when the rule
    default is projected to cause at least one avoidable Q-time violation or
    one late hot/VIP lot (means over the futures); None means the rule plan
    handles the exception (``rule_ok``).
    """
    if default.mean("qavoid") >= GATE_QAVOID_MIN - 1e-9:
        return "avoidable_qtime"
    if default.mean("hot_late") >= GATE_HOT_LATE_MIN - 1e-9:
        return "hot_late"
    return None


def escalate(exc: FabException) -> bool:
    """Legacy kind filter, only with ``SHIFT_LEAD_ESCALATE=always``."""
    if exc.kind in ALWAYS_ESCALATE:
        return True
    if exc.kind == "qtime_competition":
        base = exc.default.impact
        best = min(
            (o.impact.qtime_violations for o in exc.options if o.impact is not None),
            default=None,
        )
        if base is None or best is None:
            return False
        return base.qtime_violations - best >= QTIME_ESCALATE_MIN
    return False


# ------------------------------------------------------------------ plans
@dataclass
class Plan:
    id: str
    source: str  # rule_default | engine | llm | memory
    action: str
    levers: list[Lever] = field(default_factory=list)
    spec: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "action": self.action,
            "levers": self.spec,
            "valid": self.error is None,
            "error": self.error,
        }


def engine_plans(exc: FabException) -> list[Plan]:
    out = []
    for option in exc.options:
        source = "rule_default" if option.default else "engine"
        levers = [] if option.lever.kind == "none" else [option.lever]
        out.append(Plan(option.id, source, option.action, levers, [{"type": option.lever.kind}]))
    return out


def _overlap(span: tuple[float, float], spans: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(span[1], b) - max(span[0], a)) for a, b in spans)


def flex_pm_error(
    sim: Any, planned: list[list[tuple[float, float]]], tool: int, index: int, shift: float
) -> str | None:
    """The user's flex-PM rule. None means the move is allowed.

    * the new start is within +/-24 h of the published (planned) start and
      after now; the shift is not zero;
    * no overlap with the same tool's previous or next PM;
    * no new family overlap: the tool's PM time shared with sibling tools'
      PMs must not grow (the SMT2020 calendar puts a whole family in PM at
      once; moving one tool may only reduce that).
    """
    spans = sim.pm[tool]
    if index < 0 or index >= len(spans) or shift == 0:
        return "flex_pm: no such window or zero shift"
    start_at, end_at = spans[index]
    if start_at <= sim.clock:
        return "flex_pm: window already started"
    new = (start_at + shift, end_at + shift)
    if new[0] <= sim.clock:
        return "flex_pm: new start is in the past"
    origin = planned[tool][index][0] if index < len(planned[tool]) else start_at
    if abs(new[0] - origin) > PM_FLEX_SEC + 1e-6:
        return "flex_pm: more than 24 h from the planned start"
    others = [span for k, span in enumerate(spans) if k != index]
    if _overlap(new, others) > 0:
        return "flex_pm: overlaps the tool's previous/next PM"
    fam = sim.fab.tool_family[tool]
    family = sim.fab.families[fam]
    siblings = [
        span
        for other in range(family.tool0, family.tool0 + family.tools)
        if other != tool
        for span in sim.pm[other]
    ]
    if _overlap(new, siblings) > _overlap((start_at, end_at), siblings) + 1e-6:
        return "flex_pm: two tools of the family in PM together"
    return None


class PlanBuilder:
    """Turns DSL plans into levers, enforcing every guardrail."""

    def __init__(
        self, sim: Any, exc: FabException, moment: float, planned: list[list[tuple[float, float]]]
    ) -> None:
        self.sim = sim
        self.exc = exc
        self.moment = moment
        self.planned = planned
        fab = sim.fab
        self.by_name = {fab.lot_id[lot]: lot for lot in exc.lots}
        family = fab.families[exc.family]
        self.tools = {fab.tool_name[t]: t for t in range(family.tool0, family.tool0 + family.tools)}
        rows = inbound_lots(sim, moment, moment + LOOKAHEAD_SEC).get(exc.family, [])
        self.inbound = {lot: nxt for lot, nxt, _eta in rows}
        self.waiting = set(waiting_lots(sim, exc.family))
        self.repair = None
        if exc.kind == "breakdown" and exc.tool >= 0:
            window = _covering(sim.downs[exc.tool], moment)
            self.repair = None if window is None else window[1]

    def _lots(self, raw: Any) -> list[int]:
        if not isinstance(raw, list) or not raw:
            raise ValueError("lots must be a non-empty list of lot ids")
        out = []
        for name in raw:
            lot = self.by_name.get(str(name))
            if lot is None:
                raise ValueError(f"lot {str(name)[:20]} is not in this exception")
            if lot not in out:
                out.append(lot)
        return out

    def _frozen_elsewhere(self, lot: int) -> bool:
        fz = getattr(self.sim, "fz", None)
        if fz is None or not getattr(fz, "enabled", False):
            return False
        return not any(fz.free_for(lot, tool) for tool in self.tools.values())

    def _step(self, lot: int) -> int:
        if lot in self.waiting:
            return int(self.sim.step[lot])
        if lot in self.inbound:
            return int(self.inbound[lot])
        raise ValueError("lot is neither queued at nor inbound to the family")

    def lever(self, item: Any) -> tuple[Lever, set[int], set[int]]:
        """One DSL lever -> (Lever, kept lots, rerouted lots)."""
        if not isinstance(item, dict):
            raise ValueError("lever must be an object")
        kind = item.get("type")
        sim, exc, moment = self.sim, self.exc, self.moment
        if kind == "keep_pin":
            lots = self._lots(item.get("lots"))
            if self.repair is not None:
                until = self.repair
            else:
                hours = float(item.get("hours", 2.0))
                if not 0 < hours <= KEEP_PIN_MAX_H:
                    raise ValueError("keep_pin hours out of (0, 8]")
                until = moment + hours * 3600.0
            return Lever("keep_pin", keep_pin=frozenset(lots), until=until), set(lots), set()
        if kind == "reroute":
            if exc.kind != "breakdown":
                raise ValueError("reroute only at a breakdown")
            lots = self._lots(item.get("lots"))
            for lot in lots:
                if self._frozen_elsewhere(lot):
                    raise ValueError("frozen lot may not be rerouted")
            return Lever(), set(), set(lots)
        if kind == "boost":
            lots = self._lots(item.get("lots"))
            ttl = float(item.get("ttl_min", BOOST_MAX_MIN))
            if not 0 < ttl <= BOOST_MAX_MIN:
                raise ValueError("boost ttl_min out of (0, 60]")
            prio: dict[tuple[int, int], float] = {}
            for rank, lot in enumerate(lots):
                if self._frozen_elsewhere(lot):
                    raise ValueError("frozen lot may not be boosted")
                prio[(lot, self._step(lot))] = _BOOST + rank * 1e-6
            return Lever("prio", prio=prio, until=moment + ttl * 60.0), set(), set()
        if kind == "defer_pm":
            tool = self.tools.get(str(item.get("tool")))
            if tool is None:
                raise ValueError("defer_pm tool not in the exception's family")
            shift = float(item.get("shift_min", 0.0)) * 60.0
            index = next((k for k, (a, _b) in enumerate(sim.pm[tool]) if a > sim.clock), -1)
            error = flex_pm_error(sim, self.planned, tool, index, shift)
            if error is not None:
                raise ValueError(error)
            return Lever("pm_defer", pm=(tool, index, shift)), set(), set()
        if kind == "start_batch":
            if not sim.batch_family[exc.family]:
                raise ValueError("start_batch on a non-batch family")
            recipe = int(item.get("recipe", -1))
            recipes = {
                int(sim.fab.routes[sim.fab.lot_route[lot]].recipe[sim.step[lot]])
                for lot in self.waiting
            }
            if recipe not in recipes:
                raise ValueError("start_batch recipe has no waiting lots")
            until = moment + 30 * 60.0
            return Lever("batch_start", batch=(exc.family, recipe), until=until), set(), set()
        raise ValueError(f"unknown lever type {str(kind)[:20]}")

    def plan(self, plan_id: str, raw: Any) -> Plan:
        spec = raw.get("levers") if isinstance(raw, dict) else None
        why = str(raw.get("why", ""))[:200] if isinstance(raw, dict) else ""
        plan = Plan(plan_id, "llm", why or "model plan", [], spec if isinstance(spec, list) else [])
        try:
            if not isinstance(spec, list) or not spec or len(spec) > MAX_LEVERS:
                raise ValueError(f"levers must be a list of 1-{MAX_LEVERS}")
            kept: set[int] = set()
            moved: set[int] = set()
            for item in spec:
                lever, keep, move = self.lever(item)
                kept |= keep
                moved |= move
                if lever.kind != "none":
                    plan.levers.append(lever)
            if kept & moved:
                raise ValueError("a lot is both kept and rerouted")
            if sum(1 for lever in plan.levers if lever.kind == "pm_defer") > 1:
                raise ValueError("at most one PM move per plan")
        except (ValueError, TypeError) as error:
            plan.error = str(error)[:120]
            plan.levers = []
        return plan


# ------------------------------------------------------------------ prompts
def situation(sim: Any, exc: FabException, moment: float) -> dict[str, Any]:
    """Compact facts for the model; the same view feeds the memory."""
    fab = sim.fab
    family = fab.families[exc.family]
    lots = []
    for lot in exc.lots[:PROMPT_LOTS]:
        latest = _latest_waiting(sim, lot)
        step = int(sim.step[lot])
        lots.append(
            {
                "lot": fab.lot_id[lot],
                "class": ("VIP", "hot", "normal")[min(2, sim.tier(lot))],
                "queued_here": bool(lot in set(waiting_lots(sim, exc.family))),
                "qtime_slack_min": None if latest is None else round((latest - moment) / 60.0),
                "due_slack_min": round((_due_base(sim, lot, step) - moment) / 60.0),
            }
        )
    tools = []
    for tool in range(family.tool0, family.tool0 + family.tools):
        down = _covering(sim.downs[tool], moment)
        nxt = next(((a, b) for a, b in sim.pm[tool] if b > moment), None)
        tools.append(
            {
                "tool": fab.tool_name[tool],
                "busy": bool(sim.running[tool] >= 0),
                "down_until_h": None if down is None else round(down[1] / 3600.0, 2),
                "next_pm_h": None
                if nxt is None
                else [round(nxt[0] / 3600.0, 2), round(nxt[1] / 3600.0, 2)],
            }
        )
    return {
        "now_h": round(moment / 3600.0, 2),
        "kind": exc.kind,
        "family": family.name,
        "situation": exc.situation,
        "facts": exc.facts,
        "lots": lots,
        "tools": tools,
        "engine_options": [option.as_dict() for option in exc.options],
    }


def plan_system(max_plans: int = MAX_PLANS) -> str:
    """The PLAN_LANE prompt for a given proposer budget. ``plan_system()``
    with no argument is byte-identical to the shipped prompt."""
    return (
        "You are the shift lead of a semiconductor fab (SMT2020). A rule-based "
        "dispatcher runs the fab; you only act at this exception. Propose up to "
        f"{max_plans} alternative plans to the rule default. Every plan is tested in "
        "a simulator over several sampled futures before anything is applied, so "
        "propose plans that are genuinely different. Levers (JSON):\n"
        '{"type":"keep_pin","lots":[ids],"hours":h} lots wait for their pinned tool;\n'
        '{"type":"reroute","lots":[ids]} (breakdown only) lots go to a sibling tool;\n'
        '{"type":"boost","lots":[ids in order],"ttl_min":<=60} run these first;\n'
        '{"type":"defer_pm","tool":name,"shift_min":m} move the next PM of a family '
        "tool by m minutes (negative = earlier); within 24 h of plan, no overlap "
        "with its other PMs, no two family tools in PM together;\n"
        '{"type":"start_batch","recipe":r} start an under-filled furnace batch now.\n'
        "Only lots and tools listed in the input. Fixed lots stay on their tool. "
        'Reply with JSON only: {"plans":[{"id":"P1","levers":[...],"why":"..."}]}'
    )


PLAN_SYSTEM = plan_system()

SELECT_SYSTEM = (
    "You are the shift lead of a semiconductor fab. Each candidate plan was "
    "simulated over the same sampled futures. Lower is better for wt_min "
    "(value-weighted tardiness minutes), qviol (Q-time violations), hot_late "
    "and late_lots; higher is better for on_time. Pick one plan. Never pick a "
    "plan with more hot_late than the rule default. Justify with numbers copied "
    "exactly from the table. Reply with JSON only: "
    '{"plan_id":"...","reason":"...","cited":{"<plan_id>.<metric>":number}}'
)


def numbers_table(scores: dict[str, PlanScore], plans: dict[str, Plan]) -> list[dict[str, Any]]:
    rows = []
    for plan_id, score in scores.items():
        summary = score.summary()
        rows.append(
            {
                "plan_id": plan_id,
                "source": plans[plan_id].source,
                "action": plans[plan_id].action,
                "mean": {key: summary[key] for key in METRICS},
                "per_future": {
                    key: [round(float(getattr(run, key)), 2) for run in score.runs]
                    for key in ("wt_min", "qviol", "hot_late")
                },
            }
        )
    return rows


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def check_numbers(answer: dict[str, Any], table: list[dict[str, Any]]) -> str | None:
    """Every cited number must be a table mean; every number in the reason a
    table value (plan ids are stripped first). None means it passes."""
    means = {
        f"{row['plan_id']}.{key}": float(value)
        for row in table
        for key, value in row["mean"].items()
    }
    values = set(means.values())
    for row in table:
        for series in row["per_future"].values():
            values.update(float(v) for v in series)
    cited = answer.get("cited")
    if not isinstance(cited, dict) or not cited:
        return "number_check: no cited numbers"
    for key, value in cited.items():
        if key not in means:
            return f"number_check: unknown cell {str(key)[:30]}"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "number_check: cited value is not a number"
        if abs(number - means[key]) > max(0.051, 0.01 * abs(means[key])):
            return f"number_check: {key} cited {number}, table {means[key]}"
    reason = str(answer.get("reason", ""))
    for row in table:
        reason = re.sub(rf"\b{re.escape(str(row['plan_id']))}\b", " ", reason)
    for text in _NUMBER.findall(reason):
        number = float(text)
        if not any(abs(number - v) <= max(0.051, 0.01 * abs(v)) for v in values):
            return f"number_check: {text} is not in the table"
    return None


# ------------------------------------------------------------------ selection
def pareto_pick(scores: dict[str, PlanScore], default_id: str, order: list[str]) -> str:
    """Do no harm: no worse on qviol, hot_late, wt_min; strictly better on one."""
    base = scores[default_id]
    keys = ("qviol", "hot_late", "wt_min")
    best: tuple[tuple[float, ...], str] | None = None
    for plan_id in order:
        if plan_id == default_id or plan_id not in scores:
            continue
        score = scores[plan_id]
        diffs = [score.mean(key) - base.mean(key) for key in keys]
        if any(d > 1e-9 for d in diffs) or not any(d < -1e-9 for d in diffs):
            continue
        rank = (score.mean("qviol"), score.mean("wt_min"), score.mean("hot_late"))
        if best is None or rank < best[0]:
            best = (rank, plan_id)
    return default_id if best is None else best[1]


class CaseMemory(Protocol):
    """Shift memory (``resilimes.engines.hmem.shift_memory``)."""

    def recall(self, view: dict[str, Any]) -> list[dict[str, Any]]: ...

    def remember(self, view: dict[str, Any], entry: dict[str, Any]) -> Any: ...

    def skip_twin(self, cases: list[dict[str, Any]]) -> bool: ...


class SimShiftLead(ShiftLead):
    """``ShiftLead`` whose escalated decisions go through the twin.

    ``proposer``/``selector_llm``: a ``Completer`` (Nightshift or the mock) or
    None. ``selector``: ``pareto`` (no model) or ``llm``. ``memory``: optional
    ``CaseMemory``.
    """

    def __init__(
        self,
        twin: Twin,
        *,
        completer: Completer | None = None,
        selector: str = "pareto",
        memory: CaseMemory | None = None,
        timeout_s: float = 300.0,
        temperature: float = 0.2,
        budget: int | None = None,
        progress: Any = None,
        max_per_tick: int = 8,
        escalation: str | None = None,
        max_plans: int = MAX_PLANS,
    ) -> None:
        super().__init__(
            RuleDefault("en"), max_per_tick=max_per_tick, budget=budget, progress=progress
        )
        if selector not in ("pareto", "llm"):
            raise ValueError("selector must be pareto or llm")
        if selector == "llm" and completer is None:
            raise ValueError("selector llm needs a completer")
        self.twin = twin
        self.completer = completer
        self.max_plans = max(1, int(max_plans))
        self.selector = selector
        self.memory = memory
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.planned: list[list[tuple[float, float]]] | None = None
        self.llm_calls = 0
        self.llm_ms: list[float] = []
        self.llm_fail: dict[str, int] = {}
        self.escalation = escalation_mode(escalation)
        self.escalations = 0
        self.rule_handled = 0
        self.triggers: dict[str, int] = {}
        self.gate_ms: list[float] = []
        self.gate_forks = 0
        self.twin_skips = 0
        self.models: dict[str, int] = {}

    def on_tick(self, sim: Any, moment: float) -> None:
        if self.planned is None:
            self.planned = [list(spans) for spans in sim.pm]
        super().on_tick(sim, moment)

    # model calls ------------------------------------------------------------
    def _call(self, lane: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.completer is not None
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ]
        box: dict[str, Any] = {}
        completer = self.completer

        def run() -> None:
            try:
                box["result"] = completer.complete(
                    messages, lane=lane, temperature=self.temperature
                )
            except Exception as error:  # reported as the fallback cause
                box["error"] = error

        started = time.perf_counter()
        self.llm_calls += 1
        if self.progress is not None:
            self.progress.call_started()
        worker = threading.Thread(target=run, name=f"sim-select-{lane}", daemon=True)
        worker.start()
        worker.join(self.timeout_s)
        if self.progress is not None:
            self.progress.call_finished()
        self.llm_ms.append((time.perf_counter() - started) * 1000.0)
        try:
            if worker.is_alive():
                raise DecisionError("timeout", f"no reply in {self.timeout_s:.0f} s")
            if "error" in box:
                raise DecisionError("provider_error", type(box["error"]).__name__)
            result: LlmResult = box["result"]
            served = result.provider_model or result.response_model or result.model
            self.models[served] = self.models.get(served, 0) + 1
            if not result.mocked and REQUIRED_MODEL not in served.lower():
                # Pinned to Nemotron: a reply served by any other model
                # (e.g. a Gemini fallback in the proxy) is not used.
                raise DecisionError("non_nemotron", served[:60])
            try:
                return extract_json_object(result.content)
            except ValueError as error:
                raise DecisionError("bad_json", str(error)[:80]) from error
        except DecisionError as error:
            self.llm_fail[error.cause] = self.llm_fail.get(error.cause, 0) + 1
            raise

    # decision -----------------------------------------------------------------
    def _gate(self, sim: Any, exc: FabException, moment: float) -> tuple[PlanScore, float]:
        """Twin score of the rule default alone (no model), and its wall ms."""
        started = time.perf_counter()
        default = next(p for p in engine_plans(exc) if p.id == exc.default.id)
        forks = self.twin.forks
        score = self.twin.evaluate(sim, {default.id: default.levers}, moment)[default.id]
        self.gate_forks += self.twin.forks - forks
        ms = (time.perf_counter() - started) * 1000.0
        self.gate_ms.append(ms)
        return score, ms

    def _rule_entry(
        self, sim: Any, exc: FabException, moment: float, reason: str, gate: Any
    ) -> dict[str, Any]:
        """The rule default runs; logged as handled by rule (not escalated)."""
        calls = self.calls
        entry = super().handle(sim, exc, moment)
        self.calls = calls  # the budget counts escalations only
        self.rule_handled += 1
        entry["escalated"] = False
        entry["escalation_reason"] = reason
        entry["gate"] = gate
        return entry

    def handle(self, sim: Any, exc: FabException, moment: float) -> dict[str, Any]:
        default_id = exc.default.id
        gate_score: PlanScore | None = None
        gate: dict[str, Any] | None = None
        trigger = "always"
        if self.escalation == "always":
            if not escalate(exc):
                return self._rule_entry(sim, exc, moment, "filter", None)
        else:
            gate_score, ms = self._gate(sim, exc, moment)
            found = rule_trigger(gate_score)
            gate = {
                "default": gate_score.summary(),
                "futures": len(gate_score.runs),
                "ms": round(ms, 1),
                "trigger": found,
            }
            if found is None:
                return self._rule_entry(sim, exc, moment, "rule_ok", gate)
            trigger = found
        self.triggers[trigger] = self.triggers.get(trigger, 0) + 1
        self.sim = sim
        started = time.perf_counter()
        self.escalations += 1
        view = situation(sim, exc, moment)
        cases = self.memory.recall(view) if self.memory is not None else []
        plans = {plan.id: plan for plan in engine_plans(exc)}
        cause: str | None = None
        propose_cause: str | None = None
        reason = ""
        if self.budget is not None and self.calls >= self.budget:
            cause = "budget"
        elif self.memory is not None and self.completer is None and self.memory.skip_twin(cases):
            self.twin_skips += 1
            cause = "memory_skip"
        if cause is None and self.completer is not None:
            payload = {**view, "max_plans": self.max_plans, "similar_past_cases": cases}
            try:
                answer = self._call(PLAN_LANE, plan_system(self.max_plans), payload)
                raw = answer.get("plans")
                if not isinstance(raw, list):
                    raise DecisionError("bad_json", "plans must be a list")
                assert self.planned is not None
                builder = PlanBuilder(sim, exc, moment, self.planned)
                for k, item in enumerate(raw[: self.max_plans]):
                    plan = builder.plan(f"P{k + 1}", item)
                    plans[plan.id] = plan
            except DecisionError as error:
                propose_cause = str(error)
        scores: dict[str, PlanScore] = {}
        chosen_id = default_id
        if cause is None:
            self.calls += 1
            runnable = {pid: p.levers for pid, p in plans.items() if p.error is None}
            if gate_score is not None:
                # The gate already scored the default on the same futures
                # (same snapshot, same seeds): reuse it, fork only the rest.
                rest = {pid: lv for pid, lv in runnable.items() if pid != default_id}
                scores = {default_id: gate_score}
                if rest:
                    scores.update(self.twin.evaluate(sim, rest, moment))
            else:
                scores = self.twin.evaluate(sim, runnable, moment)
            order = list(runnable)
            if self.selector == "pareto":
                chosen_id = pareto_pick(scores, default_id, order)
            else:
                table = numbers_table(scores, plans)
                try:
                    answer = self._call(
                        SELECT_LANE,
                        SELECT_SYSTEM,
                        {
                            "exception": view["situation"],
                            "rule_default": default_id,
                            "candidates": table,
                            "similar_past_cases": cases,
                        },
                    )
                    pick = str(answer.get("plan_id", "")).strip()
                    if pick not in scores:
                        raise DecisionError("unknown_option", pick[:20])
                    problem = check_numbers(answer, table)
                    if problem is not None:
                        raise DecisionError("number_check", problem)
                    if scores[pick].mean("hot_late") > scores[default_id].mean("hot_late") + 1e-9:
                        raise DecisionError("invariant", "more hot/VIP late than the default")
                    chosen_id = pick
                    reason = str(answer.get("reason", ""))[:400]
                except DecisionError as error:
                    if error.cause in ("unknown_option", "number_check", "invariant"):
                        self.llm_fail[error.cause] = self.llm_fail.get(error.cause, 0) + 1
                    cause = str(error)
        chosen = plans[chosen_id]
        for lever in chosen.levers:
            self.apply(sim, exc, Option(chosen.id, chosen.action, lever), moment)
        receipt = None
        if scores:
            receipt = {
                "futures": len(scores[default_id].runs),
                "horizon_h": round(self.twin.config.horizon_sec / 3600.0, 2),
                "default": scores[default_id].summary(),
                "chosen": scores[chosen_id].summary(),
                "plans": {pid: score.summary() for pid, score in scores.items()},
            }
        entry = {
            "id": exc.id,
            "t": round(moment, 1),
            "t_h": round(moment / 3600.0, 3),
            "type": exc.kind,
            "family": sim.fab.families[exc.family].name,
            "tool": sim.fab.tool_name[exc.tool] if exc.tool >= 0 else None,
            "lots": [sim.fab.lot_id[lot] for lot in exc.lots[:12]],
            "situation": exc.situation,
            "options": [item.as_dict() for item in exc.options],
            "default": default_id,
            "chosen": chosen_id,
            "action": chosen.action,
            "differs": chosen_id != default_id,
            "reason": reason,
            "provider": "sim+"
            + (getattr(self.completer, "name", "llm") if self.completer else "pareto"),
            "model": "",
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "fallback": cause is not None and cause != "memory_skip",
            "fallback_cause": cause,
            "escalated": True,
            "escalation_reason": trigger,
            "gate": gate,
            "selector": self.selector,
            "propose_fallback": propose_cause,
            "plans": [plan.view() for plan in plans.values()],
            "receipt": receipt,
            "memory_cases": len(cases),
        }
        self.log.append(entry)
        if self.memory is not None:
            self.memory.remember(view, {**entry, "_recalled": cases})
        if self.progress is not None:
            self.progress.decision(entry)
        if sim.record:
            sim.events.append(("ai_decision", moment, entry))
        return entry

    def summary(self) -> dict[str, Any]:
        out = super().summary()
        ms = sorted(self.llm_ms)

        def pct(q: float) -> float | None:
            return round(ms[min(len(ms) - 1, int(q * len(ms)))], 1) if ms else None

        gms = sorted(self.gate_ms)

        def gate_pct(q: float) -> float | None:
            return round(gms[min(len(gms) - 1, int(q * len(gms)))], 1) if gms else None

        out.update(
            {
                "decider": "sim+"
                + (getattr(self.completer, "name", "llm") if self.completer else "pareto"),
                "max_plans": self.max_plans,
                "escalation_mode": self.escalation,
                "escalated": self.escalations,
                "rule_handled": self.rule_handled,
                "escalation_triggers": dict(self.triggers),
                "gate_checks": len(self.gate_ms),
                "gate_forks": self.gate_forks,
                "gate_wall_s": round(sum(self.gate_ms) / 1000.0, 2),
                "gate_ms_p50": gate_pct(0.5),
                "gate_ms_p95": gate_pct(0.95),
                "twin_forks": self.twin.forks,
                "twin_wall_s": round(self.twin.wall_s, 1),
                "twin_skips": self.twin_skips,
                "llm_calls": self.llm_calls,
                "llm_ms_p50": pct(0.5),
                "llm_ms_p95": pct(0.95),
                "llm_failures": dict(self.llm_fail),
                "served_models": dict(self.models),
                "non_nemotron_replies": self.llm_fail.get("non_nemotron", 0),
                "llm_plans": sum(
                    1 for e in self.log for p in e.get("plans", []) if p["source"] == "llm"
                ),
                "llm_plans_invalid": sum(
                    1
                    for e in self.log
                    for p in e.get("plans", [])
                    if p["source"] == "llm" and not p["valid"]
                ),
                "chosen_llm_plan": sum(
                    1 for e in self.log if str(e.get("chosen", "")).startswith("P")
                ),
            }
        )
        return out
