"""Contract tests for Evidence Schema v0.

The field set, the tier rules and the hash are the contract. If one of these
tests has to change, the schema version has to change too.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resilimes.evidence.adapters import TwinReplayService, lot_evidence
from resilimes.evidence.toolkit import HOUR
from resilimes.explain.interfaces import ReplayRequest, ReplayService, RunRecordSource
from resilimes.explain.lateness import BUCKETS, late_lots
from resilimes.explain.schema import (
    LATENESS_TIER,
    SCHEMA_VERSION,
    TIER_LABEL_JA,
    TIERS,
    EvidenceBundle,
    EvidenceItem,
    RunRef,
    Subject,
    content_hash,
)
from resilimes.smt.fab import load_fab

REF = RunRef(seed=1, horizon_sec=6 * HOUR, policy="resilimes")


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        subject=Subject(kind="lot", id="Lot_1"),
        run=REF,
        items=(
            EvidenceItem(key="lateness", tier="recorded", value=60.0, unit="sec", sources=("a",)),
            EvidenceItem(
                key="overrun.down", tier="attributed", value=40.0, unit="sec", sources=("b",)
            ),
            EvidenceItem(
                key="overrun.dispatch_other", tier="unknown", value=20.0, unit="sec", reason="x"
            ),
        ),
    ).sealed()


def test_version_and_fields_are_pinned():
    assert SCHEMA_VERSION == "evidence/v0"
    assert TIERS == ("recorded", "attributed", "unknown")
    assert TIER_LABEL_JA == {"recorded": "記録", "attributed": "観測帰因", "unknown": "不明"}
    assert set(EvidenceBundle.model_fields) == {
        "schema_version",
        "subject",
        "run",
        "items",
        "content_hash",
    }
    assert set(EvidenceItem.model_fields) == {"key", "tier", "value", "unit", "sources", "reason"}
    assert set(RunRef.model_fields) == {"seed", "horizon_sec", "policy", "label", "sched_mode"}


def test_every_lateness_bucket_has_a_tier():
    assert set(BUCKETS) | {"late_at_snapshot"} == set(LATENESS_TIER)
    assert set(LATENESS_TIER.values()) <= set(TIERS)


def test_hash_is_stable_and_detects_changes():
    bundle = _bundle()
    assert bundle.content_hash.startswith("sha256:")
    assert bundle.verify()
    assert _bundle().content_hash == bundle.content_hash
    changed = bundle.model_copy(update={"run": REF.model_copy(update={"seed": 2})})
    assert not changed.verify()
    assert content_hash(changed.body()) != bundle.content_hash
    assert not EvidenceBundle(subject=bundle.subject, run=REF).verify()


def test_round_trip_keeps_the_hash():
    bundle = _bundle()
    again = EvidenceBundle.model_validate_json(bundle.model_dump_json())
    assert again == bundle
    assert again.verify()


def test_tier_rules():
    with pytest.raises(ValidationError):
        EvidenceItem(key="k", tier="unknown", value=1.0)
    with pytest.raises(ValidationError):
        EvidenceItem(key="k", tier="recorded", value=1.0)
    with pytest.raises(ValidationError):
        EvidenceItem(key="k", tier="guess", value=1.0, sources=("a",))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        EvidenceBundle(subject=Subject(kind="lot", id="x"), run=REF, extra=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        EvidenceBundle(schema_version="evidence/v1", subject=Subject(kind="lot", id="x"), run=REF)  # type: ignore[arg-type]


def test_tier_totals():
    totals = _bundle().tier_totals()
    assert totals == {"recorded": 60.0, "attributed": 40.0, "unknown": 20.0}


@pytest.fixture(scope="module")
def service():
    return TwinReplayService(load_fab())


def test_twin_adapter_emits_a_sealed_bundle(service):
    assert isinstance(service, ReplayService)
    record = service.baseline(REF)
    assert isinstance(record, RunRecordSource)
    lots = late_lots(record.timeline)
    assert lots
    bundle = lot_evidence(record, lots[0])
    assert bundle.verify()
    lateness = next(item.value for item in bundle.items if item.key == "lateness")
    split = sum(item.value or 0.0 for item in bundle.items if item.key.startswith("overrun."))
    assert split == pytest.approx(lateness, abs=1e-3)
    assert lot_evidence(service.baseline(REF), lots[0]).content_hash == bundle.content_hash


def test_replay_without_change_matches_baseline(service):
    base = service.baseline(REF)
    lot = late_lots(base.timeline)[0]
    again = service.replay(ReplayRequest(base=REF, label="baseline"))
    assert lot_evidence(again, lot).content_hash == lot_evidence(base, lot).content_hash
