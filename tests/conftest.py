"""Test-wide settings.

The suite's expected numbers and golden digests were recorded on the qtime-r2
path, so it pins ``RESILIMES_SCHED_MODE=strict_qtime`` unless the caller set
it. ``tests/test_sched_mode.py`` covers the default (``plan``) mode explicitly.

A test whose numbers were recorded on that qtime-r2 path, and which would
otherwise follow the suite mode, requests ``strict_qtime``. That pin does not
change the scheduler. It only selects the recorded path inside the test, so
the same suite passes when CI starts it in ``plan`` and in ``strict_qtime``.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("RESILIMES_SCHED_MODE", "strict_qtime")


@pytest.fixture
def strict_qtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the recorded strict Q-time path for this test."""
    monkeypatch.setenv("RESILIMES_SCHED_MODE", "strict_qtime")
