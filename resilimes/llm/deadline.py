"""Time budgets for AI work (line-side use: never block the operator).

A task deadline is a monotonic instant held in a context variable, so the agent loop
and the provider underneath it see the same budget without threading it through every
call. Tests replace ``clock`` with a fake; nothing here sleeps.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_TASK_S = 180.0
DEFAULT_CALL_S = 90.0
DEFAULT_TTFB_S = 60.0
TTFB_MAX_MS = 300_000
# Do not start another empty-reply budget rung with less than this left.
RUNG_MIN_S = 30.0

clock: Callable[[], float] = time.monotonic
_deadline: ContextVar[float | None] = ContextVar("ai_task_deadline", default=None)


class DeadlineExceeded(RuntimeError):
    """A per-call cap or the task deadline ran out."""


def now() -> float:
    return clock()


def _env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def default_task_s() -> float:
    return _env_seconds("AI_TASK_DEADLINE_S", DEFAULT_TASK_S)


@contextmanager
def task_deadline(seconds: float | None) -> Iterator[float | None]:
    """Run the block under a wall-clock budget. ``None`` / <= 0 means no deadline.

    A nested call never extends an outer deadline; it can only tighten it.
    """
    outer = _deadline.get()
    mine = now() + seconds if seconds and seconds > 0 else None
    if outer is not None and (mine is None or outer < mine):
        mine = outer
    token = _deadline.set(mine)
    try:
        yield mine
    finally:
        _deadline.reset(token)


def remaining() -> float | None:
    """Seconds left on the task deadline, or None when there is none."""
    end = _deadline.get()
    return None if end is None else end - now()


def expired() -> bool:
    left = remaining()
    return left is not None and left <= 0
