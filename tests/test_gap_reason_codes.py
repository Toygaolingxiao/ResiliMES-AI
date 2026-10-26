"""Plan 4 v1.5: dispatch-time gap reason codes + the gap counterfactual.

The recorder must be pure observation (recorder on/off runs bit-identical),
the three record sites must fire with correct evidence, dispatch-log gaps
must beat post-hoc inference, and the counterfactual script must produce
consistent numbers on a real (simulated) scenario.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest

from resilimes.evidence.timeline import Timeline
from resilimes.insight.gap_explainer import explain_gap
from resilimes.insight.gaps import gaps_from_run
from resilimes.smt.dispatch_log import DispatchRecord, GapRecorder
from resilimes.smt.fab import Fab, load_fab
from resilimes.smt.simulate import RunResult, make_sim, pm_windows, sample_downs

H6 = 6 * 3600.0
H12 = 12 * 3600.0
# Wall-clock / timing fields: the only RunResult fields allowed to differ
# between two runs of the same scenario (verified off-vs-off).
TIMING_KEYS = {"sim_s", "sched_build_total_s", "replan_tick_total_s"}


def _digest(result: RunResult) -> str:
    data = {
        key: value
        for key, value in asdict(result).items()
        if key not in TIMING_KEYS and not key.endswith("_ms")
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@pytest.fixture(scope="module")
def fab() -> Fab:
    return load_fab()


@pytest.fixture(scope="module")
def gated(fab: Fab) -> tuple[RunResult, RunResult, GapRecorder]:
    """ResiliMES + hard Q-time gate, seed 1, 6 h: recorder off vs on."""
    downs = sample_downs(fab, 1, H6)
    pm = pm_windows(fab, H6)
    off = make_sim(
        fab, policy="resilimes", seed=1, horizon=H6, downs=downs, pm=pm, hard_qtime=True
    ).run()
    recorder = GapRecorder()
    on = make_sim(
        fab,
        policy="resilimes",
        seed=1,
        horizon=H6,
        downs=downs,
        pm=pm,
        hard_qtime=True,
        gap_recorder=recorder,
    ).run()
    return off, on, recorder


@pytest.fixture(scope="module")
def edd_batch(fab: Fab) -> tuple[RunResult, GapRecorder]:
    """Pure EDD, seed 5, 12 h: one of the seeds where the batch-rule wait
    branch actually fires on SMT2020 (it is rare; resilimes seeds 1/5 and
    EDD seed 1 never take it in 12 h)."""
    recorder = GapRecorder()
    result = make_sim(
        fab,
        policy="edd",
        seed=5,
        horizon=H12,
        downs=sample_downs(fab, 5, H12),
        pm=pm_windows(fab, H12),
        gap_recorder=recorder,
    ).run()
    return result, recorder


# ---------------------------------------------------------------------------
# Recorder unit behaviour
# ---------------------------------------------------------------------------


def test_recorder_coalesces_repeated_decisions() -> None:
    recorder = GapRecorder()
    for _ in range(3):
        recorder.record(
            "qtime_gate",
            lot=7,
            lots=(7,),
            step=10,
            tool=3,
            family=1,
            t=100.0,
            evidence={"blocked_family": 2},
        )
    recorder.record(
        "batch_wait", lot=7, lots=(7, 8), step=10, tool=3, family=1, t=200.0, wake=500.0
    )
    recorder.record(
        "batch_wait", lot=8, lots=(8, 7), step=10, tool=3, family=1, t=210.0, wake=500.0
    )
    assert len(recorder.records) == 2
    gate = recorder.by_reason("qtime_gate")[0]
    assert gate.count == 3 and gate.t == 100.0
    batch = recorder.by_reason("batch_wait")[0]
    assert batch.count == 2  # same waiting group, lot order does not matter


# ---------------------------------------------------------------------------
# Zero behaviour change + qtime_gate records
# ---------------------------------------------------------------------------


def test_recorder_on_off_identical(gated: tuple[RunResult, RunResult, GapRecorder]) -> None:
    off, on, _recorder = gated
    assert _digest(off) == _digest(on)


def test_qtime_gate_records(gated: tuple[RunResult, RunResult, GapRecorder], fab: Fab) -> None:
    _off, on, recorder = gated
    records = recorder.by_reason("qtime_gate")
    assert records, "the gate must refuse starts in this scenario"
    # Every gate block the simulator counted is recorded exactly once
    # (coalesced repeats sum back to the KPI).
    assert sum(rec.count for rec in records) == on.hard_qtime["gate_blocks"]
    for rec in records:
        assert rec.lot is not None and rec.lots == (rec.lot,)
        route = fab.routes[fab.lot_route[rec.lot]]
        assert route.cqt_limit[rec.step] > 0  # the held step is a CQT origin
        assert rec.evidence["blocked_family"] >= 0
        assert rec.evidence["target_step"] == route.cqt_target[rec.step]
        assert rec.count >= 1


# ---------------------------------------------------------------------------
# batch_wait records (the wait branch of the batch rule, recorded in situ)
# ---------------------------------------------------------------------------


def test_batch_wait_records(edd_batch: tuple[RunResult, GapRecorder]) -> None:
    _result, recorder = edd_batch
    records = recorder.by_reason("batch_wait")
    assert records, "seed 5 / EDD takes the batch wait branch"
    for rec in records:
        ev = rec.evidence
        assert ev["wafers"] < ev["floor_wafers"]  # held below BATCHMN
        assert ev["need_lots"] >= 1
        assert ev["expected_arrivals"] >= ev["need_lots"]  # waiting is rational
        assert rec.wake == ev["cap_at_s"] > rec.t
        assert len(rec.lots) >= 1 and rec.lot == rec.lots[0]


def test_batch_fill_override_starts_underfilled(
    edd_batch: tuple[RunResult, GapRecorder], fab: Fab
) -> None:
    """The research-arm fill: forcing the recorded batch lots starts the
    batch under-filled (batch_reasons gains ``forced_fill``)."""
    _result, recorder = edd_batch
    force: dict[tuple[int, int], float] = {}
    for rec in recorder.by_reason("batch_wait"):
        for lot in rec.lots:
            force[(lot, rec.step)] = rec.t
    filled = make_sim(
        fab,
        policy="edd",
        seed=5,
        horizon=H12,
        downs=sample_downs(fab, 5, H12),
        pm=pm_windows(fab, H12),
        force_start_at=force,
    ).run()
    assert filled.batch_reasons.get("forced_fill", 0) >= 1


# ---------------------------------------------------------------------------
# pm_avoidance records (synthetic PM calendar: the record site in choose)
# ---------------------------------------------------------------------------


def test_pm_avoidance_records_synthetic(fab: Fab) -> None:
    tools = len(fab.tool_name)
    recorder = GapRecorder()
    result = make_sim(
        fab,
        policy="edd",
        seed=1,
        horizon=3600.0,
        downs=[[] for _ in range(tools)],
        pm=[[(300.0, 900.0)] for _ in range(tools)],
        gap_recorder=recorder,
    ).run()
    records = recorder.by_reason("pm_avoidance")
    assert records and result.pm_avoided > 0
    for rec in records[:50]:
        assert rec.evidence["pm_start_s"] == 300.0
        assert rec.evidence["overshoot_s"] > 0
        assert rec.wake == 300.0


# ---------------------------------------------------------------------------
# Dispatch-log gaps beat post-hoc inference
# ---------------------------------------------------------------------------


def test_dispatch_gap_beats_inferred(fab: Fab) -> None:
    tools = len(fab.tool_family)
    tl = Timeline(
        fab=fab,
        horizon=7200.0,
        downs=[[] for _ in range(tools)],
        pm=[[] for _ in range(tools)],
        busy=[[(0.0, 1000.0), (4600.0, 7200.0)] if tool == 0 else [] for tool in range(tools)],
    )
    record = DispatchRecord(
        reason="qtime_gate",
        lot=11,
        lots=(11,),
        step=4,
        tool=0,
        family=fab.tool_family[0],
        t=1500.0,
        evidence={"blocked_family": 3, "target_step": 5},
    )

    class _Run:
        timeline = tl

    gaps = gaps_from_run(_Run(), min_gap_s=300.0, dispatch_records=[record])
    mine = [gap for gap in gaps if gap.tool == 0]
    assert len(mine) == 1  # the inferred gap over the same window is dropped
    gap = mine[0]
    assert gap.source == "dispatch_log" and gap.tier == "decision_record"
    assert gap.reason.value == "qtime_gate"
    assert gap.start == 1500.0 and gap.end == 4600.0  # resolved to the next busy start

    out = explain_gap(gap)
    assert out.source == "scripted" and out.fact_ok and out.tier == "decision_record"
    assert "Q-time gate refused" in out.text


# ---------------------------------------------------------------------------
# Counterfactual script: consistent numbers on a real simulated scenario
# ---------------------------------------------------------------------------


def test_counterfactual_report_consistent(fab: Fab) -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "gap_counterfactual", Path(__file__).parents[1] / "scripts" / "gap_counterfactual.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.analyse(fab, seed=5, horizon_h=12.0, policy="edd")
    assert report["scenario"]["llm"] is False
    assert report["gaps_filled"] > 0
    assert report["new_avoidable_qtime_violations"] == (
        report["filled_avoidable_qtime_violations"] - report["base_avoidable_qtime_violations"]
    )
    judged = sum(
        bucket["protective"] + bucket["not_protective"] for bucket in report["per_reason"].values()
    )
    total = sum(bucket["gaps"] for bucket in report["per_reason"].values())
    assert total == report["gaps_filled"]
    if judged:
        assert 0.0 <= report["protective_share_judged"] <= 1.0
