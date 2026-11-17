"""Timeline contract: two row axes, filters, and the page that draws them."""

from __future__ import annotations

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.timeline.model import (
    Bar,
    Block,
    Book,
    LotInfo,
    Machine,
    TimelineQuery,
    machine_rows,
    product_rows,
    window_payload,
)


def _bar(
    lot: str,
    machine: str,
    start: float,
    end: float,
    *,
    product: str = "PROD-A28",
    group: str = "Lithography",
    step: str = "LITHO",
    priority: int = 1,
    late: bool = False,
    qtime: str = "",
    pinned: bool = False,
    setup: float = 0.0,
    recipe: str = "R1",
) -> Bar:
    return Bar(
        id=f"{lot}|{step}|{start}|{machine}",
        lot=lot,
        product=product,
        machine=machine,
        group=group,
        step=step,
        recipe=recipe,
        start_min=start,
        end_min=end,
        setup_min=setup,
        priority=priority,
        due_min=600.0,
        late=late,
        qtime=qtime,
        rework=False,
        pinned=pinned,
        qty=25,
    )


def _book(*bars: Bar, blocks: list[Block] | None = None) -> Book:
    lots = {
        bar.lot: LotInfo(bar.lot, bar.product, bar.priority, bar.due_min, bar.late, bar.qty)
        for bar in bars
    }
    machines = {
        bar.machine: Machine(bar.machine, bar.machine, bar.group, bar.group) for bar in bars
    }
    for block in blocks or []:
        machines.setdefault(block.machine, Machine(block.machine, block.machine, "Lithography", ""))
    return Book(
        source="sample",
        seed=1,
        horizon_h=24.0,
        origin="2026-10-22T06:30:00Z",
        horizon_min=24 * 60.0,
        shift_min=480.0,
        machines=list(machines.values()),
        lots=list(lots.values()),
        bars=list(bars),
        blocks=blocks or [],
        skips=2,
    )


def test_rows_group_machines_and_products() -> None:
    machines = [
        Machine("ETCH-01", "Etch 1", "Etch", "etch"),
        Machine("LITHO-02", "Litho 2", "Lithography", "litho"),
        Machine("LITHO-01", "Litho 1", "Lithography", "litho"),
    ]
    rows = machine_rows(machines)
    assert [row["kind"] for row in rows] == ["group", "machine", "group", "machine", "machine"]
    assert rows[0]["label"] == "Etch"
    assert rows[3]["id"] == "LITHO-01"
    assert rows[4]["parent"] == "g:Lithography"
    lots = [
        LotInfo("LOT-1002", "PROD-A28", 2, 100, False, 25),
        LotInfo("LOT-2001", "PROD-B14", 1, 100, True, 25),
        LotInfo("LOT-1001", "PROD-A28", 1, 100, False, 25),
    ]
    product = product_rows(lots)
    assert product[0] == {
        "kind": "product",
        "id": "p:PROD-A28",
        "label": "PROD-A28",
        "count": 2,
    }
    assert [row["id"] for row in product if row["kind"] == "lot"] == [
        "LOT-1001",
        "LOT-1002",
        "LOT-2001",
    ]


def test_states_gaps_qtime_and_the_lot_cap() -> None:
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 20, setup=5),
        _bar("LOT-1", "ETCH-01", 23, 40, group="Etch"),
        _bar("LOT-1", "CMP-01", 80, 100, group="CMP"),
        _bar("LOT-2", "LITHO-01", 30, 50, pinned=True),
        _bar("LOT-3", "WET-01", 0, 10, group="Wet", priority=3, late=True, qtime="breach"),
        _bar("LOT-4", "WET-01", 10, 20, group="Wet", priority=3, qtime="risk"),
        blocks=[Block("LITHO-02", "down", 0, 600), Block("CMP-01", "pm", 0, 40)],
    )
    payload = window_payload(book, TimelineQuery(t0=0, t1=200, lots=10, now_min=10))
    by_start = {(bar["lot"], bar["start_min"]): bar for bar in payload["bars"]}  # type: ignore[index]
    assert by_start[("LOT-1", 0.0)]["state"] == "processing"
    assert by_start[("LOT-1", 0.0)]["setup_min"] == 5
    assert by_start[("LOT-2", 30.0)]["state"] == "reserved"
    assert by_start[("LOT-3", 0.0)]["late"] is True
    assert by_start[("LOT-3", 0.0)]["qtime"] == "breach"
    assert by_start[("LOT-4", 10.0)]["qtime"] == "risk"
    gaps = {gap["state"] for gap in payload["gaps"]}  # type: ignore[index]
    assert gaps == {"transport", "waiting"}
    assert any(block["kind"] == "down" for block in payload["blocks"])  # type: ignore[union-attr]
    assert payload["stats"]["skip_count"] == 2  # type: ignore[index]
    assert payload["daily"][0]["jobs"] >= 1  # type: ignore[index]
    capped = window_payload(book, TimelineQuery(t0=0, t1=200, lots=1, focus="LOT-3"))
    kept = {bar["lot"] for bar in capped["bars"]}  # type: ignore[index]
    assert "LOT-3" in kept
    assert len(kept) <= 2


def test_filters_use_wildcards_and_drop_bars_outside_the_window() -> None:
    book = _book(
        _bar("LOT-1001", "LITHO-01", 10, 40),
        _bar("LOT-2001", "ETCH-01", 10, 40, product="PROD-B14", group="Etch", priority=2),
        _bar("LOT-1001", "LITHO-01", 900, 940, step="CMP"),
    )
    payload = window_payload(
        book, TimelineQuery(t0=0, t1=100, machine="LITHO*", product="PROD-A28", priority=1)
    )
    assert [bar["step"] for bar in payload["bars"]] == ["LITHO"]  # type: ignore[index]
    assert payload["bars"][0]["end_min"] == 40  # type: ignore[index]
    searched = window_payload(book, TimelineQuery(t0=0, t1=100, q="ETCH"))
    assert searched["bars"][0]["machine"] == "ETCH-01"  # type: ignore[index]


def test_two_thousand_machine_rows_stay_grouped() -> None:
    machines = [
        Machine(f"T{index:04d}", f"T{index:04d}", f"G{index // 100}", "fam")
        for index in range(2000)
    ]
    rows = machine_rows(machines)
    assert sum(1 for row in rows if row["kind"] == "machine") == 2000
    assert rows[0]["kind"] == "group"


def _client() -> TestClient:
    settings = Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="timeline")
    return TestClient(create_app(settings))


def test_api_groups_filters_and_serves_the_page() -> None:
    client = _client()
    body = client.get("/api/timeline", params={"t0": 0, "t1": 5000, "lots": 100}).json()
    assert body["contract"] == "timeline/v1"
    assert body["source"] == "sample"
    assert body["bars"]
    assert any(row["kind"] == "group" for row in body["machine_rows"])
    assert any(
        row["kind"] == "machine" and str(row["parent"]).startswith("g:")
        for row in body["machine_rows"]
    )
    assert any(row["label"] == "PROD-A28" for row in body["product_rows"])
    children = [row for row in body["product_rows"] if row.get("parent") == "p:PROD-A28"]
    assert any(row["id"] == "LOT-1001" for row in children)
    assert any(
        block["machine"] == "LITHO-02" and block["kind"] == "down" for block in body["blocks"]
    )
    narrowed = client.get(
        "/api/timeline", params={"t0": 0, "t1": 5000, "product": "PROD-A28", "priority": 1}
    ).json()
    assert narrowed["bars"]
    assert {bar["product"] for bar in narrowed["bars"]} == {"PROD-A28"}
    assert {bar["priority"] for bar in narrowed["bars"]} == {1}
    assert client.get("/api/timeline", params={"t0": 20, "t1": 10}).status_code == 422
    page = client.get("/timeline")
    assert page.status_code == 200
    assert "/assets/product/timeline/timeline.js" in page.text
    script = client.get("/assets/product/timeline/timeline.js")
    assert script.status_code == 200
    assert "ResiliTimeline" in script.text
