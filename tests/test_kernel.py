"""DPI, PM skip, batching, APS, and the txn lock."""

from __future__ import annotations

import time

import pytest

from resilimes.config import ROOT, Settings
from resilimes.data.smt2020_kernel import load_tables
from resilimes.kernel.aps import StepLoad, backward_dues, schedule_bottleneck
from resilimes.kernel.dispatch import Candidate, MaintWindow, choose, setup_seconds
from resilimes.kernel.erp import (
    DemandOrder,
    litho_capacity_gap,
    master_schedule,
    material_check,
    release_count,
)
from resilimes.kernel.score import (
    dispatch_score,
    dynamic_priority,
    order_class_from_priority,
    score_terms,
)
from resilimes.txn.engine import InMemoryEngine, LockError
from resilimes.txn.store import InMemoryStateStore, build_store


def test_dpi_rises_as_slack_falls_and_caps_when_late() -> None:
    early = dynamic_priority(due_sec=10_000, now_sec=0, remaining_sec=100, order_class="normal")
    tight = dynamic_priority(due_sec=500, now_sec=0, remaining_sec=100, order_class="normal")
    late = dynamic_priority(due_sec=0, now_sec=0, remaining_sec=100, order_class="normal")
    assert tight.index > early.index
    assert late.late is True
    assert late.urgency == 60
    assert late.index >= tight.index
    assert early.late is False
    vip = dynamic_priority(due_sec=10_000, now_sec=0, remaining_sec=100, order_class="VIP")
    hot = dynamic_priority(due_sec=10_000, now_sec=0, remaining_sec=100, order_class="hot")
    assert vip.lot_value > hot.lot_value > early.lot_value
    priced = dynamic_priority(
        due_sec=10_000, now_sec=0, remaining_sec=100, order_class="normal", margin_tier="high"
    )
    assert priced.lot_value == early.lot_value + 1


def test_score_adds_ped_subtracts_setup_and_does_not_weight_cr() -> None:
    assert order_class_from_priority(30) == "VIP"
    assert order_class_from_priority(20) == "hot"
    assert order_class_from_priority(1) == "VIP"
    assert order_class_from_priority(2) == "hot"
    low_setup = dispatch_score(dpi=2, setup_sec=0, ped=0)
    high_setup = dispatch_score(dpi=2, setup_sec=60, ped=0)
    high_ped = dispatch_score(dpi=2, setup_sec=60, ped=5)
    assert high_setup < low_setup
    assert high_ped > high_setup
    terms = score_terms(dpi=2, setup_sec=60, ped=1, cr_reference=-4)
    assert terms["score"] == pytest.approx(dispatch_score(dpi=2, setup_sec=60, ped=1))
    assert terms["cr_reference"] == -4
    assert "hot" not in terms
    assert set(terms) == {
        "dpi",
        "w_dpi_dpi",
        "setup_sec",
        "w_setup_setup",
        "ped_risk",
        "w_ped_ped",
        "cr_reference",
        "score",
    }


def test_pm_window_skips_the_highest_dpi_lot() -> None:
    window = MaintWindow(start_sec=30 * 60, end_sec=90 * 60, kind="pm")
    long_lot = Candidate("LOT-x", "R", process_min=180, dpi=100, arrival_sec=0)
    short_lot = Candidate("LOT-y", "R", process_min=20, dpi=1, arrival_sec=1)
    decision = choose(
        equipment_id="LITHO-01",
        candidates=[long_lot, short_lot],
        now_sec=0,
        windows=[window],
    )
    assert decision.selected == ["LOT-y"]
    assert decision.skips == ["skipped LOT-x: 180 min > 30 min to PM"]
    assert decision.interrupted_runs_avoided == 1
    assert decision.pm_adherence == 1.0


def test_batch_packs_to_capacity_and_holds_a_short_partial() -> None:
    full = [
        Candidate(
            "A", "R", 10, dpi=1, arrival_sec=0, wafers=25, requires_batch=True, batch_size=50
        ),
        Candidate(
            "B", "R", 10, dpi=3, arrival_sec=1, wafers=25, requires_batch=True, batch_size=50
        ),
    ]
    packed = choose(equipment_id="FUR-01", candidates=full, now_sec=10)
    assert set(packed.selected) == {"A", "B"}
    partial = [
        Candidate(
            "C", "R", 10, dpi=9, arrival_sec=10, wafers=25, requires_batch=True, batch_size=50
        )
    ]
    held = choose(equipment_id="FUR-01", candidates=partial, now_sec=10, max_wait_sec=1800)
    assert held.selected == []
    waited = choose(equipment_id="FUR-01", candidates=partial, now_sec=10 + 1800, max_wait_sec=1800)
    assert waited.selected == ["C"]
    matrix = {("DE", "DE_BE_13_1", "DE_BE_13_2"): 420.0}
    assert setup_seconds(matrix, "DE", "DE_BE_13_1", "DE_BE_13_1") == 0
    assert setup_seconds(matrix, "DE", "DE_BE_13_1", "DE_BE_13_2") == 420
    assert setup_seconds(matrix, "DE", "missing", "other") == 0


def test_lock_uses_compare_and_set_on_the_txn_store() -> None:
    store = InMemoryStateStore()
    assert isinstance(build_store(""), InMemoryStateStore)
    engine = InMemoryEngine(store)
    lock = engine.acquire_lock(["LITHO-01"])
    assert store.get("lock:LITHO-01") == lock.lock_token
    with pytest.raises(LockError, match="already locked"):
        engine.acquire_lock(["LITHO-01"])
    engine.abort(lock)
    assert store.get("lock:LITHO-01") is None
    settings = Settings(redis_url="")
    assert settings.redis_url == ""


def test_aps_places_the_second_scanner_after_the_first() -> None:
    assert backward_dues([10, 20], 100) == [80, 100]
    rows = schedule_bottleneck(
        [
            [StepLoad("A", "scan", 10, True)],
            [StepLoad("B", "scan", 10, True)],
        ],
        [[0], [1]],
        scanners=1,
    )
    by_lot = {row.lot_id: row for row in rows}
    assert by_lot["B"].start_sec == by_lot["A"].start_sec + 10
    around = schedule_bottleneck(
        [
            [
                StepLoad("L", "clean", 10, False),
                StepLoad("L", "scan", 30, True),
                StepLoad("L", "etch", 5, False),
            ]
        ],
        [[100, 100, 100]],
        scanners=1,
    )
    by_op = {row.op_id: row for row in around}
    assert by_op["clean"].end_sec == by_op["scan"].start_sec
    assert by_op["etch"].start_sec == by_op["scan"].end_sec


def test_mps_uses_the_release_interval_not_the_repeat_count() -> None:
    assert release_count(258.46, 48 * 60) == 12
    assert release_count(10080, 48 * 60) == 1
    order = DemandOrder(
        order_id="O_HotLot_1",
        product_id="part_1",
        qty_wafers=25,
        interval_min=10080,
        order_class="hot",
        customer="derived:O_HotLot_1",
        margin_tier="unpriced",
    )
    rows = master_schedule([order], horizon_min=48 * 60)
    assert sum(int(row["lots"]) for row in rows) == 1
    gap = litho_capacity_gap(demand_min=100, scanner_tools=2, horizon_min=48 * 60)
    assert gap["gap_min"] == 100 - 2 * 48 * 60
    check = material_check({"part_9": 3}, {}, {})
    assert check[0]["status"] == "unchecked"


def test_dispatch_choose_stays_under_5ms() -> None:
    candidates = [
        Candidate(f"L{i}", "R", process_min=10, dpi=float(i), arrival_sec=float(i))
        for i in range(30)
    ]
    choose(equipment_id="T", candidates=candidates, now_sec=0)
    started = time.perf_counter()
    for _ in range(50):
        choose(equipment_id="T", candidates=candidates, now_sec=0)
    mean = (time.perf_counter() - started) / 50
    assert mean < 0.005


def test_smt2020_kernel_rows_match_the_published_files() -> None:
    tables = load_tables(ROOT / "data" / "smt2020")
    wet = next(step for step in tables.operations if step.op_id == "r_1:30")
    assert wet.max_ped_sec == 7200
    assert wet.ped_target_op_id == "r_1:31"
    assert wet.std_cycle_time == pytest.approx(1.14 * 25 * 60)
    dry = next(step for step in tables.operations if step.op_id == "r_1:36")
    assert dry.max_ped_sec == 3600
    assert dry.ped_target_op_id == "r_1:37"
    furnace = next(step for step in tables.operations if step.op_id == "r_1:1")
    assert furnace.std_cycle_time == pytest.approx(440.4 * 60)
    assert furnace.requires_batch is True
    setup = next(
        row
        for row in tables.setups
        if row.station_group_id == "DE_BE_13"
        and row.from_recipe == "DE_BE_13_1"
        and row.to_recipe == "DE_BE_13_2"
    )
    assert setup.setup_time_sec == 420
    hot = next(order for order in tables.orders if order.order_id == "O_HotLot_1")
    assert hot.order_class == "hot"
    assert hot.customer == "derived:O_HotLot_1"
    assert hot.margin_tier == "unpriced"
    assert hot.qty == 25
    assert hot.release_interval_min == 10080
    assert all(lot.ped_remaining_sec is None for lot in tables.lots)
    assert tables.lots
    assert "Litho_BE_110" in tables.scanner_families
    assert all("Track" not in family and "Met" not in family for family in tables.scanner_families)
    pm = next(row for row in tables.pm_calendar if row.cal_name == "Litho_BE_110_WK")
    assert pm.family == "Litho_BE_110"
    assert pm.duration_sec == pytest.approx(6.65 * 3600)
    assert pm.first_start_sec == pytest.approx(7 * 86400)
    assert len({step.op_id for step in tables.operations}) == len(tables.operations)
    assert len({lot.lot_id for lot in tables.lots}) == len(tables.lots)
    assert len({order.order_id for order in tables.orders}) == len(tables.orders)
    assert len({row.cal_name for row in tables.pm_calendar}) == len(tables.pm_calendar)
    setup_keys = {(row.station_group_id, row.from_recipe, row.to_recipe) for row in tables.setups}
    assert len(setup_keys) == len(tables.setups)


def test_kernel_sql_is_split_by_database() -> None:
    from resilimes.data.zetaris_layout import split_sql

    buckets = split_sql((ROOT / "data" / "sql" / "kernel.sql").read_text(encoding="utf-8"))
    assert "CREATE TABLE resilimes.lots" in buckets["fab_mes"]
    assert "CREATE TABLE resilimes.operations" in buckets["fab_mes"]
    assert "CREATE TABLE resilimes.setup_matrix" in buckets["fab_mes"]
    assert "CREATE TABLE resilimes.orders" in buckets["fab_erp"]
    assert "CREATE TABLE resilimes.pm_calendar" in buckets["fab_cmms"]
    assert "resilimes.orders" not in buckets["fab_mes"]
    assert "resilimes.lots" not in buckets["fab_erp"]
    assert "resilimes.pm_calendar" not in buckets["fab_mes"]


def test_redis_store_round_trip() -> None:
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url("redis://127.0.0.1:6379/0", socket_connect_timeout=0.2)
    try:
        client.ping()
    except Exception:
        pytest.skip("redis unreachable")
    from resilimes.txn.store import RedisStateStore

    store = RedisStateStore("redis://127.0.0.1:6379/0")
    key = "lock:LITHO-TEST"
    client.delete(key)
    assert store.compare_and_set(key, None, "token-a") is True
    assert store.compare_and_set(key, None, "token-b") is False
    assert store.get(key) == "token-a"
    assert store.compare_and_set(key, "token-a", "token-c") is True
    store.delete(key)
    assert store.get(key) is None
