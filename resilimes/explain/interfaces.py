"""The two faces the explain layer may use.

* ``RunRecordSource``: read a recorded run (``explain.record.Timeline``).
* ``ReplayService``: ask the twin to run again with a change and get the new
  record back. The explain layer only calls it; the simulator stays on the
  twin side (``resilimes.evidence.adapters``).

Nothing here imports the twin, engines, agents, kernel or domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from resilimes.explain.record import Timeline
from resilimes.explain.schema import RunRef


@runtime_checkable
class RunRecordSource(Protocol):
    @property
    def ref(self) -> RunRef: ...

    @property
    def timeline(self) -> Timeline: ...


@dataclass(frozen=True)
class ReplayRequest:
    """One what-if run against a recorded baseline.

    ``drop_downs`` / ``drop_pm`` remove down or PM spans of a tool that overlap
    the given windows; ``extra_downs`` / ``extra_pm`` add spans; ``hot_lot``
    promotes one lot. Times are seconds after the snapshot.
    """

    base: RunRef
    label: str
    drop_downs: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    drop_pm: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    extra_downs: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    extra_pm: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    hot_lot: int | None = None
    notes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ReplayService(Protocol):
    def baseline(self, ref: RunRef) -> RunRecordSource: ...

    def replay(self, request: ReplayRequest) -> RunRecordSource: ...


class WindowInvestigator(Protocol):
    """Answers "why did this family's WIP change in [t1_h, t2_h]?".

    The implementation is on the workshop side (``insight.investigator.investigate``);
    it may run guarded SQL. The explain layer only calls it.
    """

    def __call__(
        self,
        kit: Any,
        question: str,
        family: str,
        t1_h: float,
        t2_h: float,
        provider: Any,
        settings: Any,
    ) -> Any: ...
