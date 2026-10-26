"""Three-role deliberation demo (Plan: internal 3-role review, offline).

Runs three scripted events through ``resilimes.insight.deliberation`` with
the mock LLM and writes a readable receipt (JSON + Markdown) to ``outputs/``:

1. a customer expedite notice (fab-notes ``priority_change``) that the floor
   supports but whose projected boost breaks the Q-time gate;
2. a scanner breakdown where waiting for the pinned tool beats re-routing;
3. a planned-down note whose window collides with the PM calendar.

Everything here is MOCK / scripted: contexts are hand-built in the exact
shapes the planning layer and the exception engine produce, and the
narrative provider is ``MockProvider`` (``mocked: true`` in every record).
No live model is called.

    python3 scripts/run_deliberation_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resilimes.insight.deliberation import deliberate
from resilimes.llm.mock import MockProvider

LOT = "Init_Lot_3_17"

CASES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    (
        "customer_expedite_vs_qtime_gate",
        {
            "type": "priority_change",
            "lot": LOT,
            "priority": "hot",
            "new_due_h": 26.0,
            "source": "fab_note (customer request)",
            "validated": True,
        },
        {
            "plan": {
                "now_h": 6.0,
                "bands": {"critical": 2, "behind": 5, "on_plan": 40, "ahead": 12},
                "qtime_at_risk": 7,
                "lots": {
                    LOT: {
                        "band": "on_plan",
                        "score": 0.42,
                        "plan_slack_h": 9.5,
                        "qtime_at_risk": 1,
                    }
                },
                "litho_overload_days": {},
                "pm_windows": {},
            },
            "shift": {
                "exceptions": [
                    {
                        "id": "E1",
                        "kind": "hot_insertion",
                        "family": "Litho_FE_92",
                        "tool": None,
                        "lots": [LOT, "Init_Lot_5_9"],
                        "options": [
                            {
                                "id": "A",
                                "action": "rule_default",
                                "lever": "none",
                                "text": "keep the rule order (hot first within class tier)",
                                "rule_default": True,
                                "impact": {
                                    "qtime_violations": 1,
                                    "hot_late": 0,
                                    "late_lots": 2,
                                    "idle_min": 35.0,
                                },
                            },
                            {
                                "id": "B",
                                "action": "expedite",
                                "lever": "prio",
                                "text": "boost the customer lot ahead of the Q-time lot",
                                "rule_default": False,
                                "impact": {
                                    "qtime_violations": 2,
                                    "hot_late": 0,
                                    "late_lots": 1,
                                    "idle_min": 30.0,
                                },
                            },
                        ],
                    }
                ],
                "queues": {"Litho_FE_92": 4},
            },
            "field": {
                "observations": [
                    {
                        "kind": "lot_location",
                        "subject": LOT,
                        "detail": "lot is queued at Litho_FE_92, ready to run",
                    }
                ]
            },
        },
    ),
    (
        "breakdown_keep_pin_wins",
        {"type": "breakdown", "family": "Litho_FE_92", "tool": "Litho_FE_92-1"},
        {
            "plan": {
                "now_h": 6.0,
                "bands": {"critical": 0, "behind": 1, "on_plan": 45, "ahead": 14},
                "qtime_at_risk": 1,
                "lots": {},
                "litho_overload_days": {},
                "pm_windows": {},
            },
            "shift": {
                "exceptions": [
                    {
                        "id": "E2",
                        "kind": "breakdown",
                        "family": "Litho_FE_92",
                        "tool": "Litho_FE_92-1",
                        "lots": ["Init_Lot_7_21"],
                        "options": [
                            {
                                "id": "A",
                                "action": "rule_default",
                                "lever": "none",
                                "text": "re-route every pinned lot to a sibling scanner now",
                                "rule_default": True,
                                "impact": {
                                    "qtime_violations": 0,
                                    "hot_late": 1,
                                    "late_lots": 3,
                                    "idle_min": 10.0,
                                },
                            },
                            {
                                "id": "B",
                                "action": "keep_pin",
                                "lever": "keep_pin",
                                "text": "keep the pinned lot waiting for its scanner",
                                "rule_default": False,
                                "impact": {
                                    "qtime_violations": 0,
                                    "hot_late": 0,
                                    "late_lots": 2,
                                    "idle_min": 25.0,
                                },
                            },
                        ],
                    }
                ],
                "queues": {"Litho_FE_92": 2},
            },
            "field": {
                "observations": [
                    {
                        "kind": "down_report",
                        "subject": "Litho_FE_92",
                        "detail": "scanner Litho_FE_92-1 is down; repair ETA 2 h",
                    }
                ]
            },
        },
    ),
    (
        "planned_down_vs_pm_calendar",
        {
            "type": "planned_down",
            "equipment": "Litho_FE_98",
            "start": "2026-10-27T06:00:00Z",
            "start_h": 30.0,
            "duration_min": 240,
            "source": "fab_note (maintenance)",
            "validated": True,
        },
        {
            "plan": {
                "now_h": 6.0,
                "bands": {"critical": 1, "behind": 3, "on_plan": 44, "ahead": 11},
                "qtime_at_risk": 3,
                "lots": {},
                "litho_overload_days": {},
                "pm_windows": {"Litho_FE_98": [[32.0, 36.0]]},
            },
            "shift": {"exceptions": [], "queues": {}},
            "field": {"observations": []},
        },
    ),
]


def render_markdown(name: str, record: dict[str, Any]) -> str:
    lines = [
        f"## {name}",
        "",
        f"Event: `{json.dumps(record['event'], ensure_ascii=False)}`",
        "",
        "| role | verdict | summary |",
        "|---|---|---|",
    ]
    for item in record["assessments"]:
        lines.append(f"| {item['role']} | {item['verdict']} | {item['summary']} |")
    lines.append("")
    if record["conflicts"]:
        lines.append("Conflicts:")
        for conflict in record["conflicts"]:
            lines.append(
                f"- **{conflict['kind']}** ({', '.join(conflict['roles'])}): {conflict['detail']}"
            )
        lines.append("")
    decision = record["decision"]
    lines.append(
        f"Decision: **{decision.get('action')}**"
        + (f" (option {decision['option_id']})" if decision.get("option_id") else "")
    )
    lines.append("")
    lines.append(
        f"Narrative ({record['source']}, mocked={record['mocked']}, "
        f"fact_ok={record['fact_ok']}, degraded={record['degraded']}):"
    )
    lines.append("")
    lines.append(f"> {record['narrative']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    provider = MockProvider()
    records: dict[str, Any] = {}
    markdown = [
        "# Three-role deliberation — demo receipt",
        "",
        "**MOCK**: offline scripted contexts, narrative by the mock provider. "
        "No live model was called and no schedule was changed.",
        "",
    ]
    for name, event, context in CASES:
        record = deliberate(event, context, provider).to_json()
        records[name] = record
        markdown.append(render_markdown(name, record))
    out_dir = Path(__file__).resolve().parents[1] / "outputs"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "deliberation_demo.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    text = "\n".join(markdown)
    (out_dir / "deliberation_demo.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
