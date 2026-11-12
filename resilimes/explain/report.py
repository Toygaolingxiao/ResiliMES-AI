"""Read-only report of one Evidence Schema bundle.

The report adds no facts. It lays the bundle out so a page can show each
statement with its tier and sources, the share of time in each tier, and the
``content_hash`` so the same bundle can be checked again later.
"""

from __future__ import annotations

from typing import Any

from resilimes.explain.schema import TIERS, EvidenceBundle, canonical_json


def build_report(bundle: EvidenceBundle) -> dict[str, Any]:
    """One printable report. ``verified`` is true only when the hash matches."""
    totals = bundle.tier_totals()
    timed = sum(totals.values())
    percent = {tier: round(100.0 * totals[tier] / timed, 1) if timed else 0.0 for tier in TIERS}
    statements = [
        {
            "key": item.key,
            "tier": item.tier,
            "value": item.value,
            "unit": item.unit,
            "sources": list(item.sources),
            "reason": item.reason,
        }
        for item in bundle.items
    ]
    return {
        "schema_version": bundle.schema_version,
        "content_hash": bundle.content_hash,
        "verified": bundle.verify(),
        "canonical": canonical_json(bundle.body()),
        "subject": bundle.subject.model_dump(mode="json"),
        "run": bundle.run.model_dump(mode="json"),
        "statements": statements,
        "sections": {
            "what": [row["key"] for row in statements if row["tier"] == "recorded"],
            "why": [row["key"] for row in statements if row["tier"] == "attributed"],
            "unconfirmed": [
                {"key": row["key"], "reason": row["reason"]}
                for row in statements
                if row["tier"] == "unknown"
            ],
        },
        "coverage": {"seconds": totals, "percent": percent},
        "bundle": bundle.model_dump(mode="json"),
    }
