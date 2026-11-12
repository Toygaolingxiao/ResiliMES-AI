"""Workshop-side entry point for the late-lot explainer.

The logic is in ``resilimes.explain.explainer``. This module keeps the old
import path, builds the baseline run and plugs in the twin replay service.
"""

from __future__ import annotations

from typing import Any

from resilimes.evidence.adapters import TwinReplayService
from resilimes.evidence.toolkit import HOUR, RecordedRun, record_run
from resilimes.explain import explainer as _impl
from resilimes.explain.explainer import *  # noqa: F403
from resilimes.explain.explainer import HORIZON_H, Explanation
from resilimes.explain.interfaces import ReplayService
from resilimes.explain.record import RunRecord


def verify(
    base: RunRecord, lot_id: str, answer: Explanation, replay: ReplayService | None = None
) -> dict[str, Any]:
    return _impl.verify_counterfactual(base, lot_id, answer, replay or TwinReplayService(base.fab))


def base_run(fab: Any, seed: int) -> RecordedRun:
    return record_run(fab, seed=seed, horizon=HORIZON_H * HOUR)


def __getattr__(name: str) -> Any:
    """Private names of the old module (``from ... import _x``) still resolve."""
    return getattr(_impl, name)
