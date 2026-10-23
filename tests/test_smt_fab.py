"""Full SMT2020 fab. The six-lot bay stays covered by the other tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import Settings
from resilimes.domain.scenarios import SAMPLE_BAY
from resilimes.smt.fab import LITHO_MTTR_MIN, load_fab
from resilimes.smt.scenarios import SCENARIOS, run_smt
from resilimes.smt.simulate import macro_aps_ms, pm_windows, run_policy, sample_downs


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
    }
    assert all(item["kind"] == "group" for item in payload["bay"])
    assert "LITHO-02" not in {item["id"] for item in payload["bay"]}
    page = client.get("/")
    assert "query-line" in page.text


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
