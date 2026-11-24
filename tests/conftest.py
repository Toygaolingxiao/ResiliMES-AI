"""Test-wide settings.

The product default scheduling mode is ``plan`` (see
``resilimes.smt.simulate.DEFAULT_SCHED_MODE``). This file does **not** rewrite
that default.

Golden digests and expected numbers for the older qtime-r2 path were recorded
under ``RESILIMES_SCHED_MODE=strict_qtime``. Tests that need that path must
declare it:

* request the ``strict_qtime`` fixture, or
* set ``RESILIMES_SCHED_MODE`` themselves, or
* rely on the caller (``make test``, CI ``test`` job) having set the env.

``tests/test_sched_mode.py`` and ``tests/test_plan_kpi_baseline.py`` cover the
product default explicitly with the env unset.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def strict_qtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the recorded strict Q-time path for this test."""
    monkeypatch.setenv("RESILIMES_SCHED_MODE", "strict_qtime")
