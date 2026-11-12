"""Workshop-side entry point for the window investigator.

The logic is in ``resilimes.explain.investigator``. This module keeps the old
import path and plugs in guarded SQL (``evidence.sqlrun.run_guarded``).
"""

from __future__ import annotations

from typing import Any

from resilimes.common.llm import Completer
from resilimes.evidence.sqlrun import run_guarded
from resilimes.explain import investigator as _impl
from resilimes.explain.investigator import *  # noqa: F403
from resilimes.explain.investigator import MAX_CALLS, Investigation
from resilimes.explain.toolkit import Toolkit


def execute(kit: Toolkit, name: str, args: dict[str, Any], settings: Any) -> dict[str, Any]:
    return _impl.run_call(kit, name, args, settings, run_guarded)


def investigate(
    kit: Toolkit,
    question: str,
    family: str,
    t1_h: float,
    t2_h: float,
    provider: Completer | None = None,
    settings: Any = None,
    *,
    max_calls: int = MAX_CALLS,
    temperature: float = 0.2,
    deadline_s: float | None = None,
) -> Investigation:
    return _impl.investigate_window(
        kit,
        question,
        family,
        t1_h,
        t2_h,
        provider,
        settings,
        max_calls=max_calls,
        temperature=temperature,
        deadline_s=deadline_s,
        sql_runner=run_guarded,
    )


def __getattr__(name: str) -> Any:
    """Private names of the old module (``from ... import _x``) still resolve."""
    return getattr(_impl, name)
