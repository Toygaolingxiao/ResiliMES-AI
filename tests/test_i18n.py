"""Console strings stay aligned, and the landing quotes the lithography book."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.api.app import create_app
from resilimes.config import HORIZON, Settings
from resilimes.i18n import catalog, flatten, review_markdown

ROOT = Path(__file__).resolve().parents[1]
BANNED = ("t=", "heuristic", "ヒューリスティック", "启发式", "ヒューリスティク")


def test_catalog_keys_match_and_the_review_lists_them() -> None:
    data = catalog()
    en = flatten(data["en"])
    zh = flatten(data["zh"])
    ja = flatten(data["ja"])
    assert set(en) == set(zh) == set(ja)
    assert all(
        value.strip() or key.endswith("idle") or key.endswith("mock") or key.endswith("live")
        for key, value in en.items()
    )
    review = (ROOT / "docs" / "i18n_review.md").read_text(encoding="utf-8")
    assert review == review_markdown()
    for key in en:
        assert f"`{key}`" in review
    for lang in ("zh", "ja"):
        for text in flatten(data[lang]).values():
            for word in BANNED:
                assert word not in text


def test_overview_numbers_match_the_litho_recovery() -> None:
    settings = Settings(mode="mock", horizon=HORIZON, scout_signing_secret="i18n-secret")
    client = TestClient(create_app(settings))
    body = client.get("/api/scenarios").json()
    impact = body["overview"]["impacts"]["litho_down"]
    assert impact["otd_before"] == 83.3
    assert impact["otd_after"] == 100.0
    assert impact["tardy_before"] == 784
    assert impact["tardy_after"] == 0
    assert "LITHO-02" in body["overview"]["down_tools"]
    tools = {row["id"]: row for row in body["overview"]["tools"]}
    materials = {row["id"] for row in body["overview"]["materials"]}
    assert "RESIST-UV" in materials
    assert "RESIST-UV" not in tools
    assert tools["LITHO-02"]["down_until_min"] == 600
    assert tools["LITHO-02"]["state"] == "down"
    queues = {row["tool"]: row for row in body["overview"]["queues"]}
    assert queues
    assert {row["kind"] for row in body["overview"]["queues"]} == {"litho"}
    assert queues["LITHO-02"]["state"] == "down"
    blank = {"cr": None, "slack_min": None, "setup_cost_min": None, "qtime_risk": None}
    for row in body["overview"]["queues"]:
        assert row["score"] == blank
    steps = body["overview"]["wip_steps"]
    assert steps
    assert all(step["threshold"] is None and step["warning"] is False for step in steps)
    assert sum(step["lots"] for step in steps) == body["overview"]["kpis"]["wip"]
    assert body["overview"]["trigger"] == {"kind": "breakdown", "scenario_id": "litho_down"}
    report = run_recovery(settings, RecoverInput(scenario="litho_down"))
    refused = report.rejected_alternative["critique"]["violations"][0]  # type: ignore[index]
    assert refused["code"] == "equipment_down"
    assert refused["params"]["tool"] == "LITHO-02"
    assert refused["params"]["until_at"] == 600
    assert refused["params"]["start_at"] == 0
    assert "LITHO-02" in refused["detail"]
