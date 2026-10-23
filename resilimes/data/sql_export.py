"""Render the Zetaris seed from data/sample so the two copies cannot drift."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from resilimes.config import ROOT

SAMPLE = ROOT / "data" / "sample"

TABLES = (
    "equipment",
    "wip_jobs",
    "products",
    "route",
    "route_steps",
    "qtime_rule",
    "bom",
    "materials",
    "operators",
    "maintenance_logs",
)


def table_rows() -> dict[str, list[dict[str, str]]]:
    equipment = _read(SAMPLE / "equipment.json")["equipment"]
    jobs = _read(SAMPLE / "wip_jobs.json")["jobs"]
    bom = _read(SAMPLE / "bom.json")
    products = bom["products"]
    materials = _read(SAMPLE / "materials.json")["materials"]
    operators = _read(SAMPLE / "operators.json")["operators"]
    rules = _read(SAMPLE / "qtime_rules.json")["rules"]
    return {
        "equipment": [_equipment(row) for row in equipment],
        "wip_jobs": [_job(row) for row in jobs],
        "products": [
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "route_id": _s(row.get("route_id")),
            }
            for row in products
        ],
        "route": [_route(row) for row in _list(bom.get("routes"))],
        "route_steps": _routes(products),
        "qtime_rule": [_qtime(row) for row in rules],
        "bom": _bom(products),
        "materials": [
            {
                "material_id": row["material_id"],
                "name": row["name"],
                "on_hand": str(row["on_hand"]),
                "unit": row["unit"],
            }
            for row in materials
        ],
        "operators": [
            {
                "operator_id": row["operator_id"],
                "name": row["name"],
                "certified": ",".join(row["certified"]),
                "shift": row["shift"],
            }
            for row in operators
        ],
        "maintenance_logs": _maintenance(SAMPLE / "maintenance_logs.csv"),
    }


def render_sql(schema: str = "resilimes") -> str:
    rows = table_rows()
    lines = [
        "-- ResiliMES factory seed for the Zetaris SQL editor.",
        "-- Generated from data/sample. Do not edit by hand; run: python scripts/export_zetaris_sql.py",
        "--",
        "-- Assumption: the organisation can create tables in a database named",
        f"-- `{schema}`. If the SQL editor rejects CREATE TABLE, register the CSVs in",
        "-- data/zetaris/ as Lightning tables with the same names and set ZETARIS_SCHEMA.",
        "-- Numeric columns are VARCHAR on purpose. The application casts them.",
        "",
    ]
    for name in TABLES:
        columns = list(rows[name][0].keys())
        col_sql = ", ".join(f"{column} VARCHAR(256)" for column in columns)
        lines.append(f"CREATE TABLE {schema}.{name} ({col_sql});")
        for row in rows[name]:
            values = ", ".join(_quote(row[column]) for column in columns)
            listed = ", ".join(columns)
            lines.append(f"INSERT INTO {schema}.{name} ({listed}) VALUES ({values});")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_csv(name: str) -> str:
    rows = table_rows()[name]
    headers = list(rows[0].keys())
    output: list[str] = []
    writer_target = _ListWriter(output)
    writer = csv.DictWriter(writer_target, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return "".join(output)


def _equipment(row: dict[str, Any]) -> dict[str, str]:
    return {
        "equipment_id": _s(row["equipment_id"]),
        "name": _s(row["name"]),
        "area": _s(row["area"]),
        "status": _s(row["status"]),
        "capability": ",".join(_s(item) for item in _list(row.get("capability"))),
        "setup_time_min": _s(row.get("setup_time_min")),
        "operators_required": _s(row.get("operators_required")),
        "max_wip": _s(row.get("max_wip")),
        "mtbf_hours": _s(row.get("mtbf_hours")),
        "last_pm_at": _s(row.get("last_pm_at")),
        "fault_code": _s(row.get("fault_code")),
        "down_since": _s(row.get("down_since")),
    }


def _job(row: dict[str, Any]) -> dict[str, str]:
    return {
        "job_id": _s(row["job_id"]),
        "product_id": _s(row["product_id"]),
        "priority": _s(row["priority"]),
        "qty": _s(row["qty"]),
        "current_step": _s(row["current_step"]),
        "assigned_equipment": _s(row.get("assigned_equipment")),
        "status": _s(row["status"]),
        "due_at": _s(row["due_at"]),
        "started_at": _s(row.get("started_at")),
        "process_time_min": _s(row["process_time_min"]),
        "remaining_steps": ",".join(_s(item) for item in _list(row.get("remaining_steps"))),
        "preferred_equipment": ",".join(_s(item) for item in _list(row.get("preferred_equipment"))),
        "released_through": _s(row.get("released_through")),
        "rework_of": _s(row.get("rework_of")),
        "rework_count": _s(row.get("rework_count") or 0),
        "rework_limit": _s(row.get("rework_limit") or 1),
    }


def _route(row: dict[str, Any]) -> dict[str, str]:
    return {
        "route_id": _s(row["route_id"]),
        "product_id": _s(row["product_id"]),
        "name": _s(row["name"]),
    }


def _qtime(row: dict[str, Any]) -> dict[str, str]:
    return {
        "rule_id": _s(row["rule_id"]),
        "product_id": _s(row["product_id"]),
        "from_step": _s(row["from_step"]),
        "to_step": _s(row["to_step"]),
        "max_min": _s(row["max_min"]),
    }


def _routes(products: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for product in products:
        for index, step in enumerate(_list(product.get("route"))):
            if not isinstance(step, dict):
                continue
            rows.append(
                {
                    "product_id": _s(product["product_id"]),
                    "step_index": str(index),
                    "step": _s(step["step"]),
                    "capability": _s(step["capability"]),
                    "process_time_min": _s(step["process_time_min"]),
                    "setup_family": _s(step["setup_family"]),
                    "step_no": _s(step.get("step_no")),
                    "operation": _s(step.get("operation") or step["step"]),
                    "area": _s(step.get("area")),
                    "recipe": _s(step.get("recipe") or step["setup_family"]),
                    "layer": _s(step.get("layer")),
                    "rework": "true" if step.get("rework") else "false",
                }
            )
    return rows


def _bom(products: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for product in products:
        for need in _list(product.get("materials")):
            if not isinstance(need, dict):
                continue
            rows.append(
                {
                    "product_id": _s(product["product_id"]),
                    "material_id": _s(need["material_id"]),
                    "qty_per_lot": _s(need["qty_per_lot"]),
                }
            )
    return rows


def _maintenance(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            rows.append(
                {
                    "log_id": record["log_id"],
                    "equipment_id": record["equipment_id"],
                    "event_type": record["event_type"],
                    "occurred_at": record["severity_at"],
                    "severity_code": record["severity_code"],
                    "description": record["description"],
                    "estimated_repair_min": record["estimated_repair_min"],
                    "technician": record["technician"],
                }
            )
    return rows


def _read(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(path)
    return loaded


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _quote(value: str) -> str:
    if value == "":
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


class _ListWriter:
    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def write(self, text: str) -> int:
        self._sink.append(text)
        return len(text)
