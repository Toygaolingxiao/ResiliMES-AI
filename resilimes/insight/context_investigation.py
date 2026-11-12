"""Workshop-side entry point for Gantt context queries.

The logic is in ``resilimes.explain.context_investigation``. This module keeps
the old import path and plugs in the workshop-side window investigator
(``insight.investigator.investigate``, which can run guarded SQL).
"""

from __future__ import annotations

from typing import Any

from resilimes.common.llm import Completer
from resilimes.explain import context_investigation as _impl
from resilimes.explain.context_investigation import *  # noqa: F403
from resilimes.explain.interfaces import WindowInvestigator
from resilimes.explain.record import RunRecord
from resilimes.explain.toolkit import Toolkit


def investigate_context(
    run_or_kit: RunRecord | Toolkit,
    query: _impl.ContextQuery,
    provider: Completer | None = None,
    settings: Any = None,
    *,
    investigator: WindowInvestigator | None = None,
) -> _impl.ContextAnswer:
    if investigator is None:
        from resilimes.insight.investigator import investigate

        investigator = investigate
    return _impl.answer_context(run_or_kit, query, provider, settings, investigator=investigator)


def __getattr__(name: str) -> Any:
    """Private names of the old module (``from ... import _x``) still resolve."""
    return getattr(_impl, name)
