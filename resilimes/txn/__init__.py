"""Transactional boundary the scheduler does not own.

The in-memory store is the default. A Redis or database transaction on the
other branch implements the same protocols. See docs/API.md.
"""

from resilimes.txn.engine import (
    EngineTransaction,
    InMemoryEngine,
    LockError,
    MachineLock,
    TxnResult,
)
from resilimes.txn.store import InMemoryStateStore, StateStore

__all__ = [
    "EngineTransaction",
    "InMemoryEngine",
    "InMemoryStateStore",
    "LockError",
    "MachineLock",
    "StateStore",
    "TxnResult",
]
