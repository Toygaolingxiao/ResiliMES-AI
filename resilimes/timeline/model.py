"""Timeline contract ``timeline/v1``.

One book of machines, lots, and operations becomes a windowed payload.
The page draws it. Nothing here touches the scheduler.

Two windows: ``window`` is the fetched range (the page prefetches one span
on each side for panning); ``view`` is the display range the page shows.
``scope`` states how much of the display window the returned bars show;
stats are computed over the display window, never over the capped subset,
so the cards cannot silently shrink with the lot cap. ``daily`` is the
one exception: it counts the fetched window, as a navigation aid.
``skip_count`` is a whole-book replay count, not a window count at all.
``focus`` marks the focus drill-down cut: the focused lot's whole-book
bars, earliest first, cut at ``FOCUS_BAR_MAX``.
"""

from __future__ import annotations

import fnmatch
import itertools
from dataclasses import dataclass, field

CONTRACT = "timeline/v1"
# A gap this short is a move (SMT transport is 1 or 3 minutes). Longer is a queue.
TRANSPORT_MAX_MIN = 5.0
IDLE_MIN = 15.0
SHIFT_MIN = 8 * 60.0
DAY_MIN = 24 * 60.0
# Focus drill-down: a focused lot's whole-book bars, hard-cut here.
FOCUS_BAR_MAX = 400
_Q_RANK = {"": 0, "risk": 1, "breach": 2}


@dataclass
class Machine:
    id: str
    name: str
    group: str
    family: str


@dataclass
class LotInfo:
    id: str
    product: str
    priority: int
    due_min: float
    late: bool
    qty: int


@dataclass
class Bar:
    id: str
    lot: str
    product: str
    machine: str
    group: str
    step: str
    recipe: str
    start_min: float
    end_min: float
    setup_min: float
    priority: int
    due_min: float
    late: bool
    qtime: str
    rework: bool
    pinned: bool
    qty: int
    also: tuple[str, ...] = ()


@dataclass
class Block:
    machine: str
    kind: str
    start_min: float
    end_min: float


@dataclass
class Book:
    source: str
    seed: int
    horizon_h: float
    origin: str
    horizon_min: float
    shift_min: float
    machines: list[Machine]
    lots: list[LotInfo]
    bars: list[Bar]
    blocks: list[Block]
    skips: int = 0
    # Which recorded run this book is: the BookSpec key ("base", a
    # scenario name, "whatif-<digest>", "timeline-<seed>-<h>"), or
    # "sample". The payload carries it so a page can tell whether a
    # deep link would land on this run's evidence or another run's.
    book: str = "base"
    lot_index: dict[str, LotInfo] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.lot_index:
            self.lot_index = {item.id: item for item in self.lots}


@dataclass(frozen=True)
class TimelineQuery:
    t0: float | None = None
    t1: float | None = None
    # Display window, sent by the page as view_t0/view_t1. The page fetches
    # a wider window than it shows (one span of prefetch on each side, for
    # panning), so stats and scope are computed over the display window,
    # not the fetched one. Absent, the display window is the fetch window.
    view_t0: float | None = None
    view_t1: float | None = None
    product: str = ""
    lot: str = ""
    machine: str = ""
    group: str = ""
    step: str = ""
    priority: int | None = None
    q: str = ""
    focus: str = ""
    idle: bool = False
    limit: int = 8000
    lots: int = 100
    now_min: float = 0.0


def worse_qtime(left: str, right: str) -> str:
    return left if _Q_RANK.get(left, 0) >= _Q_RANK.get(right, 0) else right


def lot_state(bar: Bar, now_min: float) -> str:
    """Processing covers the clock. A pinned operation is reserved. The rest is the plan."""
    if bar.start_min <= now_min < bar.end_min:
        return "processing"
    if bar.pinned:
        return "reserved"
    return "scheduled"


def window_payload(book: Book, query: TimelineQuery) -> dict[str, object]:
    """Filter one book down to the bars, rows, and stat cards the page draws."""
    horizon = max(book.horizon_min, 60.0)
    t0 = 0.0 if query.t0 is None else min(max(0.0, query.t0), max(0.0, horizon - 1.0))
    t1 = min(horizon, t0 + 12 * 60.0) if query.t1 is None else min(horizon, query.t1)
    if t1 <= t0:
        t1 = min(horizon, t0 + 60.0)
    now = query.now_min
    narrowed = any((query.product, query.lot, query.machine, query.group, query.step, query.q))
    narrowed = narrowed or query.priority is not None

    def keep(bar: Bar) -> bool:
        if not _overlap(bar.start_min, bar.end_min, t0, t1):
            return False
        return _bar_match(bar, query)

    chosen = [bar for bar in book.bars if keep(bar)]
    # The window set, before any display cap: daily is computed over it
    # (a navigation aid across the loaded range). Stats and scope are
    # computed over the *display* window below, so the cards describe what
    # the page actually shows, not the wider prefetched fetch.
    window_bars = list(chosen)
    # Display window, clamped inside the fetch window. Absent, it is the
    # fetch window itself.
    v0 = t0 if query.view_t0 is None else min(max(query.view_t0, t0), t1)
    v1 = t1 if query.view_t1 is None else max(min(query.view_t1, t1), v0)
    view_bars = [bar for bar in window_bars if _overlap(bar.start_min, bar.end_min, v0, v1)]
    kept_lots = _cap_lots(chosen, query.lots, query.focus)
    if kept_lots is not None:
        chosen = [bar for bar in chosen if _members(bar) & kept_lots]
    chosen.sort(key=lambda bar: (bar.start_min, bar.machine, bar.lot))
    truncated = len(chosen) > query.limit
    if truncated:
        chosen = chosen[: query.limit]

    focus_all = [
        bar
        for bar in book.bars
        if query.focus and (bar.lot == query.focus or query.focus in bar.also)
    ]
    # Earliest first, so the cut keeps a defined prefix of the lot's
    # history instead of book order; the marker below names what was cut.
    focus_all.sort(key=lambda bar: (bar.start_min, bar.end_min, bar.machine, bar.id))
    focus_bars = focus_all[:FOCUS_BAR_MAX]
    gaps = _gaps(chosen, window_bars, t0, t1)
    # Bars actually drawn inside the display window: the fetched set,
    # capped, cut, and clipped to the view.
    shown_bars = [bar for bar in chosen if _overlap(bar.start_min, bar.end_min, v0, v1)]
    machines = _machines_for(book, chosen, query, narrowed, t0, t1)
    blocks = [
        block
        for block in book.blocks
        if block.machine in {item.id for item in machines}
        and _overlap(block.start_min, block.end_min, t0, t1)
    ]
    lot_ids = _lots_for(chosen, focus_bars)
    lots = [book.lot_index[lot_id] for lot_id in sorted(lot_ids) if lot_id in book.lot_index]
    return {
        "contract": CONTRACT,
        "source": book.source,
        "book": book.book,
        "seed": book.seed,
        "horizon_h": book.horizon_h,
        "origin": book.origin,
        "now_min": now,
        "horizon_min": horizon,
        "shift_min": book.shift_min or SHIFT_MIN,
        "window": {"t0": t0, "t1": t1},
        "view": {"t0": v0, "t1": v1},
        "truncated": truncated,
        # How much of the display window the returned bars show.
        # ``lots_total`` / ``bars_total`` / ``machines_total`` count the
        # display window before either cap; ``*_shown`` count the bars
        # actually drawn inside it. ``lots_capped`` is true when the lot
        # cap engaged on the fetch window (it can be true while the view
        # shows all its lots). Stats are computed over the display window,
        # so they agree with the ``*_total`` counts, not with the subset —
        # except ``skip_count``, which is a whole-book replay count (0
        # when the query is narrowed). ``daily`` stays fetch-window: it is
        # a navigation aid across the loaded range.
        "scope": {
            "lots_total": len({bar.lot for bar in view_bars}),
            "lots_shown": len({bar.lot for bar in shown_bars}),
            "lots_capped": kept_lots is not None,
            "bars_total": len(view_bars),
            "bars_shown": len(shown_bars),
            "machines_total": len({bar.machine for bar in view_bars}),
            "machines_shown": len({bar.machine for bar in shown_bars}),
        },
        "stats": _stats(view_bars, book, narrowed),
        "daily": _daily(window_bars, horizon),
        "facets": _facets(book),
        "machine_rows": machine_rows(machines),
        "product_rows": product_rows(lots),
        "bars": [_bar_json(bar, now) for bar in chosen],
        "gaps": gaps,
        "blocks": [
            {
                "machine": block.machine,
                "kind": block.kind,
                "start_min": block.start_min,
                "end_min": block.end_min,
            }
            for block in blocks
        ],
        "focus_bars": [_bar_json(bar, now) for bar in focus_bars],
        # The focus cut, marked: focus_bars bypass the window and the
        # filters, so without these counts the page would silently draw
        # a prefix of the lot's history. Always present, zero-valued
        # when no lot is focused.
        "focus": {
            "lot": query.focus,
            "bars_total": len(focus_all),
            "bars_shown": len(focus_bars),
            "bars_max": FOCUS_BAR_MAX,
            "truncated": len(focus_all) > FOCUS_BAR_MAX,
        },
        "idle_min": IDLE_MIN,
    }


def machine_rows(machines: list[Machine]) -> list[dict[str, object]]:
    """Group header, then one row per machine. Groups are sorted, tools are sorted."""
    by_group: dict[str, list[Machine]] = {}
    for machine in machines:
        by_group.setdefault(machine.group or "—", []).append(machine)
    rows: list[dict[str, object]] = []
    for group in sorted(by_group):
        members = sorted(by_group[group], key=lambda item: item.id)
        parent = f"g:{group}"
        rows.append({"kind": "group", "id": parent, "label": group, "count": len(members)})
        for machine in members:
            rows.append(
                {
                    "kind": "machine",
                    "id": machine.id,
                    "parent": parent,
                    "label": machine.name or machine.id,
                    "group": group,
                    "family": machine.family,
                }
            )
    return rows


def product_rows(lots: list[LotInfo]) -> list[dict[str, object]]:
    """Product header, then one sub-row per lot."""
    by_product: dict[str, list[LotInfo]] = {}
    for lot in lots:
        by_product.setdefault(lot.product or "—", []).append(lot)
    rows: list[dict[str, object]] = []
    for product in sorted(by_product):
        members = sorted(by_product[product], key=lambda item: item.id)
        parent = f"p:{product}"
        rows.append({"kind": "product", "id": parent, "label": product, "count": len(members)})
        for lot in members:
            rows.append(
                {
                    "kind": "lot",
                    "id": lot.id,
                    "parent": parent,
                    "label": lot.id,
                    "product": product,
                    "priority": lot.priority,
                    "due_min": lot.due_min,
                    "late": lot.late,
                }
            )
    return rows


def _stats(bars: list[Bar], book: Book, narrowed: bool) -> dict[str, object]:
    """Stats over the display-window bar set (before lot cap and bar limit).

    Each field counts what its card label says; the field names are
    historical (timeline/v1) and do not always match — the card labels
    in i18n.json name the measured unit:

    - ``total_jobs``: bars in the window. One bar is one lot's one step on
      one machine, i.e. an operation segment — not a job in the lot sense.
      The field name is historical (timeline/v1); the label reads Segments.
    - ``total_equipment``: distinct machines with at least one bar.
    - ``total_lots``: distinct ``bar.lot`` values with at least one bar.
      ``also`` members sharing a bar are not counted.
    - ``total_operations``: distinct ``bar.step`` values — step kinds, not
      step executions. The label reads Steps. Step values are assumed to
      be normalized family names; distinct strings count as distinct steps.
    - ``total_moves``: sum of ``bar.qty`` over the bars. ``qty`` is wafers
      (25 per lot per step in SMT2020; a batched bar carries 25 per lot in
      the batch), so this is wafer-steps, not moves and not distinct
      wafers: one lot is counted once per step it runs. A batched bar's
      ``qty`` includes the wafers of its ``also`` lots, which are not
      counted in Lots. The label reads Wafer-steps. The stats assume
      ``qty >= 0``; no validation is applied (real books carry 25
      wafers per lot per step).
    - ``skip_count``: whole-book replay skips (0 when narrowed); not a
      window stat.
    - ``late_lots`` / ``qtime_breach`` / ``qtime_risk``: distinct late lots
      and bars flagged breach/risk, over the same window bar set.
    """
    steps = {bar.step for bar in bars}
    return {
        "total_jobs": len(bars),
        "total_equipment": len({bar.machine for bar in bars}),
        "total_lots": len({bar.lot for bar in bars}),
        "total_operations": len(steps),
        "total_moves": int(sum(bar.qty for bar in bars)),
        "skip_count": 0 if narrowed else book.skips,
        "late_lots": len({bar.lot for bar in bars if bar.late}),
        "qtime_breach": sum(1 for bar in bars if bar.qtime == "breach"),
        "qtime_risk": sum(1 for bar in bars if bar.qtime == "risk"),
    }


def _daily(bars: list[Bar], horizon: float) -> list[dict[str, object]]:
    days = max(1, int((horizon + DAY_MIN - 1) // DAY_MIN))
    counts = [0] * days
    for bar in bars:
        index = int(bar.start_min // DAY_MIN)
        if 0 <= index < days:
            counts[index] += 1
    return [
        {"day": index, "start_min": index * DAY_MIN, "jobs": counts[index]}
        for index in range(days)
        if counts[index] or index == 0
    ]


def _facets(book: Book) -> dict[str, object]:
    products: dict[str, int] = {}
    for lot in book.lots:
        products[lot.product] = products.get(lot.product, 0) + 1
    return {
        "products": [{"id": product, "lots": products[product]} for product in sorted(products)],
        "groups": sorted({machine.group for machine in book.machines if machine.group}),
        "priorities": sorted({lot.priority for lot in book.lots}),
    }


def _machines_for(
    book: Book,
    bars: list[Bar],
    query: TimelineQuery,
    narrowed: bool,
    t0: float,
    t1: float,
) -> list[Machine]:
    used = {bar.machine for bar in bars}
    used.update(
        block.machine
        for block in book.blocks
        if _overlap(block.start_min, block.end_min, t0, t1)
        and _like(query.machine, block.machine)
        and _like(query.group, _group_of(book, block.machine))
    )
    if query.idle and not narrowed:
        return [
            machine
            for machine in book.machines
            if _like(query.machine, machine.id) and _like(query.group, machine.group)
        ]
    return [machine for machine in book.machines if machine.id in used]


def _group_of(book: Book, machine_id: str) -> str:
    for machine in book.machines:
        if machine.id == machine_id:
            return machine.group
    return ""


def _lots_for(bars: list[Bar], focus_bars: list[Bar]) -> set[str]:
    found: set[str] = set()
    for bar in (*bars, *focus_bars):
        found.add(bar.lot)
        found.update(bar.also)
    return found


def _cap_lots(bars: list[Bar], limit: int, focus: str) -> set[str] | None:
    if limit <= 0:
        return None
    score: dict[str, int] = {}
    for bar in bars:
        for lot in _members(bar):
            score[lot] = score.get(lot, 0) + 1
    if len(score) <= limit:
        return None
    ranked = sorted(score, key=lambda lot: (-score[lot], lot))
    kept = set(ranked[:limit])
    if focus:
        kept.add(focus)
    return kept


def _members(bar: Bar) -> set[str]:
    return {bar.lot, *bar.also}


def _gaps(bars: list[Bar], window_bars: list[Bar], t0: float, t1: float) -> list[dict[str, object]]:
    """Gaps between one lot's consecutive *displayed* bars.

    A gap is only reported when the lot's sequence is intact: if any bar
    involving the lot in the window was dropped by the lot cap or the bar
    limit — or is displayed under another lot's row as an also member —
    the "waiting" band would cover real processing time, so that gap is
    skipped instead of fabricated. ``window_bars`` is the pre-cap set.
    """
    by_lot: dict[str, list[Bar]] = {}
    for bar in bars:
        by_lot.setdefault(bar.lot, []).append(bar)
    window_by_lot: dict[str, list[Bar]] = {}
    for bar in window_bars:
        # Group by every lot the bar involves, not just its primary lot:
        # a batched bar processes its also lots too, so the guard must
        # see it when checking those lots' intervals.
        for lot in _members(bar):
            window_by_lot.setdefault(lot, []).append(bar)
    gaps: list[dict[str, object]] = []
    for lot, rows in by_lot.items():
        rows.sort(key=lambda bar: (bar.start_min, bar.end_min))
        for prev, nxt in itertools.pairwise(rows):
            if nxt.start_min <= prev.end_min:
                continue
            if not _overlap(prev.end_min, nxt.start_min, t0, t1):
                continue
            if _split_between(window_by_lot.get(lot, []), prev.end_min, nxt.start_min):
                continue
            gap = nxt.start_min - prev.end_min
            state = "transport" if gap <= TRANSPORT_MAX_MIN else "waiting"
            gaps.append(
                {
                    "id": f"gap:{lot}:{prev.end_min:.1f}",
                    "lot": lot,
                    "product": nxt.product,
                    "machine": nxt.machine,
                    "from_machine": prev.machine,
                    "group": nxt.group,
                    "step": nxt.step,
                    "recipe": "",
                    "start_min": prev.end_min,
                    "end_min": nxt.start_min,
                    "setup_min": 0.0,
                    "priority": nxt.priority,
                    "due_min": nxt.due_min,
                    "late": nxt.late,
                    "qtime": "",
                    "rework": False,
                    "state": state,
                    "extra": 0,
                    "qty": 0,
                    "gap": True,
                }
            )
    return gaps


def _split_between(window_rows: list[Bar], start: float, end: float) -> bool:
    """True when a window bar involving the lot overlaps (start, end).

    Such a bar was dropped from the displayed set by the lot cap or the
    bar limit, or is displayed under another lot's row as an also member,
    so the interval is not a real gap: the lot was processing.
    """
    return any(bar.start_min < end and bar.end_min > start for bar in window_rows)


def _bar_json(bar: Bar, now_min: float) -> dict[str, object]:
    body: dict[str, object] = {
        "id": bar.id,
        "lot": bar.lot,
        "product": bar.product,
        "machine": bar.machine,
        "group": bar.group,
        "step": bar.step,
        "recipe": bar.recipe,
        "start_min": bar.start_min,
        "end_min": bar.end_min,
        "setup_min": bar.setup_min,
        "priority": bar.priority,
        "due_min": bar.due_min,
        "late": bar.late,
        "qtime": bar.qtime,
        "rework": bar.rework,
        "state": lot_state(bar, now_min),
        "extra": len(bar.also),
        "qty": bar.qty,
    }
    if bar.also:
        body["also"] = list(bar.also)
    return body


def _bar_match(bar: Bar, query: TimelineQuery) -> bool:
    if query.priority is not None and bar.priority != query.priority:
        return False
    names = _members(bar)
    if query.lot and not any(_like(query.lot, name) for name in names):
        return False
    if not _like(query.product, bar.product):
        return False
    if not _like(query.machine, bar.machine):
        return False
    if not _like(query.group, bar.group):
        return False
    if not _like(query.step, bar.step):
        return False
    if not query.q:
        return True
    return any(
        _like(query.q, value)
        for value in (bar.lot, *bar.also, bar.product, bar.machine, bar.group, bar.step, bar.recipe)
    )


def _like(pattern: str, value: str) -> bool:
    if not pattern:
        return True
    pat = pattern.casefold()
    val = value.casefold()
    if "*" in pat or "?" in pat:
        return fnmatch.fnmatch(val, pat)
    return pat in val


def _overlap(start: float, end: float, t0: float, t1: float) -> bool:
    return end > t0 and start < t1
