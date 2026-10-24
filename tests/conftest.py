"""Test-wide settings.

The suite's expected numbers and golden digests were recorded on the qtime-r2
path, so it pins ``RESILIMES_SCHED_MODE=strict_qtime`` unless the caller set
it. ``tests/test_sched_mode.py`` covers the default (``plan``) mode explicitly.
"""

from __future__ import annotations

import os

os.environ.setdefault("RESILIMES_SCHED_MODE", "strict_qtime")
