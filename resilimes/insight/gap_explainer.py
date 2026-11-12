"""Moved to ``resilimes.explain.gap_explainer``. This path stays for old imports and is the same module object."""

import sys

from resilimes.explain.gap_explainer import *  # noqa: F403

sys.modules[__name__] = sys.modules["resilimes.explain.gap_explainer"]
