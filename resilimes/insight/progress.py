"""Moved to ``resilimes.common.progress``. This path stays for old imports and is the same module object."""

import sys

from resilimes.common.progress import *  # noqa: F403

sys.modules[__name__] = sys.modules["resilimes.common.progress"]
