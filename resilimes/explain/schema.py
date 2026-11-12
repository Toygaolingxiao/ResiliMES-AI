"""Evidence Schema v0.

One bundle is the evidence behind one explanation (for now: why one lot is
late). Every item carries a tier:

* ``recorded`` (記録): read straight from the run record, no inference.
* ``attributed`` (観測帰因): split from what was observed, by a fixed rule
  (for example queue time shared by tool count). Reproducible, but a rule.
* ``unknown`` (不明): the record does not say why. The item must give a reason.

A bundle carries ``schema_version`` and ``content_hash``. The hash is SHA-256
over the canonical JSON of the bundle without the hash field, so a report can
be checked later against the same bundle. Changing any field changes the hash.

Version rule: adding an optional field keeps ``evidence/v0``; renaming or
removing a field, or changing a tier rule, needs a new version and a new
contract test.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal["evidence/v0"] = "evidence/v0"

Tier = Literal["recorded", "attributed", "unknown"]
TIERS: tuple[str, ...] = ("recorded", "attributed", "unknown")
TIER_LABEL_JA = {"recorded": "記録", "attributed": "観測帰因", "unknown": "不明"}

# Lateness buckets (``explain.lateness.BUCKETS``) by tier. Processing, setup,
# transport and release holds are rows in the record. Down, PM, batch, lots
# ahead, Q-time and AI-decision waits are split by rule. ``dispatch_other`` is
# a wait with an idle tool and no recorded cause, so it is unknown.
LATENESS_TIER: dict[str, str] = {
    "processing": "recorded",
    "setup": "recorded",
    "transport": "recorded",
    "release_hold": "recorded",
    "late_at_snapshot": "recorded",
    "down": "attributed",
    "pm": "attributed",
    "batch_wait": "attributed",
    "lots_ahead": "attributed",
    "qtime": "attributed",
    "ai_decision": "attributed",
    "dispatch_other": "unknown",
}


class RunRef(BaseModel):
    """Which run the evidence comes from. Enough to replay it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int
    horizon_sec: float
    policy: str
    label: str = "baseline"
    sched_mode: str | None = None


class Subject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["lot", "tool", "window"]
    id: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    tier: Tier
    value: float | None = None
    unit: str | None = None
    sources: tuple[str, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def _tier_rules(self) -> EvidenceItem:
        if self.tier == "unknown" and not self.reason:
            raise ValueError(f"{self.key}: an unknown item needs a reason")
        if self.tier != "unknown" and not self.sources:
            raise ValueError(f"{self.key}: a {self.tier} item needs at least one source")
        return self


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["evidence/v0"] = SCHEMA_VERSION
    subject: Subject
    run: RunRef
    items: tuple[EvidenceItem, ...] = Field(default=())
    content_hash: str = ""

    def body(self) -> dict[str, Any]:
        """Everything the hash covers."""
        return self.model_dump(mode="json", exclude={"content_hash"})

    def sealed(self) -> EvidenceBundle:
        return self.model_copy(update={"content_hash": content_hash(self.body())})

    def verify(self) -> bool:
        return bool(self.content_hash) and self.content_hash == content_hash(self.body())

    def tier_totals(self, unit: str = "sec") -> dict[str, float]:
        out = dict.fromkeys(TIERS, 0.0)
        for item in self.items:
            if item.unit == unit and item.value is not None:
                out[item.tier] += item.value
        return out


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(body: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def lateness_bundle(decomposition: dict[str, Any], run: RunRef) -> EvidenceBundle:
    """Evidence bundle from one ``explain.lateness.decompose`` result.

    Uses the ``overrun_sec`` split (time while late), so the item values sum to
    ``lateness_sec``. Zero buckets are left out.
    """
    lot_id = str(decomposition["lot_id"])
    source = f"run_record:lot={lot_id}"
    items: list[EvidenceItem] = [
        EvidenceItem(
            key="lateness",
            tier="recorded",
            value=float(decomposition["lateness_sec"]),
            unit="sec",
            sources=(f"{source}:end", f"{source}:due"),
        )
    ]
    for bucket, seconds in decomposition["overrun_sec"].items():
        if seconds <= 0:
            continue
        tier = LATENESS_TIER[bucket]
        items.append(
            EvidenceItem(
                key=f"overrun.{bucket}",
                tier=tier,
                value=float(seconds),
                unit="sec",
                sources=() if tier == "unknown" else (f"{source}:visits",),
                reason=(
                    "a tool was idle and the record has no cause (pin, gate or wake latency)"
                    if tier == "unknown"
                    else None
                ),
            )
        )
    bundle = EvidenceBundle(subject=Subject(kind="lot", id=lot_id), run=run, items=tuple(items))
    return bundle.sealed()
