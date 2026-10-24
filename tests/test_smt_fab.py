"""Full SMT2020 fab. The six-lot bay stays covered by the other tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import Settings
from resilimes.domain.scenarios import SAMPLE_BAY
from resilimes.smt.fab import LITHO_MTTR_MIN, REWORK_SEC, Fab, Family, Route, load_fab
from resilimes.smt.scenarios import (
    SCENARIOS,
    _xfactor_study_note,
    run_smt,
    scout_provider_mode,
    simulate_pair,
)
from resilimes.smt.simulate import (
    X_FACTOR,
    RunResult,
    macro_aps_ms,
    pm_windows,
    rework_ready,
    run_policy,
    sample_downs,
    setup_seconds,
)
from resilimes.smt.tight import (
    TIGHT_HORIZON_SEC,
    apply_setup_rows,
    apply_tight,
    apply_xfactor,
    local_counts,
    read_benchmark,
    refusal_from_trace,
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
    assert body["horizon"] == "2018-01-01T00:00:00Z"
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
    assert report["focus"]["family"] == "Dielectric_BE_28"
    assert report["focus"]["tools_in_family"] == 3
    bars = report["gantt"]["focus_bars"]
    assert {bar["tool"] for bar in bars} == {
        "Dielectric_BE_28-1",
        "Dielectric_BE_28-2",
        "Dielectric_BE_28-3",
    }
    assert any(float(bar["s"]) >= 12 * 60 for bar in bars)


def test_mock_run_shows_sql_and_rejects_the_down_tool() -> None:
    report = run_smt(
        Settings(mode="mock", fab="smt2020", scout_signing_secret="smt-secret"),
        "litho_down",
        actor_role="planner",
        horizon_sec=30,
    )
    assert report["zetaris"]["called"] is False
    assert report["zetaris"]["queries"][0]["source"] == "resilimes"
    assert report["zetaris"]["dispatcher_input"] == ""
    assert report["refusal"] is None
    assert report["verdict"]["verdict"] == "accept"
    assert report["down_starts"] == []
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
    family = Family(name="Litho_FE_92", group="Litho", tools=2, tool0=0, litho=True, scanner=True)
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


def test_interrupted_lot_goes_to_rework_and_redoes_the_step() -> None:
    fab = _two_scanner_fab([-1, -1])
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=4000,
        downs=[[(100.0, 500.0)], []],
        pm=[[], []],
        trace=True,
        record=True,
    )
    assert result.reworks == 1
    assert any(event[0] == "rework" and event[4] == 0 for event in result.events)
    starts = [event for event in result.events if event[0] == "start"]
    # First start at 0, interrupted at 100. The redo of step 0 waits for the
    # rework hold, then runs the full 1000 s on any qualified scanner.
    assert starts[0][1] == 0.0
    redo = starts[1]
    assert redo[4] == (0,)
    assert redo[1] >= 100.0 + REWORK_SEC
    assert redo[5] - redo[1] == 1000.0
    assert result.completed_routes == 1


def test_later_litho_layer_moves_off_a_down_dedicated_scanner() -> None:
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
    # Layer 1 ran on scanner 1, which is down from 1000 s. Layer 2 is not left
    # waiting on the broken scanner: it re-pins to scanner 2.
    assert {bar["tool"] for bar in result.focus_bars} == {"Litho_FE_92-1", "Litho_FE_92-2"}
    assert result.repins == 1
    assert result.completed_routes == 1


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
    assert rework_ready(100.0) == 100.0 + REWORK_SEC


def _one_tool(name: str, cycles: list[float]) -> Fab:
    family = Family(name=name, group="Litho", tools=1, tool0=0, litho=True, scanner=True)
    remain = [0.0] * len(cycles)
    total = 0.0
    for index in range(len(cycles) - 1, -1, -1):
        total += cycles[index]
        remain[index] = total
    route = Route(
        route_id="r",
        family=[0] * len(cycles),
        cycle=cycles,
        recipe=[0] * len(cycles),
        batch_min=[0] * len(cycles),
        batch_max=[0] * len(cycles),
        cqt_limit=[0.0] * len(cycles),
        cqt_target=[-1] * len(cycles),
        remain=remain,
        step_index={index + 1: index for index in range(len(cycles))},
        dedicate_root=[-1] * len(cycles),
    )
    return Fab(
        families=[family],
        family_index={name: 0},
        tool_family=[0],
        tool_name=[f"{name}-1"],
        routes=[route],
        route_index={"r": 0},
        lot_id=["L1"],
        lot_product=["p"],
        lot_route=[0],
        lot_step=[0],
        lot_due=[100_000.0],
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


def test_overlapping_down_windows_release_at_the_later_end() -> None:
    fab = _one_tool("Litho_FE_92", [100.0])
    result = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=1000,
        downs=[[(0.0, 100.0), (50.0, 400.0)]],
        pm=[[]],
        trace=True,
    )
    assert result.completed_routes == 1
    assert result.focus_bars
    assert min(float(bar["s"]) for bar in result.focus_bars) >= 6.6


def test_drill_bars_keep_starts_after_twelve_hours() -> None:
    fab = _one_tool("Dielectric_BE_28", [13 * 3600.0, 60.0])
    held = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=24 * 3600,
        downs=[[]],
        pm=[[]],
        trace=True,
    )
    full = run_policy(
        fab,
        policy="edd",
        seed=1,
        horizon=24 * 3600,
        downs=[[]],
        pm=[[]],
        trace=True,
        bar_family=0,
        bar_until=24 * 3600,
    )
    assert all(float(bar["s"]) < 12 * 60 for bar in held.focus_bars)
    assert any(float(bar["s"]) >= 13 * 60 for bar in full.focus_bars)


def test_extract_has_forty_four_adjacent_dry_etch_wet_etch_hours() -> None:
    fab = load_fab()
    found = 0
    for route in fab.routes:
        for index, limit in enumerate(route.cqt_limit):
            if route.cqt_target[index] != index + 1 or index + 1 >= len(route.family):
                continue
            if abs(limit - 3600.0) > 1.0:
                continue
            origin = fab.families[route.family[index]].group
            nxt = fab.families[route.family[index + 1]].group
            if origin == "Dry_Etch" and nxt == "Wet_Etch":
                found += 1
    assert found == 44


def test_xfactor_copy_separates_this_run_from_the_five_seed_mean() -> None:
    text = SCENARIOS["xfactor"].summary
    assert "This run is seed 1" in text
    assert "51 under EDD and 41" in text
    assert "452 under EDD and 450" in text
    assert "52.4 vs 73.4" in text
    assert "416.2 vs 441.8" in text
    assert "not this click" in text
    qtime = SCENARIOS["qtime"].summary
    assert "Wet_Etch" in qtime
    assert "0 times" in qtime
    assert "dry" not in qtime.lower()
    before = _card(policy="edd", recleans=24, qtime_violations=428)
    after = _card(policy="resilimes", recleans=31, qtime_violations=418)
    note = _xfactor_study_note(before, after, 1, 48 * 3600.0)
    assert note.startswith("This run (seed 1")
    assert "re-cleans 24" in note
    assert "re-cleans 31" in note
    assert "Five-seed mean" in note
    assert "not this run" in note


def _card(**overrides: object) -> RunResult:
    base: dict[str, object] = {
        "policy": "edd",
        "seed": 1,
        "horizon_sec": 48 * 3600.0,
        "on_time_pct": 100.0,
        "weighted_tardiness_min": 0.0,
        "due_in_horizon": 87,
        "already_late": 0,
        "completed_routes": 1,
        "cycle_time_h": 1.0,
        "mean_step_cycle_min": 1.0,
        "litho_util_pct": 1.0,
        "scanner_util_pct": 1.0,
        "qtime_violations": 428,
        "pm_avoided": 0,
        "pm_overlaps": 0,
        "wip_replans": 0,
        "dispatch_p50_ms": 0.0,
        "dispatch_p95_ms": 0.0,
        "dispatch_decisions": 1,
        "sim_s": 0.1,
        "focus_queue_max": 0,
        "sibling_starts": 0,
        "downstream_queue_max": 0,
        "hot_steps": 0,
        "hot_scanner_start_min": None,
        "recleans": 24,
    }
    base.update(overrides)
    return RunResult(**base)  # type: ignore[arg-type]


def test_refusal_is_null_unless_the_trace_starts_the_down_tool() -> None:
    assert refusal_from_trace([]) is None
    found = refusal_from_trace(
        [{"lot_id": "Init_Lot_1_1", "tool": "Litho_FE_92-1", "t": 10.0, "down_min": 600.0}]
    )
    assert found is not None
    assert found["verdict"] == "reject"
    assert found["tool"] == "Litho_FE_92-1"
    assert "Init_Lot_1_1" in found["detail"]
    assert "event trace contains that start" in found["detail"]


def test_scout_stays_mock_without_a_token_and_follows_live() -> None:
    mock = Settings(mode="mock", fab="smt2020", scout_signing_secret="smt-secret")
    assert scout_provider_mode(mock) == "mock"
    live = Settings(
        mode="live",
        fab="smt2020",
        scout_signing_secret="smt-secret",
        zetaris_api_key="k",
        zetaris_rest_url="http://127.0.0.1:9",
        zetaris_org_id="org",
        meterless_runtime_token="rt-film-token",
    )
    assert scout_provider_mode(live) == "nightshift"


def test_zetaris_setup_rows_feed_the_dispatcher(monkeypatch: Any) -> None:
    fab = load_fab()
    key = next(iter(fab.setup))
    original = fab.setup[key]
    fam, src, dst = key
    row = [
        fab.families[fam].name,
        fab.recipe_name[src],
        fab.recipe_name[dst],
        12345.0,
    ]

    def fake_sql(sql: str) -> dict[str, object]:
        if "COUNT" in sql.upper():
            return {"headers": ["n"], "data": [[1]]}
        return {
            "headers": ["station_group_id", "from_recipe", "to_recipe", "setup_time_sec"],
            "data": [row],
        }

    monkeypatch.setattr("agent.tools_zetaris.run_sql", fake_sql)
    settings = Settings(
        mode="auto",
        fab="smt2020",
        scout_signing_secret="smt-secret",
        zetaris_api_key="k",
        zetaris_rest_url="http://127.0.0.1:9",
        zetaris_org_id="org",
    )
    report = run_smt(settings, "qtime", horizon_sec=30)
    assert report["zetaris"]["called"] is True
    assert report["zetaris"]["error"] == ""
    assert report["zetaris"]["dispatcher_input"] == "resilimes.setup_matrix"
    assert report["zetaris"]["setup_rows_applied"] == 1
    assert "setup_time_sec" in report["query"] or any(
        "setup_time_sec" in item["sql"] for item in report["zetaris"]["queries"]
    )
    assert load_fab().setup[key] == original
    plant, applied = apply_setup_rows(
        fab,
        [
            {
                "station_group_id": row[0],
                "from_recipe": row[1],
                "to_recipe": row[2],
                "setup_time_sec": row[3],
            }
        ],
    )
    assert applied == 1
    assert plant.setup[key] == 12345.0
    assert fab.setup[key] == original


def test_dataset_rules_and_pm_apply_outside_resilimes() -> None:
    fab = load_fab()
    by_name = {item.name: item.rule for item in fab.families}
    assert by_name["Implant_128"] == "rule_LSSU"
    assert by_name["Implant_132"] == "rule_LSSU"
    assert by_name["Implant_91"] == "rule_LSSU"
    assert by_name["Litho_FE_92"] == "rule_HotLotFIRST"
    hot_first = run_policy(
        _pair_fab(rule="rule_HotLotFIRST"),
        policy="smt_rule",
        seed=1,
        horizon=80,
        downs=[[]],
        pm=[[]],
    )
    least_setup = run_policy(
        _pair_fab(rule="rule_LSSU"),
        policy="smt_rule",
        seed=1,
        horizon=80,
        downs=[[]],
        pm=[[]],
    )
    assert hot_first.on_time_pct == 100.0
    assert least_setup.on_time_pct == 0.0
    waited = run_policy(
        _one_tool("Litho_FE_92", [100.0]),
        policy="edd",
        seed=1,
        horizon=1000,
        downs=[[]],
        pm=[[(50.0, 200.0)]],
        trace=True,
        bar_family=0,
        bar_until=1000,
    )
    assert waited.pm_overlaps == 0
    assert waited.pm_avoided > 0
    assert waited.focus_bars
    assert min(float(bar["s"]) for bar in waited.focus_bars) >= 3.3


def _pair_fab(rule: str) -> Fab:
    family = Family(
        name="Implant_128",
        group="Implant",
        tools=1,
        tool0=0,
        litho=False,
        scanner=False,
        rule=rule,
    )

    def route(recipe: int, route_id: str) -> Route:
        return Route(
            route_id=route_id,
            family=[0],
            cycle=[50.0],
            recipe=[recipe],
            batch_min=[0],
            batch_max=[0],
            cqt_limit=[0.0],
            cqt_target=[-1],
            remain=[50.0],
            step_index={1: 0},
            dedicate_root=[-1],
        )

    return Fab(
        families=[family],
        family_index={"Implant_128": 0},
        tool_family=[0],
        tool_name=["Implant_128-1"],
        routes=[route(0, "normal"), route(1, "hot")],
        route_index={"normal": 0, "hot": 1},
        lot_id=["L_normal", "L_hot"],
        lot_product=["p", "p"],
        lot_route=[0, 1],
        lot_step=[0, 0],
        lot_due=[1_000_000.0, 70.0],
        lot_value=[1.0, 2.0],
        lot_class=["normal", "hot"],
        lot_priority=[10, 20],
        recipe_name=["", "SU128_1"],
        setup={(0, 0, 1): 10.0},
        down_mttf={},
        down_mttr={},
        pm=[],
        focus_family=0,
        focus_tool=0,
        hot_lot=1,
        pm_calendar="",
        group_names=["Implant"],
    )


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
