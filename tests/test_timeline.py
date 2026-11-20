"""Timeline contract: two row axes, filters, and the page that draws them."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
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
    also: tuple[str, ...] = (),
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
        also=also,
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


def test_scope_reports_the_cap_and_stats_stay_window_wide() -> None:
    """H1 fix: the lot cap must be visible, and the cards must not shrink with it.

    With lots=1 the page draws one lot, but scope must still report all four
    window lots and stats must count the whole window (late LOT-3 included).
    """
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 20),
        _bar("LOT-1", "ETCH-01", 23, 40, group="Etch"),
        _bar("LOT-1", "CMP-01", 80, 100, group="CMP"),
        _bar("LOT-2", "LITHO-01", 30, 50, pinned=True),
        _bar("LOT-3", "WET-01", 0, 10, group="Wet", priority=3, late=True, qtime="breach"),
        _bar("LOT-4", "WET-01", 10, 20, group="Wet", priority=3, qtime="risk"),
    )
    capped = window_payload(book, TimelineQuery(t0=0, t1=200, lots=1))
    scope = capped["scope"]
    assert isinstance(scope, dict)
    assert scope == {
        "lots_total": 4,
        "lots_shown": 1,
        "lots_capped": True,
        "bars_total": 6,
        "bars_shown": 3,
        "machines_total": 4,
        "machines_shown": 3,
    }
    stats = capped["stats"]
    assert isinstance(stats, dict)
    assert stats["total_lots"] == 4
    assert stats["total_jobs"] == 6
    assert stats["late_lots"] == 1  # LOT-3 is late but not drawn
    assert stats["qtime_breach"] == 1
    assert stats["qtime_risk"] == 1
    assert capped["daily"][0]["jobs"] == 6  # type: ignore[index]
    assert capped["truncated"] is False

    uncapped = window_payload(book, TimelineQuery(t0=0, t1=200, lots=10))
    assert uncapped["scope"] == {  # type: ignore[comparison-overlap]
        "lots_total": 4,
        "lots_shown": 4,
        "lots_capped": False,
        "bars_total": 6,
        "bars_shown": 6,
        "machines_total": 4,
        "machines_shown": 4,
    }

    limited = window_payload(book, TimelineQuery(t0=0, t1=200, lots=10, limit=2))
    assert limited["truncated"] is True
    assert limited["scope"]["bars_total"] == 6  # type: ignore[index]
    assert limited["scope"]["bars_shown"] == 2  # type: ignore[index]
    assert limited["stats"]["total_jobs"] == 6  # type: ignore[index]


def test_scope_and_stats_follow_the_display_window() -> None:
    """Prefetch: the page fetches 3x the display span, but stats/scope
    describe the display window (view_t0/view_t1), not the fetch window."""
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 20),
        _bar("LOT-1", "ETCH-01", 23, 40, group="Etch"),
        _bar("LOT-2", "LITHO-01", 800, 820),
        _bar("LOT-2", "ETCH-01", 830, 850, group="Etch"),
    )
    payload = window_payload(book, TimelineQuery(t0=0, t1=1200, view_t0=0, view_t1=200, lots=10))
    assert payload["window"] == {"t0": 0, "t1": 1200}
    assert payload["view"] == {"t0": 0, "t1": 200}
    scope = payload["scope"]
    assert isinstance(scope, dict)
    assert scope["lots_total"] == 1  # only LOT-1 is in the display window
    assert scope["lots_shown"] == 1
    assert scope["bars_total"] == 2
    assert scope["bars_shown"] == 2
    assert scope["lots_capped"] is False
    assert payload["stats"]["total_lots"] == 1  # type: ignore[index]
    assert payload["stats"]["total_jobs"] == 2  # type: ignore[index]
    assert len(payload["bars"]) == 4  # bars still cover the fetch window
    # A view outside the fetch window clamps to an empty view, not an error.
    empty_view = window_payload(
        book, TimelineQuery(t0=0, t1=200, view_t0=150, view_t1=200, lots=10)
    )
    assert empty_view["scope"]["lots_total"] == 0  # type: ignore[index]
    assert empty_view["stats"]["total_jobs"] == 0  # type: ignore[index]
    assert empty_view["view"] == {"t0": 150, "t1": 200}


def test_stats_fields_count_what_they_say() -> None:
    """M6: total_jobs counts bars (operation segments), total_operations
    counts distinct step kinds, total_moves sums wafer quantities —
    a bar carrying qty=75 (as a batched bar does) counts 75, not one move."""
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 20, step="LITHO"),
        _bar("LOT-1", "ETCH-01", 23, 40, group="Etch", step="ETCH"),
        replace(_bar("LOT-2", "LITHO-01", 30, 50, step="LITHO"), qty=75),
    )
    payload = window_payload(book, TimelineQuery(t0=0, t1=200, lots=10))
    stats = payload["stats"]
    assert isinstance(stats, dict)
    assert stats["total_jobs"] == 3  # bars, not lots and not jobs
    assert stats["total_operations"] == 2  # LITHO + ETCH, not 3 executions
    assert stats["total_moves"] == 125  # 25 + 25 + 75 wafer-steps
    assert stats["total_lots"] == 2
    assert stats["total_equipment"] == 2
    assert payload["daily"][0]["jobs"] == 3  # type: ignore[index]


def test_gaps_skip_split_sequences() -> None:
    """An also-split sequence must not fabricate a waiting gap: LOT-1's
    bars B and D survive only because they share a bar with LOT-9, while
    C is dropped by the cap — so the B->D interval is not a gap."""
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 10),
        _bar("LOT-1", "ETCH-01", 50, 60, group="Etch", also=("LOT-9",)),
        _bar("LOT-1", "CMP-01", 70, 80, group="CMP"),
        _bar("LOT-1", "WET-01", 100, 110, group="Wet", also=("LOT-9",)),
        _bar("LOT-9", "LITHO-01", 0, 10),
        _bar("LOT-9", "ETCH-01", 12, 22, group="Etch"),
        _bar("LOT-9", "CMP-01", 24, 34, group="CMP"),
        _bar("LOT-9", "WET-01", 36, 46, group="Wet"),
        _bar("LOT-9", "LITHO-01", 48, 58),
        _bar("LOT-9", "ETCH-01", 60, 70, group="Etch"),
    )
    payload = window_payload(book, TimelineQuery(t0=0, t1=200, lots=1))
    gaps = payload["gaps"]
    assert isinstance(gaps, list)
    # LOT-1's kept bars are B and D only; the 60->100 interval covers C's
    # real processing time, so no LOT-1 gap may be reported.
    assert not [gap for gap in gaps if gap["lot"] == "LOT-1"]  # type: ignore[union-attr]
    # LOT-9's own short hops are real gaps and still reported.
    assert any(gap["lot"] == "LOT-9" for gap in gaps)  # type: ignore[union-attr]
    # Without the cap the real transport/waiting gaps appear.
    full = window_payload(book, TimelineQuery(t0=0, t1=200, lots=10))
    assert {gap["state"] for gap in full["gaps"]} == {"transport", "waiting"}  # type: ignore[union-attr]


def test_skip_count_is_book_wide_not_window_wide() -> None:
    """skip_count is the whole-book replay count (0 when narrowed); it is
    not a window stat, and the scope notice must not certify it as one."""
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 20),
        _bar("LOT-2", "LITHO-01", 30, 50),
    )
    empty = window_payload(book, TimelineQuery(t0=1000, t1=1200, lots=10))
    assert empty["stats"]["skip_count"] == 2  # type: ignore[index]
    assert empty["stats"]["total_jobs"] == 0  # type: ignore[index]
    narrowed = window_payload(book, TimelineQuery(t0=0, t1=200, lots=10, priority=2))
    assert narrowed["stats"]["skip_count"] == 0  # type: ignore[index]


def test_focus_lot_is_drawn_but_not_counted_in_scope() -> None:
    """The focus lot is selected on request: its bars draw and its lot
    lists in product rows, but scope counts window lots only."""
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 20),
        _bar("FOCUS-OUT", "LITHO-01", 1000, 1020),
    )
    payload = window_payload(book, TimelineQuery(t0=0, t1=200, lots=1, focus="FOCUS-OUT"))
    assert payload["scope"]["lots_total"] == 1  # type: ignore[index]
    assert payload["scope"]["lots_shown"] == 1  # type: ignore[index]
    assert len(payload["focus_bars"]) == 1  # type: ignore[arg-type]
    rows = payload["product_rows"]
    assert isinstance(rows, list)
    assert "FOCUS-OUT" in {row["id"] for row in rows}  # type: ignore[union-attr]


def test_lots_zero_disables_the_cap() -> None:
    """Direct model use: lots<=0 means no cap (the API forbids 0 with
    ge=1, so this is reachable only from Python). Pinned, not assumed."""
    book = _book(
        _bar("LOT-1", "LITHO-01", 0, 20),
        _bar("LOT-2", "LITHO-01", 30, 50),
        _bar("LOT-3", "WET-01", 0, 10, group="Wet"),
    )
    payload = window_payload(book, TimelineQuery(t0=0, t1=200, lots=0))
    assert payload["scope"]["lots_capped"] is False  # type: ignore[index]
    assert payload["scope"]["lots_shown"] == 3  # type: ignore[index]


def test_scope_lots_placeholders_match_in_all_languages() -> None:
    """The notice fills {shown}/{total}; a translation that dropped one
    would render 'Showing  of  lots' with no failure anywhere else."""
    catalog = json.loads(
        (ROOT / "resilimes" / "demo" / "static" / "i18n.json").read_text(encoding="utf-8")
    )
    for lang in ("en", "zh", "ja"):
        text = catalog[lang]["timeline"]["scopeLots"]
        assert "{shown}" in text and "{total}" in text, lang


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


def test_sample_book_rejects_selectors_instead_of_ignoring_them() -> None:
    client = _client()
    seeded = client.get("/api/timeline", params={"seed": 3})
    assert seeded.status_code == 422
    assert "seed=3" in seeded.json()["detail"]
    horizoned = client.get("/api/timeline", params={"horizon_h": 48})
    assert horizoned.status_code == 422
    assert "horizon_h=48" in horizoned.json()["detail"]
    booked = client.get("/api/timeline", params={"book": "litho_down"})
    assert booked.status_code == 422
    assert "book='litho_down'" in booked.json()["detail"]
    assert client.get("/api/timeline", params={"book": "bogus"}).status_code == 422
    # The default request is untouched: no selector, no complaint.
    assert client.get("/api/timeline", params={"t0": 0, "t1": 60}).status_code == 200


def test_payload_names_the_book_it_came_from() -> None:
    book = _book(_bar("LOT-1", "M1", 0, 60))
    payload = window_payload(book, TimelineQuery(t0=0, t1=120))
    assert payload["book"] == "base"
    book.book = "litho_down"
    payload = window_payload(book, TimelineQuery(t0=0, t1=120))
    assert payload["book"] == "litho_down"


def test_smt_book_selector_contract() -> None:
    from resilimes.smt.replay import BookSpec, register
    from resilimes.timeline.smt_book import BookSelectorError, load_smt_book

    # An unknown book is unknown on every path, seed or not.
    with pytest.raises(KeyError):
        load_smt_book(book="bogus", seed=1)
    with pytest.raises(KeyError):
        load_smt_book(book="bogus", horizon_h=24)
    # A known scenario book cannot be refined by seed/horizon.
    with pytest.raises(BookSelectorError, match="do not apply"):
        load_smt_book(book="litho_down", seed=1)
    with pytest.raises(BookSelectorError, match="do not apply"):
        load_smt_book(book="hot_lot", horizon_h=24)
    # Neither can a registered what-if book.
    register(BookSpec(key="whatif-contract-test", kind="whatif"))
    with pytest.raises(BookSelectorError, match="do not apply"):
        load_smt_book(book="whatif-contract-test", seed=1)


def test_smt_api_maps_selector_errors() -> None:
    settings = Settings(
        mode="mock", fab="smt2020", horizon=HORIZON, scout_signing_secret="timeline"
    )
    client = TestClient(create_app(settings))
    assert client.get("/api/timeline", params={"book": "bogus", "seed": 1}).status_code == 404
    assert client.get("/api/timeline", params={"book": "litho_down", "seed": 1}).status_code == 422


def test_api_groups_filters_and_serves_the_page() -> None:
    client = _client()
    body = client.get("/api/timeline", params={"t0": 0, "t1": 5000, "lots": 100}).json()
    assert body["contract"] == "timeline/v1"
    assert body["source"] == "sample"
    assert body["bars"]
    assert set(body["scope"]) == {
        "lots_total",
        "lots_shown",
        "lots_capped",
        "bars_total",
        "bars_shown",
        "machines_total",
        "machines_shown",
    }
    assert body["view"] == body["window"]  # no view params: view is the fetch window
    assert body["scope"]["lots_total"] == body["stats"]["total_lots"]
    assert body["scope"]["bars_total"] == body["stats"]["total_jobs"]
    viewed = client.get(
        "/api/timeline",
        params={"t0": 0, "t1": 5000, "view_t0": 0, "view_t1": 60, "lots": 100},
    ).json()
    assert viewed["view"] == {"t0": 0, "t1": 60}
    assert viewed["window"] == body["window"]  # view params do not move the fetch window
    assert viewed["stats"]["total_jobs"] <= body["stats"]["total_jobs"]
    assert (
        client.get(
            "/api/timeline", params={"t0": 0, "t1": 5000, "view_t0": 60, "view_t1": 10}
        ).status_code
        == 422
    )
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


ROOT = Path(__file__).resolve().parents[1]
TIMELINE_JS = ROOT / "resilimes" / "demo" / "static" / "product" / "timeline" / "timeline.js"

# scopeNotice is pure over (payload, copy); the driver loads timeline.js in
# a vm with a stub document (no #timeline-app, so the page never mounts)
# and calls the function ResiliTimeline exposes for this check.
SCOPE_DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf-8");
const sandbox = {
  window: {},
  document: { getElementById: () => null },
  console,
};
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const scopeNotice = sandbox.window.ResiliTimeline.scopeNotice;
const failures = [];
function check(name, cond, extra) {
  if (!cond) failures.push(extra === undefined ? name : `${name}: ${JSON.stringify(extra)}`);
}
const copy = {
  scopeLots: "Showing {shown} of {total} lots in this window. Counts cover this window; Skips counts the whole book.",
  truncated: "The window was cut at the bar limit. Narrow the time range.",
};
const capped = { scope: { lots_capped: true, lots_shown: 100, lots_total: 1684 }, truncated: false };
check("capped notice names the real counts",
  scopeNotice(capped, copy) === "Showing 100 of 1684 lots in this window. Counts cover this window; Skips counts the whole book.",
  scopeNotice(capped, copy));
const both = { scope: { lots_capped: true, lots_shown: 2, lots_total: 4 }, truncated: true };
check("capped plus bar-limit joins both sentences",
  scopeNotice(both, copy) === "Showing 2 of 4 lots in this window. Counts cover this window; Skips counts the whole book. The window was cut at the bar limit. Narrow the time range.",
  scopeNotice(both, copy));
const plain = { scope: { lots_capped: false, lots_shown: 4, lots_total: 4 }, truncated: false };
check("uncapped window shows nothing", scopeNotice(plain, copy) === "", scopeNotice(plain, copy));
const onlyLimit = { scope: { lots_capped: false, lots_shown: 2, lots_total: 2 }, truncated: true };
check("bar-limit alone keeps the old sentence",
  scopeNotice(onlyLimit, copy) === copy.truncated, scopeNotice(onlyLimit, copy));
const limitHidesLots = { scope: { lots_capped: false, lots_shown: 1568, lots_total: 1684 }, truncated: true };
check("bar-limit hiding lots still names them",
  scopeNotice(limitHidesLots, copy).startsWith("Showing 1568 of 1684 lots"), scopeNotice(limitHidesLots, copy));
const falseAlarm = { scope: { lots_capped: true, lots_shown: 4, lots_total: 4 }, truncated: false };
check("cap engaged but nothing hidden shows nothing", scopeNotice(falseAlarm, copy) === "", scopeNotice(falseAlarm, copy));
check("missing scope is silent", scopeNotice({}, copy) === "");
check("missing copy key falls back to English, never silent",
  scopeNotice(capped, {}) === "Showing 100 of 1684 lots in this window. Counts cover this window; Skips counts the whole book.",
  scopeNotice(capped, {}));
check("null copy falls back to English", scopeNotice(capped, null).startsWith("Showing 100 of 1684 lots"), scopeNotice(capped, null));
console.log(JSON.stringify({ failures }));
"""


def test_stats_card_labels_name_the_measured_unit() -> None:
    """M6/H2: the stat cards must read what the numbers count — Segments
    (bars) and Wafer-steps (summed qty over bars), not Jobs and Moves — in
    all three languages. Keys are unchanged, so this increment adds no new
    fallback churn; the page's raw-key fallback itself is a known
    divergence from the cases-page rule, recorded in TIMELINE_SCOPE.md."""
    i18n = json.loads(
        (ROOT / "resilimes" / "demo" / "static" / "i18n.json").read_text(encoding="utf-8")
    )
    expected = {
        "en": {"jobs": "Segments", "moves": "Wafer-steps"},
        "ja": {"jobs": "工程段数", "moves": "ウェーハステップ数"},
        "zh": {"jobs": "工序段数", "moves": "晶圆步数"},
    }
    for lang, labels in expected.items():
        timeline = i18n[lang]["timeline"]
        for key, value in labels.items():
            assert timeline[key] == value, (lang, key, timeline[key])
    # The neighbouring labels are untouched by this increment.
    assert i18n["en"]["timeline"]["operations"] == "Steps"
    assert i18n["en"]["timeline"]["machines"] == "Tools"
    assert i18n["en"]["timeline"]["lots"] == "Lots"
    # Wiring guard: every key paintStats() looks up in timeline.js must
    # exist in all three languages, so a renamed key cannot silently fall
    # back to the raw key on the page (timeline.js `c[key] || key`).
    js = (
        ROOT / "resilimes" / "demo" / "static" / "product" / "timeline" / "timeline.js"
    ).read_text(encoding="utf-8")
    card_keys = set(re.findall(r'\["(\w+)",\s*\(?stats\.', js))
    assert card_keys == {
        "jobs",
        "machines",
        "lots",
        "operations",
        "moves",
        "skips",
        "lateLots",
        "qtime",
    }, card_keys
    for lang in ("en", "ja", "zh"):
        missing = card_keys - set(i18n[lang]["timeline"])
        assert not missing, (lang, missing)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_timeline_scope_notice_parity(tmp_path: Path) -> None:
    driver = tmp_path / "timeline_scope_driver.cjs"
    driver.write_text(SCOPE_DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(TIMELINE_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []


# whyHref is pure over (payload, lot); same vm driver pattern as scopeNotice.
WHY_DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf-8");
const sandbox = {
  window: {},
  document: { getElementById: () => null },
  console,
};
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const whyHref = sandbox.window.ResiliTimeline.whyHref;
const failures = [];
function check(name, cond, extra) {
  if (!cond) failures.push(extra === undefined ? name : `${name}: ${JSON.stringify(extra)}`);
}
check("smt2020 payload links to the report with its own seed and horizon",
  whyHref({ source: "smt2020", seed: 7, horizon_h: 48 }, "Init_Lot_1_1") ===
    "/report?lot=Init_Lot_1_1&seed=7&horizon_h=48",
  whyHref({ source: "smt2020", seed: 7, horizon_h: 48 }, "Init_Lot_1_1"));
check("lot id is url-encoded",
  whyHref({ source: "smt2020", seed: 1, horizon_h: 48 }, "A B&1") ===
    "/report?lot=A%20B%261&seed=1&horizon_h=48");
check("missing seed and horizon fall back to 1 and 48",
  whyHref({ source: "smt2020" }, "L1") === "/report?lot=L1&seed=1&horizon_h=48");
check("seeded base refinement keeps its link",
  whyHref({ source: "smt2020", book: "timeline-7-48", seed: 7, horizon_h: 48 }, "L1") ===
    "/report?lot=L1&seed=7&horizon_h=48");
check("scenario book has no report link (the report reads the baseline run)",
  whyHref({ source: "smt2020", book: "litho_down", seed: 1, horizon_h: 48 }, "L1") === null);
check("what-if book has no report link",
  whyHref({ source: "smt2020", book: "whatif-0123456789", seed: 1, horizon_h: 48 }, "L1") === null);
check("sample payload has no report link",
  whyHref({ source: "sample", seed: 1, horizon_h: 6.98 }, "LOT-1001") === null);
check("missing payload has no report link", whyHref(null, "L1") === null);
check("missing lot has no report link", whyHref({ source: "smt2020" }, "") === null);
console.log(JSON.stringify({ failures }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_timeline_why_href_parity(tmp_path: Path) -> None:
    driver = tmp_path / "timeline_why_driver.cjs"
    driver.write_text(WHY_DRIVER, encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(TIMELINE_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == []
