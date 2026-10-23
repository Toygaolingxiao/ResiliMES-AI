"""Crisp, translated findings built only from schedule facts."""

from __future__ import annotations

from typing import Literal

from resilimes.domain.models import Critique, JobOutcome, KpiReport

Lang = Literal["en", "zh", "ja"]
LANGS: tuple[Lang, ...] = ("en", "zh", "ja")


def human_minutes(minutes: float, lang: Lang) -> str:
    """Compact duration. 17280 minutes is 12 d; 840 minutes is 14 h."""
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
) -> dict[str, dict[str, object]]:
    constraint = rejected.violations[0].constraint if rejected.violations else ""
    moved = [
        row
        for row in outcomes
        if row.before_equipment
        and row.after_equipment
        and row.before_equipment != row.after_equipment
    ]
    held = [
        row for row in outcomes if row.after_completion_min is None and row.after_tardiness_min > 0
    ]
    inserted = [
        row
        for row in outcomes
        if row.before_equipment is None
        and row.before_completion_min is None
        and row.after_equipment
    ]
    if kind == "stockout" or (held and kind != "insert_lot"):
        return _pack(_shortage(held, before, after, verdict, constraint))
    if kind == "insert_lot" or inserted:
        lead = _inserted_lead(inserted, after)
        return _pack(_rush(lead, before, after, verdict, constraint))
    if moved:
        lead = min(moved, key=lambda row: row.after_tardiness_min - row.before_tardiness_min)
        return _pack(_move(lead, before, after, verdict, constraint))
    return _pack(_generic(before, after, verdict, constraint))


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


def _pack(
    rows: dict[Lang, tuple[str, list[str], str]],
) -> dict[str, dict[str, object]]:
    return {
        lang: {"headline": headline, "points": points, "detail": detail}
        for lang, (headline, points, detail) in rows.items()
    }


def _inserted_lead(inserted: list[JobOutcome], after: KpiReport) -> JobOutcome | None:
    late = [row for row in inserted if row.job_id in after.late_lots]
    if late:
        return late[0]
    return inserted[0] if inserted else None


def _pct(before: KpiReport, after: KpiReport) -> tuple[str, str]:
    return (f"{before.on_time_delivery_pct:.1f}%", f"{after.on_time_delivery_pct:.1f}%")


def _refusal(constraint: str, lang: Lang) -> str:
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


def _move(
    lead: JobOutcome,
    before: KpiReport,
    after: KpiReport,
    verdict: str,
    constraint: str,
) -> dict[Lang, tuple[str, list[str], str]]:
    otd_b, otd_a = _pct(before, after)
    return {
        "en": (
            f"{lead.job_id} leaves {lead.before_equipment}",
            [
                f"{lead.before_equipment} stays down. {lead.job_id} was blocked on it.",
                (
                    f"It runs on {lead.after_equipment}. "
                    f"On-time delivery {otd_b} → {otd_a}. "
                    f"Weighted tardiness {human_minutes(before.weighted_tardiness_min, 'en')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'en')}."
                ),
                f"The critic {_verdict(verdict, 'en')} the schedule. {_refusal(constraint, 'en')}",
            ],
            (
                f"{lead.job_id} moves from {lead.before_equipment} to {lead.after_equipment}. "
                f"Completion {human_minutes(lead.before_completion_min or 0, 'en')} → "
                f"{human_minutes(lead.after_completion_min or 0, 'en')}. "
                f"Makespan {human_minutes(before.makespan_min, 'en')} → "
                f"{human_minutes(after.makespan_min, 'en')}. "
                f"{_refusal(constraint, 'en')}"
            ),
        ),
        "zh": (
            f"{lead.job_id} 离开 {lead.before_equipment}",
            [
                f"{lead.before_equipment} 仍然宕机。{lead.job_id} 原先被挡在上面。",
                (
                    f"改到 {lead.after_equipment}。"
                    f"准时交付 {otd_b} → {otd_a}。"
                    f"加权拖期 {human_minutes(before.weighted_tardiness_min, 'zh')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'zh')}。"
                ),
                f"评审{_verdict(verdict, 'zh')}这版排程。{_refusal(constraint, 'zh')}",
            ],
            (
                f"{lead.job_id} 从 {lead.before_equipment} 改到 {lead.after_equipment}。"
                f"完工 {human_minutes(lead.before_completion_min or 0, 'zh')} → "
                f"{human_minutes(lead.after_completion_min or 0, 'zh')}。"
                f"总工期 {human_minutes(before.makespan_min, 'zh')} → "
                f"{human_minutes(after.makespan_min, 'zh')}。"
                f"{_refusal(constraint, 'zh')}"
            ),
        ),
        "ja": (
            f"{lead.job_id} が {lead.before_equipment} を離れる",
            [
                f"{lead.before_equipment} は停止のまま。{lead.job_id} はそこに止まっていた。",
                (
                    f"{lead.after_equipment} で流す。"
                    f"納期遵守 {otd_b} → {otd_a}。"
                    f"加重遅延 {human_minutes(before.weighted_tardiness_min, 'ja')} → "
                    f"{human_minutes(after.weighted_tardiness_min, 'ja')}。"
                ),
                f"批評は日程を{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            (
                f"{lead.job_id} は {lead.before_equipment} から {lead.after_equipment} へ移る。"
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
    tard = human_minutes(after.weighted_tardiness_min, "en")
    tard_zh = human_minutes(after.weighted_tardiness_min, "zh")
    tard_ja = human_minutes(after.weighted_tardiness_min, "ja")
    count = len(held)
    return {
        "en": (
            f"{count} lots wait on RESIST-UV" if count else "Resist is short",
            [
                f"On-hand is zero. Held: {names}.",
                f"On-time delivery {otd_b} → {otd_a}. Weighted tardiness rises to {tard}.",
                f"The verdict is {_verdict(verdict, 'en')}. {_refusal(constraint, 'en')}",
            ],
            (
                f"RESIST-UV on hand is zero, so {names} stay unscheduled. "
                f"Lots that already consumed resist keep running. {_refusal(constraint, 'en')}"
            ),
        ),
        "zh": (
            f"{count} 个批次在等 RESIST-UV" if count else "光刻胶短缺",
            [
                f"库存为零。暂扣：{names}。",
                f"准时交付 {otd_b} → {otd_a}。加权拖期升到 {tard_zh}。",
                f"评审结果{_verdict(verdict, 'zh')}。{_refusal(constraint, 'zh')}",
            ],
            (
                f"RESIST-UV 库存为零，因此 {names} 不能排产。"
                f"已经用过光刻胶的批次继续加工。{_refusal(constraint, 'zh')}"
            ),
        ),
        "ja": (
            f"{count} ロットが RESIST-UV 待ち" if count else "レジスト不足",
            [
                f"在庫はゼロ。保留：{names}。",
                f"納期遵守 {otd_b} → {otd_a}。加重遅延は {tard_ja} まで増える。",
                f"批評は{_verdict(verdict, 'ja')}。{_refusal(constraint, 'ja')}",
            ],
            (
                f"RESIST-UV の在庫はゼロなので、{names} は未計画のまま。"
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
