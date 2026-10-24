"""State definitions, labels, colours and legal transitions (resilimes.smt.fsm)."""

from __future__ import annotations

import ast
import itertools
import re
from pathlib import Path

import pytest

from resilimes.smt import fsm
from resilimes.smt.fsm import (
    BatchState,
    HoldReason,
    LotFlag,
    LotState,
    QTimeBand,
    QTimeState,
    ToolState,
)

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ---------------------------------------------------------------- enums


def test_state_sets_match_the_design() -> None:
    assert [s.value for s in LotState] == [
        "waiting",
        "in_transport",
        "processing",
        "on_hold",
        "finished",
    ]
    assert {r.value for r in HoldReason} == {"rework", "qtime", "engineering"}
    assert {f.value for f in LotFlag} == {"reserved", "scheduled"}
    assert {s.value for s in ToolState} == {
        "idle",
        "setup",
        "running",
        "waiting_batch",
        "reserved",
        "down",
        "pm",
    }
    assert {s.value for s in QTimeState} == {
        "open",
        "met",
        "late",
        "held",
        "recleaned",
        "expired",
        "skipped",
        "live",
    }
    assert [b.value for b in QTimeBand] == ["safe", "urgent", "lost"]
    assert {s.value for s in BatchState} == {
        "forming",
        "ready",
        "running",
        "done",
        "interrupted",
    }


def test_overlay_flags_are_not_lot_states() -> None:
    lot_values = {s.value for s in LotState}
    assert not lot_values & {f.value for f in LotFlag}
    assert not lot_values & {r.value for r in HoldReason}


# --------------------------------------------------------- labels/colours


@pytest.mark.parametrize("kind", fsm.KINDS)
def test_every_state_has_three_languages_and_a_hex_colour(kind: str) -> None:
    enum = {
        "lot": LotState,
        "hold": HoldReason,
        "lot_flag": LotFlag,
        "tool": ToolState,
        "qtime": QTimeState,
        "qtime_band": QTimeBand,
        "batch": BatchState,
    }[kind]
    for state in enum:
        for lang in fsm.LANGS:
            assert fsm.label(kind, state, lang).strip()
        assert HEX.match(fsm.colour(kind, state)), (kind, state)
    assert [row["key"] for row in fsm.palette(kind)] == [s.value for s in enum]


@pytest.mark.parametrize(
    ("kind", "state", "en", "zh", "ja", "colour"),
    [
        ("lot", LotState.WAITING, "Waiting", "等待", "待ち", "#ffb74d"),
        ("lot", LotState.IN_TRANSPORT, "In transport", "搬送中", "搬送中", "#42a5f5"),
        ("lot", LotState.PROCESSING, "Processing", "加工中", "処理中", "#667eea"),
        ("lot", LotState.ON_HOLD, "On hold", "暂扣", "保留", "#8080C0"),
        ("lot", LotState.FINISHED, "Finished", "完工", "完了", "#4caf50"),
        ("hold", HoldReason.QTIME, "Q-time hold", "Q-time 超时暂扣", "Qタイム超過保留", "#b42318"),
        (
            "hold",
            HoldReason.REWORK,
            "Rework (breakdown)",
            "返工 (故障中断)",
            "再作業 (故障中断)",
            "#0e7490",
        ),
        ("lot_flag", LotFlag.RESERVED, "Reserved", "已预约", "予約済", "#FF69B4"),
        ("lot_flag", LotFlag.SCHEDULED, "Scheduled", "已排程", "計画済", "#82C213"),
        ("tool", ToolState.IDLE, "Idle", "空闲", "待機", "#e0e0e0"),
        ("tool", ToolState.SETUP, "Setup", "换型", "段取り", "#FFA400"),
        ("tool", ToolState.RUNNING, "Running", "加工中", "稼働中", "#667eea"),
        ("tool", ToolState.WAITING_BATCH, "Waiting for batch", "等待组批", "バッチ待ち", "#26a69a"),
        ("tool", ToolState.RESERVED, "Reserved", "预留", "予約保持", "#FF69B4"),
        ("tool", ToolState.DOWN, "Down", "宕机", "故障停止", "#d64545"),
        ("tool", ToolState.PM, "PM", "保养", "PM", "#808080"),
        ("qtime", QTimeState.MET, "Met", "达成", "遵守", "#4caf50"),
        ("qtime", QTimeState.EXPIRED, "Expired", "超时未开工", "期限切れ", "#b42318"),
        ("qtime", QTimeState.SKIPPED, "Skipped", "已跳过", "スキップ", "#D3D3D3"),
        ("batch", BatchState.FORMING, "Forming", "组批中", "編成中", "#26a69a"),
        ("batch", BatchState.READY, "Waiting for furnace", "待炉", "空き炉待ち", "#ffb74d"),
    ],
)
def test_labels_and_colours_from_the_design(
    kind: str, state: str, en: str, zh: str, ja: str, colour: str
) -> None:
    assert fsm.label(kind, state) == en
    assert fsm.label(kind, state, "zh") == zh
    assert fsm.label(kind, state, "ja") == ja
    assert fsm.colour(kind, state) == colour


def test_same_value_in_two_enums_keeps_its_own_label() -> None:
    # StrEnum members with equal values hash equal; lookups are per kind.
    assert ToolState.RUNNING == BatchState.RUNNING
    assert fsm.label("tool", ToolState.RUNNING, "zh") == "加工中"
    assert fsm.label("batch", BatchState.RUNNING, "zh") == "运行中"
    assert fsm.label("tool", "reserved", "ja") == "予約保持"
    assert fsm.label("lot_flag", "reserved", "ja") == "予約済"


def test_waiting_batch_no_longer_shares_the_lot_waiting_colour() -> None:
    assert fsm.colour("tool", ToolState.WAITING_BATCH) == "#26a69a"
    assert fsm.colour("tool", ToolState.WAITING_BATCH) != fsm.colour("lot", LotState.WAITING)


def test_lookup_errors() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        fsm.label("wafer", "waiting")
    with pytest.raises(ValueError, match="unknown lot state"):
        fsm.colour("lot", "scrapped")
    with pytest.raises(ValueError, match="unknown language"):
        fsm.label("lot", LotState.WAITING, "de")
    with pytest.raises(ValueError, match="unknown kind"):
        fsm.palette("wafer")


def test_palette_rows() -> None:
    rows = fsm.palette("tool", "zh")
    assert rows[0] == {"key": "idle", "label": "空闲", "colour": "#e0e0e0"}
    assert len(rows) == len(ToolState)


# ------------------------------------------------------------ lot table


LOT_LEGAL = {
    ("waiting", "processing"),
    ("waiting", "on_hold"),
    ("waiting", "in_transport"),
    ("processing", "in_transport"),
    ("processing", "waiting"),
    ("processing", "finished"),
    ("processing", "on_hold"),
    ("in_transport", "waiting"),
    ("in_transport", "on_hold"),
    ("on_hold", "waiting"),
}


def test_lot_table_is_exactly_the_design() -> None:
    pairs = {(a.value, b.value) for a in LotState for b in LotState if fsm.is_legal("lot", a, b)}
    assert pairs == LOT_LEGAL


def test_lot_life_from_snapshot_to_finish() -> None:
    path = [
        None,
        LotState.WAITING,
        LotState.PROCESSING,
        LotState.ON_HOLD,  # breakdown rework
        LotState.WAITING,
        LotState.PROCESSING,
        LotState.IN_TRANSPORT,
        LotState.ON_HOLD,  # arrives past its Q-time deadline
        LotState.WAITING,
        LotState.IN_TRANSPORT,  # re-clean back to Wet_Etch
        LotState.WAITING,
        LotState.PROCESSING,
        LotState.FINISHED,
    ]
    for before, after in itertools.pairwise(path):
        assert fsm.is_legal("lot", before, after), (before, after)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (LotState.IN_TRANSPORT, LotState.PROCESSING),  # must wait, even for 0 s
        (LotState.ON_HOLD, LotState.PROCESSING),
        (LotState.WAITING, LotState.FINISHED),
        (LotState.FINISHED, LotState.WAITING),
        (LotState.WAITING, LotState.WAITING),
        (LotState.ON_HOLD, LotState.ON_HOLD),
    ],
)
def test_illegal_lot_steps(before: LotState, after: LotState) -> None:
    assert not fsm.is_legal("lot", before, after)


def test_lot_starts_waiting_and_finished_is_absorbing() -> None:
    assert fsm.is_legal("lot", None, LotState.WAITING)
    for state in LotState:
        if state is not LotState.WAITING:
            assert not fsm.is_legal("lot", None, state)
    assert fsm.successors("lot", LotState.FINISHED) == frozenset()


def test_hold_reason_depends_on_where_the_lot_was() -> None:
    assert fsm.legal_hold(LotState.PROCESSING, HoldReason.REWORK)
    assert not fsm.legal_hold(LotState.PROCESSING, HoldReason.QTIME)
    assert fsm.legal_hold(LotState.WAITING, HoldReason.QTIME)
    assert fsm.legal_hold("in_transport", "qtime")
    assert not fsm.legal_hold(LotState.WAITING, HoldReason.REWORK)
    assert not fsm.legal_hold(LotState.FINISHED, HoldReason.QTIME)
    assert not fsm.legal_hold("waiting", "scrap")
    assert not fsm.legal_hold("nowhere", "qtime")
    for state, reasons in fsm.HOLD_ENTRY.items():
        assert reasons
        assert fsm.is_legal("lot", state, LotState.ON_HOLD)


# ----------------------------------------------------------- tool table


def test_tool_never_runs_into_pm() -> None:
    assert not fsm.is_legal("tool", ToolState.RUNNING, ToolState.PM)
    assert not fsm.is_legal("tool", ToolState.SETUP, ToolState.PM)
    assert not fsm.is_legal("tool", ToolState.PM, ToolState.RUNNING)
    assert not fsm.is_legal("tool", ToolState.DOWN, ToolState.RUNNING)
    assert not fsm.is_legal("tool", ToolState.SETUP, ToolState.IDLE)


def test_every_tool_state_can_break_down() -> None:
    for state in ToolState:
        if state is not ToolState.DOWN:
            assert fsm.is_legal("tool", state, ToolState.DOWN), state


@pytest.mark.parametrize(
    "path",
    [
        ["idle", "setup", "running", "idle", "running", "idle"],
        ["idle", "waiting_batch", "running", "down", "idle"],
        ["idle", "waiting_batch", "idle", "pm", "idle"],
        ["idle", "reserved", "setup", "running", "idle"],
        ["idle", "reserved", "idle"],
        ["pm", "down", "pm", "idle"],
        ["down", "idle", "reserved", "down", "idle"],
    ],
)
def test_tool_paths(path: list[str]) -> None:
    assert fsm.is_legal("tool", None, path[0])
    for before, after in itertools.pairwise(path):
        assert fsm.is_legal("tool", before, after), (before, after)


def test_tool_initial_states() -> None:
    assert {s for s in ToolState if fsm.is_legal("tool", None, s)} == {
        ToolState.IDLE,
        ToolState.DOWN,
        ToolState.PM,
    }


def test_tool_precedence_covers_every_state_once() -> None:
    assert sorted(fsm.TOOL_PRECEDENCE) == sorted(ToolState)
    assert fsm.TOOL_PRECEDENCE[0] is ToolState.DOWN
    assert fsm.TOOL_PRECEDENCE[-1] is ToolState.IDLE


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], ToolState.IDLE),
        (["idle"], ToolState.IDLE),
        ([ToolState.PM, ToolState.DOWN], ToolState.DOWN),
        ([ToolState.RUNNING, ToolState.PM], ToolState.PM),
        ([ToolState.RUNNING, ToolState.SETUP], ToolState.SETUP),
        ([ToolState.RESERVED, ToolState.RUNNING], ToolState.RUNNING),
        ([ToolState.WAITING_BATCH, ToolState.RESERVED], ToolState.RESERVED),
        (["waiting_batch", "idle"], ToolState.WAITING_BATCH),
        ({ToolState.DOWN, ToolState.RESERVED, ToolState.WAITING_BATCH}, ToolState.DOWN),
    ],
)
def test_resolve_tool_state(flags: list[str], expected: ToolState) -> None:
    assert fsm.resolve_tool_state(flags) is expected


def test_resolve_tool_state_rejects_unknown_signals() -> None:
    with pytest.raises(ValueError):
        fsm.resolve_tool_state(["broken"])


# ------------------------------------------------------- Q-time / batch


def test_qtime_open_then_exactly_one_terminal() -> None:
    assert fsm.is_legal("qtime", None, QTimeState.OPEN)
    terminals = set(QTimeState) - {QTimeState.OPEN}
    assert fsm.successors("qtime", QTimeState.OPEN) == terminals
    for state in terminals:
        assert fsm.successors("qtime", state) == frozenset()
        assert not fsm.is_legal("qtime", None, state)
        assert not fsm.is_legal("qtime", state, QTimeState.OPEN)


def test_qtime_scoring_split_matches_r2_buckets() -> None:
    assert {s.value for s in fsm.QTIME_MISSED} == {"late", "held", "recleaned", "expired"}
    assert {s.value for s in fsm.QTIME_SCORED} == {"met", "late", "held", "recleaned", "expired"}
    unscored = set(QTimeState) - fsm.QTIME_SCORED - {QTimeState.OPEN}
    assert unscored == {QTimeState.SKIPPED, QTimeState.LIVE}


@pytest.mark.parametrize(
    ("remaining", "need", "band"),
    [
        (3600.0, 1800.0, QTimeBand.SAFE),
        (2701.0, 1800.0, QTimeBand.SAFE),
        (2700.0, 1800.0, QTimeBand.URGENT),  # need + margin, inclusive
        (1800.0, 1800.0, QTimeBand.URGENT),  # need, inclusive
        (1799.0, 1800.0, QTimeBand.LOST),
        (-10.0, 0.0, QTimeBand.LOST),
    ],
)
def test_qtime_band(remaining: float, need: float, band: QTimeBand) -> None:
    assert fsm.qtime_band(remaining, need) is band


def test_qtime_band_custom_margin() -> None:
    assert fsm.qtime_band(2000.0, 1800.0, margin=100.0) is QTimeBand.SAFE


def test_urgent_margin_matches_the_simulator_constant() -> None:
    tree = ast.parse(Path("resilimes/smt/fab.py").read_text(encoding="utf-8"))
    values = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "QTIME_URGENT_MARGIN_SEC" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    assert values == [fsm.QTIME_URGENT_MARGIN_SEC]


def test_batch_lifecycle() -> None:
    for path in (
        ["forming", "ready", "running", "done"],
        ["forming", "running", "interrupted"],  # under-minimum start, then breakdown
        ["forming", "ready", "forming", "ready", "running", "done"],
    ):
        assert fsm.is_legal("batch", None, path[0])
        for before, after in itertools.pairwise(path):
            assert fsm.is_legal("batch", before, after), (before, after)
    assert not fsm.is_legal("batch", BatchState.DONE, BatchState.RUNNING)
    assert not fsm.is_legal("batch", BatchState.FORMING, BatchState.DONE)
    assert fsm.successors("batch", BatchState.INTERRUPTED) == frozenset()


# --------------------------------------------------------------- tables


@pytest.mark.parametrize("entity", list(fsm.ENTITIES))
def test_tables_are_closed_and_reachable(entity: str) -> None:
    enum = fsm.ENTITIES[entity]
    values = {s.value for s in enum}
    for state in enum:
        assert not fsm.is_legal(entity, state, state)
        assert {str(s) for s in fsm.successors(entity, state)} <= values
    seen = {s.value for s in enum if fsm.is_legal(entity, None, s)}
    frontier = list(seen)
    while frontier:
        for nxt in fsm.successors(entity, frontier.pop()):
            if str(nxt) not in seen:
                seen.add(str(nxt))
                frontier.append(str(nxt))
    assert seen == values


def test_is_legal_accepts_plain_strings_and_rejects_unknowns() -> None:
    assert fsm.is_legal("lot", "waiting", "processing")
    assert not fsm.is_legal("lot", "waiting", "scrapped")
    assert not fsm.is_legal("lot", "scrapped", "waiting")
    with pytest.raises(ValueError, match="unknown entity"):
        fsm.is_legal("wafer", "waiting", "processing")
    with pytest.raises(ValueError, match="unknown entity"):
        fsm.successors("wafer", "waiting")


def test_legacy_keys_map_onto_new_states() -> None:
    assert set(fsm.LEGACY_LOT) == {"wait", "run", "hold", "done"}
    assert set(fsm.LEGACY_LOT.values()) == set(LotState) - {LotState.IN_TRANSPORT}
    assert set(fsm.LEGACY_TOOL) == {"idle", "setup", "run", "batch_wait", "down", "pm"}
    assert set(fsm.LEGACY_TOOL.values()) == set(ToolState) - {ToolState.RESERVED}


def test_module_is_dependency_free() -> None:
    tree = ast.parse(Path(fsm.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections", "dataclasses", "enum", "typing"}
