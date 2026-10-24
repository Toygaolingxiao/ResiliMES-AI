"""Read-only full-fab views over the recorded SMT2020 replay, and full-fab intents."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import Settings
from resilimes.smt import replay
from resilimes.smt.fab import load_fab
from resilimes.smt.intents import find_ids, smt_id_errors, smt_tool_call

T = 20 * 3600.0
STATES = {"run", "idle", "setup", "down", "pm", "batch_wait"}
REASONS = {
    "vip",
    "hot",
    "late",
    "qtime",
    "rework",
    "batch",
    "same_recipe",
    "setup",
    "slack",
    "pm_skip",
    "pm_blocked",
}


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    os.environ["RESILIMES_NO_WARM"] = "1"
    app = create_app(Settings(mode="mock", fab="smt2020"))
    with TestClient(app) as test_client:
        yield test_client


def get(client: TestClient, path: str, **params: Any) -> dict[str, Any]:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_meta_is_the_full_benchmark(client: TestClient) -> None:
    body = get(client, "/api/fab/meta")
    assert body["source"] == "public industry benchmark (SMT2020)"
    assert "real data" not in str(body).lower()
    assert body["lots"] == len(body["lot_id"]) == 2156
    assert body["tools"] == 1313
    assert len(body["families"]) == 106
    assert len(body["routes"]) == 10
    assert body["horizon"] == 48 * 3600
    assert {row["key"] for row in body["books"]} == set(replay.SCENARIO_BOOKS)


def test_overview_accounts_for_every_lot_and_tool(client: TestClient) -> None:
    start = get(client, "/api/fab/overview", t=0)
    assert start["lots"]["done"] == 0
    body = get(client, "/api/fab/overview", t=T)
    assert sum(body["lots"][key] for key in ("wait", "run", "hold", "done")) == 2156
    assert sum(body["tools"].values()) == 1313
    assert body["bottlenecks"]
    assert all(row["util"] <= 1.0 for row in body["bottlenecks"])
    assert all(row["kind"] in {"VIP", "hot"} for row in body["priority"])
    # 80 on main after qtime-r2, transport and later sim changes (159 on the ui-r1 base).
    assert body["counters"]["completed_routes"] == 80


def test_tools_view_states_and_reasons(client: TestClient) -> None:
    body = get(client, "/api/fab/tools", t=T)
    assert len(body["groups"]) == 12
    assert body["families"]
    for family in body["families"]:
        for tool in family["tools"]:
            assert tool["state"] in STATES
            assert len(tool["next"]) <= 4
            for item in tool["next"]:
                assert {reason["code"] for reason in item.get("reasons", [])} <= REASONS
            if tool["state"] == "run":
                assert 0.0 <= tool["progress"] <= 1.0
        for row in family["queue_top"]:
            assert {reason["code"] for reason in row["reasons"]} <= REASONS
    diffusion = get(client, "/api/fab/tools", t=T, group="Diffusion")
    assert any(family["batch"] for family in diffusion["families"])
    one = get(client, "/api/fab/tools", t=T, family="Dielectric_BE_28")
    assert [family["family"] for family in one["families"]] == ["Dielectric_BE_28"]


def test_flow_covers_all_lots(client: TestClient) -> None:
    body = get(client, "/api/fab/flow", t=T)
    assert len(body["products"]) == 10
    assert sum(len(product["lots"]) for product in body["products"]) == 2156
    for product in body["products"]:
        assert sum(product["counts"].values()) == len(product["lots"])
        assert all(0 <= row[1] <= product["steps"] for row in product["lots"])
    assert len(body["wip_by_group"]) == 12


def test_lot_detail(client: TestClient) -> None:
    body = get(client, "/api/fab/lot/init_lot_3_17", t=T)
    assert body["lot"] == "Init_Lot_3_17"
    starts = [op["start"] for op in body["ops"]]
    assert starts == sorted(starts)
    assert all(op["start"] >= op["ready"] - 1e-6 for op in body["ops"])
    assert client.get("/api/fab/lot/LOT-9999").status_code == 404


def test_batches_respect_capacity(client: TestClient) -> None:
    body = get(client, "/api/fab/batches", t=T)
    assert body["running"]
    for row in body["running"]:
        assert row["wafers"] <= row["max"]
        assert row["family"].startswith("Diffusion")
    for row in body["forming"]:
        assert row["waiting_for"]


def test_events_window_and_filter(client: TestClient) -> None:
    body = get(client, "/api/fab/events", t0=3600, t1=T, limit=50)
    assert body["t1"] == T
    assert body["events"]
    assert all(3600 <= row["t"] <= T for row in body["events"])
    times = [row["t"] for row in body["events"]]
    assert times == sorted(times, reverse=True)
    downs = get(client, "/api/fab/events", kind="down", limit=20)
    assert {row["kind"] for row in downs["events"]} == {"down"}
    assert downs["breakdowns"]
    # A lot's class rides in "class" so it never shadows the event kind.
    promoted = get(client, "/api/fab/events", kind="priority,done", limit=50)
    assert {row["kind"] for row in promoted["events"]} <= {"priority", "done"}
    assert all(row["class"] in {"VIP", "hot", "normal"} for row in promoted["events"])


def test_kpis_match_the_replay(client: TestClient) -> None:
    body = get(client, "/api/fab/kpis")
    names = [period["name"] for period in body["periods"]]
    assert names == ["day1", "day2", "all"]
    whole = body["periods"][-1]
    assert whole["due_date"]["completed"] == body["counters"]["completed_routes"]
    assert 0.0 <= whole["qtime"]["rate"] <= 100.0
    assert round(sum(whole["activity"].values())) == 100


def test_bad_book_and_sample_fab(client: TestClient) -> None:
    assert client.get("/api/fab/overview", params={"book": "nope"}).status_code == 404
    assert client.get("/api/fab/overview", params={"book": "../x"}).status_code == 422
    sample = TestClient(create_app(Settings(mode="mock", fab="sample")))
    assert sample.get("/api/fab/meta").status_code == 404


def test_full_fab_ids_resolve() -> None:
    fab = load_fab()
    ids = find_ids(fab, "litho_fe_92-1 and init_hotlot_2_1 near Dry_Etch")
    assert ids.tool == "Litho_FE_92-1"
    assert ids.family == "Litho_FE_92"
    assert ids.lot == "Init_HotLot_2_1"
    assert ids.group == "Dry_Etch"
    down = smt_tool_call(fab, "Litho_FE_92-1 down for 90 min")
    assert down is not None and down.intent == "mark_tool_down"
    assert down.parameters.equipment_id == "Litho_FE_92-1"
    assert smt_id_errors(fab, down) == []
    family = smt_tool_call(fab, "DE_BE_11 is down 30 min")
    assert family is not None
    assert "DE_BE_11-1" in smt_id_errors(fab, family)[0]


def test_full_fab_intent_runs_a_whatif_book(client: TestClient) -> None:
    proposed = client.post("/api/intents", json={"incident": "rush Init_Lot_3_17 to Dry_Etch"})
    body = proposed.json()
    assert body["status"] == "pending_confirmation", body
    assert body["call"]["parameters"]["lot_id"] == "Init_Lot_3_17"
    done = client.post("/api/intents/confirm", json={"confirmation_id": body["confirmation_id"]})
    result = done.json()
    assert result["status"] == "executed"
    assert result["committed"] is False and result["simulated"] is True
    assert result["book"].startswith("whatif-")
    assert result["kpis"]["before"]["on_time_delivery_pct"] == 57.14
    meta = get(client, "/api/fab/meta", book=result["book"])
    assert meta["promoted"] == "Init_Lot_3_17"
    lot = get(client, "/api/fab/lot/Init_Lot_3_17", book=result["book"])
    assert lot["kind"] == "VIP"


def test_bay_ids_keep_the_sample_plant_path(client: TestClient) -> None:
    body = client.post("/api/intents", json={"incident": "ETCH-02 is down for 45 min"}).json()
    assert body["status"] == "pending_confirmation", body
    assert body["call"]["parameters"]["equipment_id"] == "ETCH-02"


def test_full_fab_family_name_is_rejected_with_a_hint(client: TestClient) -> None:
    body = client.post("/api/intents", json={"incident": "DE_BE_11 is down 30 min"}).json()
    assert body["status"] == "rejected"
    assert "DE_BE_11-1" in body["errors"][0]


def test_full_fab_hold_is_not_modelled(client: TestClient) -> None:
    body = client.post("/api/intents", json={"incident": "hold Init_Lot_9_203"}).json()
    assert body["status"] == "pending_confirmation"
    result = client.post(
        "/api/intents/confirm", json={"confirmation_id": body["confirmation_id"]}
    ).json()
    assert result["status"] == "aborted"
    assert result["book"] is None
