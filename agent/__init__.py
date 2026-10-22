"""ResiliMES multi-agent package: Planner, Specialist, Evaluator."""

from .llm import chat_completion, get_openai_client

__all__ = [
    "chat_completion",
    "get_openai_client",
    "plan_incident",
    "evaluate_plan",
]


def __getattr__(name: str):
    # Lazy exports avoid runpy warnings for `python -m agent.planner|evaluator`.
    if name == "plan_incident":
        from .planner import plan_incident

        return plan_incident
    if name == "evaluate_plan":
        from .evaluator import evaluate_plan

        return evaluate_plan
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
