"""World Model and Markovian engines on signed Scout contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from resilimes.engines.contracts import ContractError
from resilimes.engines.markovian.engine import (
    MarkovianEngine,
    compress,
    flat_checkpoint_units,
)
from resilimes.engines.scout.engine import default_scout
from resilimes.engines.world_model.engine import WorldModel

SECRET = "engine-secret"
CLOCK = datetime(2026, 10, 23, 2, 0, tzinfo=UTC)


def _contract() -> dict:
    decision = default_scout(signing_secret=SECRET, clock=lambda: CLOCK).decide(
        {
            "prompt": "Machine Litho-02 Down",
            "user": {"id": "u", "role": "planner"},
            "surface": "mes_console",
        }
    )
    assert decision.execution_contract is not None
    return decision.execution_contract


def test_ingest_is_idempotent_and_replayable() -> None:
    world = WorldModel(SECRET)
    contract = _contract()
    first = world.ingest(
        event_type="equipment.observed",
        entity_type="equipment",
        entity_id="LITHO-02",
        payload={"status": "DOWN"},
        contract=contract,
        idempotency_key="boot",
        now=CLOCK,
    )
    second = world.ingest(
        event_type="equipment.observed",
        entity_type="equipment",
        entity_id="LITHO-02",
        payload={"status": "DOWN"},
        contract=contract,
        idempotency_key="boot",
        now=CLOCK,
    )
    assert first["eventId"] == second["eventId"]
    assert len(world.events) == 1
    rows = world.query(contract, entity_id="LITHO-02", now=CLOCK)
    assert rows[0]["status"] == "DOWN"


def test_payload_type_does_not_overwrite_the_job_entity() -> None:
    world = WorldModel(SECRET)
    contract = _contract()
    world.ingest(
        event_type="job.assigned",
        entity_type="job",
        entity_id="LOT-1001",
        payload={
            "equipmentId": "LITHO-01",
            "step": "LITHO",
            "type": "reassign",
            "actionType": "reassign",
        },
        contract=contract,
        idempotency_key="commit-LOT-1001-LITHO",
        required_capability="schedule.commit",
        now=CLOCK,
    )
    rows = world.query(contract, entity_type="job", now=CLOCK)
    assert len(rows) == 1
    assert rows[0]["type"] == "job"
    assert rows[0]["id"] == "LOT-1001"
    assert rows[0]["equipmentId"] == "LITHO-01"
    assert rows[0]["step"] == "LITHO"
    assert rows[0]["actionType"] == "reassign"


def test_world_model_refuses_unsigned_and_out_of_scope() -> None:
    world = WorldModel(SECRET)
    with pytest.raises(ContractError):
        world.ingest(
            event_type="equipment.observed",
            entity_type="equipment",
            entity_id="LITHO-02",
            payload={"status": "DOWN"},
            contract={"signedBy": "scout"},
            now=CLOCK,
        )
    contract = _contract()
    with pytest.raises(ContractError, match="capability"):
        world.ingest(
            event_type="job.assigned",
            entity_type="job",
            entity_id="LOT-1",
            payload={"equipmentId": "LITHO-01"},
            contract=contract,
            required_capability="not.allowed",
            now=CLOCK,
        )


def test_compress_drops_transcript_and_keeps_decisions() -> None:
    compacted = compress(
        {
            "decisions": ["moved LOT-1001"],
            "entities": {"equipment": "LITHO-02"},
            "state": {"verdict": "accept"},
            "transcript": "x" * 8000,
            "open_issues": [],
        }
    )
    assert compacted["marker"] == "STATE_CHECKPOINT"
    assert compacted["decisions"] == ["moved LOT-1001"]
    assert "transcript" not in compacted
    assert compacted["state"]["verdict"] == "accept"


def test_chunk_failure_is_contained() -> None:
    engine = MarkovianEngine(SECRET)

    def boom(_carry: dict) -> dict:
        raise RuntimeError("confused chunk")

    def recover(carry: dict) -> dict:
        assert "transcript" not in carry
        return {
            "decisions": ["recovered"],
            "entities": {},
            "open_issues": [],
            "state": {"ok": True},
            "transcript": "do not keep " * 400,
        }

    result = engine.run_from_contract(_contract(), [boom, recover], {"seed": 1}, now=CLOCK)
    assert result.chunks[0].ok is False
    assert result.chunks[0].error == "RuntimeError"
    assert result.chunks[1].ok is True
    assert result.chunks[1].marker == "TASK_COMPLETE"
    assert "transcript" not in result.final_state
    assert result.final_state["state"]["ok"] is True


def test_checkpoint_size_stays_below_replayed_history() -> None:
    """A size comparison of JSON checkpoints. Not a model token count."""
    from resilimes.engines.markovian.engine import replayed_history_units

    steps = [120] * 8
    assert flat_checkpoint_units(steps, 40) < replayed_history_units(steps)


def test_markovian_refuses_a_contract_without_memory_write() -> None:
    decision = default_scout(signing_secret=SECRET, clock=lambda: CLOCK).decide(
        {
            "prompt": "what is the fab status",
            "user": {"id": "u", "role": "viewer"},
            "surface": "mes_console",
        }
    )
    engine = MarkovianEngine(SECRET)
    with pytest.raises(ContractError):
        engine.run_from_contract(
            decision.execution_contract or {}, [], {}, now=CLOCK + timedelta(0)
        )
