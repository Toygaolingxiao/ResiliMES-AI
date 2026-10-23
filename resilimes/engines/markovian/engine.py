"""Markovian chunked reasoning.

Each chunk receives a compressed checkpoint (decisions, entities, structured
state) instead of the growing transcript. The checkpoint size stays flat. A failed
chunk is contained: later chunks still run on the last good checkpoint.
The reported units are len(JSON) // 4, a size comparison between non-LLM calls,
not a model tokenizer and not a token-savings claim.

Marker strings follow the public spec: STATE_CHECKPOINT and TASK_COMPLETE.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from resilimes.engines.contracts import verify_contract

_DROP = {"transcript", "messages", "raw_prompt", "prose", "history"}
CarryFn = Callable[[dict[str, Any]], dict[str, Any]]


class ChunkRecord(BaseModel):
    index: int
    ok: bool
    checkpoint_units: int
    marker: str
    error: str | None = None


class RunResult(BaseModel):
    chunks: list[ChunkRecord] = Field(default_factory=list)
    final_state: dict[str, Any] = Field(default_factory=dict)
    checkpoint_units: int = 0
    replayed_history_units: int = 0
    unit: str = "json_chars_div_4"
    marker: str = "TASK_COMPLETE"


class MarkovianEngine:
    def __init__(
        self,
        verify_contracts_with: str,
        *,
        chunk_size: int = 1200,
        max_chunks: int = 8,
    ) -> None:
        self._secret = verify_contracts_with
        self.chunk_size = chunk_size
        self.max_chunks = max_chunks

    def run_from_contract(
        self,
        contract: dict[str, Any],
        steps: list[CarryFn],
        state: dict[str, Any] | None = None,
        *,
        now: Any = None,
    ) -> RunResult:
        verify_contract(
            contract,
            secret=self._secret,
            engine="markovian",
            required_capability="memory.write",
            now=now,
        )
        carry = compress(
            {
                "decisions": [],
                "entities": {},
                "open_issues": [],
                "state": state or {},
                "transcript": "",
            }
        )
        records: list[ChunkRecord] = []
        outputs: list[int] = []
        for index, step in enumerate(steps[: self.max_chunks]):
            incoming = compress(carry)
            incoming_units = json_units(incoming)
            try:
                produced = step(incoming)
                if not isinstance(produced, dict):
                    produced = {"state": {"value": produced}}
                carry = compress(produced)
                outputs.append(json_units(carry))
                records.append(
                    ChunkRecord(
                        index=index,
                        ok=True,
                        checkpoint_units=incoming_units,
                        marker="STATE_CHECKPOINT",
                    )
                )
            except Exception as exc:
                records.append(
                    ChunkRecord(
                        index=index,
                        ok=False,
                        checkpoint_units=incoming_units,
                        marker="STATE_CHECKPOINT",
                        error=type(exc).__name__,
                    )
                )
        marker = "TASK_COMPLETE" if records and records[-1].ok else "STATE_CHECKPOINT"
        if records and records[-1].ok:
            records[-1].marker = "TASK_COMPLETE"
        replayed = replayed_history_units(outputs or [json_units(carry)])
        return RunResult(
            chunks=records,
            final_state=carry,
            checkpoint_units=sum(item.checkpoint_units for item in records),
            replayed_history_units=replayed,
            marker=marker,
        )


def compress(carry: dict[str, Any]) -> dict[str, Any]:
    """Keep decisions and entities. Drop transcripts and oversized prose."""
    state = carry.get("state") or {}
    trimmed = _trim(state) if isinstance(state, dict) else {}
    decisions = list(carry.get("decisions") or [])[-12:]
    entities = carry.get("entities") if isinstance(carry.get("entities"), dict) else {}
    issues = list(carry.get("open_issues") or [])[-8:]
    return {
        "marker": "STATE_CHECKPOINT",
        "decisions": decisions,
        "entities": _trim(entities) if isinstance(entities, dict) else {},
        "open_issues": issues,
        "state": trimmed,
    }


def json_units(value: object) -> int:
    """JSON length divided by 4. This is a size comparison, not a model token count."""
    encoded = json.dumps(value, default=str, sort_keys=True)
    return max(1, len(encoded) // 4)


def replayed_history_units(step_units: list[int]) -> int:
    """Size if each chunk resent every earlier chunk. Not a token savings claim."""
    total = 0
    running = 0
    for count in step_units:
        running += count
        total += running
    return total


def flat_checkpoint_units(step_units: list[int], carry_units: int) -> int:
    """Size if each chunk pays for its own output plus one fixed checkpoint."""
    return sum(count + carry_units for count in step_units)


def _trim(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key in _DROP:
            continue
        if isinstance(item, str) and len(item) > 500:
            cleaned[key] = item[:500]
        elif isinstance(item, dict):
            cleaned[key] = _trim(item)
        else:
            cleaned[key] = item
    return cleaned
