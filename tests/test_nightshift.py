"""Nightshift completion budget, reasoning strips, and empty replies."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from resilimes.agents.orchestrator import _narrative_from_model
from resilimes.config import Settings
from resilimes.llm.nightshift import NightshiftProvider, strip_reasoning


def _settings(**overrides: object) -> Settings:
    base = dict(
        mode="live",
        meterless_runtime_token="real-token",
        nemotron_model="nvidia/nemotron-3.5-lightning-30b-a3b",
        nemotron_max_tokens=4096,
        llm_max_retries=1,
        zetaris_api_key="x",
        zetaris_rest_url="https://api.example.test/api/v1.0",
        zetaris_org_id="1",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _reply(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _provider(settings: Settings | None = None) -> NightshiftProvider:
    with patch("resilimes.llm.nightshift.build_openai_client", return_value=MagicMock()):
        provider = NightshiftProvider(settings or _settings())
    provider._client = MagicMock()
    return provider


def test_default_model_is_nemotron_lightning() -> None:
    assert Settings().nemotron_model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert Settings().nemotron_max_tokens == 4096


def test_strip_reasoning_drops_think_blocks_and_a_leaked_prefix() -> None:
    leaked = "planning the sentence\n</think>\n\nLOT-1001 moves to LITHO-01."
    assert strip_reasoning(leaked) == "LOT-1001 moves to LITHO-01."
    blocked = "Keep <think>hidden plan</think> the lot on LITHO-01."
    assert strip_reasoning(blocked) == "Keep  the lot on LITHO-01."
    both = "<think>draft</think>still thinking</think>\nThe move is legal."
    assert strip_reasoning(both) == "The move is legal."


def test_empty_content_retries_once_with_a_larger_budget() -> None:
    provider = _provider()
    provider._client.chat.completions.create = MagicMock(
        side_effect=[_reply(""), _reply('{"narrative": "LOT-1001 leaves LITHO-02."}')]
    )
    result = provider.complete([{"role": "user", "content": "explain"}], lane="explainer")
    assert result.content == '{"narrative": "LOT-1001 leaves LITHO-02."}'
    assert result.mocked is False
    calls = provider._client.chat.completions.create.call_args_list
    assert [call.kwargs["max_tokens"] for call in calls] == [4096, 8192]


def test_think_only_body_is_empty_and_retries() -> None:
    provider = _provider()
    provider._client.chat.completions.create = MagicMock(
        side_effect=[_reply("<think>only reasoning</think>"), _reply("The lot moves.")]
    )
    result = provider.complete([{"role": "user", "content": "explain"}], lane="explainer")
    assert result.content == "The lot moves."
    assert provider._client.chat.completions.create.call_count == 2


def test_empty_reply_after_retry_keeps_the_deterministic_narrative() -> None:
    provider = _provider()
    provider._client.chat.completions.create = MagicMock(side_effect=[_reply(None), _reply("   ")])
    result = provider.complete([{"role": "user", "content": "explain"}], lane="explainer")
    assert result.content == ""
    assert result.mocked is False
    spoken = _narrative_from_model(result.content, "LOT-1001 leaves LITHO-02.")
    assert spoken == "LOT-1001 leaves LITHO-02."
    assert provider._client.chat.completions.create.call_count == 2
