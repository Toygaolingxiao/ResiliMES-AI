"""Construct the provider selected by settings."""

from __future__ import annotations

from resilimes.config import Settings
from resilimes.llm.mock import MockProvider
from resilimes.llm.nightshift import NightshiftProvider


def build_provider(settings: Settings) -> MockProvider | NightshiftProvider:
    if settings.use_nightshift:
        return NightshiftProvider(settings)
    return MockProvider()
