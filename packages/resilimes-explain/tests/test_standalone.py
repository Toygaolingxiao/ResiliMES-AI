"""Tests for the explain distribution on its own (no twin, no engines).

Run from packages/resilimes-explain after installing the package into a clean
environment. Everything here uses small hand-built records.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import resilimes.explain as explain
from resilimes.explain.factcheck import FactRegistry, check
from resilimes.explain.gaps import find_gaps
from resilimes.explain.investigator import run_call
from resilimes.explain.lateness import decompose, late_lots
from resilimes.explain.record import RunRecord, Timeline, Visit
from resilimes.explain.schema import (
    SCHEMA_VERSION,
    EvidenceBundle,
    EvidenceItem,
    RunRef,
    Subject,
    lateness_bundle,
)
from resilimes.explain.sqlguard import SqlRejected, guard
from resilimes.explain.toolkit import Toolkit

FORBIDDEN = ("smt", "engines", "agents", "kernel", "domain", "insight", "evidence", "llm")


def test_all_modules_import_without_the_rest():
    for info in pkgutil.iter_modules(explain.__path__):
        importlib.import_module(f"resilimes.explain.{info.name}")
    loaded = [name for name in sys.modules if name.startswith("resilimes.")]
    bad = [n for n in loaded if n.split(".")[1] in FORBIDDEN]
    assert not bad, bad


def _fab() -> SimpleNamespace:
    route = SimpleNamespace(batch_max=[0], cycle=[300.0], family=[0])
    return SimpleNamespace(
        families=[SimpleNamespace(tool0=0, tools=1, name="F0")],
        family_index={"F0": 0},
        tool_family=[0],
        tool_name=["T0"],
        routes=[route],
        lot_route=[0],
        lot_due=[200.0],
        lot_id=["Lot-1"],
        lot_product=["P1"],
        lot_class=["regular"],
        pm=[],
    )


def _record() -> RunRecord:
    """One lot, one tool. Ready at 0, the tool is down until 100, runs 100..400."""
    fab = _fab()
    visit = Visit(lot=0, step=0, family=0, ready=0.0, start=100.0, tool=0, leave=400.0)
    visit.outcome = "done"
    tl = Timeline(
        fab=fab,
        horizon=1000.0,
        downs=[[(0.0, 100.0)]],
        pm=[[]],
        visits={0: [visit]},
        busy=[[(100.0, 400.0)]],
        reserved=[[]],
        completed={0: 400.0},
        by_family={0: [visit]},
        _ready_index={0: [0.0]},
    )
    return RunRecord(
        fab=fab, seed=1, horizon=1000.0, policy="test", downs=tl.downs, pm=tl.pm, timeline=tl
    )


def test_lateness_split_on_a_hand_built_record():
    tl = _record().timeline
    assert late_lots(tl) == [0]
    split = decompose(tl, 0)
    assert split["exact"]
    assert split["lateness_sec"] == pytest.approx(200.0)
    assert split["history_sec"]["down"] == pytest.approx(100.0)
    assert split["history_sec"]["processing"] == pytest.approx(300.0)
    assert split["overrun_sec"]["processing"] == pytest.approx(200.0)


def test_evidence_bundle_from_the_split():
    record = _record()
    ref = RunRef(seed=record.seed, horizon_sec=record.horizon, policy=record.policy)
    bundle = lateness_bundle(decompose(record.timeline, 0), ref)
    assert bundle.schema_version == SCHEMA_VERSION
    assert bundle.verify()
    assert bundle.tier_totals()["recorded"] == pytest.approx(400.0)  # lateness + processing


def test_schema_rules():
    with pytest.raises(ValidationError):
        EvidenceItem(key="k", tier="unknown", value=1.0)
    bundle = EvidenceBundle(
        subject=Subject(kind="lot", id="x"), run=RunRef(seed=1, horizon_sec=1.0, policy="p")
    ).sealed()
    assert bundle.verify()


def test_toolkit_and_class_tier_on_a_hand_built_record():
    record = _record()
    record.class_tiers = {"VIP": 0}
    assert record.class_tier("VIP") == 0
    assert record.class_tier("regular") == 2
    kit = Toolkit(record)
    assert kit.family_id("F0") == 0


def test_gap_finder_on_a_hand_built_record():
    tl = _record().timeline
    # The tool is down 0..100 and busy 100..400, then idle to the horizon.
    gaps = find_gaps(tl, min_gap_s=60.0)
    assert any(tool == 0 and start >= 400.0 for tool, start, _end in gaps)


def test_sql_call_needs_an_injected_runner():
    kit = Toolkit(_record())
    out = run_call(kit, "sql", {"sql": "SELECT 1"}, None)
    assert "error" in out
    seen = {}

    def runner(sql, settings):
        seen["sql"] = sql
        return {"sql": sql, "rows": []}

    assert run_call(kit, "sql", {"sql": "SELECT 1"}, None, runner)["rows"] == []
    assert seen["sql"] == "SELECT 1"


def test_fact_check_and_sql_guard():
    registry = FactRegistry()
    registry.add({"lot": "Init_Lot_3_17", "wait_min": 42})
    assert check("Init_Lot_3_17 waited 42 min.", registry) == []
    assert check("Init_Lot_9_99 waited 43 min.", registry)
    with pytest.raises(SqlRejected):
        guard("DELETE FROM x")
