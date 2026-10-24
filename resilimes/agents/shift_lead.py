# ruff: noqa: RUF001  (full-width punctuation in zh/ja reason text)
"""AI shift lead: a model's judgment at scheduling exceptions, never per dispatch.

The dispatcher stays rule-based. At each scheduling tick the engine
(``resilimes.smt.exceptions``) detects the few points where a human shift
lead would step in, builds 2-4 legal options with a projected impact each,
and marks the rule default. Only then is a decider asked:

* ``LlmDecider``: one compact prompt (situation, options with impacts, fab
  goal) to any ``Completer`` (Nightshift or the offline mock); the reply must
  be JSON ``{"option_id": ..., "reason": ...}``.
* ``HeuristicStandIn``: NOT an LLM. Picks the lowest projected impact
  (Q-time violations, then hot/VIP late, then late lots, then idle minutes).
  Used for the deterministic study arm and CI.
* ``RuleDefault``: always the rule default (equals no shift lead).

Every answer is validated: the option must be one that was offered and pass
the guardrails (no hot/VIP lot made late versus the default, PM deferral
bounded and once per window). A timeout, an error, bad JSON, an unknown
option or a failed guardrail falls back to the rule default, which is a no-op,
and the cause is logged. Each decision is logged (``ShiftLead.log``) and, on
a recorded run, appended to the run's events as ``("ai_decision", t, entry)``.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from resilimes.agents.jsonutil import extract_json_object
from resilimes.llm.base import Completer, LlmResult
from resilimes.smt.exceptions import (
    KINDS,
    Detector,
    FabException,
    Option,
    pm_shift_ok,
)

LANE = "shift_lead"
LANGS = {"zh": "Simplified Chinese", "ja": "Japanese", "en": "English"}
HEURISTIC_NAME = "heuristic-stand-in (not an LLM)"
_WAKE = 3  # resilimes.smt.simulate._WAKE
_BIAS_SCALE = 0.1  # keeps a lever inside its urgency band (|bias| < 0.5)

FAB_GOAL = (
    "Optimise the whole fab, not one product: keep the load level across tool "
    "families, favour no route or customer. Protect Q-time windows first. "
    "Respect hot and VIP lots: never pick an option that makes one late. "
    "Among options equal on those, prefer fewer late lots, then less tool idle "
    "time and less queue growth. The rule default is safe and needs no reason "
    "to keep."
)
SYSTEM_PROMPT = (
    "You are the shift lead of a 300 mm wafer fab. The dispatcher runs on rules; "
    "you are asked only at exceptions. You get the situation and 2-4 options the "
    "scheduling engine has already checked as legal, each with a projected impact "
    "over the next 2 hours (qtime_violations, late_lots, hot_late, idle_min, "
    "queue_growth; lower is better). Choose exactly one offered option. Reply with "
    'one JSON object only: {"option_id": "<id>", "reason": "<one short sentence>"}.'
)


@dataclass
class Decision:
    option_id: str
    reason: str
    provider: str
    model: str = ""
    latency_ms: float = 0.0


class Decider(Protocol):
    name: str

    def decide(self, exc: FabException) -> Decision: ...


def build_messages(exc: FabException, lang: str = "zh") -> list[dict[str, str]]:
    """The compact prompt: system role plus one JSON user message."""
    language = LANGS.get(lang, LANGS["en"])
    payload = {
        "time_h": round(exc.t / 3600.0, 2),
        "exception": exc.kind,
        "situation": exc.situation,
        "facts": exc.facts,
        "options": [option.as_dict() for option in exc.options],
        "goal": FAB_GOAL,
        "answer": {
            "option_id": [option.id for option in exc.options],
            "reason": f"one sentence in {language}, at most 40 words",
            "lang": lang,
        },
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def best_option(options: list[Option]) -> Option:
    """Lowest projected impact; a tie keeps the rule default."""
    default = next(option for option in options if option.default)

    def key(option: Option) -> tuple[float, ...]:
        impact = option.impact
        base = impact.key() if impact is not None else (float("inf"),)
        return (*base, 0.0 if option.default else 1.0)

    best = min(options, key=key)
    if (
        default.impact is not None
        and best.impact is not None
        and best.impact.key() == default.impact.key()
    ):
        return default
    return best


_REASONS = {
    "zh": {
        "default": "各选项预测影响相同或默认最优，维持规则默认。",
        "better": "预测Q-time违规{q}件、迟交{late}件，优于默认（{dq}件/{dlate}件）。",
    },
    "ja": {
        "default": "予測影響が同等かルール既定が最良のため、既定を維持。",
        "better": "予測Q-time違反{q}件・遅延{late}件で、既定（{dq}件/{dlate}件）より良い。",
    },
    "en": {
        "default": "Projected impacts tie or the rule default is best; keep the rule.",
        "better": "Projects {q} Q-time misses and {late} late lots vs {dq}/{dlate} by default.",
    },
}


def stand_in_reason(chosen: Option, default: Option, lang: str) -> str:
    text = _REASONS.get(lang, _REASONS["en"])
    if chosen.default or chosen.impact is None or default.impact is None:
        return text["default"]
    return text["better"].format(
        q=chosen.impact.qtime_violations,
        late=chosen.impact.late_lots,
        dq=default.impact.qtime_violations,
        dlate=default.impact.late_lots,
    )


class RuleDefault:
    """Always the rule default: a shift lead that never overrides."""

    name = "rules"

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang

    def decide(self, exc: FabException) -> Decision:
        return Decision(exc.default.id, _REASONS[self.lang]["default"], self.name)


class HeuristicStandIn:
    """Deterministic stand-in for the LLM. NOT a language model.

    Picks the option with the lowest projected impact, lexicographic on
    (Q-time violations, hot/VIP late, late lots, idle minutes); a tie keeps
    the rule default.
    """

    name = HEURISTIC_NAME

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang

    def decide(self, exc: FabException) -> Decision:
        chosen = best_option(exc.options)
        reason = stand_in_reason(chosen, exc.default, self.lang)
        return Decision(chosen.id, reason, self.name, model="lexicographic-impact")


class DecisionError(RuntimeError):
    def __init__(self, cause: str, detail: str = "") -> None:
        self.cause = cause
        super().__init__(f"{cause}: {detail}" if detail else cause)


class LlmDecider:
    """Ask a ``Completer`` (Nightshift or the mock) for one option id."""

    def __init__(
        self,
        completer: Completer,
        *,
        lang: str = "zh",
        timeout_s: float = 30.0,
        temperature: float = 0.0,
    ) -> None:
        self.completer = completer
        self.lang = lang
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.name = str(getattr(completer, "name", "llm"))

    def _call(self, messages: list[dict[str, str]]) -> LlmResult:
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["result"] = self.completer.complete(
                    messages, lane=LANE, temperature=self.temperature
                )
            except Exception as exc:  # reported as the fallback cause
                box["error"] = exc

        worker = threading.Thread(target=run, name="shift-lead-llm", daemon=True)
        worker.start()
        worker.join(self.timeout_s)
        if worker.is_alive():
            raise DecisionError("timeout", f"no reply in {self.timeout_s:.0f} s")
        if "error" in box:
            error = box["error"]
            raise DecisionError("provider_error", type(error).__name__)
        result: LlmResult = box["result"]
        return result

    def decide(self, exc: FabException) -> Decision:
        started = time.perf_counter()
        result = self._call(build_messages(exc, self.lang))
        latency = result.latency_ms or (time.perf_counter() - started) * 1000.0
        try:
            payload = extract_json_object(result.content)
        except ValueError as error:
            raise DecisionError("bad_json", str(error)[:80]) from error
        option_id = payload.get("option_id")
        reason = payload.get("reason", "")
        if not isinstance(option_id, str) or not isinstance(reason, str):
            raise DecisionError("bad_json", "option_id and reason must be strings")
        return Decision(
            option_id=option_id.strip(),
            reason=reason.strip()[:300],
            provider=result.provider + (" (mock)" if result.mocked else ""),
            model=result.model,
            latency_ms=round(latency, 1),
        )


def check_option(sim: Any, exc: FabException, option: Option | None) -> str | None:
    """Guardrails on a chosen option. None means it passes."""
    if option is None:
        return "unknown_option"
    if option.default:
        return None
    default = exc.default
    if option.impact is None or default.impact is None:
        return "invariant: no impact estimate"
    if option.impact.hot_late > default.impact.hot_late:
        return "invariant: makes a hot/VIP lot late"
    lever = option.lever
    if lever.kind == "pm_defer":
        if lever.pm is None or not pm_shift_ok(sim, *lever.pm):
            return "invariant: PM deferral out of bounds"
    elif lever.kind == "prio":
        if any(lot not in exc.lots for lot, _step in lever.prio):
            return "invariant: boost outside the exception's lots"
    elif lever.kind == "keep_pin":
        if not lever.keep_pin <= set(exc.lots):
            return "invariant: pin kept outside the exception's lots"
    elif lever.kind == "batch_start":
        if lever.batch is None or lever.batch[0] != exc.family:
            return "invariant: batch outside the exception's family"
    elif lever.kind != "none":
        return f"invariant: unknown lever {lever.kind}"
    return None


class ShiftLead:
    """The hook ``run_policy(..., shift_lead=ShiftLead(decider))`` attaches.

    One instance per run. ``simulate._Sim`` calls ``on_tick`` at every
    scheduling tick and reads the active levers through ``bias``,
    ``may_reroute`` and ``start_batch``.
    """

    def __init__(
        self, decider: Decider, *, max_per_tick: int = 8, budget: int | None = None
    ) -> None:
        self.decider = decider
        self.max_per_tick = max_per_tick
        # At most ``budget`` decider calls per run; later exceptions keep the
        # rule default (logged as fallback "budget").
        self.budget = budget
        self.calls = 0
        self.detector: Detector | None = None
        self.sim: Any = None
        self.log: list[dict[str, Any]] = []
        self._prio: dict[tuple[int, int], tuple[float, float]] = {}
        self._pins: dict[int, float] = {}
        self._batch: dict[tuple[int, int], float] = {}

    # Levers read by the simulator ------------------------------------------
    def bias(self, lot: int, index: int) -> float:
        row = self._prio.get((lot, index))
        if row is None or self.sim is None or self.sim.clock >= row[1]:
            return 0.0
        return _BIAS_SCALE * row[0]

    def may_reroute(self, lot: int, moment: float) -> bool:
        until = self._pins.get(lot)
        return until is None or moment >= until

    def start_batch(self, fam: int, recipe: int, moment: float) -> bool:
        until = self._batch.get((fam, recipe))
        return until is not None and moment < until

    def prio_map(self) -> dict[tuple[int, int], float]:
        clock = -1.0 if self.sim is None else self.sim.clock
        return {key: value for key, (value, until) in self._prio.items() if clock < until}

    def kept_pins(self, moment: float) -> set[int]:
        return {lot for lot, until in self._pins.items() if moment < until}

    # Tick ------------------------------------------------------------------
    def on_tick(self, sim: Any, moment: float) -> None:
        self.sim = sim
        if self.detector is None:
            self.detector = Detector(sim, self.max_per_tick)
        self._prio = {key: row for key, row in self._prio.items() if moment < row[1]}
        self._pins = {lot: until for lot, until in self._pins.items() if moment < until}
        self._batch = {key: until for key, until in self._batch.items() if moment < until}
        for exc in self.detector.detect(moment):
            self.handle(sim, exc, moment)

    def handle(self, sim: Any, exc: FabException, moment: float) -> dict[str, Any]:
        self.sim = sim
        cause: str | None = None
        decision: Decision | None = None
        started = time.perf_counter()
        try:
            if self.budget is not None and self.calls >= self.budget:
                raise DecisionError("budget", f"{self.budget} decider calls used")
            self.calls += 1
            decision = self.decider.decide(exc)
        except DecisionError as error:
            cause = str(error)
        except Exception as error:  # any decider failure falls back
            cause = f"error: {type(error).__name__}"
        option: Option | None = None
        if decision is not None:
            option = exc.option(decision.option_id)
            cause = check_option(sim, exc, option)
        fallback = cause is not None
        if fallback or option is None:
            option = exc.default
        self.apply(sim, exc, option, moment)
        provider = decision.provider if decision is not None else self.decider.name
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
            "default": exc.default.id,
            "chosen": option.id,
            "action": option.action,
            "differs": not option.default,
            "reason": decision.reason if decision is not None and not fallback else "",
            "provider": provider,
            "model": decision.model if decision is not None else "",
            "latency_ms": (
                decision.latency_ms
                if decision is not None and decision.latency_ms
                else round((time.perf_counter() - started) * 1000.0, 2)
            ),
            "fallback": fallback,
            "fallback_cause": cause,
        }
        self.log.append(entry)
        if sim.record:
            sim.events.append(("ai_decision", moment, entry))
        return entry

    def apply(self, sim: Any, exc: FabException, option: Option, moment: float) -> None:
        lever = option.lever
        if lever.kind == "prio":
            for key, value in lever.prio.items():
                self._prio[key] = (value, lever.until)
        elif lever.kind == "keep_pin":
            for lot in lever.keep_pin:
                self._pins[lot] = lever.until
        elif lever.kind == "batch_start" and lever.batch is not None:
            self._batch[lever.batch] = lever.until
            family = sim.fab.families[lever.batch[0]]
            for tool in range(family.tool0, family.tool0 + family.tools):
                if sim.running[tool] < 0:
                    sim.push(moment, _WAKE, tool)
        elif lever.kind == "pm_defer" and lever.pm is not None:
            tool, index, shift = lever.pm
            start_at, end_at = sim.pm[tool][index]
            sim.pm[tool][index] = (start_at + shift, end_at + shift)
            assert self.detector is not None
            self.detector.pm_deferred.add((tool, start_at + shift))
            if sim.running[tool] < 0:
                sim.push(moment, _WAKE, tool)

    # Report ----------------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        by_kind = {kind: 0 for kind in KINDS}
        differs = {kind: 0 for kind in KINDS}
        causes: dict[str, int] = {}
        latencies: list[float] = []
        for entry in self.log:
            by_kind[entry["type"]] += 1
            if entry["differs"]:
                differs[entry["type"]] += 1
            if entry["fallback"]:
                key = str(entry["fallback_cause"]).split(":")[0]
                causes[key] = causes.get(key, 0) + 1
            latencies.append(float(entry["latency_ms"]))
        latencies.sort()

        def pct(value: float) -> float | None:
            if not latencies:
                return None
            return round(latencies[min(len(latencies) - 1, int(value * len(latencies)))], 2)

        return {
            "decider": self.decider.name,
            "exceptions": len(self.log),
            "by_type": by_kind,
            "differs": sum(differs.values()),
            "differs_by_type": differs,
            "fallbacks": sum(causes.values()),
            "fallback_causes": causes,
            "latency_ms_p50": pct(0.5),
            "latency_ms_p95": pct(0.95),
        }


def decision_rows(events: list[tuple[Any, ...]]) -> list[tuple[float, str, dict[str, Any]]]:
    """``ai_decision`` events as event-log rows ``(t, kind, body)``.

    Same row shape as the replay's ``recent_events`` (``resilimes.smt.replay``
    on the UI branch), so the event-log API can merge them as kind
    ``ai_decision`` ("AI判断" in the UI).
    """
    rows: list[tuple[float, str, dict[str, Any]]] = []
    for event in events:
        if event[0] != "ai_decision":
            continue
        entry = event[2]
        body = {
            "label": "AI判断",
            "id": entry["id"],
            "type": entry["type"],
            "family": entry["family"],
            "tool": entry["tool"],
            "chosen": entry["chosen"],
            "action": entry["action"],
            "default": entry["default"],
            "differs": entry["differs"],
            "reason": entry["reason"],
            "provider": entry["provider"],
            "fallback": entry["fallback"],
            "fallback_cause": entry["fallback_cause"],
            "options": entry["options"],
        }
        rows.append((float(event[1]), "ai_decision", body))
    return rows


def build_decider(provider: str, *, lang: str = "zh", timeout_s: float = 30.0) -> Decider:
    """``heuristic`` (not an LLM), ``rules``, ``mock`` or ``nightshift``."""
    if provider == "heuristic":
        return HeuristicStandIn(lang)
    if provider == "rules":
        return RuleDefault(lang if lang in _REASONS else "en")
    if provider == "mock":
        from resilimes.llm.mock import MockProvider

        return LlmDecider(MockProvider(), lang=lang, timeout_s=timeout_s)
    if provider == "nightshift":
        from resilimes.config import load_settings
        from resilimes.llm.factory import build_provider

        settings = load_settings()
        if not settings.use_nightshift:
            raise RuntimeError(
                "--provider nightshift needs RESILIMES_MODE=live (or auto) and the "
                "Nightshift settings in .env"
            )
        return LlmDecider(build_provider(settings), lang=lang, timeout_s=timeout_s)
    raise ValueError(f"unknown provider {provider!r}")
