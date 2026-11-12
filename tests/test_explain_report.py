"""The report page lays out an Evidence Schema bundle and does not run the twin."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.explain.lateness import decompose
from resilimes.explain.record import Timeline, Visit
from resilimes.explain.report import build_report
from resilimes.explain.schema import (
    EvidenceBundle,
    EvidenceItem,
    RunRef,
    Subject,
    lateness_bundle,
)

REF = RunRef(seed=1, horizon_sec=3600.0, policy="resilimes")


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        subject=Subject(kind="lot", id="Lot-1"),
        run=REF,
        items=(
            EvidenceItem(key="lateness", tier="recorded", value=60.0, unit="sec", sources=("due",)),
            EvidenceItem(
                key="overrun.down", tier="attributed", value=40.0, unit="sec", sources=("visits",)
            ),
            EvidenceItem(
                key="overrun.dispatch_other",
                tier="unknown",
                value=20.0,
                unit="sec",
                reason="a tool was idle and the record has no cause (pin, gate or wake latency)",
            ),
        ),
    ).sealed()


def test_report_lists_tier_sources_and_hash():
    bundle = _bundle()
    report = build_report(bundle)
    assert report["schema_version"] == "evidence/v0"
    assert report["verified"] is True
    assert report["content_hash"] == bundle.content_hash
    assert report["content_hash"].startswith("sha256:")
    by_key = {row["key"]: row for row in report["statements"]}
    assert by_key["lateness"]["tier"] == "recorded"
    assert by_key["lateness"]["sources"] == ["due"]
    assert by_key["overrun.down"]["tier"] == "attributed"
    assert by_key["overrun.dispatch_other"]["tier"] == "unknown"
    assert by_key["overrun.dispatch_other"]["reason"]
    assert report["sections"]["what"] == ["lateness"]
    assert report["sections"]["why"] == ["overrun.down"]
    assert report["sections"]["unconfirmed"] == [
        {
            "key": "overrun.dispatch_other",
            "reason": by_key["overrun.dispatch_other"]["reason"],
        }
    ]
    assert report["coverage"]["percent"] == {
        "recorded": 50.0,
        "attributed": 33.3,
        "unknown": 16.7,
    }
    changed = bundle.model_copy(update={"content_hash": "sha256:" + "0" * 64})
    assert build_report(changed)["verified"] is False


def _hand_record():
    route = SimpleNamespace(batch_max=[0], cycle=[300.0])
    fab = SimpleNamespace(
        families=[SimpleNamespace(tool0=0, tools=1, name="F0")],
        routes=[route],
        lot_route=[0],
        lot_due=[100.0],
        lot_id=["Lot-1"],
        lot_product=["P"],
        lot_class=["regular"],
    )
    visit = Visit(lot=0, step=0, family=0, ready=0.0, start=100.0, tool=0, leave=400.0)
    visit.outcome = "done"
    timeline = Timeline(
        fab=fab,
        horizon=1000.0,
        downs=[[(0.0, 100.0)]],
        pm=[[]],
        visits={0: [visit]},
        busy=[[(100.0, 400.0)]],
        reserved=[[]],
        completed={0: 400.0},
        by_family={0: [visit]},
    )
    ref = RunRef(seed=1, horizon_sec=1000.0, policy="resilimes")
    return SimpleNamespace(timeline=timeline, ref=ref)


def test_report_routes_read_a_bundle_and_leave_the_console(monkeypatch):
    record = _hand_record()
    monkeypatch.setattr(
        "resilimes.api.explain_pages.baseline_record", lambda seed, horizon_h: record
    )
    client = TestClient(
        create_app(Settings(mode="mock", fab="sample", horizon=HORIZON, scout_signing_secret="x"))
    )
    listed = client.get("/api/explain/report/lots", params={"seed": 1, "horizon_h": 1})
    assert listed.status_code == 200
    assert listed.json()["lots"][0]["lot"] == "Lot-1"

    body = client.get("/api/explain/report", params={"lot": "Lot-1", "seed": 1, "horizon_h": 1})
    assert body.status_code == 200
    payload = body.json()
    assert payload["verified"] is True
    assert payload["subject"]["id"] == "Lot-1"
    assert any(row["sources"] for row in payload["statements"])
    split = lateness_bundle(decompose(record.timeline, 0), record.ref)
    assert payload["content_hash"] == split.content_hash

    checked = client.post("/api/explain/report/verify", json=payload["bundle"])
    assert checked.status_code == 200
    assert checked.json()["verified"] is True
    assert checked.json()["recomputed"] == payload["content_hash"]

    tampered = dict(payload["bundle"])
    tampered["content_hash"] = "sha256:" + "ab" * 32
    assert client.post("/api/explain/report/verify", json=tampered).json()["verified"] is False
    assert (
        client.get("/api/explain/report", params={"lot": "missing", "seed": 1}).status_code == 404
    )

    page = client.get("/report")
    assert page.status_code == 200
    assert "/assets/product/report/report.js" in page.text
    index = client.get("/")
    assert index.status_code == 200
    assert 'id="report-link"' in index.text
    assert 'href="/report"' in index.text
    assert 'id="panel-recover"' in index.text
