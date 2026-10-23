"""Shared contract verification for every Meterless engine boundary.

Signing assumption: the public spec says
`HMAC_SHA256(secret, canonical_json(contract_without_signature))` but does not
pin the canonicalization algorithm. ResiliMES uses UTF-8 JSON with sorted keys
and compact separators, nulls removed. See docs/ASSUMPTIONS.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any


class ContractError(PermissionError):
    """Raised when a downstream engine refuses a contract."""


def canonical_json(data: Any) -> str:
    return json.dumps(
        _prune(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sign_body(body: dict[str, Any], secret: str) -> dict[str, Any]:
    payload = dict(body)
    payload.pop("signature", None)
    payload["signedBy"] = "scout"
    digest = hmac.new(
        secret.encode("utf-8"),
        canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    payload["signature"] = digest
    return payload


def verify_contract(
    contract: dict[str, Any] | None,
    *,
    secret: str,
    engine: str,
    required_capability: str | None = None,
    now: datetime | None = None,
) -> None:
    if not contract:
        raise ContractError(f"{engine} refused an empty contract")
    if contract.get("signedBy") != "scout":
        raise ContractError(f"{engine} refused a contract not signed by scout")
    signature = contract.get("signature")
    if not isinstance(signature, str) or not signature:
        raise ContractError(f"{engine} refused an unsigned contract")
    unsigned = {key: value for key, value in contract.items() if key != "signature"}
    expected = hmac.new(
        secret.encode("utf-8"),
        canonical_json(unsigned).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ContractError(f"{engine} refused a contract with a bad signature")
    expires_raw = contract.get("expiresAt")
    if not isinstance(expires_raw, str):
        raise ContractError(f"{engine} refused a contract with no expiry")
    expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
    current = now or datetime.now(UTC)
    if current >= expires:
        raise ContractError(f"{engine} refused an expired contract {contract.get('contractId')}")
    risk = contract.get("risk") or {}
    if isinstance(risk, dict) and risk.get("level") == "block":
        raise ContractError(f"{engine} refused a blocked contract")
    if required_capability is not None:
        scope = contract.get("scope") or {}
        capabilities = scope.get("capabilities") if isinstance(scope, dict) else []
        if required_capability not in (capabilities or []):
            raise ContractError(
                f"{engine} refused capability {required_capability}; contract allows {capabilities}"
            )
    if isinstance(risk, dict) and risk.get("level") == "high":
        approvals = risk.get("approvals") or []
        if not approvals:
            raise ContractError(f"{engine} refused a high-risk contract with no approval")


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _prune(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_prune(item) for item in value]
    if isinstance(value, float):
        return round(value, 4)
    return value
