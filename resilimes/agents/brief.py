"""Crisp, translated findings built only from schedule facts."""

from __future__ import annotations

from typing import Literal

from resilimes.domain.models import Critique, JobOutcome, KpiReport

Lang = Literal["en", "zh", "ja"]
LANGS: tuple[Lang, ...] = ("en", "zh", "ja")


def human_minutes(minutes: float, lang: Lang) -> str:
    """Compact duration. 840 minutes is 14 h. Two days and up is shown in days."""
    sign = "−" if minutes < 0 else ""
    total = round(abs(minutes))
    if total < 60:
        if lang == "en":
            return f"{sign}{total} min"
        if lang == "zh":
            return f"{sign}{total} 分钟"
        return f"{sign}{total}分"
    if total < 48 * 60:
        hours, mins = divmod(total, 60)
        if mins == 0:
            if lang == "en":
                return f"{sign}{hours} h"
            if lang == "zh":
                return f"{sign}{hours} 小时"
            return f"{sign}{hours}時間"
        if lang == "en":
            return f"{sign}{hours} h {mins} min"
        if lang == "zh":
            return f"{sign}{hours} 小时 {mins} 分"
        return f"{sign}{hours}時間{mins}分"
    days, rem = divmod(total, 1440)
    hours = round(rem / 60)
    if hours == 24:
        days += 1
        hours = 0
    if hours == 0:
        if lang == "en":
            return f"{sign}{days} d"
        if lang == "zh":
            return f"{sign}{days} 天"
        return f"{sign}{days}日"
    if lang == "en":
        return f"{sign}{days} d {hours} h"
    if lang == "zh":
        return f"{sign}{days} 天 {hours} 小时"
    return f"{sign}{days}日{hours}時間"


def schedule_brief(
    *,
    kind: str,
    outcomes: list[JobOutcome],
    before: KpiReport,
    after: KpiReport,
    rejected: Critique,
    verdict: str,
    bottleneck: str = "",
    focus_equipment: str = "",
    repair_min: int | None = None,
) -> dict[str, dict[str, object]]:
    constraint = rejected.violations[0].constraint if rejected.violations else ""
    moved = [
        row
        for row in outcomes
        if row.before_equipment
        and row.after_equipment
        and row.before_equipment != row.after_equipment
    ]
    step_moves = [
        row
        for row in outcomes
        if row.moved_from and row.moved_to and row.moved_from != row.moved_to
    ]
    held = [row for row in outcomes if row.job_id in after.unscheduled_lots]
    inserted = [
        row
        for row in outcomes
        if row.before_equipment is None
        and row.before_completion_min is None
        and row.after_equipment
    ]
    if kind == "scale":
        chosen = _scale(outcomes, before, after, verdict, constraint)
    elif kind == "qtime":
        chosen = _queue(held, before, after, verdict, constraint)
    elif kind == "rework":
        chosen = _rework(before, after, verdict, constraint)
    elif kind == "stockout" or (held and kind != "insert_lot"):
        chosen = _shortage(held, before, after, verdict, constraint)
    elif kind == "insert_lot" or inserted:
        lead = _inserted_lead(inserted, after)
        chosen = _rush(lead, before, after, verdict, constraint)
    elif step_moves or moved:
        pool = step_moves or moved
        if focus_equipment:
            named = [
                row
                for row in pool
                if row.moved_from == focus_equipment or row.before_equipment == focus_equipment
            ]
            if named:
                pool = named
        lead = min(pool, key=lambda row: row.after_tardiness_min - row.before_tardiness_min)
        chosen = _move(lead, before, after, verdict, constraint)
    elif focus_equipment:
        chosen = _named_down(focus_equipment, repair_min, before, after, verdict, constraint)
    else:
        chosen = _generic(before, after, verdict, constraint)
    return _pack(_with_bottleneck(chosen, bottleneck))


def refusal_brief(reason: str, *, approval: bool = False) -> dict[str, dict[str, object]]:
    if approval:
        copies = {
            "en": (
                "This stop needs an approval",
                [
                    "Scout signed a high-risk contract and did not run it.",
                    "No tool is stopped and no schedule is written.",
                    "Record an approval, then ask again.",
                ],
                "High-risk intents stay unsigned for execution until an approval is attached.",
            ),
            "zh": (
                "这个停机需要批准",
                [
                    "Scout 签了高风险合同，但没有执行。",
                    "没有设备被停下，也没有写入排程。",
                    "记下批准后再问一次。",
                ],
                "高风险意图在附上批准之前不会执行。",
            ),
            "ja": (
                "この停止には承認が要る",
                [
                    "Scout は高リスクの契約に署名し、実行はしていない。",
                    "装置は止まっておらず、日程も書いていない。",
                    "承認を記録してから、もう一度頼む。",
                ],
                "高リスクの意図は、承認が付くまで実行されない。",
            ),
        }
    else:
        copies = {
            "en": (
                "Scout refused this request",
                [
                    reason,
                    "No schedule was written.",
                    "The lot book is unchanged.",
                ],
                reason,
            ),
            "zh": (
                "Scout 拒绝了这个请求",
                [
                    reason,
                    "没有写入排程。",
                    "在制批次保持原样。",
                ],
                reason,
            ),
            "ja": (
                "Scout がこの依頼を拒否した",
                [
                    reason,
                    "日程は書いていない。",
                    "仕掛ロットはそのまま。",
                ],
                reason,
            ),
        }
    return {
        lang: {"headline": headline, "points": points, "detail": detail}
        for lang, (headline, points, detail) in copies.items()
    }


def status_brief(down: list[str], blocked: list[str]) -> dict[str, dict[str, object]]:
    down_text = ", ".join(down) if down else {"en": "none", "zh": "无", "ja": "なし"}
    blocked_text = ", ".join(blocked) if blocked else {"en": "none", "zh": "无", "ja": "なし"}

    def down_of(lang: Lang) -> str:
        return down_text if isinstance(down_text, str) else down_text[lang]

    def blocked_of(lang: Lang) -> str:
        return blocked_text if isinstance(blocked_text, str) else blocked_text[lang]

    return {
        "en": {
            "headline": "Line status, read only",
            "points": [
                f"Down or in maintenance: {down_of('en')}.",
                f"Blocked lots: {blocked_of('en')}.",
                "No schedule is committed from a status question.",
            ],
            "detail": (
                f"Tools down or in maintenance: {down_of('en')}. "
                f"Blocked lots: {blocked_of('en')}. "
                "Ask about a breakdown, a rush order, or a material shortage to reschedule."
            ),
        },
        "zh": {
            "headline": "产线状态，只读",
            "points": [
                f"宕机或保养：{down_of('zh')}。",
                f"被挡住的批次：{blocked_of('zh')}。",
                "状态询问不会提交排程。",
            ],
            "detail": (
                f"宕机或保养：{down_of('zh')}。"
                f"被挡住的批次：{blocked_of('zh')}。"
                "要重排，请说明故障、急单或物料短缺。"
            ),
        },
        "ja": {
            "headline": "ライン状態。読み取りのみ",
            "points": [
                f"停止または保全：{down_of('ja')}。",
                f"ブロック中のロット：{blocked_of('ja')}。",
                "状態の質問では日程を確定しない。",
            ],
            "detail": (
                f"停止または保全：{down_of('ja')}。"
                f"ブロック中のロット：{blocked_of('ja')}。"
                "再計画するなら、故障、特急、または材料不足を指定する。"
            ),
        },
    }


def _with_bottleneck(
    rows: dict[Lang, tuple[str, list[str], str]],
    bottleneck: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    if not bottleneck:
        return rows
    updated: dict[Lang, tuple[str, list[str], str]] = {}
    for lang, (headline, points, detail) in rows.items():
        clause = _bottleneck_clause(bottleneck, lang)
        copied = list(points)
        copied[-1] = f"{copied[-1]} {clause}"
        updated[lang] = (headline, copied, f"{detail} {clause}")
    return updated


def _bottleneck_clause(area: str, lang: Lang) -> str:
    if lang == "zh":
        return f"这一步保住了 {area} 这个瓶颈。"
    if lang == "ja":
        return f"この手はボトルネックの {area} を守る。"
    return f"This keeps the {area} bottleneck fed."


def _queue(
    held: list[JobOutcome],
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    job = held[0].job_id if held else "The lot"
    extra = len(held) > 1
    hold_en = (
        f"The book holds {len(held)} lots, including {job}." if extra else f"The book holds {job}."
    )
    hold_zh = f"账上暂扣 {len(held)} 个批次，包括 {job}。" if extra else f"账上暂扣 {job}。"
    hold_ja = (
        f"帳票は {len(held)} ロットを保留する。{job} を含む。"
        if extra
        else f"帳票は {job} を保留する。"
    )
    otd_b, otd_a = _pct(before, after)
    return {
        "en": (
            f"{job} misses the clean queue time",
            [
                "Clean finished before the clock. The next film had to start within 15 min.",
                f"{hold_en} On-time delivery {otd_b} → {otd_a}.",
                f"The verdict is {_verdict(verdict, 'en')}. {_refusal(constraint, 'en')}",
            ],
            (
                f"{job} is held because deposition would start after the clean queue time. "
                f"{_hold_clock(before, after, 'en')} {_refusal(constraint, 'en')}"
            ),
        ),
        "zh": (
            f"{job} 错过了清洗后的队列时间",
            [
                "清洗在时钟之前已经结束。下一道成膜必须在 15 分钟内开工。",
                f"{hold_zh}准时交付 {otd_b} → {otd_a}。",
                f"评审结果{_verdict(verdict, 'zh')}。{_refusal(constraint, 'zh')}",
            ],
            (
                f"{job} 被暂扣，因为成膜会在清洗后的队列时间之后才开工。"
                f"{_hold_clock(before, after, 'zh')}{_refusal(constraint, 'zh')}"
            ),
        ),
        "ja": (
            f"{job} は洗浄後の待ち時間を外した",
            [
                "洗浄は時計の前に終わっている。次の成膜は 15 分以内に始める。",
                f"{hold_ja}納期遵守 {otd_b} → {otd_a}。",
                f"批評は{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            (
                f"{job} は、成膜が洗浄後の待ち時間の後に始まるため保留。"
                f"{_hold_clock(before, after, 'ja')}{_refusal(constraint, 'ja')}"
            ),
        ),
    }


def _rework(
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    job = "LOT-1004"
    otd_b, otd_a = _pct(before, after)
    close_en = f"The critic {_verdict(verdict, 'en')} the book."
    close_zh = f"评审{_verdict(verdict, 'zh')}这版账。"
    close_ja = f"批評は計画を{_verdict(verdict, 'ja')}。"
    if constraint:
        close_en = f"{close_en} {_refusal(constraint, 'en')}"
        close_zh = f"{close_zh}{_refusal(constraint, 'zh')}"
        close_ja = f"{close_ja}{_refusal(constraint, 'ja')}"
    return {
        "en": (
            f"{job} re-measures after overlay",
            [
                "Overlay failed at metrology. Strip, re-expose, then one re-measure. The limit is 1.",
                f"The scanner and the measure tool take the extra pass. On-time delivery {otd_b} → {otd_a}.",
                close_en,
            ],
            (
                f"{job} strips, re-exposes, and measures once. "
                f"A second loop is not inserted. {close_en}"
            ),
        ),
        "zh": (
            f"{job} 套刻失败后复测",
            [
                "量测套刻失败。去胶，再曝光，再量一次。上限是 1。",
                f"光刻和量测多走一道。准时交付 {otd_b} → {otd_a}。",
                close_zh,
            ],
            f"{job} 去胶、再曝光并复测一次。不会插入第二次。{close_zh}",
        ),
        "ja": (
            f"{job} は重ね合わせのあと再測定",
            [
                "測定で重ね合わせ不良。剥離し、再露光し、一度だけ再測定。上限は 1。",
                f"リソと測定が一行程増える。納期遵守 {otd_b} → {otd_a}。",
                close_ja,
            ],
            f"{job} は剥離し、再露光し、一度測定する。二度目は入れない。{close_ja}",
        ),
    }


def _pack(
    rows: dict[Lang, tuple[str, list[str], str]],
) -> dict[str, dict[str, object]]:
    return {
        lang: {
            "headline": headline.strip(),
            "points": [point.strip() for point in points],
            "detail": detail.strip(),
        }
        for lang, (headline, points, detail) in rows.items()
    }


def _inserted_lead(inserted: list[JobOutcome], after: KpiReport) -> JobOutcome | None:
    late = [row for row in inserted if row.job_id in after.late_lots]
    if late:
        return late[0]
    return inserted[0] if inserted else None


def _pct(before: KpiReport, after: KpiReport) -> tuple[str, str]:
    return (f"{before.on_time_delivery_pct:.1f}%", f"{after.on_time_delivery_pct:.1f}%")


def _hold_clock(before: KpiReport, after: KpiReport, lang: Lang) -> str:
    """Say what the tardiness figure is when held lots have no finish time."""
    if after.unscheduled_lots and after.weighted_tardiness_min == before.weighted_tardiness_min:
        if lang == "zh":
            return "暂扣批次不假设完工时刻。"
        if lang == "ja":
            return "保留ロットに完了時刻は仮定しない。"
        return "Held lots are not given a finish time."
    if lang == "zh":
        return (
            f"加权拖期 {human_minutes(before.weighted_tardiness_min, 'zh')} → "
            f"{human_minutes(after.weighted_tardiness_min, 'zh')}。"
        )
    if lang == "ja":
        return (
            f"加重遅延 {human_minutes(before.weighted_tardiness_min, 'ja')} → "
            f"{human_minutes(after.weighted_tardiness_min, 'ja')}。"
        )
    return (
        f"Weighted tardiness {human_minutes(before.weighted_tardiness_min, 'en')} → "
        f"{human_minutes(after.weighted_tardiness_min, 'en')}."
    )


def _named_down(
    tool: str,
    repair_min: int | None,
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    span_en = human_minutes(repair_min, "en") if repair_min else ""
    span_zh = human_minutes(repair_min, "zh") if repair_min else ""
    span_ja = human_minutes(repair_min, "ja") if repair_min else ""
    otd_b, otd_a = _pct(before, after)
    title_en = f"{tool} is down for {span_en}" if span_en else f"{tool} is down"
    title_zh = f"{tool} 宕机 {span_zh}" if span_zh else f"{tool} 宕机"
    title_ja = f"{tool} は {span_ja}停止" if span_ja else f"{tool} は停止"
    return {
        "en": (
            title_en,
            [
                f"{tool} is the tool in the request.",
                f"On-time delivery {otd_b} → {otd_a}.",
                f"The critic {_verdict(verdict, 'en')} the schedule. {_refusal(constraint, 'en')}",
            ],
            f"{title_en}. {_refusal(constraint, 'en')}",
        ),
        "zh": (
            title_zh,
            [
                f"请求点名的是 {tool}。",
                f"准时交付 {otd_b} → {otd_a}。",
                f"评审{_verdict(verdict, 'zh')}这版排程。{_refusal(constraint, 'zh')}",
            ],
            f"{title_zh}。{_refusal(constraint, 'zh')}",
        ),
        "ja": (
            title_ja,
            [
                f"依頼が名指しした装置は {tool}。",
                f"納期遵守 {otd_b} → {otd_a}。",
                f"批評は日程を{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            f"{title_ja}。{_refusal(constraint, 'ja')}",
        ),
    }


def _refusal(constraint: str, lang: Lang) -> str:
    if not constraint:
        return ""
    table: dict[str, dict[Lang, str]] = {
        "equipment_status": {
            "en": "Starting the blocked lot on the down tool was refused.",
            "zh": "在宕机设备上开工被拒绝。",
            "ja": "停止中の装置で着手する案は拒否された。",
        },
        "preemption": {
            "en": "Pulling a running lot off its tool was refused.",
            "zh": "把正在加工的批次撤下设备被拒绝。",
            "ja": "加工中のロットを装置から外す案は拒否された。",
        },
        "material": {
            "en": "Starting lithography without the resist was refused.",
            "zh": "没有光刻胶就开工被拒绝。",
            "ja": "レジストなしで露光を始める案は拒否された。",
        },
        "qtime": {
            "en": "Starting CMP after the queue-time window was refused.",
            "zh": "超过队列时间再开始 CMP 被拒绝。",
            "ja": "待ち時間を過ぎて CMP を始める案は拒否された。",
        },
    }
    if constraint in table:
        return table[constraint][lang]
    if lang == "zh":
        return "一个更差的替代方案被拒绝。"
    if lang == "ja":
        return "より悪い代替案は拒否された。"
    return "A weaker alternative was refused."


def _verdict(verdict: str, lang: Lang) -> str:
    table: dict[str, dict[Lang, str]] = {
        "accept": {"en": "accepted", "zh": "接受", "ja": "受理"},
        "conditional": {"en": "conditional", "zh": "有条件", "ja": "条件付き"},
        "reject": {"en": "rejected", "zh": "拒绝", "ja": "却下"},
    }
    return table.get(verdict, table["accept"])[lang]


def _scale(
    outcomes: list[JobOutcome],
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    same = [
        row
        for row in outcomes
        if row.priority == 1
        and row.before_equipment
        and row.before_equipment == row.after_equipment
        and str(row.before_equipment).startswith("LITHO")
        and row.before_equipment != "LITHO-03"
    ]
    count = len(same)
    otd_b, otd_a = _pct(before, after)
    tardy_b = human_minutes(before.weighted_tardiness_min, "en")
    tardy_zh = human_minutes(before.weighted_tardiness_min, "zh")
    tardy_ja = human_minutes(before.weighted_tardiness_min, "ja")
    tardy_a = human_minutes(after.weighted_tardiness_min, "en")
    detail = (
        f"Verdict {verdict}. Refused alternative failed {constraint or 'no check'}. "
        f"Baseline is EDD dispatch. On-time delivery {otd_b} → {otd_a}. "
        f"Weighted tardiness {tardy_b} → {tardy_a}. "
        f"Lots at risk {before.lots_at_risk} → {after.lots_at_risk}."
    )
    return {
        "en": (
            "EDD dispatch already meets the dues",
            [
                (
                    f"LITHO-03 is down for 600 minutes. EDD dispatch puts {count} "
                    "priority-1 lots on up scanners, and priority recovery keeps them there."
                ),
                f"On-time delivery {otd_b} → {otd_a}. Lots at risk {before.lots_at_risk} → {after.lots_at_risk}.",
                f"Weighted tardiness {tardy_b} → {tardy_a}.",
            ],
            detail,
        ),
        "zh": (
            "EDD 派工已经满足交期",
            [
                f"LITHO-03 宕机 600 分钟。EDD 派工把 {count} 个优先 1 的批次放到可用光刻机，优先级恢复保持原机。",
                f"准时交付 {otd_b} → {otd_a}。风险批次 {before.lots_at_risk} → {after.lots_at_risk}。",
                f"加权拖期 {tardy_zh} → {human_minutes(after.weighted_tardiness_min, 'zh')}。",
            ],
            detail,
        ),
        "ja": (
            "EDD 差し立てで納期は守れている",
            [
                f"LITHO-03 は 600 分停止。EDD は優先 1 の {count} ロットを稼働中のスキャナーへ置き、優先度回復はそこを維持する。",
                f"納期遵守 {otd_b} → {otd_a}。リスクロット {before.lots_at_risk} → {after.lots_at_risk}。",
                f"加重遅延 {tardy_ja} → {human_minutes(after.weighted_tardiness_min, 'ja')}。",
            ],
            detail,
        ),
    }


def _move(
    lead: JobOutcome,
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    otd_b, otd_a = _pct(before, after)
    origin = lead.moved_from or lead.before_equipment or ""
    dest = lead.moved_to or lead.after_equipment or ""
    blocked = not lead.moved_from or lead.moved_from == lead.before_equipment
    step = lead.moved_step or ""
    if blocked:
        wait_en = f"{origin} stays down. {lead.job_id} was blocked on it."
        wait_zh = f"{origin} 仍然宕机。{lead.job_id} 原先被挡在上面。"
        wait_ja = f"{origin} は停止のまま。{lead.job_id} はそこに止まっていた。"
    else:
        wait_en = f"{origin} stays down. {lead.job_id} {step} was on it."
        wait_zh = f"{origin} 仍然宕机。{lead.job_id} 的 {step} 原先排在上面。"
        wait_ja = f"{origin} は停止のまま。{lead.job_id} の {step} はそこにあった。"
    return {
        "en": (
            f"{lead.job_id} leaves {origin}",
            [
                wait_en,
                (
                    f"It runs on {dest}. "
                    f"On-time delivery {otd_b} → {otd_a}. "
                    f"Weighted tardiness {human_minutes(before.weighted_tardiness_min, 'en')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'en')}."
                ),
                f"The critic {_verdict(verdict, 'en')} the schedule. {_refusal(constraint, 'en')}",
            ],
            (
                f"{lead.job_id} moves from {origin} to {dest}. "
                f"Completion {human_minutes(lead.before_completion_min or 0, 'en')} → "
                f"{human_minutes(lead.after_completion_min or 0, 'en')}. "
                f"Makespan {human_minutes(before.makespan_min, 'en')} → "
                f"{human_minutes(after.makespan_min, 'en')}. "
                f"{_refusal(constraint, 'en')}"
            ),
        ),
        "zh": (
            f"{lead.job_id} 离开 {origin}",
            [
                wait_zh,
                (
                    f"改到 {dest}。"
                    f"准时交付 {otd_b} → {otd_a}。"
                    f"加权拖期 {human_minutes(before.weighted_tardiness_min, 'zh')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'zh')}。"
                ),
                f"评审{_verdict(verdict, 'zh')}这版排程。{_refusal(constraint, 'zh')}",
            ],
            (
                f"{lead.job_id} 从 {origin} 改到 {dest}。"
                f"完工 {human_minutes(lead.before_completion_min or 0, 'zh')} → "
                f"{human_minutes(lead.after_completion_min or 0, 'zh')}。"
                f"总工期 {human_minutes(before.makespan_min, 'zh')} → "
                f"{human_minutes(after.makespan_min, 'zh')}。"
                f"{_refusal(constraint, 'zh')}"
            ),
        ),
        "ja": (
            f"{lead.job_id} が {origin} を離れる",
            [
                wait_ja,
                (
                    f"{dest} で流す。"
                    f"納期遵守 {otd_b} → {otd_a}。"
                    f"加重遅延 {human_minutes(before.weighted_tardiness_min, 'ja')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'ja')}。"
                ),
                f"批評は日程を{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            (
                f"{lead.job_id} は {origin} から {dest} へ移る。"
                f"完了 {human_minutes(lead.before_completion_min or 0, 'ja')} → "
                f"{human_minutes(lead.after_completion_min or 0, 'ja')}。"
                f"総所要 {human_minutes(before.makespan_min, 'ja')} → "
                f"{human_minutes(after.makespan_min, 'ja')}。"
                f"{_refusal(constraint, 'ja')}"
            ),
        ),
    }


def _rush(
    lead: JobOutcome | None,
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    otd_b, otd_a = _pct(before, after)
    job = lead.job_id if lead else "the rush lot"
    tool = lead.after_equipment if lead and lead.after_equipment else "the line"
    late = human_minutes(lead.after_tardiness_min, "en") if lead else "late"
    late_zh = human_minutes(lead.after_tardiness_min, "zh") if lead else "迟"
    late_ja = human_minutes(lead.after_tardiness_min, "ja") if lead else "遅れ"
    finish = human_minutes(lead.after_completion_min or 0, "en") if lead else ""
    finish_zh = human_minutes(lead.after_completion_min or 0, "zh") if lead else ""
    finish_ja = human_minutes(lead.after_completion_min or 0, "ja") if lead else ""
    delta = human_minutes(after.weighted_tardiness_min - before.weighted_tardiness_min, "en")
    delta_zh = human_minutes(after.weighted_tardiness_min - before.weighted_tardiness_min, "zh")
    delta_ja = human_minutes(after.weighted_tardiness_min - before.weighted_tardiness_min, "ja")
    return {
        "en": (
            f"{job} finishes {late} late",
            [
                f"{job} is due in 3 h and finishes at {finish} on {tool}.",
                f"On-time delivery {otd_b} → {otd_a}. Weighted tardiness rises by {delta}.",
                f"The critic {_verdict(verdict, 'en')} the book. {_refusal(constraint, 'en')}",
            ],
            (
                f"{job} enters on {tool} and finishes {late} after its due time. "
                f"Lots already running stay on their tools. {_refusal(constraint, 'en')}"
            ),
        ),
        "zh": (
            f"{job} 晚 {late_zh} 完工",
            [
                f"{job} 要求 3 小时内交货，在 {tool} 上 {finish_zh} 完工。",
                f"准时交付 {otd_b} → {otd_a}。加权拖期增加 {delta_zh}。",
                f"评审{_verdict(verdict, 'zh')}这版账。{_refusal(constraint, 'zh')}",
            ],
            (
                f"{job} 进入 {tool}，比交期晚 {late_zh}。"
                f"已经在加工的批次留在原设备。{_refusal(constraint, 'zh')}"
            ),
        ),
        "ja": (
            f"{job} は {late_ja}遅れで終わる",
            [
                f"{job} の納期は 3 時間後。{tool} で {finish_ja} に終わる。",
                f"納期遵守 {otd_b} → {otd_a}。加重遅延は {delta_ja} 増える。",
                f"批評は計画を{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            (
                f"{job} は {tool} に入り、納期より {late_ja}遅れて終わる。"
                f"加工中のロットは装置に残す。{_refusal(constraint, 'ja')}"
            ),
        ),
    }


def _shortage(
    held: list[JobOutcome],
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    names = ", ".join(row.job_id for row in held) or "lots"
    otd_b, otd_a = _pct(before, after)
    count = len(held)
    return {
        "en": (
            f"{count} lots wait on RESIST-UV" if count else "Resist is short",
            [
                f"On-hand is zero. Held: {names}.",
                (
                    f"On-time delivery {otd_b} → {otd_a}. "
                    "Blocked until RESIST-UV is replenished. No delivery time is assumed."
                ),
                f"The verdict is {_verdict(verdict, 'en')}. {_refusal(constraint, 'en')}",
            ],
            (
                f"RESIST-UV on hand is zero, so {names} stay unscheduled until it is replenished. "
                "No delivery time is assumed. "
                f"Lots that already consumed resist keep running. {_refusal(constraint, 'en')}"
            ),
        ),
        "zh": (
            f"{count} 个批次在等 RESIST-UV" if count else "光刻胶短缺",
            [
                f"库存为零。暂扣：{names}。",
                f"准时交付 {otd_b} → {otd_a}。在 RESIST-UV 补货之前一直挡住。不假设到货时间。",
                f"评审结果{_verdict(verdict, 'zh')}。{_refusal(constraint, 'zh')}",
            ],
            (
                f"RESIST-UV 库存为零，因此 {names} 在补货之前不能排产。不假设到货时间。"
                f"已经用过光刻胶的批次继续加工。{_refusal(constraint, 'zh')}"
            ),
        ),
        "ja": (
            f"{count} ロットが RESIST-UV 待ち" if count else "レジスト不足",
            [
                f"在庫はゼロ。保留：{names}。",
                f"納期遵守 {otd_b} → {otd_a}。RESIST-UV の補充までブロック。納入時刻は仮定しない。",
                f"批評は{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            (
                f"RESIST-UV の在庫はゼロなので、{names} は補充まで未計画のまま。納入時刻は仮定しない。"
                f"レジストを消費済みのロットは流し続ける。{_refusal(constraint, 'ja')}"
            ),
        ),
    }


def _generic(
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    otd_b, otd_a = _pct(before, after)
    return {
        "en": (
            "Schedule checked",
            [
                f"On-time delivery {otd_b} → {otd_a}.",
                (
                    f"Weighted tardiness {human_minutes(before.weighted_tardiness_min, 'en')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'en')}."
                ),
                f"The critic {_verdict(verdict, 'en')} it. {_refusal(constraint, 'en')}",
            ],
            _refusal(constraint, "en"),
        ),
        "zh": (
            "排程已核对",
            [
                f"准时交付 {otd_b} → {otd_a}。",
                (
                    f"加权拖期 {human_minutes(before.weighted_tardiness_min, 'zh')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'zh')}。"
                ),
                f"评审{_verdict(verdict, 'zh')}。{_refusal(constraint, 'zh')}",
            ],
            _refusal(constraint, "zh"),
        ),
        "ja": (
            "日程を照合した",
            [
                f"納期遵守 {otd_b} → {otd_a}。",
                (
                    f"加重遅延 {human_minutes(before.weighted_tardiness_min, 'ja')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'ja')}。"
                ),
                f"批評は{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            _refusal(constraint, "ja"),
        ),
    }
