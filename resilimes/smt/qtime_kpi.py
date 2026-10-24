"""Q-time achievement with every missed bucket in the denominator.

A window is one dataset CQT span (origin step end to target step start). Each
window the run opens ends in exactly one bucket:

- ``met``: the target step started at or before the deadline.
- ``started_late``: the target step started after the deadline, either directly
  (``late``) or after a Q-time hold (``held``).
- ``recleaned``: the lot went back through the wet step that opened the window.
- ``open_expired``: the deadline passed inside the horizon and the window was
  still open at the horizon.

``rate_pct`` is met over the sum of the four. Windows whose deadline lies after
the horizon (``live``) and windows whose target was skipped by sampling are not
scored. Windows inherited from the snapshot are reported on their own, never
in the dispatcher's rate. A rate of met / (met + started late) alone leaves
re-cleans and expired windows out and overstates the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def bucket_counts(windows: Mapping[str, int]) -> dict[str, Any]:
    """Four buckets and the true rate from raw outcome counts."""
    met = int(windows.get("met", 0))
    late = int(windows.get("late", 0)) + int(windows.get("held", 0))
    recleaned = int(windows.get("recleaned", 0))
    expired = int(windows.get("expired", 0))
    scored = met + late + recleaned + expired
    return {
        "met": met,
        "started_late": late,
        "held": int(windows.get("held", 0)),
        "recleaned": recleaned,
        "open_expired": expired,
        "scored": scored,
        "rate_pct": round(100.0 * met / scored, 1) if scored else None,
        "open_live": int(windows.get("live", 0)),
        "skipped": int(windows.get("skipped", 0)),
    }


def qtime_buckets(result: Any) -> dict[str, Any]:
    """API block for one run: dispatcher windows, inherited windows, hold time."""
    body = bucket_counts(getattr(result, "qtime_windows", {}) or {})
    body["inherited"] = bucket_counts(getattr(result, "qtime_inherited", {}) or {})
    body["hold_lot_min"] = float(getattr(result, "qtime_hold_lot_min", 0.0))
    return body
