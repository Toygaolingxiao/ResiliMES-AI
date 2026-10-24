"""H-MEM conformance (the spec's vendored vectors.json, Apache 2.0) plus shift memory."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from resilimes.engines.hmem import HMEM, ShiftMemory

VECTORS = json.loads(
    (Path(__file__).parents[1] / "resilimes/engines/hmem/vectors.json").read_text("utf-8")
)
T0 = VECTORS["clock"]
DAY = 24 * 3600 * 1000
S = VECTORS["sections"]


def _ids(section: str) -> list[Any]:
    return [pytest.param(case, id=case["id"]) for case in S[section]]


@pytest.mark.parametrize("case", _ids("record-validation"))
def test_record_validation(case: dict[str, Any]) -> None:
    h = HMEM(clock=lambda: T0)
    try:
        h.add(content=case["input"]["content"], source=case["input"]["source"])
        rejected = False
    except ValueError:
        rejected = True
    assert rejected == (case["expect"] == "reject")


@pytest.mark.parametrize("case", _ids("feedback-deltas"))
def test_feedback_deltas(case: dict[str, Any]) -> None:
    h = HMEM(clock=lambda: T0)
    m = h.add(content="feedback target record", confidence=case["start"], source="conformance")
    before = m.accessCount
    h.feedback(m.id, case["kind"])
    after = h.store.get(m.id)
    assert after is not None
    assert after.confidence == pytest.approx(case["expectConfidence"], abs=1e-9)
    if "expectAccessDelta" in case:
        assert after.accessCount - before == case["expectAccessDelta"]
    if "expectTag" in case:
        assert case["expectTag"] in after.tags


@pytest.mark.parametrize("case", _ids("ranking-order"))
def test_ranking_order(case: dict[str, Any]) -> None:
    h = HMEM(clock=lambda: T0)
    by = {
        r["key"]: h.add(
            content=r["content"], confidence=r["confidence"], layer=r["layer"], source="conformance"
        )
        for r in case["records"]
    }
    for r in case["records"]:
        if "supersededByKey" in r:
            by[r["key"]].supersededBy = by[r["supersededByKey"]].id
    order = [hit.memory.id for hit in h.query(case["query"], {"threshold": 0, "topN": 10}).memories]
    expected = [by[key].id for key in case["expectOrder"]]
    assert all(order.index(a) < order.index(b) for a, b in itertools.pairwise(expected))


@pytest.mark.parametrize("case", _ids("sleep-guardrails"))
def test_sleep_guardrails(case: dict[str, Any]) -> None:
    now = [T0]
    h = HMEM(clock=lambda: now[0])
    by = {
        r["key"]: h.add(content=r["content"], source=r["source"], derivedFrom=r.get("derivedFrom"))
        for r in case["records"]
    }
    now[0] = T0 + case["ageDays"] * DAY
    before = sorted(m.id for m in h.store.all())
    preview = h.sleep.preview()
    assert sorted(m.id for m in h.store.all()) == before, "preview mutated the store"
    for key in case["expectArchived"]:
        assert by[key].id in preview["toArchive"]
    for key in case["expectProtected"]:
        assert by[key].id not in preview["toArchive"]
    report = h.sleep.execute(preview)
    for key in case["expectProtected"]:
        assert h.store.get(by[key].id) is not None
    assert isinstance(report["backupId"], str) and report["backupId"]
    h.sleep.restore(report["backupId"])
    assert sorted(m.id for m in h.store.all()) == before


@pytest.mark.parametrize("case", _ids("conflict-gate"))
def test_conflict_gate(case: dict[str, Any]) -> None:
    h = HMEM(clock=lambda: T0)
    a = h.add(
        content=case["a"]["content"], confidence=case["a"]["confidence"], source="conformance"
    )
    b = h.add(
        content=case["b"]["content"], confidence=case["b"]["confidence"], source="conformance"
    )
    found = h.conflicts.scan()
    assert found
    outcome = h.conflicts.autoResolve(found[0])
    assert outcome in ("resolved", "queued")
    ma, mb = h.store.get(a.id), h.store.get(b.id)
    assert ma is not None and mb is not None
    if outcome == "resolved":
        assert ma.supersededBy or mb.supersededBy


@pytest.mark.parametrize("case", _ids("ledger-audit"))
def test_ledger_audit(case: dict[str, Any]) -> None:
    h = HMEM(clock=lambda: T0)
    m = h.add(content="audited record", confidence=case["start"], source="conformance")
    h.feedback(m.id, case["kind"])
    history = [e for e in h.ledger.history(m.id) if e["action"] != "read"]
    assert [e["action"] for e in history] == case["expectActions"]
    assert history[-1]["previousState"]["confidence"] == pytest.approx(case["expectPrev"])
    assert history[-1]["newState"]["confidence"] == pytest.approx(case["expectNew"])


@pytest.mark.parametrize("case", _ids("dream-boundary"))
def test_dream_boundary(case: dict[str, Any]) -> None:
    h = HMEM(clock=lambda: T0)
    for r in case["records"]:
        h.add(content=r["content"], type=r["type"], source="conformance")
    count = len(h.store.all())
    proposals = h.dreaming.dream()
    assert proposals and len(h.store.all()) == count
    created = h.dreaming.approve(proposals[0].id)
    assert created is not None and created.layer == "long_term" and created.derivedFrom


# ---------------------------------------------------------------- shift memory
def _view(kind: str = "breakdown", family: str = "LithoA") -> dict[str, Any]:
    return {
        "kind": kind,
        "family": family,
        "situation": f"{family} scanner down, 6 lots pinned",
        "tools": [{"tool": f"{family}_1", "down_until_h": 3.0}],
    }


def _entry(eid: str, chosen: str, dwt: float, levers: list[str]) -> dict[str, Any]:
    base = {"wt_min": 100.0, "qviol": 2.0, "hot_late": 0.0}
    chosen_kpi = {**base, "wt_min": 100.0 + dwt}
    plans = [{"id": "A", "levers": []}, {"id": chosen, "levers": [{"type": t} for t in levers]}]
    return {
        "id": eid,
        "t_h": 1.0,
        "tool": "LithoA_1",
        "chosen": chosen,
        "default": "A",
        "fallback": False,
        "plans": plans,
        "receipt": {"futures": 3, "horizon_h": 8.0, "default": base, "chosen": chosen_kpi},
    }


def test_shift_memory_receipts_recall_override_and_playbook() -> None:
    mem = ShiftMemory(scope="test")
    for k in range(3):
        mem.remember(_view(), _entry(f"e{k}", "B", -30.0, ["keep_pin"]))
    mem.remember(_view("pm_conflict", "Implant"), _entry("e9", "A", 0.0, []))
    cases = mem.recall(_view())
    assert 1 <= len(cases) <= 5 and all(c["kind"] == "breakdown" for c in cases[:3])
    assert cases[0]["delta_wt_min"] == -30.0
    assert not mem.skip_twin(cases)  # those cases improved on the default
    playbook = mem.propose_playbook()
    assert len(playbook) == 1 and "keep_pin" in playbook[0]["text"]
    assert len(mem.h.store.all()) == 4, "a proposal is not a record until approved"
    approved = mem.approve_playbook(playbook[0]["id"], by="shift-lead")
    assert approved is not None and approved.derivedFrom and approved.layer == "long_term"
    override = mem.record_override(
        "e0", "A", by="shift-lead", note="scanner ETA was wrong", kind="breakdown", family="LithoA"
    )
    twin = mem.h.store.get(mem.by_exception["e0"])
    assert twin is not None and twin.supersededBy == override.id and "review" in twin.tags
    assert override.provenance["origin"] == "human"


def test_skip_twin_needs_repeated_default_receipts(tmp_path: Path) -> None:
    mem = ShiftMemory()
    for k in range(3):
        mem.remember(_view(), _entry(f"d{k}", "A", 0.0, []))
    assert mem.skip_twin(mem.recall(_view()))
    path = tmp_path / "mem.json"
    mem.save(path)
    again = ShiftMemory.load(path)
    assert len(again.h.store.all()) == 3 and again.skip_twin(again.recall(_view()))
