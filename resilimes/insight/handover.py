# ruff: noqa: RUF001  (zh/ja templates use full-width punctuation on purpose)
"""Shift handover report: one 12 h shift, read in six 2 h chunks, written for the next shift.

Engine: the repo's Markovian engine (``engines.markovian``). Each 2 h chunk is one
Markovian step: it gets the compressed checkpoint from the previous chunk (open
issues, tools down, WIP bubbles, short notes; no transcript) plus the deterministic
facts of its own window, and the model (Nemotron through Nightshift; a scripted
stand-in offline) returns notes and the issues still open. A seventh step composes the
report in en, zh or ja from the last checkpoint and the end-of-shift facts. The
engine needs a signed contract with ``memory.write``; the report signs a fixed
handover contract with the Scout key (no Scout intent is added, so Scout routing
does not change). If the engine refuses the contract, the same steps run in a plain
loop with the same compression and the result says ``engine: own_loop``.

Every id and number in the report must come from the facts (one rewrite, then
flagged). Must-mention recall = share of the deterministic must-mention ids (tools
down at shift end, top at-risk lots, next-shift PM tools, top WIP bubbles) that the
report names. Advice only: nothing is dispatched or committed.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from resilimes.agents.jsonutil import extract_json_object
from resilimes.engines.contracts import ContractError, sign_body
from resilimes.engines.markovian.engine import MarkovianEngine, compress
from resilimes.evidence.factcheck import FactRegistry, check
from resilimes.evidence.toolkit import HOUR, RecordedRun
from resilimes.llm import deadline
from resilimes.llm.base import Completer, LlmResult

LANE = "handover"
LANGUAGES = {"en": "English", "zh": "Simplified Chinese", "ja": "Japanese"}
SHIFT_H = 12.0
CHUNK_H = 2.0
# (seed, shift start hour) on the 48 h run; the next 12 h supply PM plans and repair ETAs.
SHIFTS = ((1, 12.0), (1, 24.0), (2, 12.0), (2, 24.0))
SECTIONS = ("top_issues", "wip_bubbles", "at_risk_lots", "tools_down", "next_shift_pm", "overrides")
MAX_ITEMS = 6

CHUNK_SYSTEM = """You are the AI shift lead of a semiconductor fab simulation, reading the shift
two hours at a time. You get CHECKPOINT (what earlier chunks found, compressed) and FACTS for
this two-hour window as JSON. Reply with ONE JSON object, no prose outside it:
{"notes": ["<= 3 short notes on what mattered in this window"],
 "open_issues": ["ids (tool, family or lot names) that still need attention"],
 "resolved": ["ids from CHECKPOINT open_issues that are no longer a problem"]}
Use only ids and numbers that appear in CHECKPOINT or FACTS."""

COMPOSE_SYSTEM = """You write the shift handover report for the incoming shift of a semiconductor
fab simulation. You get CHECKPOINT (the compressed notes of the six two-hour chunks) and
END_FACTS (tools down at shift end with repair ETA, PM in the next 12 h and, if none, the
next calendar PM, at-risk lots, WIP bubbles, decision overrides and their outcomes). Reply with ONE JSON object, no prose outside it:
{"summary": "<= 2 sentences",
 "top_issues": ["..."], "wip_bubbles": ["..."], "at_risk_lots": ["..."],
 "tools_down": [{"tool": "<name>", "eta_h": <number>, "note": "..."}],
 "next_shift_pm": ["..."], "overrides": ["..."]}
At most 6 items per list. Name every tool in END_FACTS.tools_down_at_end, every lot in
END_FACTS.must_mention.lots, every tool in END_FACTS.next_shift_pm and every family in
END_FACTS.must_mention.families. Use only ids and numbers from CHECKPOINT and END_FACTS
(hours as given, e.g. 31.5). Advice only: do not order actions, suggest them."""


# ---- deterministic facts ---------------------------------------------------------------------
def _h(seconds: float) -> float:
    return round(seconds / HOUR, 1)


def _spans(run: RecordedRun, kind: str, start: float, end: float) -> list[dict[str, Any]]:
    fab = run.fab
    table = run.downs if kind == "down" else run.pm
    rows: list[dict[str, Any]] = []
    for tool, spans in enumerate(table):
        for left, right in spans:
            if left < end and right > start:
                rows.append(
                    {
                        "tool": fab.tool_name[tool],
                        "family": fab.families[fab.tool_family[tool]].name,
                        "from_h": _h(left),
                        "to_h": _h(right),
                        "min_in_window": round((min(right, end) - max(left, start)) / 60.0, 1),
                    }
                )
    rows.sort(key=lambda row: -row["min_in_window"])
    return rows


def _bubbles(run: RecordedRun, start: float, end: float) -> list[dict[str, Any]]:
    tl = run.timeline
    rows: list[dict[str, Any]] = []
    for fam, family in enumerate(run.fab.families):
        before, after = tl.waiting_at(fam, start), tl.waiting_at(fam, end)
        if after - before >= max(5, 0.5 * before):
            rows.append({"family": family.name, "wip_from": before, "wip_to": after})
    rows.sort(key=lambda row: row["wip_from"] - row["wip_to"])
    return rows[:3]


def _overrides(run: RecordedRun, start: float, end: float) -> list[dict[str, Any]]:
    fab, tl = run.fab, run.timeline
    rows: list[dict[str, Any]] = []
    for lot, items in tl.displaced.items():
        for item in items:
            if start <= item.at < end:
                rows.append(
                    {
                        "lot": fab.lot_id[lot],
                        "tool": fab.tool_name[item.tool],
                        "at_h": _h(item.at),
                        "delay_min": round((item.until - item.at) / 60.0, 1),
                        "source": item.source,
                    }
                )
    unique = {(row["lot"], row["tool"], row["at_h"]): row for row in rows}
    return sorted(unique.values(), key=lambda row: row["at_h"])


def calendar_pm(fab: Any, after_h: float, limit: int = 3) -> list[dict[str, Any]]:
    """Earliest calendar PMs (per family) starting after ``after_h``, however far out."""
    rows = []
    after = after_h * HOUR
    for fam, first, interval, duration, _name in fab.pm:
        if interval <= 0 or duration <= 0:
            continue
        start = first
        while start < after:
            start += interval
        rows.append(
            {
                "family": fab.families[fam].name,
                "from_h": _h(start),
                "hours": round(duration / HOUR, 1),
            }
        )
    rows.sort(key=lambda row: row["from_h"])
    return rows[:limit]


def chunk_facts(run: RecordedRun, start_h: float, end_h: float) -> dict[str, Any]:
    start, end = start_h * HOUR, end_h * HOUR
    done = sum(1 for at in run.timeline.completed.values() if start <= at < end)
    return {
        "window_h": [start_h, end_h],
        "tools_down": _spans(run, "down", start, end)[:MAX_ITEMS],
        "pm": _spans(run, "pm", start, end)[:MAX_ITEMS],
        "wip_bubbles": _bubbles(run, start, end),
        "overrides": _overrides(run, start, end)[:MAX_ITEMS],
        "lots_finished": done,
    }


def _remaining_sec(run: RecordedRun, lot: int, moment: float) -> float:
    fab = run.fab
    route = fab.routes[fab.lot_route[lot]]
    step = fab.lot_step[lot]
    for visit in run.timeline.visits.get(lot, []):
        if visit.ready > moment:
            break
        step = visit.step + 1 if visit.leave is not None and visit.leave <= moment else visit.step
    return route.remain[step] if 0 <= step < len(route.remain) else 0.0


def end_facts(run: RecordedRun, start_h: float, end_h: float) -> dict[str, Any]:
    fab, tl = run.fab, run.timeline
    start, end = start_h * HOUR, end_h * HOUR
    down_end = [
        {
            "tool": row["tool"],
            "family": row["family"],
            "since_h": row["from_h"],
            "eta_h": row["to_h"],
            "hours_left": round(row["to_h"] - end_h, 1),
        }
        for row in _spans(run, "down", end - 1.0, end)
    ]
    next_pm = [
        {"tool": row["tool"], "family": row["family"], "from_h": row["from_h"], "to_h": row["to_h"]}
        for row in _spans(run, "pm", end, end + SHIFT_H * HOUR)
        if row["from_h"] >= end_h
    ]
    next_pm.sort(key=lambda row: row["from_h"])
    at_risk: list[dict[str, Any]] = []
    for lot in range(len(fab.lot_id)):
        done = tl.completed.get(lot)
        due = fab.lot_due[lot]
        if (done is not None and done <= end) or due > end + SHIFT_H * HOUR:
            continue
        slack = due - end - _remaining_sec(run, lot, end)
        if slack < 2 * HOUR:
            at_risk.append(
                {
                    "lot": fab.lot_id[lot],
                    "due_h": _h(due),
                    "slack_h": _h(slack),
                    "late_now": due < end,
                }
            )
    at_risk.sort(key=lambda row: row["slack_h"])
    overrides = _overrides(run, start, end)
    for row in overrides:
        lot = fab.lot_id.index(row["lot"])
        finished = tl.completed.get(lot)
        row["displaced_lot_late"] = (finished if finished is not None else end) > fab.lot_due[lot]
    bubbles = _bubbles(run, start, end)
    must = {
        "tools": sorted(
            {row["tool"] for row in down_end[:MAX_ITEMS]}
            | {row["tool"] for row in next_pm[:MAX_ITEMS]}
        ),
        "lots": [row["lot"] for row in at_risk[:3]],
        "families": [row["family"] for row in bubbles],
    }
    return {
        "shift_h": [start_h, end_h],
        "tools_down_at_end": down_end[:MAX_ITEMS],
        "next_shift_pm": next_pm[:MAX_ITEMS],
        "next_calendar_pm": calendar_pm(fab, end_h),
        "at_risk_lots": at_risk[:8],
        "at_risk_count": len(at_risk),
        "wip_bubbles": bubbles,
        "overrides": overrides[:MAX_ITEMS],
        "override_count": len(overrides),
        "override_source": "rule-based Q-time overrides unless the run had an AI shift lead",
        "must_mention": must,
    }


def must_mention(end: dict[str, Any]) -> list[str]:
    must = end["must_mention"]
    return [*must["tools"], *must["lots"], *must["families"]]


# ---- scripted stand-in -----------------------------------------------------------------------
_T = {
    "en": {
        "chunk": "{a}-{b} h: {downs} tool(s) down, {bubbles} WIP bubble(s), {done} lots finished.",
        "summary": "{down} tool(s) still down, {risk} lot(s) at risk, {pm} PM(s) next shift.",
        "issue_down": "{tool} down until {eta} h",
        "issue_risk": "{lot} at risk, due {due} h",
        "bubble": "{family}: WIP {a} -> {b}",
        "risk": "{lot}: due {due} h, slack {slack} h",
        "note": "since {since} h, ETA {eta} h",
        "pm": "{tool} PM {a}-{b} h",
        "override": "{lot} passed over at {tool} ({delay} min); late: {late}",
        "yes": "yes",
        "no": "no",
        "next_pm": "none in the next 12 h; next calendar PM {family} at {at} h",
    },
    "zh": {
        "chunk": "{a}-{b} h：{downs} 台机台宕机，{bubbles} 处 WIP 堆积，完成 {done} 批。",
        "summary": "{down} 台机台仍宕机，{risk} 批有迟交风险，下一班 {pm} 项 PM。",
        "issue_down": "{tool} 宕机至 {eta} h",
        "issue_risk": "{lot} 有迟交风险，交期 {due} h",
        "bubble": "{family}：WIP {a} -> {b}",
        "risk": "{lot}：交期 {due} h，余量 {slack} h",
        "note": "自 {since} h 起，预计 {eta} h 恢复",
        "pm": "{tool} PM {a}-{b} h",
        "override": "{lot} 在 {tool} 被让行（{delay} 分钟）；迟交：{late}",
        "yes": "是",
        "no": "否",
        "next_pm": "未来 12 小时无 PM；下一次计划 PM：{family}，{at} h",
    },
    "ja": {
        "chunk": "{a}-{b} h：装置ダウン {downs} 台、WIP 滞留 {bubbles} か所、完了 {done} ロット。",
        "summary": "装置ダウン継続 {down} 台、遅延リスク {risk} ロット、次シフトの PM {pm} 件。",
        "issue_down": "{tool} は {eta} h までダウン",
        "issue_risk": "{lot} に遅延リスク、納期 {due} h",
        "bubble": "{family}：WIP {a} -> {b}",
        "risk": "{lot}：納期 {due} h、余裕 {slack} h",
        "note": "{since} h からダウン、復旧見込み {eta} h",
        "pm": "{tool} PM {a}-{b} h",
        "override": "{lot} は {tool} で後回し（{delay} 分）；遅延：{late}",
        "yes": "あり",
        "no": "なし",
        "next_pm": "今後 12 時間の PM なし。次の計画 PM：{family}、{at} h",
    },
}


class ScriptedHandover:
    """Offline stand-in: reads the facts from the prompt and fills fixed templates."""

    name = "mock"
    mocked = True

    def __init__(self, language: str) -> None:
        self.t = _T.get(language, _T["en"])

    def model_for(self, lane: str) -> str:
        return "scripted-mock"

    def complete(
        self, messages: list[dict[str, str]], *, lane: str, temperature: float = 0.2
    ) -> LlmResult:
        data = json.loads(messages[1]["content"].split("\n", 1)[1])
        content = json.dumps(self._compose(data) if "END_FACTS" in data else self._chunk(data))
        return LlmResult(
            content=content,
            model="scripted-mock",
            provider=self.name,
            lane=lane,
            latency_ms=0.0,
            mocked=True,
        )

    def _chunk(self, data: dict[str, Any]) -> dict[str, Any]:
        facts = data["FACTS"]
        a, b = facts["window_h"]
        note = self.t["chunk"].format(
            a=a,
            b=b,
            downs=len(facts["tools_down"]),
            bubbles=len(facts["wip_bubbles"]),
            done=facts["lots_finished"],
        )
        open_ids = [row["tool"] for row in facts["tools_down"] if row["to_h"] > b]
        open_ids += [row["family"] for row in facts["wip_bubbles"]]
        return {"notes": [note], "open_issues": open_ids, "resolved": []}

    def _compose(self, data: dict[str, Any]) -> dict[str, Any]:
        t, end = self.t, data["END_FACTS"]
        down, risk, pm = end["tools_down_at_end"], end["at_risk_lots"], end["next_shift_pm"]
        issues = [t["issue_down"].format(tool=r["tool"], eta=r["eta_h"]) for r in down[:3]]
        issues += [t["issue_risk"].format(lot=r["lot"], due=r["due_h"]) for r in risk[:3]]
        return {
            "summary": t["summary"].format(down=len(down), risk=min(len(risk), 8), pm=len(pm)),
            "top_issues": issues[:MAX_ITEMS],
            "wip_bubbles": [
                t["bubble"].format(family=r["family"], a=r["wip_from"], b=r["wip_to"])
                for r in end["wip_bubbles"]
            ],
            "at_risk_lots": [
                t["risk"].format(lot=r["lot"], due=r["due_h"], slack=r["slack_h"])
                for r in risk[:MAX_ITEMS]
            ],
            "tools_down": [
                {
                    "tool": r["tool"],
                    "eta_h": r["eta_h"],
                    "note": t["note"].format(since=r["since_h"], eta=r["eta_h"]),
                }
                for r in down
            ],
            "next_shift_pm": [
                t["pm"].format(tool=r["tool"], a=r["from_h"], b=r["to_h"]) for r in pm
            ]
            or [
                t["next_pm"].format(family=r["family"], at=r["from_h"])
                for r in end["next_calendar_pm"][:1]
            ],
            "overrides": [
                t["override"].format(
                    lot=r["lot"],
                    tool=r["tool"],
                    delay=r["delay_min"],
                    late=t["yes"] if r["displaced_lot_late"] else t["no"],
                )
                for r in end["overrides"]
            ],
        }


# ---- report rendering ------------------------------------------------------------------------
HEADINGS = {
    "en": {
        "title": "Shift handover",
        "summary": "Summary",
        "top_issues": "Top issues",
        "wip_bubbles": "WIP bubbles",
        "at_risk_lots": "At-risk lots",
        "tools_down": "Tools down (ETA, note)",
        "next_shift_pm": "PM next shift",
        "overrides": "Decision overrides and outcomes",
        "none": "none",
        "advice": "Advice only; nothing was dispatched.",
    },
    "zh": {
        "title": "交班报告",
        "summary": "概要",
        "top_issues": "主要问题",
        "wip_bubbles": "WIP 堆积",
        "at_risk_lots": "有迟交风险的批次",
        "tools_down": "宕机机台（预计恢复、备注）",
        "next_shift_pm": "下一班 PM",
        "overrides": "决策让行及结果",
        "none": "无",
        "advice": "仅供参考；未下发任何派工。",
    },
    "ja": {
        "title": "シフト引き継ぎ",
        "summary": "概要",
        "top_issues": "主な課題",
        "wip_bubbles": "WIP 滞留",
        "at_risk_lots": "遅延リスクのあるロット",
        "tools_down": "ダウン中の装置（復旧見込み・メモ）",
        "next_shift_pm": "次シフトの PM",
        "overrides": "判断による後回しとその結果",
        "none": "なし",
        "advice": "助言のみ。払い出しは行っていません。",
    },
}


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        return f"{item.get('tool', '')} · ETA {item.get('eta_h', '')} h · {item.get('note', '')}"
    return str(item)


def report_text(report: dict[str, Any]) -> str:
    """All model-written text of the report (what the fact check reads)."""
    parts = [str(report.get("summary", ""))]
    for key in SECTIONS:
        parts += [_item_text(item) for item in report.get(key) or []]
    return "\n".join(parts)


def render_markdown(report: dict[str, Any], language: str, shift_h: list[float]) -> str:
    head = HEADINGS.get(language, HEADINGS["en"])
    lines = [
        f"# {head['title']} · {shift_h[0]}-{shift_h[1]} h",
        "",
        f"**{head['summary']}:** {report.get('summary', '')}",
    ]
    for key in SECTIONS:
        lines += ["", f"## {head[key]}"]
        items = report.get(key) or []
        lines += [f"- {_item_text(item)}" for item in items] or [f"- {head['none']}"]
    lines += ["", f"_{head['advice']}_"]
    return "\n".join(lines) + "\n"


def _validate(report: Any) -> list[str]:
    if not isinstance(report, dict):
        return ["reply must be a JSON object"]
    errors = [f"missing list {key}" for key in SECTIONS if not isinstance(report.get(key), list)]
    if not isinstance(report.get("summary"), str):
        errors.append("summary must be a string")
    for item in report.get("tools_down") or []:
        if not isinstance(item, dict) or "tool" not in item:
            errors.append("tools_down items need tool, eta_h, note")
            break
    return errors


# ---- the run ---------------------------------------------------------------------------------
def handover_contract(secret: str, minutes: int = 30) -> dict[str, Any]:
    now = datetime.now(UTC)
    body = {
        "contractId": uuid.uuid4().hex,
        "intent": {"primary": "ai.shift_handover", "parameters": {}, "parser": "fixed"},
        "risk": {"level": "low", "flags": [], "redactions": [], "approvals": []},
        "toolPlan": [{"tool": "markovian.checkpoint", "capability": "memory.write", "args": {}}],
        "scope": {
            "user": {"id": "ai.handover", "role": "viewer"},
            "surface": "ai_evidence",
            "capabilities": ["world.query", "memory.write"],
        },
        "issuedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": (now + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return sign_body(body, secret)


def _signing_secret() -> str:
    from resilimes.config import DEV_SCOUT_SECRET, ConfigError, get_settings

    try:
        return get_settings().scout_signing_secret or DEV_SCOUT_SECRET
    except ConfigError:
        return DEV_SCOUT_SECRET


def handover(
    run: RecordedRun,
    start_h: float,
    provider: Completer | None = None,
    *,
    language: str = "en",
    temperature: float = 0.2,
    secret: str | None = None,
    deadline_s: float | None = None,
) -> dict[str, Any]:
    """Write one shift handover report. Returns report, markdown, metrics and the engine used.

    The report runs under a wall-clock budget (``deadline_s``, default AI_TASK_DEADLINE_S
    = 180 s). On timeout no further model call is made; the result is marked ``timeout``
    and keeps its deterministic parts (end-of-shift facts, must-mention list).
    """
    budget = deadline_s if deadline_s is not None else deadline.default_task_s()
    with deadline.task_deadline(budget):
        return _handover(
            run, start_h, provider, language=language, temperature=temperature, secret=secret
        )


def _handover(
    run: RecordedRun,
    start_h: float,
    provider: Completer | None,
    *,
    language: str,
    temperature: float,
    secret: str | None,
) -> dict[str, Any]:
    end_h = start_h + SHIFT_H
    if provider is None or provider.mocked:
        provider = ScriptedHandover(language)
    lang = LANGUAGES.get(language, "English")
    registry = FactRegistry()
    registry.add_text(f"{start_h} {end_h} {SHIFT_H} {CHUNK_H}")
    bundle: dict[str, Any] = {"calls": 0, "models": [], "chunk_notes": [], "errors": []}
    started = time.perf_counter()
    t_start = deadline.now()

    def complete(messages: list[dict[str, str]]) -> LlmResult:
        """One model call, refused once the report's time budget is gone."""
        if bundle.get("timeout") or deadline.expired():
            bundle["timeout"] = True
            raise deadline.DeadlineExceeded("handover time budget used")
        try:
            return provider.complete(messages, lane=LANE, temperature=temperature)
        except deadline.DeadlineExceeded:
            bundle["timeout"] = True
            raise

    def ask(
        system: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Write all text in {lang}; keep JSON keys and ids as given.\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ]
        for _attempt in range(3):
            reply = complete(messages)
            bundle["calls"] += 1
            bundle["models"].append(reply.provider_model or f"unreported:{reply.model}")
            messages.append({"role": "assistant", "content": reply.content})
            try:
                return extract_json_object(reply.content), messages
            except (ValueError, json.JSONDecodeError):
                messages.append({"role": "user", "content": "Reply with one JSON object only."})
        return None, messages

    def chunk_step(index: int) -> Any:
        a = start_h + index * CHUNK_H
        b = a + CHUNK_H

        def step(carry: dict[str, Any]) -> dict[str, Any]:
            facts = chunk_facts(run, a, b)
            registry.add(facts)
            reply, _messages = ask(CHUNK_SYSTEM, {"CHECKPOINT": carry, "FACTS": facts})
            if reply is None:
                raise ValueError("chunk reply was not JSON")
            notes = [str(note) for note in (reply.get("notes") or [])][:3]
            bundle["chunk_notes"].append({"window_h": [a, b], "notes": notes})
            resolved = {str(item) for item in reply.get("resolved") or []}
            issues = [
                str(item) for item in carry.get("open_issues") or [] if str(item) not in resolved
            ]
            issues += [
                str(item) for item in reply.get("open_issues") or [] if str(item) not in issues
            ]
            entities = dict(carry.get("entities") or {})
            entities["tools_down"] = {
                row["tool"]: row["to_h"] for row in facts["tools_down"] if row["to_h"] > b
            }
            entities["wip_bubbles"] = {row["family"]: row["wip_to"] for row in facts["wip_bubbles"]}
            entities["overrides"] = int(entities.get("overrides", 0)) + len(facts["overrides"])
            return {
                "decisions": [
                    *list(carry.get("decisions") or []),
                    f"{a}-{b} h: " + " / ".join(notes),
                ],
                "entities": entities,
                "open_issues": issues[-8:],
                "state": {"chunk": index + 1, "shift_h": [start_h, end_h]},
            }

        return step

    def compose(carry: dict[str, Any]) -> dict[str, Any]:
        end = end_facts(run, start_h, end_h)
        registry.add(end)
        report, messages = ask(COMPOSE_SYSTEM, {"CHECKPOINT": carry, "END_FACTS": end})
        bundle["end"] = end
        fixes = 0
        while report is not None:
            errors = _validate(report)
            misses = [] if errors else check(report_text(report), registry)
            if not errors and (not misses or bundle.get("repaired")):
                bundle["fact_misses"] = misses
                break
            if errors and fixes >= 2:
                report = None
                break
            if errors:
                fixes += 1
                prompt = "Fix: " + "; ".join(errors)
            else:
                bundle["repaired"] = True
                prompt = (
                    "These numbers/names are not in CHECKPOINT or END_FACTS: "
                    + ", ".join(misses[:12])
                    + ". Rewrite the whole JSON using only those values."
                )
            messages.append({"role": "user", "content": prompt})
            reply = complete(messages)
            bundle["calls"] += 1
            bundle["models"].append(reply.provider_model or f"unreported:{reply.model}")
            messages.append({"role": "assistant", "content": reply.content})
            try:
                report = extract_json_object(reply.content)
            except (ValueError, json.JSONDecodeError):
                report = None
        if report is None:
            raise ValueError("no valid report")
        bundle["report"] = report
        return {**carry, "state": {**dict(carry.get("state") or {}), "composed": True}}

    steps = [chunk_step(index) for index in range(int(SHIFT_H / CHUNK_H))] + [compose]
    engine_used = "markovian"
    chunks: list[dict[str, Any]] = []
    checkpoint_units = replayed_units = 0
    try:
        engine = MarkovianEngine(secret or _signing_secret(), max_chunks=len(steps))
        result = engine.run_from_contract(handover_contract(secret or _signing_secret()), steps)
        chunks = [record.model_dump() for record in result.chunks]
        checkpoint_units, replayed_units = result.checkpoint_units, result.replayed_history_units
    except ContractError as exc:
        engine_used = "own_loop"
        bundle["errors"].append(f"markovian refused: {exc}")
        carry = compress({"decisions": [], "entities": {}, "open_issues": [], "state": {}})
        for index, step in enumerate(steps):
            try:
                carry = compress(step(compress(carry)))
                chunks.append({"index": index, "ok": True})
            except Exception as err:
                chunks.append({"index": index, "ok": False, "error": type(err).__name__})
    if "end" not in bundle:
        bundle["end"] = end_facts(run, start_h, end_h)
    report = bundle.get("report")
    must = must_mention(bundle["end"]) if "end" in bundle else []
    text = render_markdown(report, language, [start_h, end_h]) if report else ""
    named = [item for item in must if item.lower() in text.lower()]
    return {
        "seed": run.seed,
        "shift_h": [start_h, end_h],
        "language": language,
        "engine": engine_used,
        "chunks": chunks,
        "chunks_ok": sum(1 for row in chunks if row.get("ok")),
        "checkpoint_units": checkpoint_units,
        "replayed_history_units": replayed_units,
        "chunk_notes": bundle["chunk_notes"],
        "end_facts": bundle.get("end"),
        "report": report,
        "markdown": text,
        "fact_misses": bundle.get("fact_misses", []) if report else [],
        "fact_ok": bool(report) and not bundle.get("fact_misses"),
        "repaired": bool(bundle.get("repaired")),
        "must_mention": must,
        "must_named": named,
        "must_recall": round(len(named) / len(must), 3) if must else 1.0,
        "llm_calls": bundle["calls"],
        "response_models": bundle["models"],
        "provider": provider.name,
        "mocked": provider.mocked,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "elapsed_s": round(deadline.now() - t_start, 3),
        "timeout": bool(bundle.get("timeout")),
        "error": None
        if report
        else "timeout: handover time budget used"
        if bundle.get("timeout")
        else "no report (" + "; ".join(bundle["errors"] or ["compose failed"]) + ")",
        "advice_only": True,
    }
