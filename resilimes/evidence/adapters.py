"""Twin-side adapters for the explain layer.

``TwinRunRecord`` turns a ``RecordedRun`` into ``explain.interfaces.RunRecordSource``.
``TwinReplayService`` implements ``explain.interfaces.ReplayService`` with
``record_run``. These are the only places that join the simulator and the
explain layer; ``resilimes.explain`` never imports this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from resilimes.evidence.toolkit import RecordedRun, record_run
from resilimes.explain.interfaces import ReplayRequest
from resilimes.explain.lateness import decompose
from resilimes.explain.record import Timeline
from resilimes.explain.schema import EvidenceBundle, RunRef, lateness_bundle
from resilimes.smt.fab import Fab


@dataclass(frozen=True)
class TwinRunRecord:
    run: RecordedRun

    @property
    def ref(self) -> RunRef:
        return RunRef(
            seed=self.run.seed,
            horizon_sec=float(self.run.horizon),
            policy=self.run.policy,
            label=self.run.label,
        )

    @property
    def timeline(self) -> Timeline:
        return self.run.timeline


class TwinReplayService:
    """Runs the twin. Baselines are cached by ``RunRef``."""

    def __init__(self, fab: Fab) -> None:
        self.fab = fab
        self._baselines: dict[RunRef, TwinRunRecord] = {}

    def baseline(self, ref: RunRef) -> TwinRunRecord:
        cached = self._baselines.get(ref)
        if cached is None:
            run = record_run(
                self.fab,
                seed=ref.seed,
                horizon=ref.horizon_sec,
                policy=ref.policy,
                label=ref.label,
            )
            cached = TwinRunRecord(run)
            self._baselines[ref] = cached
        return cached

    def replay(self, request: ReplayRequest) -> TwinRunRecord:
        base = request.base
        run = record_run(
            self.fab,
            seed=base.seed,
            horizon=base.horizon_sec,
            policy=base.policy,
            label=request.label,
            extra_downs=request.extra_downs or None,
            extra_pm=request.extra_pm or None,
            drop_downs=request.drop_downs or None,
            drop_pm=request.drop_pm or None,
            hot_lot=request.hot_lot,
        )
        return TwinRunRecord(run)


def lot_evidence(record: TwinRunRecord, lot: int) -> EvidenceBundle:
    """Evidence Schema v0 bundle for why ``lot`` is late in ``record``."""
    return lateness_bundle(decompose(record.timeline, lot), record.ref)
