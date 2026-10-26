"""Notes-rooted hard cases: the root cause is stated in fab-notes text only.

Companion to :mod:`resilimes.insight.hard_cases`. Each case here is a single
injected fault (ground truth by construction, same injector machinery), chosen
so the anomaly indicators do NOT convict it: at generation time the rule
baseline's top-1 must miss the truth. The only channel that names the cause is
a set of fab notes attached to the case, in the exact item format of
``data/notes/fab_notes.json`` (feat/fab-notes branch: id / ts / source / lang /
hard_for_regex / text / gold). The case does not depend on that file's path;
the items are embedded in the case JSON.

The notes are presented to the investigator inside the question text (the
fact-check registry includes the question, so equipment names and times from
the notes are citable). The anomaly-only scripted stand-in cannot read them,
so offline it fails these cases like the baseline; :func:`notes_hint` is a
small disclosed keyword extractor (Plan-2 arm-B style script extraction) that
scores what the text channel alone can answer, and a live model gets the same
text in its prompt.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

from resilimes.evidence.toolkit import Fab, RecordedRun, Toolkit
from resilimes.insight.hard_cases import FaultSpec, HardCase, _spec, build_multi_injection
from resilimes.insight.hard_cases import case_signals as _signals
from resilimes.insight.injector import _symptom, candidates, faulted_run, main_upstream
from resilimes.insight.investigator import anomaly_scores, baseline_rank

SCENARIO_DAY = "2026-10-22"  # same scenario day as data/notes/fab_notes.json
NEXT_DAY = "2026-10-23"


def _iso(hour: float, day: str = SCENARIO_DAY) -> str:
    hh = int(hour)
    mm = round((hour - hh) * 60)
    if mm == 60:
        hh, mm = hh + 1, 0
    return f"{day}T{hh:02d}:{mm:02d}:00Z"


def _hhmm(hour: float) -> str:
    hh = int(hour)
    mm = round((hour - hh) * 60)
    if mm == 60:
        hh, mm = hh + 1, 0
    return f"{hh:02d}:{mm:02d}"


@dataclass
class NotesCase(HardCase):
    """A hard case whose root cause is only stated in the attached notes."""

    notes_items: list[dict[str, Any]] = field(default_factory=list)
    baseline_pred: list[str] = field(default_factory=list)  # baseline top-2 at generation

    @property
    def question(self) -> str:
        base = super().question
        if not self.notes_items:
            return base
        lines = [f"- [{item['ts']}] ({item['source']}) {item['text']}" for item in self.notes_items]
        return (
            base + "\n\nFab notes from this shift (text only; the monitoring tools do not "
            "see them):\n" + "\n".join(lines)
        )


@dataclass
class NotesTemplate:
    name: str
    seed: int
    spec: FaultSpec
    lang: str  # language of the gold note


NOTES_TEMPLATES: list[NotesTemplate] = [
    NotesTemplate("notes-down-masked-s1", 1, _spec("tool_down", "primary", tool_frac=0.15), "en"),
    NotesTemplate("notes-pm-masked-s2", 2, _spec("pm_in_peak", "primary", tool_frac=0.25), "en"),
    NotesTemplate(
        "notes-burst-masked-s1",
        1,
        _spec("release_burst", "primary", release_frac=0.3),
        "zh",
    ),
    NotesTemplate(
        "notes-batch-invisible-s2",
        2,
        _spec("batch_cap", "primary", batch_cap_wafers=10),
        "en",
    ),
    NotesTemplate(
        "notes-starve-masked-s1", 1, _spec("upstream_starvation", "primary", tool_frac=0.25), "ja"
    ),
]


# ---- the text channel: a disclosed keyword extractor --------------------------------
_PM_WORDS = ("preventive maintenance", " pm", "定期", "メンテナンス", "保養", "保养")
_BATCH_WORDS = ("batch", "derate", "capped", "批次", "單批", "单批", "上限")
_RELEASE_WORDS = ("放行", "released", "release all", "held lots")
_DOWN_WORDS = (
    "fault",
    "down",
    "failed",
    "failure",
    "breakdown",
    "故障",
    "停機",
    "停机",
    "停止",
    "ダウン",
)
_LOT_ID = re.compile(r"Init_(?:Hot)?Lot_\d+_\d+")  # both lot-id forms in the fab data


def _has(text: str, words: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(word in low or word in text for word in words)


def notes_hint(items: list[dict[str, Any]], family: str, upstream: str | None) -> str | None:
    """Cause named by the notes text for this family, or None when ambiguous.

    Text-only (never reads the gold annotations): a note counts when it names
    a tool of this family (``<family>-<n>``), a tool of the upstream family, or
    held lots being released. Keyword sets are fixed up front; when the notes
    point at more than one distinct cause the extractor abstains.
    """
    hints: list[str] = []
    for item in items:
        text = str(item.get("text", ""))
        if _has(text, _RELEASE_WORDS) and _LOT_ID.search(text):
            hints.append("release_burst")
            continue
        if family and f"{family}-" in text:
            target = "self"
        elif upstream and f"{upstream}-" in text:
            target = "upstream"
        else:
            continue
        if _has(text, _PM_WORDS):
            hints.append("pm_in_peak" if target == "self" else "upstream_starvation")
        elif _has(text, _BATCH_WORDS):
            if target == "self":
                hints.append("batch_cap")
        elif _has(text, _DOWN_WORDS):
            hints.append("tool_down" if target == "self" else "upstream_starvation")
    unique = set(hints)
    return hints[0] if len(unique) == 1 else None


# ---- note construction ---------------------------------------------------------------
def _item(
    note_id: str,
    ts_h: float,
    source: str,
    lang: str,
    text: str,
    gold: list[dict[str, Any]],
    day: str = SCENARIO_DAY,
) -> dict[str, Any]:
    return {
        "id": note_id,
        "ts": _iso(ts_h, day),
        "source": source,
        "lang": lang,
        "hard_for_regex": False,
        "text": text,
        "gold": gold,
    }


def _gold_note(
    template: NotesTemplate,
    part: dict[str, Any],
    fab: Fab,
    fam: int,
    kit: Toolkit,
) -> dict[str, Any]:
    cause = template.spec.cause
    window = part.get("window_h") or [template.spec.t0_h, template.spec.t0_h + template.spec.dur_h]
    start_h, end_h = (float(window[0]), float(window[1]))
    dur_h = end_h - start_h
    if cause == "tool_down":
        equip = str(part["tools_down"][0])
        text = (
            f"{equip} fault: vacuum pump failure. The tool is down from "
            f"{_hhmm(start_h)} today; expected repair time {dur_h:g} h. "
            "Lots are being rerouted where possible."
        )
        gold = [
            {
                "type": "planned_down",
                "equipment": equip,
                "start": _iso(start_h),
                "duration_min": int(dur_h * 60),
            }
        ]
        return _item("g1", start_h - 0.5, "maintenance", template.lang, text, gold)
    if cause == "pm_in_peak":
        equip = str(part["tools_pm"][0])
        text = (
            f"PM notice: {equip} will be down for preventive maintenance on "
            f"{SCENARIO_DAY} from {_hhmm(start_h)} to {_hhmm(end_h)} "
            "(brought forward from next week after a leak check)."
        )
        gold = [
            {
                "type": "planned_down",
                "equipment": equip,
                "start": _iso(start_h),
                "duration_min": int(dur_h * 60),
            }
        ]
        return _item("g1", start_h - 1.0, "maintenance", template.lang, text, gold)
    if cause == "release_burst":
        held = _held_lots(fab, fam)
        lot = fab.lot_id[held[0]] if held else "Init_Lot_0_0"
        text = (
            f"客户催单：{lot} 等被 hold 的批次已全部提前放行，"  # noqa: RUF001
            f"{_hhmm(start_h)} 起陆续进站，请相关站点留意在制品上升。"  # noqa: RUF001
        )
        gold = [{"type": "priority_change", "lot": lot, "priority": "hot"}]
        return _item("g1", start_h - 0.5, "planning", template.lang, text, gold)
    if cause == "batch_cap":
        cap = int(part["batch_cap_wafers"])
        equip = fab.tool_name[sorted(kit.tl.family_tools(fam))[0]]
        text = (
            f"Contamination control: {fab.families[fam].name} batch size is capped "
            f"at {cap} wafers per run from {_hhmm(start_h)} until further notice "
            f"({equip} line). Starts will run with partial batches meanwhile."
        )
        gold = [
            {
                "type": "capacity_derate",
                "equipment": equip,
                "factor": round(cap / 25, 2),
                "window_h": dur_h,
            }
        ]
        return _item("g1", start_h - 0.5, "engineering", template.lang, text, gold)
    if cause == "upstream_starvation":
        up = main_upstream(kit, fam)
        tools = sorted(kit.tl.family_tools(up))
        equip = fab.tool_name[tools[0]]
        text = (
            f"{equip}は本日{_hhmm(start_h)}から{dur_h:g}時間、真空ポンプ故障のため"
            "停止します。下流への供給が減少する見込みです。"
        )
        gold = [
            {
                "type": "planned_down",
                "equipment": equip,
                "start": _iso(start_h),
                "duration_min": int(dur_h * 60),
            }
        ]
        return _item("g1", start_h - 0.5, "shift", template.lang, text, gold)
    raise ValueError(f"no gold note template for {cause!r}")


def _held_lots(fab: Fab, fam: int) -> list[int]:
    out = []
    for lot in range(len(fab.lot_id)):
        route = fab.routes[fab.lot_route[lot]]
        step = fab.lot_step[lot]
        if fam in route.family[step : step + 2]:
            out.append(lot)
    return out


def _distractors(fab: Fab, kit: Toolkit, skip: set[int]) -> list[dict[str, Any]]:
    others = [i for i in range(len(fab.families)) if i not in skip]
    first, second = others[0], others[1]
    tool_a = fab.tool_name[sorted(kit.tl.family_tools(first))[0]]
    tool_b = fab.tool_name[sorted(kit.tl.family_tools(second))[0]]
    lot = fab.lot_id[0]
    return [
        _item(
            "d1",
            5.0,
            "maintenance",
            "en",
            f"PM notice: {tool_a} will be down for preventive maintenance tomorrow "
            f"({NEXT_DAY}) from 08:00 to 12:00.",
            [
                {
                    "type": "planned_down",
                    "equipment": tool_a,
                    "start": f"{NEXT_DAY}T08:00:00Z",
                    "duration_min": 240,
                }
            ],
        ),
        _item(
            "d2",
            5.5,
            "planning",
            "en",
            f"Customer escalation: {lot} is now a hot lot, effective immediately.",
            [{"type": "priority_change", "lot": lot, "priority": "hot"}],
        ),
        _item(
            "d3",
            4.0,
            "shift",
            "en",
            f"Recap: yesterday's {tool_b} alarm was cleared within the hour; "
            "all tools are back to normal.",
            [],
        ),
    ]


def make_notes_case(
    fab: Fab, template: NotesTemplate, base_run: RecordedRun, *, max_tries: int = 12
) -> NotesCase | None:
    """Build one notes case; None when no family passes the gates.

    Gates: the injected fault's symptom is visible, and the rule baseline's
    top-1 on the faulted run misses the truth (the indicators must not convict
    it -- the notes text is the only channel that names the cause).
    """
    spec = template.spec
    cause = spec.cause
    base = Toolkit(base_run)
    rng = random.Random(template.name)
    pool = candidates(cause, base, rng)

    def noise(fam: int) -> float:
        # Masking screen (base run only, no simulation): a family whose OTHER
        # indicators already swing naturally can hide a modest injected signal.
        scores = anomaly_scores(base, fab.families[fam].name, 6.0, 12.0)
        return max(score for name, score in scores.items() if name != cause)

    pool.sort(key=lambda fam: -noise(fam))
    for fam in pool[:max_tries]:
        injection = build_multi_injection([spec], base, fam)
        if injection is None:
            continue
        run = faulted_run(fab, template.seed, injection, label=template.name)
        kit = Toolkit(run)
        symptom = _symptom(cause, kit, base, fam, injection.t1_h, injection.t_end_h)
        if symptom is None:
            continue
        direction, t2_h, w1, w2, b2 = symptom
        rank = baseline_rank(kit, fab.families[fam].name, injection.t1_h, t2_h)
        if rank[0] == cause:
            continue  # the indicators convict it; not a notes case
        up = main_upstream(base, fam)
        part = dict(injection.describe["parts"][0])
        gold = _gold_note(template, part, fab, fam, base)
        items = [gold, *_distractors(fab, base, {fam, up})]
        rng.shuffle(items)
        for index, item in enumerate(items):
            item["id"] = f"n{index + 1:02d}"
        return NotesCase(
            case_id=template.name,
            category="notes",
            seed=template.seed,
            family=fab.families[fam].name,
            upstream=fab.families[up].name if up >= 0 else None,
            t1_h=injection.t1_h,
            t2_h=t2_h,
            direction=direction,
            wip_t1=w1,
            wip_t2=w2,
            base_wip_t2=b2,
            truths=[cause],
            decoy=None,
            specs=[vars(spec)],
            injection=injection.describe["parts"],
            signals=_signals(kit, fab.families[fam].name, injection.t1_h, t2_h),
            notes_items=items,
            baseline_pred=rank[:2],
        )
    return None
