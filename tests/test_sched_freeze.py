"""Frozen dispatch zone (sched-freeze): off is main, on keeps lots on their tool."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.freeze import FreezeConfig, inversions, read_tick_log
from resilimes.smt.simulate import RunResult, pm_windows, run_policy, sample_downs

HOURS = 3.0
# sha256 of the 3 h published seed-1 run on main (c75ff85), timing fields left out.
MAIN_GOLDEN = {
    "resilimes": "0856dd5b0b3eb52847b421703d708d90f21a7b23307a54b01b8827f9f38c72a8",
    "edd": "7663f6893a35fcc8c72ec9c3759393d60ab12304ec1c7a3cf09ef664964afbc7",
}
TIMING = {
    "sim_s",
    "dispatch_p50_ms",
    "dispatch_p95_ms",
    "dispatch_busy_p50_ms",
    "dispatch_busy_p95_ms",
    "replan_tick_p50_ms",
    "replan_tick_p95_ms",
    "replan_tick_total_s",
    "sched_freeze",
}
# Planning-layer fields (planning-r1): constant zeros/empty when no plan is passed,
# so they are left out of the off-path digest like the empty lot_log.
PLAN_FIELDS = {
    "plan_used",
    "plan_due_fallbacks",
    "sched_starts",
    "sched_follow",
    "deviations",
    "sched_stale_detail",
    "sched_build_p95_ms",
    "sched_build_total_s",
}
ENV = (
    "RESILIMES_SCHED_FREEZE",
    "RESILIMES_FREEZE_LOTS",
    "RESILIMES_FREEZE_MIN",
    "RESILIMES_SCHED_TRACK",
    "RESILIMES_TICK_LOG",
)


@pytest.fixture(scope="module")
def fab() -> Fab:
    return load_fab()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def _run(fab: Fab, policy: str, freeze: FreezeConfig | None, hours: float = HOURS) -> RunResult:
    horizon = hours * 3600.0
    return run_policy(
        fab,
        policy=policy,
        seed=1,
        horizon=horizon,
        downs=sample_downs(fab, 1, horizon),
        pm=pm_windows(fab, horizon),
        trace=False,
        record=True,
        freeze=freeze,
    )


def _digest(result: RunResult, *, freeze_events: bool = True) -> str:
    # lot_log is the evidence toolkit's opt-in field (always {} here); it is not dispatch output.
    data = {
        key: value
        for key, value in asdict(result).items()
        if key not in TIMING
        and not (key == "lot_log" and not value)
        and not (key in PLAN_FIELDS and not result.plan_used)
    }
    if not freeze_events:
        data["events"] = [e for e in data["events"] if e[0] not in ("sched_tick", "unfreeze")]
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@pytest.mark.parametrize("policy", ["resilimes", "edd"])
def test_off_is_byte_identical_to_main(fab: Fab, policy: str) -> None:
    result = _run(fab, policy, None)
    assert result.sched_freeze == {}
    assert _digest(result) == MAIN_GOLDEN[policy]


@pytest.mark.parametrize("policy", ["resilimes", "edd"])
def test_tracking_only_does_not_change_dispatch(fab: Fab, policy: str) -> None:
    tracked = _run(fab, policy, FreezeConfig(track=True))
    assert any(event[0] == "sched_tick" for event in tracked.events)
    assert _digest(tracked, freeze_events=False) == MAIN_GOLDEN[policy]
    stats = tracked.sched_freeze
    assert stats["enabled"] is False
    assert stats["ticks"] > 0
    assert stats["unfreeze_total"] == 0
    assert stats["second_transports"] > 0


def test_env_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not FreezeConfig.from_env().active
    monkeypatch.setenv("RESILIMES_SCHED_FREEZE", "1")
    monkeypatch.setenv("RESILIMES_FREEZE_LOTS", "3")
    monkeypatch.setenv("RESILIMES_FREEZE_MIN", "45")
    cfg = FreezeConfig.from_env()
    assert cfg.enabled and cfg.active
    assert cfg.max_lots == 3
    assert cfg.max_sec == 45 * 60.0


def test_inversions_counts_pairwise_swaps() -> None:
    assert inversions([]) == 0
    assert inversions([0, 1, 2, 3]) == 0
    assert inversions([1, 0, 2]) == 1
    assert inversions([3, 2, 1, 0]) == 6


def _frozen_violations(result: RunResult) -> tuple[int, int]:
    """Starts of a frozen lot on another tool, without an unfreeze before it."""
    frozen: dict[int, int] = {}
    checked = 0
    bad = 0
    for event in result.events:
        kind = event[0]
        if kind == "sched_tick":
            frozen = {lot: tool for tool, lots in event[2].items() for lot in lots}
        elif kind == "unfreeze":
            frozen.pop(event[2], None)
        elif kind == "start":
            tool, lots = event[2], event[3]
            for lot in lots:
                held = frozen.pop(lot, None)
                if held is not None:
                    checked += 1
                    if held != tool:
                        bad += 1
    return checked, bad


@pytest.mark.parametrize("policy", ["resilimes", "edd"])
def test_frozen_lots_stay_on_their_tool(fab: Fab, policy: str) -> None:
    off = _run(fab, policy, FreezeConfig(track=True))
    on = _run(fab, policy, FreezeConfig(enabled=True))
    stats = on.sched_freeze
    checked, bad = _frozen_violations(on)
    assert checked > 100
    assert bad == 0
    assert stats["frozen_starts"] > 0
    assert sum(stats["unfreezes"].values()) == stats["unfreeze_total"]
    assert stats["unfreezes"]["other"] == 0
    assert stats["second_transports"] * 20 < off.sched_freeze["second_transports"]
    assert stats["staged_tool_change_rate"] < off.sched_freeze["staged_tool_change_rate"]


def test_tick_log_fields(fab: Fab, tmp_path: Path) -> None:
    path = tmp_path / "run_on.jsonl.gz"
    _run(fab, "resilimes", FreezeConfig(enabled=True, log_path=str(path)), hours=1.0)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows: list[dict[str, Any]] = [json.loads(line) for line in handle]
    assert len(rows) == 12
    first, second = rows[0], rows[1]
    for key in ("t", "queues", "tools", "holds", "ai_decisions", "diff", "unfreezes"):
        assert key in first
    assert first["freeze"] is True
    tool = next(iter(second["tools"].values()))
    assert {"frozen", "planned"} <= set(tool)
    for key in ("tool_changes", "kendall_tau_distance", "order_swaps", "frozen", "replanned"):
        assert key in second["diff"]
    page = read_tick_log(str(tmp_path), "run_on", offset=10, limit=5)
    assert page["count"] == 2 and page["more"] is False
    assert page["ticks"][0]["t"] == rows[10]["t"]


def test_tick_log_endpoint(fab: Fab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "demo.jsonl"
    path.write_text('{"t": 300.0}\n{"t": 600.0}\n', encoding="utf-8")
    monkeypatch.setenv("RESILIMES_TICK_LOG_DIR", str(tmp_path))
    settings = Settings(mode="mock", fab="sample", horizon=HORIZON)
    client = TestClient(create_app(settings))
    listed = client.get("/api/sched/ticks").json()
    assert listed["runs"] == ["demo"]
    page = client.get("/api/sched/ticks", params={"run": "demo", "offset": 1}).json()
    assert page["ticks"] == [{"t": 600.0}]
    assert client.get("/api/sched/ticks", params={"run": "../etc"}).status_code == 404
    assert client.get("/api/sched/ticks", params={"run": "nope"}).status_code == 404
