"""Opt-in fault plan for the simulator (evidence toolkit / investigator study).

``run_policy(..., faults=None)`` is the default and leaves every code path of
the simulator unchanged. A plan only adds what an injected fault needs that
the down and PM lists cannot express:

* ``hold_until``: lot index -> sim second. The lot is not queued at t=0; it
  arrives at that second (a held release that comes back as a burst).
* ``setup_family`` / ``setup_extra_sec`` / ``setup_window``: every recipe
  changeover on that family's tools takes ``setup_extra_sec`` longer while the
  sim clock is inside the window (changeover blow-up, "setup thrash").
* ``batch_family`` / ``batch_cap_wafers`` / ``batch_window``: the batch size
  cap (BATCHMX, wafers) of that family's batch steps is lowered while the
  clock is inside the window.

Tool downs and PM moves are injected through the existing ``downs`` and ``pm``
lists and need no plan entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FaultPlan:
    hold_until: dict[int, float] = field(default_factory=dict)
    setup_family: int = -1
    setup_extra_sec: float = 0.0
    setup_window: tuple[float, float] = (0.0, 0.0)
    batch_family: int = -1
    batch_cap_wafers: int = 0
    batch_window: tuple[float, float] = (0.0, 0.0)

    def setup_extra(self, family: int, changeover: bool, moment: float) -> float:
        if not changeover or family != self.setup_family or self.setup_extra_sec <= 0:
            return 0.0
        start, end = self.setup_window
        return self.setup_extra_sec if start <= moment < end else 0.0

    def batch_cap(self, family: int, cap: int, moment: float) -> int:
        if family != self.batch_family or self.batch_cap_wafers <= 0 or cap <= 0:
            return cap
        start, end = self.batch_window
        if start <= moment < end:
            return min(cap, self.batch_cap_wafers)
        return cap
