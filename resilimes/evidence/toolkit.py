"""Twin-side adapter: run the simulator once and keep the run record.

``record_run`` runs the simulator with ``record=True, lot_log=True`` (and an
optional fault plan). The queries (``Toolkit``) live in
``resilimes.explain.toolkit`` and are re-exported here for old imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from resilimes.evidence.timeline import build_timeline
from resilimes.explain.factcheck import FactRegistry
from resilimes.explain.record import RunRecord, Timeline
from resilimes.explain.toolkit import HOUR, Toolkit, _h
from resilimes.kernel.score import CLASS_TIER
from resilimes.smt.fab import Fab
from resilimes.smt.faults import FaultPlan
from resilimes.smt.simulate import RunResult, pm_windows, run_policy, sample_downs

__all__ = [
    "HOUR",
    "Fab",
    "FactRegistry",
    "RecordedRun",
    "RunRecord",
    "Timeline",
    "Toolkit",
    "_h",
    "record_run",
]


@dataclass(kw_only=True)
class RecordedRun(RunRecord):
    """A run record plus the simulator objects behind it (twin side only)."""

    result: RunResult
    faults: FaultPlan | None = None

    def __post_init__(self) -> None:
        if not self.class_tiers:
            self.class_tiers = dict(CLASS_TIER)


def record_run(
    fab: Fab,
    *,
    seed: int,
    horizon: float,
    policy: str = "resilimes",
    faults: FaultPlan | None = None,
    extra_downs: dict[int, list[tuple[float, float]]] | None = None,
    extra_pm: dict[int, list[tuple[float, float]]] | None = None,
    label: str = "baseline",
    hot_lot: int | None = None,
    drop_downs: dict[int, list[tuple[float, float]]] | None = None,
    drop_pm: dict[int, list[tuple[float, float]]] | None = None,
) -> RecordedRun:
    """One recorded run. ``hot_lot`` promotes one lot; ``drop_*`` remove the down or
    PM spans of a tool that overlap the given windows (counterfactual re-runs)."""
    downs = [list(spans) for spans in sample_downs(fab, seed, horizon)]
    pm = [list(spans) for spans in pm_windows(fab, horizon)]
    for tool, spans in (extra_downs or {}).items():
        downs[tool] = sorted(downs[tool] + list(spans))
    for tool, spans in (extra_pm or {}).items():
        pm[tool] = sorted(pm[tool] + list(spans))
    for tool, windows in (drop_downs or {}).items():
        downs[tool] = [span for span in downs[tool] if not _overlaps(span, windows)]
    for tool, windows in (drop_pm or {}).items():
        pm[tool] = [span for span in pm[tool] if not _overlaps(span, windows)]
    result = run_policy(
        fab,
        policy=policy,
        seed=seed,
        horizon=horizon,
        downs=downs,
        pm=pm,
        record=True,
        lot_log=True,
        faults=faults,
        hot_lot=hot_lot,
        promote_hot=hot_lot is not None,
    )
    timeline = build_timeline(
        fab, result, downs=downs, pm=pm, hold_until=faults.hold_until if faults else None
    )
    return RecordedRun(
        fab=fab,
        seed=seed,
        horizon=horizon,
        policy=policy,
        downs=downs,
        pm=pm,
        result=result,
        timeline=timeline,
        faults=faults,
        label=label,
    )


def _overlaps(span: tuple[float, float], windows: list[tuple[float, float]]) -> bool:
    return any(span[0] < right and left < span[1] for left, right in windows)
