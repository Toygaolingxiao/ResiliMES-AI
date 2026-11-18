"""Quality API contract: ``GET /api/quality`` serves the quality/v0 report.

The endpoint computes the report live from the stored fault-injection
benchmark files (``results_pc/investigator_nightshift_v2.json`` /
``v1.json``) via ``insight.quality_adapter.evaluate_file()``. These
tests pin the first measurement (v2 misattribution 4/24, v1 11/22) at
the HTTP layer, the error mapping (unknown variant 404, broken
benchmark file 503), and that the served report validates as a real
``QualityReport``. The page-side consumer is covered by
``tests/test_quality_page.py`` (server-envelope handling) and
``tests/test_frontend_dirs.py`` (wiring).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resilimes.api.app import create_app
from resilimes.api.quality import BENCHMARK_DIR
from resilimes.config import Settings
from resilimes.explain.quality import QualityReport


def _client() -> TestClient:
    return TestClient(create_app(Settings(fab="sample", mode="auto")))


def test_default_variant_is_v2_first_measurement() -> None:
    body = _client().get("/api/quality").json()
    assert body["api_version"] == "quality-api/v0"
    assert body["variant"] == "v2"
    assert body["source"] == "results_pc/investigator_nightshift_v2.json"
    assert body["adapter_version"] == "adapter/v0"
    assert body["metrics_version"] == "quality/v0"
    report = body["report"]
    assert report["total_samples"] == 24
    assert report["truth_known"] == 24
    assert report["misattribution"] == {"numerator": 4, "denominator": 24, "value": 4 / 24}
    assert report["over_unknown"] == {"numerator": 0, "denominator": 24, "value": 0.0}
    assert report["calibration_samples"] == 0
    assert report["expected_calibration_error"] is None
    summary = body["summary"]
    assert summary["samples"] == 24
    assert summary["skipped"] == {}
    assert summary["source"] == "investigator_nightshift_v2"
    # The served report is a genuine quality/v0 report, not a hand shape.
    QualityReport.model_validate(report)


def test_variant_v1_first_measurement() -> None:
    body = _client().get("/api/quality", params={"variant": "v1"}).json()
    assert body["variant"] == "v1"
    assert body["source"] == "results_pc/investigator_nightshift_v1.json"
    report = body["report"]
    assert report["total_samples"] == 24
    assert report["misattribution"] == {"numerator": 11, "denominator": 22, "value": 0.5}
    assert report["over_unknown"] == {"numerator": 2, "denominator": 24, "value": 2 / 24}
    assert report["calibration_samples"] == 0
    assert report["expected_calibration_error"] is None
    QualityReport.model_validate(report)


def test_unknown_variant_is_404() -> None:
    assert _client().get("/api/quality", params={"variant": "v3"}).status_code == 404
    assert _client().get("/api/quality", params={"variant": ""}).status_code == 404


def test_missing_benchmark_file_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import resilimes.api.quality as quality_api

    monkeypatch.setattr(quality_api, "BENCHMARK_DIR", tmp_path)
    assert _client().get("/api/quality").status_code == 503


def test_malformed_benchmark_file_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import resilimes.api.quality as quality_api

    (tmp_path / "investigator_nightshift_v2.json").write_text(
        json.dumps({"rows": "not-a-list"}), encoding="utf-8"
    )
    monkeypatch.setattr(quality_api, "BENCHMARK_DIR", tmp_path)
    assert _client().get("/api/quality").status_code == 503


def test_duplicate_case_id_benchmark_file_is_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import resilimes.api.quality as quality_api

    row = {"case_id": "c1", "truth": "tool_down", "ai": {"primary_cause": "tool_down"}}
    (tmp_path / "investigator_nightshift_v2.json").write_text(
        json.dumps({"rows": [row, dict(row)]}), encoding="utf-8"
    )
    monkeypatch.setattr(quality_api, "BENCHMARK_DIR", tmp_path)
    assert _client().get("/api/quality").status_code == 503


def test_quality_endpoint_is_read_only() -> None:
    client = _client()
    assert client.post("/api/quality").status_code == 405
    assert client.get("/api/quality").status_code == 200
    assert BENCHMARK_DIR.name == "results_pc"
