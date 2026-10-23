"""Markovian chunked reasoning.

Each chunk receives a compressed checkpoint (decisions, entities, structured
state) instead of the growing transcript. Cost per chunk stays flat. A failed
chunk is contained: later chunks still run on the last good checkpoint.

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
    input_tokens: int
    marker: str
    error: str | None = None


class RunResult(BaseModel):
    chunks: list[ChunkRecord] = Field(default_factory=list)
    final_state: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = 0
    naive_tokens: int = 0
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
            incoming_tokens = estimate_tokens(incoming)
            try:
                produced = step(incoming)
                if not isinstance(produced, dict):
                    produced = {"state": {"value": produced}}
                carry = compress(produced)
                outputs.append(estimate_tokens(carry))
                records.append(
                    ChunkRecord(
                        index=index,
                        ok=True,
                        input_tokens=incoming_tokens,
                        marker="STATE_CHECKPOINT",
                    )
                )
            except Exception as exc:
                records.append(
                    ChunkRecord(
                        index=index,
                        ok=False,
                        input_tokens=incoming_tokens,
                        marker="STATE_CHECKPOINT",
                        error=type(exc).__name__,
                    )
                )
        marker = "TASK_COMPLETE" if records and records[-1].ok else "STATE_CHECKPOINT"
        if records and records[-1].ok:
            records[-1].marker = "TASK_COMPLETE"
        naive = naive_cumulative_tokens(outputs or [estimate_tokens(carry)])
        return RunResult(
            chunks=records,
            final_state=carry,
            input_tokens=sum(item.input_tokens for item in records),
            naive_tokens=naive,
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


def estimate_tokens(value: object) -> int:
    encoded = json.dumps(value, default=str, sort_keys=True)
    return max(1, len(encoded) // 4)


def naive_cumulative_tokens(step_tokens: list[int]) -> int:
    """Quadratic history: step k re-sends every previous step."""
    total = 0
    running = 0
    for count in step_tokens:
        running += count
        total += running
    return total


def markovian_cumulative_tokens(step_tokens: list[int], carry_tokens: int) -> int:
    """Flat carry: each step pays for its own output plus a fixed checkpoint."""
    return sum(count + carry_tokens for count in step_tokens)


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
