"""Pick the data source for the current settings."""

from __future__ import annotations

from resilimes.config import Settings
from resilimes.data.sample_source import SampleSource
from resilimes.data.zetaris_source import ZetarisSource


def build_source(settings: Settings) -> SampleSource | ZetarisSource:
    if settings.use_zetaris:
        return ZetarisSource(
            schema=settings.zetaris_schema,
            timeout_s=settings.zetaris_timeout_s,
        )
    return SampleSource(settings.data_dir, schema=settings.zetaris_schema)
