"""Timeline book from one recorded SMT2020 run. Read-only."""

from __future__ import annotations

import threading

from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.replay import WAFERS_PER_LOT, BookSpec, Replay, get_replay, known_spec
from resilimes.timeline.model import Bar, Block, Book, LotInfo, Machine, worse_qtime

_LOCK = threading.Lock()
_CACHE: dict[str, Book] = {}


class BookSelectorError(ValueError):
    """A seed/horizon was combined with a book it does not refine."""


def load_smt_book(
    *, book: str = "base", seed: int | None = None, horizon_h: float | None = None
) -> Book:
    """The baseline book is the one the fab views already record. A seed or horizon asks for another.

    ``book`` and ``seed``/``horizon_h`` are two different selectors and are
    never silently combined: a seed or horizon refines only the ``base``
    book. An unknown book name raises ``KeyError`` on every path; a known
    book combined with a seed or horizon raises ``BookSelectorError``.
    """
    fab = load_fab()
    if seed is None and horizon_h is None:
        spec = known_spec(fab, book)
    else:
        if book != "base":
            known_spec(fab, book)  # KeyError for an unknown book, as on the baseline path
            raise BookSelectorError(
                f"seed/horizon do not apply to the book {book!r}; they refine only the 'base' book."
            )
        chosen_seed = 1 if seed is None else seed
        chosen_h = 48.0 if horizon_h is None else horizon_h
        spec = BookSpec(
            key=f"timeline-{chosen_seed}-{chosen_h:.9g}",
            seed=chosen_seed,
            horizon=chosen_h * 3600.0,
        )
    with _LOCK:
        cached = _CACHE.get(spec.key)
    if cached is not None:
        return cached
    replay = get_replay(spec)
    built = book_from_replay(replay)
    with _LOCK:
        _CACHE[spec.key] = built
    return built


def book_from_replay(replay: Replay) -> Book:
    fab = replay.fab
    late = [_is_late(replay, lot) for lot in range(len(fab.lot_id))]
    qtime = _qtime_index(replay)
    reworked = {(lot, step) for _moment, _tool, lot, step in replay.reworks}
    machines = [
        Machine(
            id=name,
            name=name,
            group=fab.families[fab.tool_family[index]].group,
            family=fab.families[fab.tool_family[index]].name,
        )
        for index, name in enumerate(fab.tool_name)
    ]
    lots = [
        LotInfo(
            id=fab.lot_id[lot],
            product=fab.lot_product[lot],
            priority=int(fab.lot_priority[lot]),
            due_min=replay.due[lot] / 60.0,
            late=late[lot],
            qty=WAFERS_PER_LOT,
        )
        for lot in range(len(fab.lot_id))
    ]
    bars: list[Bar] = []
    for piece in replay.pieces:
        if piece.end <= piece.start:
            continue
        family = fab.families[piece.family]
        primary = piece.lots[0]
        step = piece.steps[0]
        flag = ""
        any_late = False
        for lot, lot_step in zip(piece.lots, piece.steps, strict=False):
            flag = worse_qtime(flag, _qflag(qtime, lot, lot_step, piece.start))
            any_late = any_late or late[lot]
        others = tuple(fab.lot_id[lot] for lot in piece.lots[1:])
        recipe = _recipe(fab, primary, step, piece.recipe)
        start = piece.start / 60.0
        end = piece.end / 60.0
        bars.append(
            Bar(
                id=f"{fab.lot_id[primary]}|{step}|{start:.1f}|{fab.tool_name[piece.tool]}",
                lot=fab.lot_id[primary],
                product=fab.lot_product[primary],
                machine=fab.tool_name[piece.tool],
                group=family.group,
                step=family.name,
                recipe=recipe,
                start_min=start,
                end_min=end,
                setup_min=min(piece.setup, piece.end - piece.start) / 60.0,
                priority=int(fab.lot_priority[primary]),
                due_min=replay.due[primary] / 60.0,
                late=any_late,
                qtime=flag,
                rework=(primary, step) in reworked,
                pinned=False,
                qty=WAFERS_PER_LOT * len(piece.lots),
                also=others,
            )
        )
    blocks: list[Block] = []
    horizon = replay.horizon
    for tool, windows in enumerate(replay.downs):
        blocks.extend(_blocks(fab.tool_name[tool], "down", windows, horizon))
    for tool, windows in enumerate(replay.pm):
        blocks.extend(_blocks(fab.tool_name[tool], "pm", windows, horizon))
    return Book(
        source="smt2020",
        seed=replay.spec.seed,
        horizon_h=round(replay.horizon / 3600.0, 2),
        origin=fab.snapshot,
        horizon_min=max(replay.horizon / 60.0, 60.0),
        shift_min=8 * 60.0,
        machines=machines,
        lots=lots,
        bars=bars,
        blocks=blocks,
        skips=sum(len(rows) for rows in replay.skips),
        book=replay.spec.key,
    )


def _is_late(replay: Replay, lot: int) -> bool:
    finished = replay.finished[lot]
    due = replay.due[lot]
    if finished >= 0:
        return finished > due
    return due <= replay.horizon


def _qtime_index(replay: Replay) -> dict[tuple[int, int], tuple[str, float, float]]:
    found: dict[tuple[int, int], tuple[str, float, float]] = {}
    for window in replay.qwins:
        key = (window.lot, window.target)
        previous = found.get(key)
        if previous is not None and previous[0] == "violated":
            continue
        found[key] = (window.outcome, window.opened, window.deadline)
    return found


def _qflag(
    index: dict[tuple[int, int], tuple[str, float, float]], lot: int, step: int, start: float
) -> str:
    item = index.get((lot, step))
    if item is None:
        return ""
    outcome, opened, deadline = item
    if outcome == "violated" or start > deadline:
        return "breach"
    span = deadline - opened
    if span > 0 and start > opened + 0.8 * span:
        return "risk"
    return ""


def _recipe(fab: Fab, lot: int, step: int, recipe_id: int) -> str:
    if 0 <= recipe_id < len(fab.recipe_name) and fab.recipe_name[recipe_id]:
        return fab.recipe_name[recipe_id]
    route = fab.routes[fab.lot_route[lot]]
    if 0 <= step < len(route.recipe):
        index = route.recipe[step]
        if 0 <= index < len(fab.recipe_name):
            return fab.recipe_name[index]
    return ""


def _blocks(
    machine: str, kind: str, windows: list[tuple[float, float]], horizon: float
) -> list[Block]:
    blocks: list[Block] = []
    for start, end in windows:
        clipped_end = min(end, horizon)
        if clipped_end <= start:
            continue
        blocks.append(
            Block(
                machine=machine,
                kind=kind,
                start_min=max(0.0, start) / 60.0,
                end_min=clipped_end / 60.0,
            )
        )
    return blocks
