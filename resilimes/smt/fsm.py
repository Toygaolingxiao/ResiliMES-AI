"""State machines for the SMT2020 fab replay: lot, tool, Q-time window, batch.

Pure definitions only: state enums, en/zh/ja labels and colours, the legal
transition tables, and small helpers. Nothing here reads the simulator; the
replay derives each entity's state intervals from the recorded events and can
check every derived step with :func:`is_legal`.

Entities (design: ``FSM_DESIGN.md``, r1):

- Lot: five main states, exactly one at any time. ``ON_HOLD`` carries a
  :class:`HoldReason`. ``reserved`` and ``scheduled`` are overlay flags shown on
  top of the main state, never states of their own.
- Tool: seven states. When the raw signals overlap (a breakdown inside a PM
  window, a reservation on a tool that is running) :func:`resolve_tool_state`
  picks one by :data:`TOOL_PRECEDENCE`.
- Q-time window: ``OPEN`` then exactly one terminal outcome, the same names as
  the simulator's Q-time r2 buckets. While open, :func:`qtime_band` gives the
  live urgency band (safe, urgent, lost).
- Furnace batch: a lifecycle derived in the replay (the simulator forms
  batches on the fly and keeps no batch object).

Zero-length states are kept, not skipped: a lot that arrives and starts in the
same instant goes ``IN_TRANSPORT -> WAITING -> PROCESSING``, and a tool that
ends one piece and starts the next goes ``RUNNING -> IDLE -> SETUP``. Derivers
emit the instant state so every step stays in the tables.

Colours follow Schedule_Viewer where it has one (lot ``processing_by``,
``waiting_at_eqp``, ``transferring_by``, ``completed``, ``constrained``; tool
``pending_batch``; S_SCHED_FLAG ``F`` and ``Y``) and the current fab UI
otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

_K = TypeVar("_K", bound=StrEnum)
_V = TypeVar("_V")

LANGS = ("en", "zh", "ja")

# Mirrors resilimes.smt.fab.QTIME_URGENT_MARGIN_SEC (kept literal so this
# module stays import-free; a test checks the two agree).
QTIME_URGENT_MARGIN_SEC = 900.0


@dataclass(frozen=True)
class Label:
    """Display text in each language plus one colour."""

    en: str
    zh: str
    ja: str
    colour: str

    def text(self, lang: str = "en") -> str:
        if lang not in LANGS:
            raise ValueError(f"unknown language {lang!r}; expected one of {LANGS}")
        value: str = getattr(self, lang)
        return value


# --------------------------------------------------------------------- lot


class LotState(StrEnum):
    WAITING = "waiting"
    IN_TRANSPORT = "in_transport"
    PROCESSING = "processing"
    ON_HOLD = "on_hold"
    FINISHED = "finished"


class HoldReason(StrEnum):
    REWORK = "rework"  # breakdown interrupted the piece; redo the same step
    QTIME = "qtime"  # Q-time deadline passed and no re-clean is allowed
    ENGINEERING = "engineering"  # enum only, nothing raises it in r1


class LotFlag(StrEnum):
    RESERVED = "reserved"  # a tool is held idle for this lot
    SCHEDULED = "scheduled"  # the replay knows the lot's next start


LOT_LABELS: dict[LotState, Label] = {
    LotState.WAITING: Label("Waiting", "等待", "待ち", "#ffb74d"),
    LotState.IN_TRANSPORT: Label("In transport", "搬送中", "搬送中", "#42a5f5"),
    LotState.PROCESSING: Label("Processing", "加工中", "処理中", "#667eea"),
    LotState.ON_HOLD: Label("On hold", "暂扣", "保留", "#8080C0"),
    LotState.FINISHED: Label("Finished", "完工", "完了", "#4caf50"),
}

HOLD_LABELS: dict[HoldReason, Label] = {
    HoldReason.REWORK: Label(
        "Rework (breakdown)", "返工 (故障中断)", "再作業 (故障中断)", "#0e7490"
    ),
    HoldReason.QTIME: Label("Q-time hold", "Q-time 超时暂扣", "Qタイム超過保留", "#b42318"),
    HoldReason.ENGINEERING: Label("Engineering hold", "工程暂扣", "技術保留", "#8080C0"),
}

LOT_FLAG_LABELS: dict[LotFlag, Label] = {
    LotFlag.RESERVED: Label("Reserved", "已预约", "予約済", "#FF69B4"),
    LotFlag.SCHEDULED: Label("Scheduled", "已排程", "計画済", "#82C213"),
}

LOT_INITIAL: frozenset[LotState] = frozenset({LotState.WAITING})
LOT_TERMINAL: frozenset[LotState] = frozenset({LotState.FINISHED})

LOT_TRANSITIONS: dict[LotState, frozenset[LotState]] = {
    LotState.WAITING: frozenset(
        {
            LotState.PROCESSING,  # start
            LotState.ON_HOLD,  # Q-time hold at the deadline
            LotState.IN_TRANSPORT,  # re-clean: back to the Wet_Etch origin
        }
    ),
    LotState.PROCESSING: frozenset(
        {
            LotState.IN_TRANSPORT,  # end, next measured step elsewhere
            LotState.WAITING,  # end, no-transport ablation only
            LotState.FINISHED,  # end of the last step
            LotState.ON_HOLD,  # tool breakdown: rework
        }
    ),
    LotState.IN_TRANSPORT: frozenset(
        {
            LotState.WAITING,  # arrive
            LotState.ON_HOLD,  # arrive with a pending Q-time deadline
        }
    ),
    LotState.ON_HOLD: frozenset({LotState.WAITING}),  # hold over, same step
    LotState.FINISHED: frozenset(),
}

# Which hold reasons may be entered from which state.
HOLD_ENTRY: dict[LotState, frozenset[HoldReason]] = {
    LotState.PROCESSING: frozenset({HoldReason.REWORK}),
    LotState.WAITING: frozenset({HoldReason.QTIME, HoldReason.ENGINEERING}),
    LotState.IN_TRANSPORT: frozenset({HoldReason.QTIME}),
}


def legal_hold(from_state: LotState | str, reason: HoldReason | str) -> bool:
    """May a lot in ``from_state`` go on hold for ``reason``?"""
    try:
        state = LotState(from_state)
        why = HoldReason(reason)
    except ValueError:
        return False
    return why in HOLD_ENTRY.get(state, frozenset())


# -------------------------------------------------------------------- tool


class ToolState(StrEnum):
    IDLE = "idle"
    SETUP = "setup"
    RUNNING = "running"
    WAITING_BATCH = "waiting_batch"
    RESERVED = "reserved"
    DOWN = "down"
    PM = "pm"


# Highest first. SETUP is the first part of a piece, so it wins over RUNNING
# when a deriver raises both for the same instant.
TOOL_PRECEDENCE: tuple[ToolState, ...] = (
    ToolState.DOWN,
    ToolState.PM,
    ToolState.SETUP,
    ToolState.RUNNING,
    ToolState.RESERVED,
    ToolState.WAITING_BATCH,
    ToolState.IDLE,
)

TOOL_LABELS: dict[ToolState, Label] = {
    ToolState.IDLE: Label("Idle", "空闲", "待機", "#e0e0e0"),
    ToolState.SETUP: Label("Setup", "换型", "段取り", "#FFA400"),
    ToolState.RUNNING: Label("Running", "加工中", "稼働中", "#667eea"),
    ToolState.WAITING_BATCH: Label("Waiting for batch", "等待组批", "バッチ待ち", "#26a69a"),
    ToolState.RESERVED: Label("Reserved", "预留", "予約保持", "#FF69B4"),
    ToolState.DOWN: Label("Down", "宕机", "故障停止", "#d64545"),
    ToolState.PM: Label("PM", "保养", "PM", "#808080"),
}

# A tool may sit inside a breakdown or PM window at t=0.
TOOL_INITIAL: frozenset[ToolState] = frozenset({ToolState.IDLE, ToolState.DOWN, ToolState.PM})

TOOL_TRANSITIONS: dict[ToolState, frozenset[ToolState]] = {
    ToolState.IDLE: frozenset(
        {
            ToolState.SETUP,
            ToolState.RUNNING,
            ToolState.WAITING_BATCH,
            ToolState.RESERVED,
            ToolState.DOWN,
            ToolState.PM,
        }
    ),
    ToolState.SETUP: frozenset({ToolState.RUNNING, ToolState.DOWN}),
    # Never RUNNING -> PM: no piece may cross a PM start.
    ToolState.RUNNING: frozenset({ToolState.IDLE, ToolState.DOWN}),
    ToolState.WAITING_BATCH: frozenset(
        {ToolState.SETUP, ToolState.RUNNING, ToolState.IDLE, ToolState.DOWN, ToolState.PM}
    ),
    ToolState.RESERVED: frozenset(
        {ToolState.SETUP, ToolState.RUNNING, ToolState.IDLE, ToolState.DOWN, ToolState.PM}
    ),
    ToolState.DOWN: frozenset({ToolState.IDLE, ToolState.PM}),
    ToolState.PM: frozenset({ToolState.IDLE, ToolState.DOWN}),
}


def resolve_tool_state(flags: Iterable[ToolState | str]) -> ToolState:
    """One tool state from the raised signals, by :data:`TOOL_PRECEDENCE`.

    No signal means ``IDLE``. Unknown names raise ``ValueError``.
    """
    raised = {ToolState(flag) for flag in flags}
    for state in TOOL_PRECEDENCE:
        if state in raised:
            return state
    return ToolState.IDLE


# ----------------------------------------------------------- Q-time window


class QTimeState(StrEnum):
    OPEN = "open"
    MET = "met"
    LATE = "late"  # target step started after the deadline
    HELD = "held"  # Q-time hold, then started late
    RECLEANED = "recleaned"  # sent back through the Wet_Etch origin
    EXPIRED = "expired"  # deadline passed inside the horizon, still open
    SKIPPED = "skipped"  # target step unmeasured by sampling; not scored
    LIVE = "live"  # still open at the horizon, deadline after it; not scored


class QTimeBand(StrEnum):
    SAFE = "safe"
    URGENT = "urgent"
    LOST = "lost"


QTIME_LABELS: dict[QTimeState, Label] = {
    QTimeState.OPEN: Label("Open", "计时中", "計時中", "#42a5f5"),
    QTimeState.MET: Label("Met", "达成", "遵守", "#4caf50"),
    QTimeState.LATE: Label("Started late", "超时开工", "遅延着工", "#ef5350"),
    QTimeState.HELD: Label("Held", "超时暂扣", "超過保留", "#8080C0"),
    QTimeState.RECLEANED: Label("Re-cleaned", "已重洗", "再洗浄", "#0e7490"),
    QTimeState.EXPIRED: Label("Expired", "超时未开工", "期限切れ", "#b42318"),
    QTimeState.SKIPPED: Label("Skipped", "已跳过", "スキップ", "#D3D3D3"),
    QTimeState.LIVE: Label("Live at horizon", "视野末仍计时", "期間末計時中", "#b0bec5"),
}

QTIME_BAND_LABELS: dict[QTimeBand, Label] = {
    QTimeBand.SAFE: Label("Safe", "安全", "余裕", "#4caf50"),
    QTimeBand.URGENT: Label("Urgent", "紧急", "緊急", "#FFA400"),
    QTimeBand.LOST: Label("Cannot be met", "已来不及", "間に合わない", "#b42318"),
}

QTIME_INITIAL: frozenset[QTimeState] = frozenset({QTimeState.OPEN})
QTIME_TERMINAL: frozenset[QTimeState] = frozenset(set(QTimeState) - {QTimeState.OPEN})
# Same split as the simulator's Q-time r2 buckets.
QTIME_MISSED: frozenset[QTimeState] = frozenset(
    {QTimeState.LATE, QTimeState.HELD, QTimeState.RECLEANED, QTimeState.EXPIRED}
)
QTIME_SCORED: frozenset[QTimeState] = QTIME_MISSED | {QTimeState.MET}

QTIME_TRANSITIONS: dict[QTimeState, frozenset[QTimeState]] = {
    QTimeState.OPEN: QTIME_TERMINAL,
    **{state: frozenset() for state in QTIME_TERMINAL},
}


def qtime_band(remaining: float, need: float, margin: float = QTIME_URGENT_MARGIN_SEC) -> QTimeBand:
    """Live band of an open window.

    ``remaining`` is seconds to the deadline, ``need`` the seconds the lot still
    needs to reach the target step. ``LOST`` when ``remaining < need``,
    ``URGENT`` when ``need <= remaining <= need + margin``, else ``SAFE``.
    """
    if remaining < need:
        return QTimeBand.LOST
    if remaining <= need + margin:
        return QTimeBand.URGENT
    return QTimeBand.SAFE


# ------------------------------------------------------------------- batch


class BatchState(StrEnum):
    FORMING = "forming"  # same-recipe wafers below BATCHMN
    READY = "ready"  # enough wafers, no free furnace
    RUNNING = "running"
    DONE = "done"
    INTERRUPTED = "interrupted"  # furnace breakdown; every member to rework


BATCH_LABELS: dict[BatchState, Label] = {
    BatchState.FORMING: Label("Forming", "组批中", "編成中", "#26a69a"),
    BatchState.READY: Label("Waiting for furnace", "待炉", "空き炉待ち", "#ffb74d"),
    BatchState.RUNNING: Label("Running", "运行中", "処理中", "#667eea"),
    BatchState.DONE: Label("Done", "完成", "完了", "#4caf50"),
    BatchState.INTERRUPTED: Label("Interrupted", "中断", "中断", "#d64545"),
}

BATCH_INITIAL: frozenset[BatchState] = frozenset({BatchState.FORMING})
BATCH_TERMINAL: frozenset[BatchState] = frozenset({BatchState.DONE, BatchState.INTERRUPTED})

BATCH_TRANSITIONS: dict[BatchState, frozenset[BatchState]] = {
    # FORMING -> RUNNING: an under-minimum start with a logged wait-rule reason.
    BatchState.FORMING: frozenset({BatchState.READY, BatchState.RUNNING}),
    # READY -> FORMING: a sibling furnace took part of the pool.
    BatchState.READY: frozenset({BatchState.RUNNING, BatchState.FORMING}),
    BatchState.RUNNING: frozenset({BatchState.DONE, BatchState.INTERRUPTED}),
    BatchState.DONE: frozenset(),
    BatchState.INTERRUPTED: frozenset(),
}


# ----------------------------------------------------------------- lookups

ENTITIES: dict[str, type[StrEnum]] = {
    "lot": LotState,
    "tool": ToolState,
    "qtime": QTimeState,
    "batch": BatchState,
}


def _by_value(table: Mapping[_K, _V]) -> dict[str, _V]:
    return {str(key): value for key, value in table.items()}


_TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {
    "lot": _by_value(LOT_TRANSITIONS),
    "tool": _by_value(TOOL_TRANSITIONS),
    "qtime": _by_value(QTIME_TRANSITIONS),
    "batch": _by_value(BATCH_TRANSITIONS),
}

_INITIAL: dict[str, frozenset[str]] = {
    "lot": LOT_INITIAL,
    "tool": TOOL_INITIAL,
    "qtime": QTIME_INITIAL,
    "batch": BATCH_INITIAL,
}

# Keyed by kind name, not by member: StrEnum members of different enums with
# the same value ("running", "reserved") compare and hash equal.
_LABELS: dict[str, dict[str, Label]] = {
    "lot": _by_value(LOT_LABELS),
    "hold": _by_value(HOLD_LABELS),
    "lot_flag": _by_value(LOT_FLAG_LABELS),
    "tool": _by_value(TOOL_LABELS),
    "qtime": _by_value(QTIME_LABELS),
    "qtime_band": _by_value(QTIME_BAND_LABELS),
    "batch": _by_value(BATCH_LABELS),
}

KINDS: tuple[str, ...] = tuple(_LABELS)


def _entity(entity: str) -> str:
    if entity not in _TRANSITIONS:
        raise ValueError(f"unknown entity {entity!r}; expected one of {tuple(ENTITIES)}")
    return entity


def is_legal(entity: str, from_state: str | None, to_state: str) -> bool:
    """Is ``from_state -> to_state`` a legal step for ``entity``?

    ``entity`` is ``lot``, ``tool``, ``qtime`` or ``batch``. ``from_state=None``
    asks whether ``to_state`` is a legal first state. Self-loops are not
    transitions and return False. Unknown state names return False; an
    unknown entity raises ``ValueError``.
    """
    table = _TRANSITIONS[_entity(entity)]
    if from_state is None:
        return to_state in _INITIAL[entity]
    return to_state in table.get(from_state, frozenset())


def successors(entity: str, state: str) -> frozenset[str]:
    """Legal next states of ``state`` (empty for terminal or unknown)."""
    return _TRANSITIONS[_entity(entity)].get(state, frozenset())


def label(kind: str, state: str, lang: str = "en") -> str:
    """Display text for ``state`` of ``kind`` (see :data:`KINDS`)."""
    return _spec(kind, state).text(lang)


def colour(kind: str, state: str) -> str:
    """Hex colour for ``state`` of ``kind``."""
    return _spec(kind, state).colour


def _spec(kind: str, state: str) -> Label:
    if kind not in _LABELS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
    try:
        return _LABELS[kind][str(state)]
    except KeyError:
        raise ValueError(f"unknown {kind} state {state!r}") from None


def palette(kind: str, lang: str = "en") -> list[dict[str, str]]:
    """``[{key, label, colour}]`` in declaration order, for an API meta block."""
    if kind not in _LABELS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
    return [
        {"key": str(key), "label": spec.text(lang), "colour": spec.colour}
        for key, spec in _LABELS[kind].items()
    ]


# Keys the r0 replay and fab UI use today, for the wiring step.
LEGACY_LOT: dict[str, LotState] = {
    "wait": LotState.WAITING,
    "run": LotState.PROCESSING,
    "hold": LotState.ON_HOLD,
    "done": LotState.FINISHED,
}
LEGACY_TOOL: dict[str, ToolState] = {
    "idle": ToolState.IDLE,
    "setup": ToolState.SETUP,
    "run": ToolState.RUNNING,
    "batch_wait": ToolState.WAITING_BATCH,
    "down": ToolState.DOWN,
    "pm": ToolState.PM,
}
