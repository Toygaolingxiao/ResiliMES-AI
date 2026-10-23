"""World Model — append-only plant event log.

Implements the public World Model properties that the recovery loop needs:
an append-only log, idempotent ingest, and a replayable entity view.
The browser control plane from the spec is the ResiliMES console, which
renders the replayed schedule rather than a second admin UI.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from resilimes.engines.contracts import canonical_json, verify_contract


class WorldModel:
    def __init__(self, verify_contracts_with: str) -> None:
        self._secret = verify_contracts_with
        self.events: list[dict[str, Any]] = []
        self._ids: dict[str, dict[str, Any]] = {}
        self.schema_version = 1

    def ingest(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        contract: dict[str, Any],
        idempotency_key: str | None = None,
        required_capability: str = "world.sync",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        verify_contract(
            contract,
            secret=self._secret,
            engine="world-model",
            required_capability=required_capability,
            now=now,
        )
        identity = canonical_json(
            {
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": payload,
                "key": idempotency_key,
            }
        )
        event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        existing = self._ids.get(event_id)
        if existing is not None:
            return existing
        event = {
            "schemaVersion": self.schema_version,
            "eventId": event_id,
            "eventType": event_type,
            "entityType": entity_type,
            "entityId": entity_id,
            "payload": payload,
            "contractId": contract.get("contractId"),
            "occurredAt": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.events.append(event)
        self._ids[event_id] = event
        return event

    def replay(self) -> dict[str, dict[str, Any]]:
        entities: dict[str, dict[str, Any]] = {}
        for event in self.events:
            key = f"{event['entityType']}:{event['entityId']}"
            current = entities.get(key)
            if current is None:
                current = {}
            payload = event["payload"]
            if isinstance(payload, dict):
                for field, value in payload.items():
                    # Identity comes from the event, never from a payload key
                    # that happens to be named id or type.
                    if field in {"id", "type"}:
                        continue
                    current[field] = value
            current["id"] = event["entityId"]
            current["type"] = event["entityType"]
            current["lastEvent"] = event["eventId"]
            entities[key] = current
        return entities

    def query(
        self,
        contract: dict[str, Any],
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        verify_contract(
            contract,
            secret=self._secret,
            engine="world-model",
            required_capability="world.query",
            now=now,
        )
        rows = list(self.replay().values())
        if entity_type is not None:
            rows = [row for row in rows if row.get("type") == entity_type]
        if entity_id is not None:
            rows = [row for row in rows if row.get("id") == entity_id]
        return rows
