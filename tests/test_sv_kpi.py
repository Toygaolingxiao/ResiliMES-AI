"""KPIs ported from Schedule_Viewer, on hand-built records."""

from __future__ import annotations

from resilimes.smt.kpi import (
    Op,
    Run,
    activity,
    batch_formation,
    due_date_adherence,
    equipment_stats,
    load_by_group,
    lot_step_stats,
    qtime_achievement,
    same_recipe_runs,
    setup_time,
    throughput,
)


def test_due_date_adherence_counts_completed_lots() -> None:
    body = due_date_adherence({"A": 100.0, "B": 400.0}, {"A": 200.0, "B": 280.0, "C": 50.0})
    assert body["completed"] == 2
    assert body["on_time"] == 1
    assert body["on_time_rate"] == 50.0
    assert body["avg_delay_min"] == 2.0
    assert body["max_delay_min"] == 2.0
    assert due_date_adherence({}, {})["on_time_rate"] == 0.0


def test_qtime_achievement_ignores_open_and_recleaned() -> None:
    body = qtime_achievement(["met", "met", "met", "violated", "open", "recleaned"])
    assert body == {"checked": 4, "violated": 1, "rate": 75.0}
    assert qtime_achievement([])["rate"] == 100.0


def test_lot_step_stats_drops_first_op() -> None:
    ops = [
        Op("L1", "normal", "T1", 0.0, 600.0),
        Op("L1", "normal", "T2", 1200.0, 1800.0),
        Op("L1", "normal", "T3", 1800.0, 2400.0),
    ]
    body = lot_step_stats(ops)
    row = body["all"]
    assert row["ops"] == 2
    assert row["queue_mean_min"] == 5.0
    assert row["lead_mean_min"] == 15.0
    assert row["xfactor_mean"] == 1.5
    assert body["normal"]["ops"] == 2


def test_setup_and_equipment_share() -> None:
    runs = [
        Run("T1", "G", 0.0, 1800.0, 600.0, "r1", 1),
        Run("T1", "G", 1200.0, 3600.0, 0.0, "r1", 1),
    ]
    setup = setup_time(runs, tools=2, lo=0.0, hi=3600.0)
    assert setup["setup_min"] == 10.0
    assert setup["setup_rate"] == round(100.0 * 600 / 7200, 2)
    stats = equipment_stats(runs, ["T1", "T2"], 0.0, 3600.0)
    assert stats["idle_min"] == 60.0
    assert stats["wait_rate"] == 50.0


def test_throughput_counts_run_ends_in_period() -> None:
    runs = [Run("T", "G", 0.0, 50.0, 0.0, "r", 2), Run("T", "G", 60.0, 150.0, 0.0, "r", 3)]
    assert throughput(runs, 0.0, 100.0) == {"lots": 2, "wafers": 50}


def test_batch_formation_caps_fill() -> None:
    runs = [
        Run("F", "Diffusion", 0.0, 1.0, 0.0, "r", 2, cap_lots=4),
        Run("F", "Diffusion", 1.0, 2.0, 0.0, "r", 6, cap_lots=4),
        Run("S", "Litho", 0.0, 1.0, 0.0, "r", 1, cap_lots=1),
    ]
    body = batch_formation(runs)
    assert body["batches"] == 2
    assert body["avg_lots"] == 4.0
    assert body["fill_rate"] == 75.0


def test_same_recipe_blocks() -> None:
    runs = [
        Run("T", "G", 0.0, 1.0, 0.0, "a", 1),
        Run("T", "G", 1.0, 2.0, 0.0, "a", 1),
        Run("T", "G", 2.0, 3.0, 0.0, "b", 1),
        Run("U", "G", 0.0, 1.0, 0.0, "a", 1),
    ]
    body = same_recipe_runs(runs)
    assert body["operations"] == 4
    assert body["avg_consecutive"] == round(4 / 3, 2)
    assert body["grouping_rate"] == 25.0


def test_load_by_group_and_activity() -> None:
    runs = [Run("T1", "A", 0.0, 3600.0, 600.0, "r", 1)]
    rows = load_by_group(runs, {"A": 2, "B": 1}, 0.0, 3600.0)
    assert rows[0] == {"group": "A", "tools": 2, "busy_h": 1.0, "load_rate": 50.0}
    assert rows[1]["load_rate"] == 0.0
    shares = activity(runs, [(0.0, 1800.0)], [(1800.0, 3600.0)], 3, 0.0, 3600.0)
    assert round(sum(shares.values())) == 100
    assert shares["setup"] == round(100 * 600 / 10800, 2)
    assert shares["down"] == shares["pm"]
