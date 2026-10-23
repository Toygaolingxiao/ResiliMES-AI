"""Live connectors used by the recovery path: Nightshift chat and the Zetaris client.

The recovery loop does not import a planner or an evaluator from this package.
Planning is `resilimes.domain.schedule`. The critic is `resilimes.domain.critique`.
Nightshift only explains.
"""

from .llm import chat_completion, get_openai_client

__all__ = [
    "chat_completion",
    "get_openai_client",
]
