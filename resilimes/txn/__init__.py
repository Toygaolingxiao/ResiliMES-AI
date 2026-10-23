"""Transactional boundary the scheduler does not own.

``InMemoryStateStore`` is the default. ``RedisStateStore`` implements the same
``get`` / ``set`` / ``delete`` / ``compare_and_set`` protocol when ``REDIS_URL``
is set. ``InMemoryEngine`` is the transaction for either store. See docs/API.md.
"""

from resilimes.txn.engine import (
    EngineTransaction,
    InMemoryEngine,
    LockError,
    MachineLock,
    TxnResult,
)
from resilimes.txn.store import InMemoryStateStore, RedisStateStore, StateStore, build_store

__all__ = [
    "EngineTransaction",
    "InMemoryEngine",
    "InMemoryStateStore",
    "LockError",
    "MachineLock",
    "RedisStateStore",
    "StateStore",
    "TxnResult",
    "build_store",
]
