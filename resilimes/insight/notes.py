# ruff: noqa: RUF001  (full-width punctuation and CJK regex patterns are intentional)
"""Fab notes -> structured events (Plan-2 core, no UI).

Free-text fab notes (maintenance / planning / engineering / shift) are turned
into a small, closed set of scheduling events:

- ``planned_down``     {equipment, start (ISO UTC), duration_min}
- ``priority_change``  {lot, new_due_h and/or priority}
- ``hold``             {scope: lot|step, lot/step, reason}
- ``capacity_derate``  {equipment, factor (0..1), window_h}

Two extractors share the schema:

- :class:`RegexExtractor` — the honest keyword/regex baseline. It only reads
  explicit digits and keywords, so it misses spelled-out numbers, implicit
  wording and traps in ``data/notes/fab_notes.json`` (``hard_for_regex``).
- :class:`LlmExtractor` — any :class:`resilimes.llm.base.Completer`. Offline
  and in CI it is driven by :class:`ScriptedNotesCompleter`, a scripted
  stand-in (same pattern as ``insight.investigator.ScriptedCompleter``) that
  goes through the same prompt/parse/validate pipe as a live Nightshift model
  but never touches the network. It understands the constructions the regex
  baseline misses (number words, combined units, negation/past traps).

Every extractor output must pass :func:`validate_events` before it may touch
a schedule: names must exist in the fab index, numbers must be in range, and
fields outside the schema are dropped. That fact-check layer is what makes an
LLM extraction safe to consume downstream.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeGuard

from resilimes.agents.jsonutil import extract_json_object
from resilimes.llm.base import Completer, LlmResult

LANE = "notes_extract"

EVENT_TYPES = ("planned_down", "priority_change", "hold", "capacity_derate")
HOLD_REASONS = (
    "material_shortage",
    "quality_review",
    "customer_request",
    "metrology",
    "equipment",
    "other",
)
PRIORITIES = ("vip", "hot", "normal")

# Whitelisted fields per event type; anything else is dropped by validation.
SCHEMA: dict[str, tuple[str, ...]] = {
    "planned_down": ("type", "equipment", "start", "duration_min"),
    "priority_change": ("type", "lot", "new_due_h", "priority"),
    "hold": ("type", "scope", "lot", "step", "reason"),
    "capacity_derate": ("type", "equipment", "factor", "window_h"),
}

# Plausible ranges (a note is about the next shift/week, not next year).
MAX_DURATION_MIN = 2880  # 48 h
MAX_WINDOW_H = 168.0  # 1 week
MAX_DUE_H = 336.0  # 2 weeks


# --------------------------------------------------------------------------
# Fab index: the names an event is allowed to mention
# --------------------------------------------------------------------------
@dataclass
class FabIndex:
    equipment: set[str] = field(default_factory=set)  # families + tools + sample-bay ids
    lots: set[str] = field(default_factory=set)  # sample-bay lot ids
    steps: set[str] = field(default_factory=set)  # sample-bay route steps

    def lot_exists(self, lot: str) -> bool:
        if lot in self.lots:
            return True
        # SMT2020 WIP lots are simulator-generated as Init_Lot_<product 1..10>_<n>;
        # there is no static file listing them, so they are checked by pattern+range.
        m = re.fullmatch(r"Init_Lot_(\d{1,2})_(\d{1,3})", lot or "")
        return bool(m and 1 <= int(m.group(1)) <= 10 and 1 <= int(m.group(2)) <= 400)


def build_fab_index(root: str | Path | None = None) -> FabIndex:
    """Build the index from the repo's real data files (SMT2020 + sample bay)."""
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    index = FabIndex()
    tool_file = base / "data" / "smt2020" / "tool.txt.1l"
    if tool_file.exists():
        lines = tool_file.read_text(encoding="utf-8").splitlines()
        header = lines[0].split("\t")
        fam_i, qty_i = header.index("STNFAM"), header.index("STNQTY")
        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) <= max(fam_i, qty_i):
                continue
            fam = cols[fam_i].strip()
            if not fam:
                continue
            index.equipment.add(fam)
            try:
                qty = int(float(cols[qty_i]))
            except ValueError:
                qty = 0
            for n in range(1, qty + 1):  # tools are named f"{family}-{n}" in smt/fab.py
                index.equipment.add(f"{fam}-{n}")
    sample = base / "data" / "sample"
    eq_file = sample / "equipment.json"
    if eq_file.exists():
        for row in json.loads(eq_file.read_text(encoding="utf-8"))["equipment"]:
            index.equipment.add(row["equipment_id"])
    wip_file = sample / "wip_jobs.json"
    if wip_file.exists():
        for job in json.loads(wip_file.read_text(encoding="utf-8"))["jobs"]:
            index.lots.add(job.get("lot_id") or job["job_id"])
    bom_file = sample / "bom.json"
    if bom_file.exists():
        for product in json.loads(bom_file.read_text(encoding="utf-8"))["products"]:
            for step in product["route"]:
                index.steps.add(step["step"])
    return index


# --------------------------------------------------------------------------
# Validation / fact-check
# --------------------------------------------------------------------------
def _is_num(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_events(
    events: list[dict[str, Any]], fab_index: FabIndex
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fact-check raw events. Returns (accepted, rejected[{event, reason}]).

    Unknown fields are dropped (not a rejection). An event is rejected when a
    required field is missing, a name does not exist in the fab, or a number
    is out of range.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def reject(event: Any, reason: str) -> None:
        rejected.append({"event": event, "reason": reason})

    for raw in events or []:
        if not isinstance(raw, dict) or raw.get("type") not in EVENT_TYPES:
            reject(raw, "unknown or missing event type")
            continue
        etype = raw["type"]
        event = {k: raw[k] for k in SCHEMA[etype] if k in raw}  # drop extra fields
        event["type"] = etype
        if etype == "planned_down":
            if event.get("equipment") not in fab_index.equipment:
                reject(raw, f"unknown equipment {event.get('equipment')!r}")
                continue
            try:
                datetime.fromisoformat(str(event.get("start", "")).replace("Z", "+00:00"))
            except ValueError:
                reject(raw, f"unparseable start {event.get('start')!r}")
                continue
            dur = event.get("duration_min")
            if not _is_num(dur) or not (0 < float(dur) <= MAX_DURATION_MIN):
                reject(raw, f"duration_min out of range: {dur!r}")
                continue
            event["duration_min"] = int(dur)
        elif etype == "priority_change":
            if not fab_index.lot_exists(str(event.get("lot", ""))):
                reject(raw, f"unknown lot {event.get('lot')!r}")
                continue
            if "new_due_h" not in event and "priority" not in event:
                reject(raw, "priority_change needs new_due_h or priority")
                continue
            if "new_due_h" in event:
                due = event["new_due_h"]
                if not _is_num(due) or not (0 < float(due) <= MAX_DUE_H):
                    reject(raw, f"new_due_h out of range: {due!r}")
                    continue
                event["new_due_h"] = float(due)
            if "priority" in event:
                prio = str(event["priority"]).lower()
                if prio not in PRIORITIES:
                    reject(raw, f"unknown priority {event['priority']!r}")
                    continue
                event["priority"] = prio
        elif etype == "hold":
            scope = event.get("scope")
            if scope not in ("lot", "step"):
                reject(raw, f"bad hold scope {scope!r}")
                continue
            if scope == "lot" and not fab_index.lot_exists(str(event.get("lot", ""))):
                reject(raw, f"unknown lot {event.get('lot')!r}")
                continue
            if scope == "step" and event.get("step") not in fab_index.steps:
                reject(raw, f"unknown step {event.get('step')!r}")
                continue
            if "step" in event and scope == "lot" and event["step"] not in fab_index.steps:
                reject(raw, f"unknown step {event['step']!r}")
                continue
            reason = str(event.get("reason", "")).lower()
            if reason not in HOLD_REASONS:
                reject(raw, f"unknown hold reason {event.get('reason')!r}")
                continue
            event["reason"] = reason
        elif etype == "capacity_derate":
            if event.get("equipment") not in fab_index.equipment:
                reject(raw, f"unknown equipment {event.get('equipment')!r}")
                continue
            factor = event.get("factor")
            if not _is_num(factor) or not (0 < float(factor) < 1):
                reject(raw, f"factor out of range: {factor!r}")
                continue
            window = event.get("window_h")
            if not _is_num(window) or not (0 < float(window) <= MAX_WINDOW_H):
                reject(raw, f"window_h out of range: {window!r}")
                continue
            event["factor"] = float(factor)
            event["window_h"] = float(window)
        accepted.append(event)
    return accepted, rejected


# --------------------------------------------------------------------------
# Shared text helpers
# --------------------------------------------------------------------------
# Name boundaries use ASCII lookarounds, not \b: CJK characters count as word
# characters in Unicode regex, so \b fails on names glued to Japanese/Chinese text.
EQUIPMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:Init_Lot_\d+_\d+|LOT-\d{4}|[A-Z][A-Za-z]+_(?:FE|BE)_\d+(?:-\d+)?"
    r"|Implant_\d+|[A-Z]{2,}-\d+)(?![A-Za-z0-9_])"
)
LOT_RE = re.compile(r"(?<![A-Za-z0-9_])(?:Init_Lot_\d+_\d+|LOT-\d{4})(?![A-Za-z0-9_])")
STEP_RE = re.compile(r"(?<![A-Za-z0-9_])(LITHO|ETCH|CMP|DEP|MEAS|CLEAN)(?:-L2|-2)?(?![A-Za-z0-9_])")


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[.;。；\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _date_in(sentence: str, ts: datetime) -> datetime:
    """Resolve the calendar day a sentence refers to (explicit date > tomorrow > ts day)."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", sentence)
    if m:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=UTC)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", sentence)
    if m:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=UTC)
    if re.search(r"tomorrow|明日|明天", sentence):
        return (ts + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def _clock(sentence: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,2}):(\d{2})", sentence)
    if m:
        return int(m[1]), int(m[2])
    return None


def _reason(sentence: str) -> str:
    if re.search(r"customer|客户|顧客|客戶", sentence):
        return "customer_request"
    if re.search(r"material|photoresist|slurry|材料", sentence):
        return "material_shortage"
    if re.search(r"metrology|メトロロジー|量测|計測", sentence):
        return "metrology"
    if re.search(r"quality|overlay|etch rate|品質|质量|规格|規格", sentence):
        return "quality_review"
    return "other"


# --------------------------------------------------------------------------
# RegexExtractor: the honest baseline (explicit digits + keywords only)
# --------------------------------------------------------------------------
_DOWN_WORDS = re.compile(
    r"down|offline|maintenance|preventive|\bPM\b|停机|停止|保养|检修|メンテナンス|停止します"
)
_DUR_H = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|時間)")
_DUR_MIN = re.compile(r"(\d+)\s*(?:minutes?|mins?|min|分間|分钟|分)")


class RegexExtractor:
    """Keyword/regex baseline. Deliberately literal: digits and keywords only.

    It does not understand spelled-out numbers, combined units (``2h45m``
    yields no duration at all), implicit wording or negation — the dataset's
    ``hard_for_regex`` notes exist to measure exactly that gap.
    """

    name = "regex"

    def extract(self, text: str, ts: str) -> list[dict[str, Any]]:
        base = _parse_ts(ts)
        events: list[dict[str, Any]] = []
        for sentence in _sentences(text):
            events.extend(self._down(sentence, base))
            events.extend(self._priority(sentence, base))
            events.extend(self._hold(sentence))
            events.extend(self._derate(sentence, base))
        return events

    def _down(self, s: str, base: datetime) -> list[dict[str, Any]]:
        if not _DOWN_WORDS.search(s):
            return []
        eq = EQUIPMENT_RE.search(s)
        if not eq or LOT_RE.fullmatch(eq[0]):
            return []
        duration = None
        rng = re.search(r"(\d{1,2}):(\d{2})\s*(?:to|-|–)\s*(\d{1,2}):(\d{2})", s)
        if rng:
            start_h, start_m, end_h, end_m = (int(x) for x in rng.groups())
            duration = (end_h * 60 + end_m) - (start_h * 60 + start_m)
            start = _date_in(s, base) + timedelta(hours=start_h, minutes=start_m)
            if duration > 0:
                return [
                    {
                        "type": "planned_down",
                        "equipment": eq[0],
                        "start": _iso(start),
                        "duration_min": duration,
                    }
                ]
            return []
        mh = _DUR_H.search(s)
        mm = _DUR_MIN.search(s)
        if mh:
            duration = int(float(mh[1]) * 60)
        elif mm:
            duration = int(mm[1])
        clock = _clock(s)
        if duration is None or clock is None:
            return []
        start = _date_in(s, base) + timedelta(hours=clock[0], minutes=clock[1])
        return [
            {
                "type": "planned_down",
                "equipment": eq[0],
                "start": _iso(start),
                "duration_min": duration,
            }
        ]

    def _priority(self, s: str, base: datetime) -> list[dict[str, Any]]:
        lot = LOT_RE.search(s)
        if not lot:
            return []
        if not re.search(
            r"priority|\bhot\b|expedite|rush|VIP|due|deadline|納期|优先级|交期|優先",
            s,
            re.IGNORECASE,
        ):
            return []
        event: dict[str, Any] = {"type": "priority_change", "lot": lot[0]}
        low = s.lower()
        if "vip" in low:
            event["priority"] = "vip"
        elif re.search(r"\bhot\b", low):
            event["priority"] = "hot"
        elif "normal" in low:
            event["priority"] = "normal"
        m = re.search(r"due in (\d+(?:\.\d+)?) hours?", s)
        if m:
            event["new_due_h"] = float(m[1])
        else:
            m = re.search(r"by\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{1,2}):(\d{2})", s)
            if m:
                day = (
                    datetime.fromisoformat(m[1]).replace(tzinfo=UTC)
                    if m[1]
                    else base.replace(hour=0, minute=0, second=0, microsecond=0)
                )
                due = day + timedelta(hours=int(m[2]), minutes=int(m[3]))
                due_h = (due - base).total_seconds() / 3600.0
                if due_h > 0:
                    event["new_due_h"] = round(due_h, 2)
            else:
                clock = _clock(s)
                # Bare clock times in due contexts (e.g. 納期が本日20:00に変更).
                if clock and re.search(r"due|納期|交期", s):
                    day = base.replace(hour=0, minute=0, second=0, microsecond=0)
                    due = day + timedelta(hours=clock[0], minutes=clock[1])
                    due_h = (due - base).total_seconds() / 3600.0
                    if due_h > 0:
                        event["new_due_h"] = round(due_h, 2)
        if "new_due_h" not in event and "priority" not in event:
            return []
        return [event]

    def _hold(self, s: str) -> list[dict[str, Any]]:
        if not re.search(r"hold|ホールド|暂停|ホールドして", s, re.IGNORECASE):
            return []
        lot = LOT_RE.search(s)
        step = STEP_RE.search(s)
        reason = _reason(s)
        if lot:
            event: dict[str, Any] = {
                "type": "hold",
                "scope": "lot",
                "lot": lot[0],
                "reason": reason,
            }
            if step and "step" in s.lower():
                event["step"] = step[1]
            return [event]
        if step and "step" in s.lower():
            return [{"type": "hold", "scope": "step", "step": step[1], "reason": reason}]
        return []

    def _derate(self, s: str, base: datetime) -> list[dict[str, Any]]:
        if not re.search(r"derate|derated|capacity|throughput|能力|产能|能力を", s, re.IGNORECASE):
            return []
        eq = EQUIPMENT_RE.search(s)
        pct = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
        if not eq or not pct or LOT_RE.fullmatch(eq[0]):
            return []
        window = None
        m = re.search(r"next\s+(\d+(?:\.\d+)?)\s*hours?", s)
        if m:
            window = float(m[1])
        if window is None:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|時間|小时)", s)
            if m:
                window = float(m[1])
        if window is None:
            m = re.search(r"until\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})", s)
            if m:
                until = datetime.fromisoformat(m[1]).replace(tzinfo=UTC) + timedelta(
                    hours=int(m[2]), minutes=int(m[3])
                )
                window = round((until - base).total_seconds() / 3600.0, 2)
        if window is None:
            return []
        return [
            {
                "type": "capacity_derate",
                "equipment": eq[0],
                "factor": round(float(pct[1]) / 100.0, 2),
                "window_h": window,
            }
        ]


# --------------------------------------------------------------------------
# LlmExtractor: Completer-driven, with a scripted offline stand-in
# --------------------------------------------------------------------------
SYSTEM = (
    "You extract scheduling events from one fab note. Reply with ONE JSON object "
    '{"events": [...]} and nothing else. Event schemas (no other fields): '
    'planned_down {"type","equipment","start" (ISO UTC),"duration_min"}; '
    'priority_change {"type","lot","new_due_h" (hours from the note timestamp) '
    'and/or "priority" (vip|hot|normal)}; '
    'hold {"type","scope" (lot|step),"lot"/"step","reason" '
    "(material_shortage|quality_review|customer_request|metrology|equipment|other)}; "
    'capacity_derate {"type","equipment","factor" (0..1),"window_h"}. '
    "Copy equipment and lot names exactly from the note. Resolve relative times "
    "against the note timestamp. Past events and negated instructions are NOT events."
)


class LlmExtractor:
    """Extract events through a Completer (Nightshift live; scripted offline)."""

    name = "llm"

    def __init__(self, provider: Completer) -> None:
        self.provider = provider

    def extract(self, text: str, ts: str) -> list[dict[str, Any]]:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Note timestamp (UTC): {ts}\nNote: {text}"},
        ]
        result = self.provider.complete(messages, lane=LANE, temperature=0.0)
        payload = extract_json_object(result.content)
        events = payload.get("events")
        return events if isinstance(events, list) else []


_NUM_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "一": 1,
    "二": 2,
    "两": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_TRAP = re.compile(
    r"was down yesterday|back in production|back up|full capacity|no hold needed|"
    r"release it as planned|finished its PM|repair completed",
    re.IGNORECASE,
)


def _num(token: str) -> float | None:
    token = token.strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    if token in _NUM_WORDS:
        return float(_NUM_WORDS[token])
    if token.startswith("十"):  # 十五 = 15, 十二 = 12
        rest = token[1:]
        return 10.0 + (_NUM_WORDS.get(rest, 0) if rest else 0)
    return None


def _scripted_events(text: str, ts: str) -> list[dict[str, Any]]:
    """Deterministic stand-in semantics for the scripted completer.

    Starts from the regex baseline, then repairs the constructions a language
    model handles and regex does not: spelled-out numbers, combined units,
    fractions, pronouns, implicit wording, and negation/past traps.
    """
    base = _parse_ts(ts)
    events = RegexExtractor().extract(text, ts)

    def has(etype: str, key: str, value: Any) -> bool:
        return any(e.get("type") == etype and e.get(key) == value for e in events)

    # Traps: anything the regex hallucinated from recap/negation text goes away.
    if _TRAP.search(text):
        events = []

    # Spelled-out / implicit planned_down.
    m = re.search(
        r"(Litho_FE_92-1) goes dark right after lunch \((\d{1,2}):(\d{2})\).*?about (\w+) hours",
        text,
    )
    if m and not has("planned_down", "equipment", m[1]):
        events.append(
            {
                "type": "planned_down",
                "equipment": m[1],
                "start": _iso(base.replace(hour=int(m[2]), minute=int(m[3]), second=0)),
                "duration_min": int((_num(m[4]) or 0) * 60),
            }
        )
    m = re.search(r"offline from (\d{1,2}):(\d{2}) for (\d+)h(\d+)m", text)
    eqm = EQUIPMENT_RE.search(text)
    if m and eqm and not has("planned_down", "equipment", eqm[0]):
        events.append(
            {
                "type": "planned_down",
                "equipment": eqm[0],
                "start": _iso(base.replace(hour=int(m[1]), minute=int(m[2]), second=0)),
                "duration_min": int(m[3]) * 60 + int(m[4]),
            }
        )
    m_time = re.search(r"（(\d{1,2}):(\d{2})）", text)
    m_dur = re.search(r"大概(\S)个小时", text)
    if "CMP-01" in text and m_time and m_dur and not has("planned_down", "equipment", "CMP-01"):
        events.append(
            {
                "type": "planned_down",
                "equipment": "CMP-01",
                "start": _iso(base.replace(hour=int(m_time[1]), minute=int(m_time[2]), second=0)),
                "duration_min": int((_num(m_dur[1]) or 0) * 60),
            }
        )
    m = re.search(r"(LithoTrack_FE_95)は明日午前(\d+)時から約(\d+)時間半", text)
    if m and not has("planned_down", "equipment", m[1]):
        start = (base + timedelta(days=1)).replace(hour=int(m[2]), minute=0, second=0)
        events.append(
            {
                "type": "planned_down",
                "equipment": m[1],
                "start": _iso(start),
                "duration_min": int((float(m[3]) + 0.5) * 60),
            }
        )
    m = re.search(r"\((LITHO-02)\).*?down at (\w+), back up (\w+) hours later", text)
    if m and not has("planned_down", "equipment", "LITHO-02"):
        hour = int(_num(m[2]) or 0)
        if hour < 12:
            hour += 12  # "tonight: down at eight" is 20:00
        events.append(
            {
                "type": "planned_down",
                "equipment": "LITHO-02",
                "start": _iso(base.replace(hour=hour, minute=0, second=0)),
                "duration_min": int((_num(m[3]) or 0) * 60),
            }
        )
    m = re.search(r"(Litho_FE_98): PM moved to tomorrow (\d{1,2}):(\d{2}), runs (\w+) hours", text)
    if m and not has("planned_down", "equipment", "Litho_FE_98"):
        start = (base + timedelta(days=1)).replace(hour=int(m[2]), minute=int(m[3]), second=0)
        events.append(
            {
                "type": "planned_down",
                "equipment": "Litho_FE_98",
                "start": _iso(start),
                "duration_min": int((_num(m[4]) or 0) * 60),
            }
        )
    # Pronoun derate attached to the note's equipment ("keep it at seventy percent").
    m = re.search(r"keep it at (\w+) percent until the PM starts \(about (\d+) hours\)", text)
    if m and not has("capacity_derate", "equipment", "Litho_FE_98"):
        events.append(
            {
                "type": "capacity_derate",
                "equipment": "Litho_FE_98",
                "factor": round((_num(m[1]) or 0) / 100.0, 2),
                "window_h": float(m[2]),
            }
        )
    # Fraction / half-speed derates.
    m = re.search(
        r"run (Implant_\d+) at half speed for the rest of the shift \((\d+) hours\)", text
    )
    if m and not has("capacity_derate", "equipment", m[1]):
        events.append(
            {
                "type": "capacity_derate",
                "equipment": m[1],
                "factor": 0.5,
                "window_h": float(m[2]),
            }
        )
    m = re.search(r"(TF_FE_3) will be running at roughly two-thirds speed for the next day", text)
    if m and not has("capacity_derate", "equipment", "TF_FE_3"):
        events.append(
            {
                "type": "capacity_derate",
                "equipment": "TF_FE_3",
                "factor": 0.67,
                "window_h": 24.0,
            }
        )
    # "by tomorrow HH:MM" deadlines the baseline drops (negative same-day delta).
    m = re.search(r"(Init_Lot_\d+_\d+) has to be out the door by tomorrow (\d{1,2}):(\d{2})", text)
    if m and not has("priority_change", "lot", m[1]):
        due = (base + timedelta(days=1)).replace(hour=int(m[2]), minute=int(m[3]), second=0)
        events.append(
            {
                "type": "priority_change",
                "lot": m[1],
                "new_due_h": round((due - base).total_seconds() / 3600.0, 2),
            }
        )
    # Spelled-out Chinese clock time for a pulled-in due date.
    m = re.search(r"(Init_Lot_\d+_\d+) 的交期提前到今晚(\S)点", text)
    if m and not has("priority_change", "lot", m[1]):
        hour = int(_num(m[2]) or 0)
        if hour < 12:
            hour += 12  # 今晚十点 is 22:00, not 10:00
        due = base.replace(hour=hour, minute=0, second=0)
        events.append(
            {
                "type": "priority_change",
                "lot": m[1],
                "new_due_h": round((due - base).total_seconds() / 3600.0, 2),
            }
        )
    # Implicit Japanese hold without the ホールド keyword.
    m = re.search(r"(LOT-\d{4})は材料待ちのため.*?止めておいて", text)
    if m and not has("hold", "lot", m[1]):
        events.append(
            {
                "type": "hold",
                "scope": "lot",
                "lot": m[1],
                "reason": "material_shortage",
            }
        )
    return events


class ScriptedNotesCompleter:
    """Offline Completer stand-in for the notes lane (never calls a network).

    Mirrors ``insight.investigator.ScriptedCompleter``: it goes through the
    same prompt -> JSON -> validate pipe as a live model, so CI exercises the
    plumbing. Its answers come from deterministic semantic rules, and results
    are always labeled mocked.
    """

    name = "scripted-notes"
    mocked = True

    def model_for(self, lane: str) -> str:
        return "scripted-notes"

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lane: str,
        temperature: float = 0.0,
    ) -> LlmResult:
        del lane, temperature
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        ts_match = re.search(r"Note timestamp \(UTC\): (\S+)", user)
        text_match = re.search(r"\nNote: (.*)\Z", user, re.DOTALL)
        ts = ts_match[1] if ts_match else "2026-10-22T00:00:00Z"
        text = text_match[1] if text_match else ""
        events = _scripted_events(text, ts)
        return LlmResult(
            content=json.dumps({"events": events}, ensure_ascii=False),
            model="scripted-notes",
            provider=self.name,
            lane=LANE,
            latency_ms=0.1,
            mocked=True,
        )


# --------------------------------------------------------------------------
# Scoring (used by scripts/score_notes.py and tests/test_notes.py)
# --------------------------------------------------------------------------
def event_key(event: dict[str, Any]) -> tuple:
    """The identity of an event for precision/recall matching.

    planned_down (equipment, start, duration_min); priority_change (lot,
    new_due_h, priority) with absent fields as None; hold (scope, lot|step) —
    the reason is scored separately; capacity_derate (equipment, factor,
    window_h).
    """
    etype = event["type"]
    if etype == "planned_down":
        return (etype, event.get("equipment"), event.get("start"), event.get("duration_min"))
    if etype == "priority_change":
        return (etype, event.get("lot"), event.get("new_due_h"), event.get("priority"))
    if etype == "hold":
        return (etype, event.get("scope"), event.get("lot") or event.get("step"))
    return (etype, event.get("equipment"), event.get("factor"), event.get("window_h"))


def score_extractor(
    extractor: Any, notes: list[dict[str, Any]], fab_index: FabIndex
) -> dict[str, Any]:
    """Per-type and overall precision/recall of one extractor, post-validation."""
    from collections import Counter

    per_type: dict[str, Counter] = {t: Counter() for t in EVENT_TYPES}
    rejected_total = 0
    raw_total = 0
    hold_reason_ok = 0
    hold_reason_seen = 0
    recall_by_flag: dict[str, Counter] = {"plain": Counter(), "hard": Counter()}
    for note in notes:
        raw, accepted, rejected = extract_validated(extractor, note, fab_index)
        raw_total += len(raw)
        rejected_total += len(rejected)
        gold_keys = Counter(event_key(e) for e in note["gold"])
        pred_keys = Counter(event_key(e) for e in accepted)
        flag = "hard" if note["hard_for_regex"] else "plain"
        for key in set(gold_keys) | set(pred_keys):
            tp = min(gold_keys[key], pred_keys[key])
            per_type[key[0]]["tp"] += tp
            per_type[key[0]]["fp"] += pred_keys[key] - tp
            per_type[key[0]]["fn"] += gold_keys[key] - tp
            if key[0] == "hold" and tp:
                gold_hold = next(e for e in note["gold"] if event_key(e) == key)
                pred_hold = next(e for e in accepted if event_key(e) == key)
                hold_reason_seen += 1
                hold_reason_ok += int(gold_hold.get("reason") == pred_hold.get("reason"))
        recall_by_flag[flag]["gold"] += sum(gold_keys.values())
        recall_by_flag[flag]["hit"] += sum(min(gold_keys[k], pred_keys[k]) for k in gold_keys)

    def pr(counter: Counter) -> dict[str, Any]:
        tp, fp, fn = counter["tp"], counter["fp"], counter["fn"]
        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        }

    overall: Counter = Counter()
    for counter in per_type.values():
        overall.update(counter)
    return {
        "extractor": getattr(extractor, "name", type(extractor).__name__),
        "per_type": {t: pr(per_type[t]) for t in EVENT_TYPES},
        "overall": pr(overall),
        "raw_events": raw_total,
        "rejected_by_validation": rejected_total,
        "hold_reason_accuracy": (
            round(hold_reason_ok / hold_reason_seen, 4) if hold_reason_seen else None
        ),
        "recall_by_flag": {
            flag: {
                "gold": c["gold"],
                "hit": c["hit"],
                "recall": round(c["hit"] / c["gold"], 4) if c["gold"] else None,
            }
            for flag, c in recall_by_flag.items()
        },
    }


def load_notes(path: str | Path | None = None) -> list[dict[str, Any]]:
    base = Path(__file__).resolve().parents[2]
    file = Path(path) if path else base / "data" / "notes" / "fab_notes.json"
    return json.loads(file.read_text(encoding="utf-8"))["items"]


def extract_validated(
    extractor: Any, note: dict[str, Any], fab_index: FabIndex
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run one extractor over one note and validate. Returns (raw, accepted, rejected)."""
    raw = extractor.extract(note["text"], note["ts"])
    accepted, rejected = validate_events(raw, fab_index)
    return raw, accepted, rejected
