"""Cause taxonomy for "why did this family's WIP change?" questions.

Shared by the investigator (which ranks and names a cause) and the fault
injection benchmark (which injects one cause and knows the truth). Kept here,
not in the benchmark, so the explain layer does not depend on the benchmark.
"""

from __future__ import annotations

from resilimes.explain.toolkit import Toolkit

TAXONOMY: tuple[str, ...] = (
    "tool_down",
    "pm_in_peak",
    "release_burst",
    "setup_thrash",
    "batch_cap",
    "upstream_starvation",
)
CAUSE_TEXT = {
    "tool_down": "unplanned tool down at the family (capacity lost)",
    "pm_in_peak": "planned PM placed in the family's arrival peak (capacity lost to PM)",
    "release_burst": "a burst of lots released / arriving at once",
    "setup_thrash": "setup thrash: much more setup time per start (changeovers)",
    "batch_cap": "batch size cap lowered: fewer lots per batch start",
    "upstream_starvation": "the main upstream family stopped feeding (it is down), so WIP drains",
}


def main_upstream(kit: Toolkit, fam: int) -> int:
    for src, _n in kit.route_upstream(fam).most_common():
        if src != fam and src >= 0:
            return src
    return -1
