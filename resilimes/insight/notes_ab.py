# ruff: noqa: RUF001  (the report template is Chinese; full-width punctuation is intentional)
"""A/B/C schedule comparison for notes-driven scheduling (Plan-2 evaluation).

Arms (same notes, same book, only the event feed differs):

- **A** — no notes: the baseline schedule, blind to everything in the notes.
- **B** — AI events: extractor output over the notes, fact-checked by
  :func:`resilimes.insight.notes.validate_events`, then applied.
- **C** — gold events: the hand-labeled events applied (oracle ceiling).

Headline metric — **gap closure** on avoidable Q-time violations
(``hard_qtime.miss_class == "avoidable"`` in the real simulator):

    gap_closure = (A - B) / (A - C)

1.0 means B closes the entire gold gap; 0 means B is no better than blind;
``None`` when A == C (gold adds nothing on this book, ratio undefined).

Collateral damage (target 0), reported alongside, never hidden:

- ``wrong_events_applied`` — validated B events that took effect but match
  no gold event for their note (includes events extracted from zero-gold
  trap notes).
- ``new_violations`` — ``max(0, B_avoidable - A_avoidable)``: avoidable
  violations B introduced that A did not have.

Runner protocol: any object with
``run(events, truth) -> ArmOutcome`` where ``events`` are validated event
dicts tagged with ``_note_id`` and ``truth`` maps note id -> gold key
Counter. A live runner ignores ``truth`` (correctness must emerge from the
schedule); it exists for the mock.

- :class:`MockScheduleRunner` — a deterministic miniature ledger model so
  the whole pipeline and the report render end-to-end offline. Its numbers
  are **ledger units, not fab data**.
- Live runner (owner's machine): implement the protocol against
  ``resilimes.smt.simulate.run_policy`` (planned_down -> ``downs`` windows,
  priority_change -> hot lot / due handling, hold/derate -> fault plan) and
  pass it to :func:`compare_arms`, or drop it in as
  ``resilimes/insight/notes_ab_live.py`` with a ``build_runner()`` factory
  and use ``scripts/compare_notes_ab.py --runner live``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from resilimes.insight.notes import event_key

# Mock ledger constants (NOT fab measurements; see class docstring).
MOCK_BASE_AVOIDABLE = 160
MOCK_UNAVOIDABLE = 30
MOCK_EFFECT = {  # avoidable violations prevented per correctly applied event
    "planned_down": 3,
    "priority_change": 2,
    "hold": 2,
    "capacity_derate": 2,
}
MOCK_HARM = 4  # avoidable violations added per wrongly applied event


@dataclass
class ArmOutcome:
    avoidable_qtime: int
    qtime_violations: int | None = None
    on_time_pct: float | None = None
    completed: int | None = None
    applied: list[dict[str, Any]] = field(default_factory=list)
    unsupported: int = 0


class ScheduleRunner(Protocol):
    name: str
    is_mock: bool

    def run(self, events: list[dict[str, Any]], truth: dict[str, Counter]) -> ArmOutcome: ...


class MockScheduleRunner:
    """Deterministic ledger stand-in for the real simulator.

    Avoidable violations = base - sum(effects of applied events that match
    gold) + harm * (applied events that match nothing). It peeks at
    ``truth`` because a ledger has no physics; the live runner must not.
    Every report produced with it is labeled MOCK.
    """

    name = "mock-ledger"
    is_mock = True

    def run(self, events: list[dict[str, Any]], truth: dict[str, Counter]) -> ArmOutcome:
        remaining = {note_id: Counter(keys) for note_id, keys in truth.items()}
        avoidable = MOCK_BASE_AVOIDABLE
        applied: list[dict[str, Any]] = []
        for event in events:
            applied.append(event)
            keys = remaining.setdefault(event["_note_id"], Counter())
            key = event_key(event)
            if keys[key] > 0:
                keys[key] -= 1
                avoidable -= MOCK_EFFECT[event["type"]]
            else:
                avoidable += MOCK_HARM
        return ArmOutcome(
            avoidable_qtime=avoidable,
            qtime_violations=avoidable + MOCK_UNAVOIDABLE,
            applied=applied,
        )


def _tag(events: list[dict[str, Any]], note_id: str) -> list[dict[str, Any]]:
    return [dict(e, _note_id=note_id) for e in events]


def gap_closure(a: int, b: int, c: int) -> float | None:
    """(A - B) / (A - C); None when gold adds nothing (A == C)."""
    if a == c:
        return None
    return round((a - b) / (a - c), 4)


def compare_arms(
    notes: list[dict[str, Any]],
    b_events_by_note: dict[str, list[dict[str, Any]]],
    runner: ScheduleRunner,
) -> dict[str, Any]:
    """Run arms A/B/C and compute the headline metrics.

    ``b_events_by_note`` must be the *validated* B events per note id
    (see ``resilimes.insight.notes.extract_validated``).
    """
    truth = {note["id"]: Counter(event_key(e) for e in note["gold"]) for note in notes}
    gold_events = [e for note in notes for e in _tag(note["gold"], note["id"])]
    b_events = [e for note in notes for e in _tag(b_events_by_note.get(note["id"], []), note["id"])]
    outcomes = {
        "A": runner.run([], truth),
        "B": runner.run(b_events, truth),
        "C": runner.run(gold_events, truth),
    }
    a, b, c = (outcomes[arm].avoidable_qtime for arm in ("A", "B", "C"))

    # Collateral: applied B events whose key matches no remaining gold key.
    remaining = {note_id: Counter(keys) for note_id, keys in truth.items()}
    wrong = 0
    for event in outcomes["B"].applied:
        keys = remaining.setdefault(event["_note_id"], Counter())
        key = event_key(event)
        if keys[key] > 0:
            keys[key] -= 1
        else:
            wrong += 1

    def arm_view(outcome: ArmOutcome) -> dict[str, Any]:
        return {
            "avoidable_qtime": outcome.avoidable_qtime,
            "qtime_violations": outcome.qtime_violations,
            "on_time_pct": outcome.on_time_pct,
            "completed": outcome.completed,
            "applied_events": len(outcome.applied),
            "unsupported_events": outcome.unsupported,
        }

    return {
        "runner": runner.name,
        "is_mock": runner.is_mock,
        "primary_metric": "avoidable_qtime_violations",
        "arms": {arm: arm_view(outcomes[arm]) for arm in ("A", "B", "C")},
        "gap_closure": gap_closure(a, b, c),
        "collateral": {
            "wrong_events_applied": wrong,
            "new_violations": max(0, b - a),
            "target": 0,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Fill the standard A/B/C report template from a comparison report dict.

    ``report`` is the dict built by ``scripts/compare_notes_ab.py``:
    {comparison, extraction: {extractor_name: score_extractor result}}.
    """
    comp = report["comparison"]
    arms = comp["arms"]
    closure = comp["gap_closure"]
    mode = "MOCK — ledger model, not a fab simulation" if comp["is_mock"] else "LIVE"
    lines = [
        "# Notes A/B/C 对比报告",
        "",
        f"- 模式：**{mode}**（runner: {comp['runner']}）",
        "- A = 无 notes 基线；B = AI 抽取事件（经事实核查后生效）；C = gold 事件（天花板）",
        f"- 主指标：{comp['primary_metric']}",
        "",
        "## 头条指标",
        "",
        f"- **缺口弥合率 (A-B)/(A-C)：{closure if closure is not None else 'n/a（A=C，gold 无增益）'}**",
        f"- **误伤次数：{comp['collateral']['wrong_events_applied']}**"
        f"（错误事件生效数，目标 0）；新增违规：{comp['collateral']['new_violations']}",
        "",
        "## 三臂结果",
        "",
        "| arm | avoidable Q-time | Q-time violations | on-time % | completed | applied | unsupported |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ("A", "B", "C"):
        v = arms[arm]
        lines.append(
            f"| {arm} | {v['avoidable_qtime']} | {v['qtime_violations']} | "
            f"{v['on_time_pct']} | {v['completed']} | {v['applied_events']} | "
            f"{v['unsupported_events']} |"
        )
    lines += ["", "## 抽取质量（同集对比）", ""]
    for name, score in report["extraction"].items():
        o = score["overall"]
        lines += [
            f"### {name}",
            "",
            f"总体 precision {o['precision']} / recall {o['recall']}；"
            f"被核查拦下 {score['rejected_by_validation']} 条；"
            f"hold reason 准确率 {score['hold_reason_accuracy']}",
            "",
            "| type | precision | recall | TP | FP | FN |",
            "|---|---|---|---|---|---|",
        ]
        for etype, row in score["per_type"].items():
            lines.append(
                f"| {etype} | {row['precision']} | {row['recall']} | "
                f"{row['tp']} | {row['fp']} | {row['fn']} |"
            )
        lines.append("")
    lines += [
        "## 口径与遗留",
        "",
        "- 缺口弥合率以可避免 Q-time 违规为主指标；A=C 时记 n/a，不硬算。",
        "- 误伤 = B 生效但与 gold 不匹配的事件数 + B 相对 A 新增的违规数，两项分列，目标均为 0。",
        "- mock 模式数字为 ledger 模型单位，不是 fab 仿真结果；live 结果由所有者本机以真实 runner 重跑后替换本节数字。",
        "",
    ]
    return "\n".join(lines)
