"""Moved to ``resilimes.common.deadline``. This path stays for old imports and is the same module object."""

import sys

from resilimes.common.deadline import *  # noqa: F403

sys.modules[__name__] = sys.modules["resilimes.common.deadline"]
