"""Pull a JSON object out of a model reply and check it against a JSON schema.

The schema is the Pydantic model's JSON Schema. The checker covers the fragment
those models emit: objects, arrays, enums, numbers, and ``anyOf``. Unknown
fields are ignored. A payload that fails the schema never becomes a plan.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL | re.IGNORECASE)


class SchemaError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) or "schema validation failed")


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = _FENCE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("JSON value is not an object")
    return payload


def check_schema(
    instance: Any, schema: dict[str, Any], defs: dict[str, Any] | None = None
) -> list[str]:
    """Return schema violations. An empty list means the instance matches."""
    if defs is None:
        defs = schema.get("$defs") or {}
        if not isinstance(defs, dict):
            defs = {}
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        target = defs.get(name)
        if not isinstance(target, dict):
            return [f"unresolved schema ref {name}"]
        return check_schema(instance, target, defs)
    if "anyOf" in schema:
        options = schema["anyOf"]
        if isinstance(options, list) and any(
            isinstance(option, dict) and not check_schema(instance, option, defs)
            for option in options
        ):
            return []
        return ["no schema alternative matched"]
    expected = schema.get("type")
    if isinstance(expected, list):
        if any(not check_schema(instance, {**schema, "type": item}, defs) for item in expected):
            return []
        return ["type mismatch"]
    errors: list[str] = []
    if expected == "object":
        if not isinstance(instance, dict):
            return ["expected object"]
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        for key in schema.get("required") or []:
            if key not in instance:
                errors.append(f"missing {key}")
        for key, value in instance.items():
            prop = properties.get(key)
            if isinstance(prop, dict):
                errors.extend(_prefix(str(key), check_schema(value, prop, defs)))
        return errors
    if expected == "array":
        if not isinstance(instance, list):
            return ["expected array"]
        minimum = schema.get("minItems")
        if isinstance(minimum, int) and len(instance) < minimum:
            errors.append("too short")
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(instance) > maximum:
            errors.append("too long")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(_prefix(str(index), check_schema(item, item_schema, defs)))
        return errors
    if expected == "string":
        if not isinstance(instance, str):
            return ["expected string"]
        enum = schema.get("enum")
        if isinstance(enum, list) and instance not in enum:
            return [f"{instance!r} is not one of {enum}"]
        return []
    if expected in {"number", "integer"}:
        if isinstance(instance, bool) or not isinstance(instance, int | float):
            return ["expected number"]
        if expected == "integer" and not isinstance(instance, int):
            return ["expected integer"]
        if "minimum" in schema and instance < schema["minimum"]:
            return ["below minimum"]
        if "maximum" in schema and instance > schema["maximum"]:
            return ["above maximum"]
        return []
    if expected == "boolean":
        if not isinstance(instance, bool):
            return ["expected boolean"]
        return []
    if expected == "null":
        if instance is not None:
            return ["expected null"]
        return []
    return errors


def parse_model(text: str, model: type[BaseModel]) -> BaseModel:
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SchemaError([str(exc)]) from exc
    schema = model.model_json_schema()
    errors = check_schema(payload, schema)
    if errors:
        raise SchemaError(errors)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise SchemaError(_pydantic_errors(exc)) from exc


def _pydantic_errors(exc: ValidationError) -> list[str]:
    rendered: list[str] = []
    for item in exc.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()))
        rendered.append(f"{loc}: {item.get('msg', 'invalid')}" if loc else str(item.get("msg")))
    return rendered or ["schema validation failed"]


def _prefix(name: str, errors: list[str]) -> list[str]:
    return [f"{name}: {item}" for item in errors]
