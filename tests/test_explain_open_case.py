"""explain(..., open_case=True) attaches one follow-up case. Default stays off."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from resilimes.explain.explainer import _open_case, explain


def test_open_case_defaults_off() -> None:
    assert inspect.signature(explain).parameters["open_case"].default is False


def test_open_case_helper_records_the_suggested_severity() -> None:
    kit = SimpleNamespace(run=SimpleNamespace(seed=1, horizon=3600.0, policy="baseline", label="t"))
    book = _open_case(kit, "LOT-1", 45.0)
    assert book["book_version"] == "cases/v0"
    case = book["cases"][0]
    assert case["lot"] == "LOT-1"
    assert case["severity"] == "major"
    assert case["lateness_min"] == 45.0
    assert case["status"] == "open"
    assert "45" in case["severity_reason"]
