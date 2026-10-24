"""Evidence toolkit: simulator hooks, timeline, exact lateness split, fab_ops, fact check."""

from __future__ import annotations

import pytest

from resilimes.data.zetaris_layout import (
    DATABASE_FOR_TABLE,
    DATASOURCE_FOR_DATABASE,
    split_sql,
)
from resilimes.evidence.fab_ops import ops_rows, ops_sql
from resilimes.evidence.factcheck import FactRegistry, check
from resilimes.evidence.lateness import (
    BUCKETS,
    TOLERANCE_SEC,
    decompose,
    late_lots,
    rounded_minutes,
)
from resilimes.evidence.toolkit import HOUR, Toolkit, record_run
from resilimes.smt.fab import load_fab
from resilimes.smt.faults import FaultPlan
from resilimes.smt.simulate import pm_windows, run_policy, sample_downs


@pytest.fixture(scope="module")
def fab():
    return load_fab()


@pytest.fixture(scope="module")
def run24(fab):
    return record_run(fab, seed=1, horizon=24 * HOUR)


def test_hooks_do_not_change_the_default_run(fab):
    horizon = 6 * HOUR
    downs = sample_downs(fab, 2, horizon)
    pm = pm_windows(fab, horizon)
    plain = run_policy(
        fab, policy="resilimes", seed=2, horizon=horizon, downs=downs, pm=pm, record=True
    )
    hooked = run_policy(
        fab,
        policy="resilimes",
        seed=2,
        horizon=horizon,
        downs=downs,
        pm=pm,
        record=True,
        lot_log=True,
        faults=FaultPlan(hold_until={}),
    )
    assert plain.events == hooked.events
    assert plain.on_time_pct == hooked.on_time_pct
    assert plain.lot_log == {}
    assert hooked.lot_log["ready"] and hooked.lot_log["setup"]


def test_every_late_lot_splits_exactly(run24):
    lots = late_lots(run24.timeline)
    assert len(lots) >= 15
    for lot in lots:
        split = decompose(run24.timeline, lot)
        assert split["exact"], split["lot_id"]
        assert abs(sum(split["history_sec"].values()) - split["end_sec"]) <= TOLERANCE_SEC
        assert abs(sum(split["overrun_sec"].values()) - split["lateness_sec"]) <= TOLERANCE_SEC
        assert set(BUCKETS) <= set(split["history_sec"])
        assert min(split["history_sec"].values()) >= -TOLERANCE_SEC


def test_rounded_minutes_add_up():
    parts = {"a": 100.0, "b": 200.0, "c": 333.3}
    shown = rounded_minutes(parts)
    assert round(sum(shown.values()), 1) == round(sum(parts.values()) / 60.0, 1)


def test_toolkit_queries_feed_the_fact_registry(run24, fab):
    kit = Toolkit(run24)
    name = fab.families[fab.focus_family].name
    wip = kit.family_wip(name, 0, 4)
    assert wip["series"][0]["hour"] == 0
    window = kit.family_window(name, 0, 6)
    assert window["tools"] == fab.families[fab.focus_family].tools
    kit.tool_states(name, 0, 6)
    kit.upstream(name, 0, 6)
    late = kit.late_lots(5)
    first = late["late_lots"][0]["lot"]
    split = kit.lot_lateness(first)
    assert split["exact"]
    assert round(sum(split["while_late_min"].values()), 1) == split["late_min"]
    kit.maintenance(name)
    assert len(kit.calls) == 7
    assert first.upper() in kit.registry.ids
    assert not check(f"{first} was {split['late_min']} min late at {name}.", kit.registry)


def test_factcheck_flags_invented_ids_and_numbers():
    registry = FactRegistry()
    registry.add({"lot": "Init_Lot_3_17", "late_min": 42.5, "tool": "LITHO-02"})
    assert check("Init_Lot_3_17 was 42.5 min late on LITHO-02, two causes.", registry) == []
    misses = check("Init_Lot_9_99 was 77 min late on LITHO-09.", registry)
    assert "unknown id Init_Lot_9_99" in misses
    assert "unknown number 77" in misses
    assert "unknown id LITHO-09" in misses


def test_fab_ops_export_routes_to_its_own_datasource(run24):
    tables = ops_rows(run24)
    assert tables["ops_events"] and tables["ops_kpi_hourly"]
    buckets = split_sql(ops_sql({k: v[:3] for k, v in tables.items()}))
    assert "CREATE TABLE resilimes.ops_events" in buckets["fab_ops"]
    assert not buckets["fab_mes"].strip()
    assert DATASOURCE_FOR_DATABASE["fab_ops"] == "fab_ops"
    assert DATABASE_FOR_TABLE["ops_kpi_hourly"] == "fab_ops"


def test_fault_hold_delays_release(fab):
    horizon = 4 * HOUR
    lot = 0
    run = record_run(fab, seed=1, horizon=horizon, faults=FaultPlan(hold_until={lot: 2 * HOUR}))
    first = run.timeline.visits[lot][0]
    assert first.ready >= 2 * HOUR
    assert run.timeline.gaps[lot][0].kind == "release_hold"
