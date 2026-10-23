"""Full SMT2020 fab. The six-lot bay stays covered by the other tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import Settings
from resilimes.domain.scenarios import SAMPLE_BAY
from resilimes.smt.fab import LITHO_MTTR_MIN, Fab, Family, Route, load_fab
from resilimes.smt.scenarios import SCENARIOS, run_smt, simulate_pair
from resilimes.smt.simulate import (
    X_FACTOR,
    interrupt_remaining,
    macro_aps_ms,
    pm_windows,
    run_policy,
    sample_downs,
    setup_seconds,
)
from resilimes.smt.tight import (
    TIGHT_HORIZON_SEC,
    apply_tight,
    apply_xfactor,
    local_counts,
    read_benchmark,
)


def test_extract_counts_match_the_published_fab() -> None:
    fab = load_fab()
    assert len(fab.families) == 106
    assert len(fab.tool_name) == 1313
    assert fab.litho_tools == 102
    assert fab.scanner_tools == 82
    assert fab.products == 10
    assert len(fab.lot_id) == 2156
    assert len(fab.group_names) == 12
    focus = fab.families[fab.focus_family]
    assert focus.name == "Litho_FE_92"
    assert focus.scanner is True
    assert fab.tool_name[fab.focus_tool] == "Litho_FE_92-1"
    assert fab.pm_calendar == "Litho_FE_92_WK"
    assert fab.lot_priority[fab.hot_lot] == 10


def test_sample_bay_is_labeled_and_not_the_default_fab() -> None:
    assert SAMPLE_BAY is True
    assert Settings().fab == "smt2020"
    assert "litho_down" in SCENARIOS
    assert "LOT-1001" not in SCENARIOS["litho_down"].summary


def test_short_horizon_dispatches_the_full_tool_set() -> None:
    fab = load_fab()
    horizon = 20 * 60.0
    downs = sample_downs(
        fab,
        1,
        horizon,
        forced_tool=fab.focus_tool,
        forced_until=LITHO_MTTR_MIN * 60.0,
    )
    pm = pm_windows(fab, horizon)
    result = run_policy(
        fab,
        policy="resilimes",
        seed=1,
        horizon=horizon,
        downs=downs,
        pm=pm,
        trace=False,
        focus_down_until=LITHO_MTTR_MIN * 60.0,
    )
    assert result.dispatch_decisions >= 1000
    assert result.dispatch_p95_ms >= result.dispatch_p50_ms
    assert result.sim_s < 30
    assert result.sibling_starts > 0
    aps_ms, steps = macro_aps_ms(fab)
    assert steps > 1000
    assert aps_ms < 5000


def test_api_default_lists_the_full_fab_scenarios() -> None:
    client = TestClient(create_app(Settings(mode="mock", fab="smt2020")))
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["data_source"] == "smt2020"
    assert body["groups"] == 106
    assert body["tools"] == 1313
    assert body["litho_tools"] == 102
    assert body["lots"] == 2156
    scenarios = client.get("/api/scenarios")
    assert scenarios.status_code == 200
    payload = scenarios.json()
    assert payload["data_source"] == "smt2020"
    assert {item["id"] for item in payload["scenarios"]} == {
        "litho_down",
        "hot_lot",
        "pm_avoid",
        "wip_threshold",
        "qtime",
        "tight_p1",
        "xfactor",
    }
    assert all(item["kind"] == "group" for item in payload["bay"])
    assert "LITHO-02" not in {item["id"] for item in payload["bay"]}
    page = client.get("/")
    assert "query-line" in page.text


def test_tight_book_is_a_constructed_due_stress() -> None:
    fab = load_fab()
    book = apply_tight(fab)
    assert fab.tool_name[book.down_tool] == "Dielectric_BE_28-1"
    assert len(book.p1) == 8
    assert len(book.decoy) == 13
    assert book.fab.lot_class[book.p1[0]] == "VIP"
    assert book.fab.lot_due[book.p1[0]] == 8 * 3600
    assert book.fab.lot_due[book.decoy[0]] == 7.2 * 3600
    assert book.fab.lot_due[0] > TIGHT_HORIZON_SEC or 0 in book.p1 or 0 in book.decoy
    counts = local_counts(fab)
    assert counts["lots"] == 2156
    assert counts["operations"] == 4013
    read = read_benchmark(Settings(mode="mock", fab="smt2020"), fab)
    assert read["called"] is False
    assert read["mode"] == "extract"
    assert read["sources"] == ["resilimes", "fab_cmms", "fab_erp"]
    sql = "\n".join(item["sql"] for item in read["queries"])
    assert "SELECT COUNT(*) AS n FROM resilimes.lots" in sql
    assert "fab_cmms.pm_calendar" in sql
    assert "fab_erp.orders" in sql
    assert read["row_counts"]["lots"] == 2156


def test_tight_vip_dues_make_edd_lose_on_seed_one() -> None:
    fab = load_fab()
    scenario = SCENARIOS["tight_p1"]
    report = simulate_pair(fab, scenario, seed=1, horizon=TIGHT_HORIZON_SEC)
    before = report["kpis"]["before"]
    after = report["kpis"]["after"]
    assert before["policy"] == "edd"
    assert after["on_time_pct"] > before["on_time_pct"]
    assert after["weighted_tardiness_min"] < before["weighted_tardiness_min"] * 0.7
    assert after["qtime_violations"] < before["qtime_violations"]
    tight = report["tight"]
    assert tight["spotlight_lot"] == "Init_Lot_2_23"
    assert tight["spotlight_late_h_before"] > 5
    assert tight["spotlight_late_h_after"] == 0
    assert "public industry benchmark (SMT2020)" in tight["note"]


def test_mock_run_shows_sql_and_rejects_the_down_tool() -> None:
    report = run_smt(
        Settings(mode="mock", fab="smt2020", scout_signing_secret="smt-secret"),
        "litho_down",
        actor_role="planner",
        horizon_sec=30,
    )
    assert report["zetaris"]["called"] is False
    assert report["zetaris"]["queries"][0]["source"] == "resilimes"
    assert report["refusal"]["verdict"] == "reject"
    assert report["refusal"]["tool"] == "Litho_FE_92-1"
    assert report["refusal"]["lot_id"]
    assert report["explain"]["mocked"] is True
    assert report["explain"]["meterless_request_id"] == ""


def test_litho_dedication_follows_forward_same_family_links() -> None:
    fab = load_fab()
    covered = 0
    later = 0
    for route in fab.routes:
        assert len(route.dedicate_root) == len(route.family)
        for index, root in enumerate(route.dedicate_root):
            if root < 0:
                continue
            covered += 1
            assert route.family[root] == route.family[index]
            assert root <= index
            if root != index:
                later += 1
    assert covered == 99
    assert later == 73


def _two_scanner_fab(dedicate_root: list[int]) -> Fab:
    family = Family(
        name="Litho_FE_92", group="Litho", tools=2, tool0=0, litho=True, scanner=True
    )
    route = Route(
        route_id="r",
        family=[0, 0],
        cycle=[1000.0, 100.0],
        recipe=[0, 0],
        batch_min=[0, 0],
        batch_max=[0, 0],
        cqt_limit=[0.0, 0.0],
        cqt_target=[-1, -1],
        remain=[1100.0, 100.0],
        step_index={1: 0, 2: 1},
        dedicate_root=dedicate_root,
    )
    return Fab(
        families=[family],
        family_index={"Litho_FE_92": 0},
        tool_family=[0, 0],
        tool_name=["Litho_FE_92-1", "Litho_FE_92-2"],
        routes=[route],
        route_index={"r": 0},
        lot_id=["L1"],
        lot_product=["p"],
        lot_route=[0],
        lot_step=[0],
        lot_due=[10_000.0],
        lot_value=[1.0],
        lot_class=["normal"],
        lot_priority=[10],
        recipe_name=[""],
        setup={},
        down_mttf={},
        down_mttr={},
        pm=[],
        focus_family=0,
        focus_tool=0,
        hot_lot=0,
        pm_calendar="",
        group_names=["Litho"],
    )


def test_interrupted_lot_resumes_on_the_same_scanner() -> None:
    fab = _two_scanner_fab([-1, -1])
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=4000,
        downs=[[(100.0, 500.0)], []],
        pm=[[], []],
        trace=True,
    )
    bars = result.focus_bars
    # The interrupted 1000 s piece resumes on scanner 1 after disposition.
    # The next layer is not dedicated, so scanner 2 may run that layer.
    assert any(bar["tool"] == "Litho_FE_92-1" and float(bar["s"]) >= 15 for bar in bars)
    assert all(float(bar["s"]) >= 30 for bar in bars if bar["tool"] == "Litho_FE_92-2")
    assert result.completed_routes == 1


def test_later_litho_layer_waits_for_the_scanner_that_ran_the_first() -> None:
    fab = _two_scanner_fab([0, 0])
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=2000,
        downs=[[(1000.0, 5000.0)], []],
        pm=[[], []],
        trace=True,
    )
    assert {bar["tool"] for bar in result.focus_bars} == {"Litho_FE_92-1"}
    assert result.completed_routes == 0


def test_xfactor_dues_are_remaining_process_times_the_factor() -> None:
    fab = load_fab()
    plant = apply_xfactor(fab)
    assert plant is not fab
    assert plant.lot_due is not fab.lot_due
    for index, (route_i, step) in enumerate(zip(fab.lot_route, fab.lot_step, strict=True)):
        assert plant.lot_due[index] == fab.routes[route_i].remain[step] * X_FACTOR
        if index > 20:
            break


def test_scanner_families_have_no_setup_and_a_breakdown_stops_the_clock() -> None:
    fab = load_fab()
    for family in fab.families:
        if not family.scanner:
            continue
        for key, seconds in fab.setup.items():
            assert key[0] != fab.family_index[family.name] or seconds == 0
    assert setup_seconds(fab, fab.focus_family, 0, 1) == 0
    remain, ready = interrupt_remaining(0.0, 100.0, 400.0)
    assert remain == 300.0
    assert ready == 100.0 + 15.0 * 60.0
    done, _ready = interrupt_remaining(0.0, 400.0, 400.0)
    assert done == 0.0


def test_viewer_is_blocked_before_the_sim() -> None:
    report = run_smt(
        Settings(mode="mock", fab="smt2020", scout_signing_secret="smt-secret"),
        "litho_down",
        actor_role="viewer",
        horizon_sec=60,
    )
    assert report["blocked"] is True
    assert report["data_source"] == "smt2020"
    assert "query" in report
