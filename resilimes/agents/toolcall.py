"""Natural language to one validated dispatch payload.

Nemotron may emit this object. It does not place lots, score a schedule, or
move a tool through its states. The regex path is the labeled fallback when
Nightshift is down or the model payload fails the schema.
"""

from __future__ import annotations

import re
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from resilimes.agents.jsonutil import SchemaError, check_schema, extract_json_object
from resilimes.domain.models import Plant
from resilimes.llm.base import Completer

IntentName = Literal[
    "insert_hot_lot",
    "move_pm",
    "mark_tool_down",
    "hold_lot",
    "release_lot",
    "what_if",
]

_EQUIPMENT_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d{2}$")
_LOT_ID = re.compile(r"^LOT-\d+$")
_FAULT = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_LOT = re.compile(r"\b(LOT-\d+)\b", re.I)
_EQUIPMENT = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,})-(\d{2})(?!\d)")
_DURATION = re.compile(
    r"(\d+)\s*(minutes|minute|mins|min|hours|hour|hrs|hr|分钟|小时|時間|分)",
    re.I,
)
_START = re.compile(r"(?:start(?:\s+at)?|t)\s*=?\s*(\d+)", re.I)
_WHAT_IF = re.compile(r"what[- ]if|如果|假如|もし", re.I)
_RELEASE = re.compile(r"release lot|放行批次|ロット解除|\brelease\b", re.I)
_HOLD = re.compile(r"hold lot|暂停批次|ロット保留|\bhold\b", re.I)
_PM = re.compile(r"\bpm\b|preventive maintenance|保养|保全|メンテナンス", re.I)
_HOT = re.compile(
    r"hot lot|rush|expedite|insert lot|热批|急单|插单|ホット|特急",
    re.I,
)
_DOWN = re.compile(r"\bdown\b|\bfault\b|\boffline\b|宕机|停机|故障|ダウン", re.I)
_INVENTORY = re.compile(r"check inventory|check stock|核对库存|确认库存|在庫確認", re.I)
_NOTIFY = re.compile(
    r"(?:notify|通知|連絡)\s+([A-Za-z][\w-]{0,40})",
    re.I,
)
_AREAS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"lithography|光刻", re.I), "Lithography"),
    (re.compile(r"\betch\b|蚀刻|エッチ", re.I), "Etch"),
    (re.compile(r"\bcmp\b|研磨", re.I), "CMP"),
    (re.compile(r"\bwet\b|清洗", re.I), "Wet"),
    (re.compile(r"metrology|量测|計測", re.I), "Metrology"),
    (re.compile(r"deposition|\bdep\b|沉积|成膜", re.I), "Deposition"),
)

SCOUT_INTENT: dict[str, str] = {
    "insert_hot_lot": "plant.rush_order",
    "move_pm": "plant.machine_down",
    "mark_tool_down": "plant.machine_down",
    "hold_lot": "plant.hold_lot",
    "release_lot": "plant.release_lot",
    "what_if": "plant.explain",
}


class ValidationRules(BaseModel):
    model_config = ConfigDict(extra="ignore")

    check_inventory: bool
    notify_pe: str


class InsertHotLotParameters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lot_id: str
    target_station_group: str
    priority_override: bool
    reason: str


class MovePmParameters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    equipment_id: str
    new_start_min: int = Field(ge=0, le=10080)
    duration_min: int = Field(ge=1, le=10080)
    reason: str


class MarkToolDownParameters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    equipment_id: str
    eta_min: int = Field(ge=0, le=10080)
    reason: str
    fault_code: str = "UNPLANNED_DOWN"


class LotReasonParameters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lot_id: str
    reason: str


class WhatIfParameters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    equipment_id: str = ""
    lot_id: str = ""
    eta_min: int | None = Field(default=None, ge=0, le=10080)


class InsertHotLotCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal["insert_hot_lot"]
    parameters: InsertHotLotParameters
    validation_rules: ValidationRules


class MovePmCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal["move_pm"]
    parameters: MovePmParameters
    validation_rules: ValidationRules


class MarkToolDownCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal["mark_tool_down"]
    parameters: MarkToolDownParameters
    validation_rules: ValidationRules


class HoldLotCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal["hold_lot"]
    parameters: LotReasonParameters
    validation_rules: ValidationRules


class ReleaseLotCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal["release_lot"]
    parameters: LotReasonParameters
    validation_rules: ValidationRules


class WhatIfCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal["what_if"]
    parameters: WhatIfParameters
    validation_rules: ValidationRules


ToolCall = (
    InsertHotLotCall | MovePmCall | MarkToolDownCall | HoldLotCall | ReleaseLotCall | WhatIfCall
)

CALL_MODELS: dict[str, type[BaseModel]] = {
    "insert_hot_lot": InsertHotLotCall,
    "move_pm": MovePmCall,
    "mark_tool_down": MarkToolDownCall,
    "hold_lot": HoldLotCall,
    "release_lot": ReleaseLotCall,
    "what_if": WhatIfCall,
}

EXAMPLE_INSERT_HOT_LOT: dict[str, Any] = {
    "intent": "insert_hot_lot",
    "parameters": {
        "lot_id": "LOT-9921",
        "target_station_group": "LITHO-03",
        "priority_override": True,
        "reason": "Engineering sample requested by customer urgent test",
    },
    "validation_rules": {"check_inventory": True, "notify_pe": "Yamamoto-san"},
}


class DispatchParse(BaseModel):
    call: dict[str, Any] | None = None
    source: str
    request_id: str = ""
    errors: list[str] = Field(default_factory=list)
    fallback_reason: str = ""


def schemas() -> dict[str, dict[str, Any]]:
    return {name: model.model_json_schema() for name, model in CALL_MODELS.items()}


def tool_call_from_payload(payload: dict[str, Any]) -> ToolCall:
    intent = payload.get("intent")
    model = CALL_MODELS.get(str(intent))
    if model is None:
        raise SchemaError([f"unknown intent {intent}"])
    errors = check_schema(payload, model.model_json_schema())
    if errors:
        raise SchemaError(errors)
    try:
        parsed = cast(ToolCall, model.model_validate(payload))
    except ValidationError as exc:
        raise SchemaError([err.get("msg", "invalid") for err in exc.errors()]) from exc
    _check_fault(parsed)
    return parsed


def tool_call_from_text(text: str) -> ToolCall:
    return tool_call_from_payload(extract_json_object(text))


def regex_tool_call(text: str) -> ToolCall | None:
    """Map a dispatcher sentence onto the same object the model is asked for."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    rules = _rules(cleaned)
    reason = cleaned[:240]
    lot = _lot(cleaned)
    equipment = _equipment(cleaned)
    area = _area(cleaned)
    minutes = _minutes(cleaned)
    if _WHAT_IF.search(cleaned):
        return WhatIfCall(
            intent="what_if",
            parameters=WhatIfParameters(
                question=reason,
                equipment_id=equipment,
                lot_id=lot,
                eta_min=minutes,
            ),
            validation_rules=rules,
        )
    if _RELEASE.search(cleaned) and lot:
        return ReleaseLotCall(
            intent="release_lot",
            parameters=LotReasonParameters(lot_id=lot, reason=reason),
            validation_rules=rules,
        )
    if _HOLD.search(cleaned) and lot:
        return HoldLotCall(
            intent="hold_lot",
            parameters=LotReasonParameters(lot_id=lot, reason=reason),
            validation_rules=rules,
        )
    if _PM.search(cleaned) and equipment:
        return MovePmCall(
            intent="move_pm",
            parameters=MovePmParameters(
                equipment_id=equipment,
                new_start_min=_start(cleaned),
                duration_min=minutes if minutes is not None else 60,
                reason=reason,
            ),
            validation_rules=rules,
        )
    if _HOT.search(cleaned) and lot:
        target = equipment or area
        if not target:
            return None
        urgent = bool(
            re.search(r"hot|rush|urgent|priority|特急|紧急|优先|急|热批|ホット", cleaned, re.I)
        )
        return InsertHotLotCall(
            intent="insert_hot_lot",
            parameters=InsertHotLotParameters(
                lot_id=lot,
                target_station_group=target,
                priority_override=urgent,
                reason=reason,
            ),
            validation_rules=rules,
        )
    if _DOWN.search(cleaned) and equipment:
        fault = "LASER_FAULT" if re.search(r"laser|激光", cleaned, re.I) else "UNPLANNED_DOWN"
        return MarkToolDownCall(
            intent="mark_tool_down",
            parameters=MarkToolDownParameters(
                equipment_id=equipment,
                eta_min=minutes if minutes is not None else 60,
                reason=reason,
                fault_code=fault,
            ),
            validation_rules=rules,
        )
    return None


def parse_dispatch(provider: Completer, text: str) -> DispatchParse:
    """Model first, regex when the provider is mock or the payload is unusable."""
    if provider.mocked:
        return _from_regex(text, request_id="", fallback_reason="Nightshift is not configured.")
    try:
        result = provider.complete(_messages(text), lane="intent", temperature=0.0)
    except Exception as exc:
        parsed = _from_regex(text, request_id="", fallback_reason=str(exc))
        return parsed
    try:
        call = tool_call_from_text(result.content)
    except (SchemaError, ValueError, TypeError) as exc:
        return _from_regex(
            text,
            request_id=result.meterless_request_id,
            fallback_reason=str(exc),
        )
    return DispatchParse(
        call=call.model_dump(),
        source="nemotron",
        request_id=result.meterless_request_id,
        errors=[],
        fallback_reason="",
    )


def call_from_dump(payload: dict[str, Any]) -> ToolCall:
    return tool_call_from_payload(payload)


def id_errors(call: ToolCall, plant: Plant) -> list[str]:
    """Unknown lots, tools, and station groups. A failure signs nothing."""
    errors: list[str] = []
    jobs = plant.job_map()
    tools = plant.equipment_map()
    areas = {item.area.casefold(): item.area for item in plant.equipment}
    lot_id = str(getattr(call.parameters, "lot_id", "") or "")
    if lot_id and (_LOT_ID.fullmatch(lot_id) is None or lot_id not in jobs):
        errors.append(f"Unknown lot {lot_id}.")
    equipment_id = str(getattr(call.parameters, "equipment_id", "") or "")
    if equipment_id and (
        _EQUIPMENT_ID.fullmatch(equipment_id) is None or equipment_id not in tools
    ):
        errors.append(f"Unknown equipment {equipment_id}.")
    target = str(getattr(call.parameters, "target_station_group", "") or "")
    if target:
        if _EQUIPMENT_ID.fullmatch(target):
            if target not in tools:
                errors.append(f"Unknown equipment {target}.")
        elif target.casefold() not in areas:
            errors.append(f"Unknown station group {target}.")
    return errors


def scout_model_intent(call: ToolCall, request_id: str) -> dict[str, Any]:
    """Subset Scout will sign. The full tool call stays beside the contract."""
    params = call.parameters
    payload: dict[str, Any] = {
        "intent": SCOUT_INTENT[call.intent],
        "confidence": 0.9,
        "meterless_request_id": request_id,
    }
    lot_id = str(getattr(params, "lot_id", "") or "")
    if lot_id and _LOT_ID.fullmatch(lot_id):
        payload["job_id"] = lot_id
    equipment = str(getattr(params, "equipment_id", "") or "")
    target = str(getattr(params, "target_station_group", "") or "")
    chosen = equipment or target
    if chosen and _EQUIPMENT_ID.fullmatch(chosen):
        payload["equipment_id"] = chosen
    eta = getattr(params, "eta_min", None)
    duration = getattr(params, "duration_min", None)
    if isinstance(eta, int):
        payload["repair_min"] = eta
    elif call.intent == "move_pm" and isinstance(duration, int):
        payload["repair_min"] = duration
    fault = str(getattr(params, "fault_code", "") or "")
    if fault and _FAULT.fullmatch(fault):
        payload["fault_code"] = fault
    return payload


def _from_regex(text: str, *, request_id: str, fallback_reason: str) -> DispatchParse:
    call = regex_tool_call(text)
    if call is None:
        return DispatchParse(
            call=None,
            source="deterministic-fallback",
            request_id=request_id,
            errors=["Could not read a dispatch intent from the text."],
            fallback_reason=fallback_reason,
        )
    return DispatchParse(
        call=call.model_dump(),
        source="deterministic-fallback",
        request_id=request_id,
        errors=[],
        fallback_reason=fallback_reason,
    )


def _messages(text: str) -> list[dict[str, str]]:
    catalog = {name: model.model_json_schema() for name, model in CALL_MODELS.items()}
    return [
        {
            "role": "system",
            "content": (
                "You convert a dispatcher sentence into one JSON tool call. "
                "Do not compute a schedule, a score, a matrix, or a tool state change. "
                "intent is one of insert_hot_lot, move_pm, mark_tool_down, hold_lot, "
                "release_lot, what_if. validation_rules.check_inventory is a boolean. "
                "validation_rules.notify_pe is a person's name or an empty string. "
                "priority_override is a boolean. Return one JSON object and nothing else. "
                f"Example: {EXAMPLE_INSERT_HOT_LOT}. Schemas: {catalog}."
            ),
        },
        {"role": "user", "content": text},
    ]


def _rules(text: str) -> ValidationRules:
    notify = ""
    found = _NOTIFY.search(text)
    if found:
        notify = found.group(1)
    return ValidationRules(check_inventory=_INVENTORY.search(text) is not None, notify_pe=notify)


def _lot(text: str) -> str:
    found = _LOT.search(text)
    return found.group(1).upper() if found else ""


def _equipment(text: str) -> str:
    found = _EQUIPMENT.search(text)
    if not found:
        return ""
    return f"{found.group(1).upper()}-{found.group(2)}"


def _area(text: str) -> str:
    for pattern, name in _AREAS:
        if pattern.search(text):
            return name
    return ""


def _minutes(text: str) -> int | None:
    found = _DURATION.search(text)
    if not found:
        return None
    amount = int(found.group(1))
    unit = found.group(2).lower()
    if unit.startswith("h") or unit in {"小时", "時間"}:
        return amount * 60
    return amount


def _start(text: str) -> int:
    found = _START.search(text)
    if not found:
        return 0
    return int(found.group(1))


def _check_fault(call: ToolCall) -> None:
    fault = str(getattr(call.parameters, "fault_code", "") or "")
    if fault and _FAULT.fullmatch(fault) is None:
        raise SchemaError(["fault_code failed validation."])
