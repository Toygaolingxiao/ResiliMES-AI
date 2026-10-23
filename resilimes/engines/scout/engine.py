"""Scout Intent — sense, interpret, guard, route, recommend.

This is a Python implementation of the public Scout contract
(https://github.com/Meterless/Meterless/blob/main/engines/scout-intent/AGENTS.md).
`@meterless/scout` is a specification, not a published library. The pipeline,
intent record, and HMAC execution contract follow that spec. Canonical JSON is
documented in docs/ASSUMPTIONS.md.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from resilimes.engines.contracts import ContractError, sign_body

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_PACKAGE = Path(__file__).resolve().parent

_TRIGGERS: dict[str, tuple[str, ...]] = {
    "plant.machine_down": (
        r"\bdown\b",
        r"\bfault\b",
        r"\bbreakdown\b",
        r"\boffline\b",
        r"\blaser\b",
        r"宕机",
        r"停机",
        r"故障",
        r"停止",
        r"ダウン",
        r"维修",
        r"修理",
    ),
    "plant.rush_order": (r"\brush\b", r"\bhot lot\b", r"\bexpedite\b", r"pull[- ]in"),
    "plant.material_shortage": (
        r"\bshortage\b",
        r"\bstockout\b",
        r"\bout of\b",
        r"\bphotoresist\b",
        r"\bresist\b",
    ),
    "plant.explain": (r"\bexplain\b", r"\bwhy\b"),
    "plant.query_status": (r"\bstatus\b", r"\bqueue\b", r"\bwip\b", r"\bwhich tools\b"),
    "plant.emergency_stop": (
        r"emergency stop",
        r"entire factory",
        r"shut down every",
        r"stop the entire",
        r"stop all tools",
    ),
    "plant.rework": (r"\brework\b", r"\boverlay\b", r"\bstrip\b"),
    "plant.qtime": (r"\bq-time\b", r"\bqueue time\b", r"\bqueue-time\b"),
}

_INJECTION = (
    r"ignore (all |any |previous )?instructions",
    r"you are now",
    r"reveal (the )?(secret|token|api key)",
    r"drop table",
    r"</?system>",
    r"\bjailbreak\b",
    r"\bexfiltrate\b",
    r"\bdelete\b.+\bfrom\b",
)

_TOOLS: dict[str, list[dict[str, str]]] = {
    "world.query": [{"tool": "specialist.query_plant", "capability": "world.query"}],
    "world.sync": [{"tool": "world.bootstrap", "capability": "world.sync"}],
    "schedule.recover": [
        {"tool": "planner.propose", "capability": "schedule.recover"},
        {"tool": "evaluator.critique", "capability": "schedule.recover"},
    ],
    "schedule.commit": [{"tool": "world.commit_schedule", "capability": "schedule.commit"}],
    "memory.write": [{"tool": "markovian.checkpoint", "capability": "memory.write"}],
}

_EQUIPMENT = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,})-(\d{2})(?!\d)")
_REPAIR = re.compile(
    r"(\d+)\s*(minutes|minute|mins|min|hours|hour|hrs|hr|分钟|小时|時間|分)",
    re.I,
)
_MATERIAL = re.compile(r"\b(RESIST-UV|WAFER-300|WAFER-200|GAS-CF4|SLURRY-OX)\b", re.I)
_PRODUCT = re.compile(r"\b(PROD-[A-Z0-9]+)\b", re.I)


class Decision(BaseModel):
    intent: dict[str, Any]
    risk: dict[str, Any]
    tool_plan: list[dict[str, Any]] = Field(default_factory=list)
    execution_contract: dict[str, Any] | None = None
    needs_clarification: bool = False
    latency_ms: float = 0.0


class Scout:
    """Decision pipeline that runs before any recovery action."""

    def __init__(
        self,
        intent_registry: str | dict[str, Any],
        policy_pack: str = "default",
        model_profiles: str | dict[str, Any] | None = None,
        *,
        signing_secret: str,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = 300,
        provider_mode: str = "mock",
    ) -> None:
        self._registry = _load_json(intent_registry)
        self._profiles = _load_json(model_profiles) if model_profiles else {"profiles": []}
        self._validate_registry(self._registry)
        self._intents = list(self._registry["intents"])
        self._by_id = {item["id"]: item for item in self._intents}
        self._triggers = {
            key: tuple(re.compile(pattern, re.I) for pattern in patterns)
            for key, patterns in _TRIGGERS.items()
        }
        self._injection = tuple(re.compile(pattern, re.I) for pattern in _INJECTION)
        self._policy_pack = policy_pack
        self._policy_version = f"resilimes-{policy_pack}-1"
        self._secret = signing_secret
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl_seconds
        self._provider_mode = provider_mode
        self._issued: dict[str, dict[str, Any]] = {}
        self._ulids = _UlidFactory()

    def classify(self, data: dict[str, Any]) -> dict[str, Any]:
        prompt = str(data.get("prompt") or "")
        ranked = self._rank(prompt)
        return {
            "candidates": [
                {"intent": intent_id, "score": round(score, 4)} for intent_id, score in ranked[:3]
            ]
        }

    def decide(self, data: dict[str, Any]) -> Decision:
        started = self._clock()
        prompt = str(data.get("prompt") or "")
        surface = str(data.get("surface") or "mes_console")
        user = data.get("user") or {"id": "planner.ops", "role": "planner"}
        if not isinstance(user, dict):
            user = {"id": "unknown", "role": "viewer"}
        approvals = data.get("approvals") or []
        if not isinstance(approvals, list):
            approvals = []

        ranked = self._rank(prompt)
        top_id, top_score = ranked[0]
        if top_score < 0.35:
            top_id, top_score = "plant.query_status", max(top_score, 0.2)
            needs_clarification = True
        else:
            needs_clarification = top_score < 0.45
        intent = self._by_id[top_id]
        parameters = self._bind(prompt, top_id)
        references = _references(parameters)
        flags: list[dict[str, str]] = []
        level = str(intent["riskClass"])
        block_reason: str | None = None

        injection = self._injection_hit(prompt)
        if injection:
            level = "block"
            block_reason = "Prompt injection detected."
            flags.append({"code": "prompt_injection", "detail": injection})
        elif str(user.get("role") or "") not in intent["roles"]:
            level = "block"
            block_reason = f"Role {user.get('role')} cannot invoke {top_id}."
            flags.append({"code": "role_denied", "detail": block_reason})
        elif surface not in intent["surfaces"]:
            level = "block"
            block_reason = f"Surface {surface} cannot invoke {top_id}."
            flags.append({"code": "surface_denied", "detail": block_reason})

        risk: dict[str, Any] = {
            "level": level,
            "flags": flags,
            "redactions": [],
            "approvals": approvals,
            "reason": block_reason,
        }
        alternates = [
            {"intent": intent_id, "score": round(score, 4)}
            for intent_id, score in ranked[1:3]
            if score > 0
        ]
        decision_intent = {
            "primary": top_id,
            "parameters": parameters,
            "references": references,
            "confidence": round(min(1.0, top_score), 4),
            "alternates": alternates,
        }
        if level == "block":
            done = Decision(
                intent=decision_intent,
                risk=risk,
                tool_plan=[],
                execution_contract=None,
                needs_clarification=False,
            )
            done.latency_ms = _elapsed_ms(started, self._clock())
            return done

        capabilities = list(intent["capabilities"])
        tool_plan: list[dict[str, Any]] = []
        for capability in capabilities:
            for tool in _TOOLS.get(capability, []):
                tool_plan.append({**tool, "args": parameters})
        profile = self._select_profile(top_id)
        now = self._clock()
        body: dict[str, Any] = {
            "contractId": self._ulids.next(now),
            "traceId": secrets.token_hex(8),
            "intent": decision_intent,
            "risk": {
                "level": level,
                "flags": flags,
                "redactions": [],
                "approvals": approvals,
            },
            "toolPlan": tool_plan,
            "modelProfile": profile,
            "scope": {
                "user": {"id": user.get("id"), "role": user.get("role")},
                "surface": surface,
                "capabilities": capabilities,
                "budget": {"tokensMax": 8000, "costMaxUSD": 0.05},
            },
            "issuedAt": _iso(now),
            "expiresAt": _iso(now + timedelta(seconds=self._ttl)),
            "registryVersion": int(self._registry["registryVersion"]),
            "policyPackVersion": self._policy_version,
        }
        contract = sign_body(body, self._secret)
        self._issued[contract["contractId"]] = contract
        done = Decision(
            intent=decision_intent,
            risk=risk,
            tool_plan=tool_plan,
            execution_contract=contract,
            needs_clarification=needs_clarification,
        )
        done.latency_ms = _elapsed_ms(started, self._clock())
        return done

    def replan(self, parent: str, reason: str, state: dict[str, Any] | None = None) -> Decision:
        original = self._issued.get(parent)
        if original is None:
            raise ContractError(f"Unknown parent contract {parent}")
        now = self._clock()
        intent = json.loads(json.dumps(original["intent"]))
        parameters = dict(intent.get("parameters") or {})
        parameters["replan_reason"] = reason
        if state:
            parameters["replan_state"] = {key: state[key] for key in list(state)[:8]}
        intent["parameters"] = parameters
        body: dict[str, Any] = {
            "contractId": self._ulids.next(now),
            "parentId": parent,
            "traceId": original["traceId"],
            "intent": intent,
            "risk": original["risk"],
            "toolPlan": original["toolPlan"],
            "modelProfile": original["modelProfile"],
            "scope": original["scope"],
            "issuedAt": _iso(now),
            "expiresAt": _iso(now + timedelta(seconds=self._ttl)),
            "registryVersion": original["registryVersion"],
            "policyPackVersion": original["policyPackVersion"],
        }
        contract = sign_body(body, self._secret)
        self._issued[contract["contractId"]] = contract
        return Decision(
            intent=intent,
            risk=dict(original["risk"]),
            tool_plan=list(original["toolPlan"]),
            execution_contract=contract,
        )

    def _rank(self, prompt: str) -> list[tuple[str, float]]:
        scored = [(item["id"], self._score(item, prompt)) for item in self._intents]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored

    def _score(self, intent: dict[str, Any], prompt: str) -> float:
        patterns = self._triggers.get(intent["id"], ())
        hits = sum(1 for pattern in patterns if pattern.search(prompt))
        trigger = 0.0
        if hits:
            trigger = min(0.85, 0.62 + 0.08 * (hits - 1))
        example = 0.0
        contained = False
        prompt_tokens = _tokens(prompt)
        for sample in intent.get("examples") or []:
            sample_tokens = _tokens(str(sample))
            example = max(example, _jaccard(prompt, str(sample)))
            if sample_tokens and sample_tokens <= prompt_tokens:
                contained = True
        score = 0.7 * trigger + 0.3 * example if hits else 0.45 * example
        if contained and hits:
            score = max(score, 0.92)
        elif example >= 0.99 and hits:
            score = max(score, 0.94)
        elif example >= 0.99:
            score = max(score, 0.8)
        return score

    def _bind(self, prompt: str, intent_id: str) -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        match = _EQUIPMENT.search(prompt)
        if match:
            parameters["equipment_id"] = f"{match.group(1).upper()}-{match.group(2)}"
        repair = _REPAIR.search(prompt)
        if repair:
            amount = int(repair.group(1))
            unit = repair.group(2).lower()
            parameters["repair_min"] = amount * 60 if unit.startswith("h") else amount
        material = _MATERIAL.search(prompt)
        if material:
            parameters["material_id"] = material.group(1).upper()
        product = _PRODUCT.search(prompt)
        if product:
            parameters["product_id"] = product.group(1).upper()
        if (
            intent_id == "plant.machine_down"
            and "fault_code" not in parameters
            and "laser" in prompt.lower()
        ):
            parameters["fault_code"] = "LASER_FAULT"
        return parameters

    def _injection_hit(self, prompt: str) -> str | None:
        for pattern in self._injection:
            found = pattern.search(prompt)
            if found:
                return found.group(0)
        return None

    def _select_profile(self, intent_id: str) -> dict[str, Any]:
        profiles = list(self._profiles.get("profiles") or [])
        local = [
            item
            for item in profiles
            if item.get("local") and "plant" in (item.get("dataClasses") or [])
        ]
        if self._provider_mode == "mock":
            for item in local:
                if item.get("provider") == "mock":
                    return {
                        "id": item["id"],
                        "provider": item["provider"],
                        "model": item["model"],
                        "lane": item.get("lane"),
                    }
        lane = "critic" if intent_id == "plant.explain" else "planner"
        for item in local:
            if item.get("provider") == "meterless-nightshift" and item.get("lane") == lane:
                return {
                    "id": item["id"],
                    "provider": item["provider"],
                    "model": item["model"],
                    "lane": item.get("lane"),
                }
        for item in local:
            if item.get("provider") == "meterless-nightshift":
                return {
                    "id": item["id"],
                    "provider": item["provider"],
                    "model": item["model"],
                    "lane": item.get("lane"),
                }
        return {"id": "unrouted", "provider": self._provider_mode, "model": "unknown", "lane": lane}

    @staticmethod
    def _validate_registry(registry: dict[str, Any]) -> None:
        intents = registry.get("intents")
        if not isinstance(intents, list) or not intents:
            raise ValueError("Intent registry has no intents")
        if "registryVersion" not in registry:
            raise ValueError("Intent registry is missing registryVersion")
        for intent in intents:
            if not intent.get("examples"):
                raise ValueError(f"Intent {intent.get('id')} requires examples")
            for field in ("id", "roles", "surfaces", "capabilities", "riskClass", "version"):
                if field not in intent:
                    raise ValueError(f"Intent {intent.get('id')} is missing {field}")


def default_scout(
    *,
    signing_secret: str,
    provider_mode: str = "mock",
    clock: Callable[[], datetime] | None = None,
    ttl_seconds: int = 300,
) -> Scout:
    return Scout(
        str(_PACKAGE / "intents.json"),
        policy_pack="default",
        model_profiles=str(_PACKAGE / "profiles.json"),
        signing_secret=signing_secret,
        clock=clock,
        ttl_seconds=ttl_seconds,
        provider_mode=provider_mode,
    )


class _UlidFactory:
    def __init__(self) -> None:
        self._ms = -1
        self._rand = 0

    def next(self, moment: datetime) -> str:
        ms = int(moment.timestamp() * 1000) & ((1 << 48) - 1)
        if ms == self._ms:
            self._rand = (self._rand + 1) & ((1 << 80) - 1)
        else:
            self._ms = ms
            self._rand = secrets.randbits(80)
        return _crockford(ms, 10) + _crockford(self._rand, 16)


def _crockford(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def _load_json(source: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    loaded = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object in {source}")
    return loaded


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _references(parameters: dict[str, Any]) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    if parameters.get("equipment_id"):
        refs["equipment"] = {"id": parameters["equipment_id"], "type": "equipment"}
    if parameters.get("material_id"):
        refs["material"] = {"id": parameters["material_id"], "type": "material"}
    if parameters.get("product_id"):
        refs["product"] = {"id": parameters["product_id"], "type": "product"}
    return refs


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _elapsed_ms(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() * 1000)
