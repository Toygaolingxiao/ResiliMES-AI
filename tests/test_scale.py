"""Scale fab: a seeded 36-tool plant, and a fast smoke of the same generator."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resilimes.agents.brief import schedule_brief
from resilimes.agents.planner import naive_alternative, reject_alternative
from resilimes.data.scale_export import render_scale_csv, render_scale_sql, scale_rows
from resilimes.data.sql_export import TABLES
from resilimes.domain.checks import validate
from resilimes.domain.critique import critique_schedule
from resilimes.domain.kpis import evaluate, job_outcomes
from resilimes.domain.loadmap import load_map
from resilimes.domain.scale_fab import SCALE_DOWN_TOOL, SCALE_LOTS, build_scale_plant
from resilimes.domain.schedule import POLICY_EDD, POLICY_RECOVER, schedule_plant

HORIZON = datetime(2026, 10, 22, 6, 30, tzinfo=UTC)


def test_scale_plant_is_deterministic_and_covers_the_loop() -> None:
    first = build_scale_plant(HORIZON)
    second = build_scale_plant(HORIZON)
    assert [job.job_id for job in first.jobs] == [job.job_id for job in second.jobs]
    assert [job.due_at for job in first.jobs] == [job.due_at for job in second.jobs]
    assert len(first.jobs) == SCALE_LOTS
    assert len(first.equipment) == 36
    areas = {item.area for item in first.equipment}
    assert areas == {"Deposition", "Lithography", "Metrology", "Etch", "Clean", "CMP"}
    assert any(
        item.equipment_id == "DEP-01" and "cvd_oxide" in item.capability for item in first.equipment
    )
    assert any(
        step.capability == "cvd_oxide" for product in first.products for step in product.route
    )
    assert first.qtime_rules
    assert first.reticles
    assert first.inhibits
    assert any(
        job.status == "BLOCKED" and job.assigned_equipment == SCALE_DOWN_TOOL for job in first.jobs
    )
    down = next(item for item in first.equipment if item.equipment_id == SCALE_DOWN_TOOL)
    assert down.status == "DOWN"
    assert down.available_at_min == 600


def test_scale_smoke_moves_hot_lots_off_the_down_scanner() -> None:
    plant = build_scale_plant(HORIZON, lots=40)
    started = time.perf_counter()
    before = schedule_plant(plant, POLICY_EDD)
    after = schedule_plant(plant, POLICY_RECOVER)
    committed = critique_schedule(plant, after)
    rejected = reject_alternative(plant, naive_alternative(plant, "scale"))
    checked = validate(plant, after)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.5
    assert not after.unscheduled
    assert not before.unscheduled
    before_kpi = evaluate(plant, before)
    after_kpi = evaluate(plant, after)
    assert after_kpi.on_time_delivery_pct >= before_kpi.on_time_delivery_pct
    assert after_kpi.lots_at_risk <= before_kpi.lots_at_risk
    assert after_kpi.weighted_tardiness_min <= before_kpi.weighted_tardiness_min
    assert committed.verdict == "accept"
    assert checked["failed"] == 0
    assert validate(plant, before)["failed"] == 0
    assert rejected.violations
    assert rejected.violations[0].constraint == "equipment_status"
    assert "LITHO-03" in rejected.violations[0].detail
    early_down = [
        op for op in before.operations if op.equipment_id == SCALE_DOWN_TOOL and op.start_min < 600
    ]
    assert not early_down
    heatmap = load_map(plant, after, 12 * 60)
    assert len(heatmap["rows"]) == 36
    assert heatmap["buckets"] == 12
    outcomes = job_outcomes(plant, before, plant, after)
    brief = schedule_brief(
        kind="scale",
        outcomes=outcomes,
        before=before_kpi,
        after=after_kpi,
        rejected=rejected,
        verdict=committed.verdict,
    )
    assert brief["en"]["headline"] == "EDD dispatch already meets the dues"
    assert "EDD dispatch" in brief["en"]["points"][0]
    assert "100.0%" in brief["en"]["points"][1]


def test_scale_seed_matches_the_generator() -> None:
    text = render_scale_sql()
    assert "DROP " not in text.upper()
    assert "LITHO-03" in text
    assert "SL-0001" in text
    assert "CREATE TABLE resilimes.wip_jobs" in text
    rows = scale_rows()
    assert len(rows["wip_jobs"]) == SCALE_LOTS
    assert len(rows["equipment"]) == 36
    assert Path("data/sql/scale_seed.sql").read_text(encoding="utf-8") == text
    for name in TABLES:
        committed = Path(f"data/zetaris/scale/{name}.csv").read_text(encoding="utf-8")
        assert committed == render_scale_csv(name)


@pytest.mark.benchmark
def test_thousand_lot_recover_is_under_three_seconds() -> None:
    if os.environ.get("RESILIMES_BENCHMARK") != "1":
        pytest.skip("set RESILIMES_BENCHMARK=1 to time the 1000-lot recover")
    plant = build_scale_plant(HORIZON)
    started = time.perf_counter()
    before = schedule_plant(plant, POLICY_EDD)
    after = schedule_plant(plant, POLICY_RECOVER)
    critique_schedule(plant, after)
    reject_alternative(plant, naive_alternative(plant, "scale"))
    validate(plant, after)
    elapsed = time.perf_counter() - started
    assert len(before.operations) > 1000
    assert len(after.operations) > 1000
    assert elapsed < 3.0
