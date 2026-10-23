"""Key-value state behind a dispatch transaction.

Values are strings. A missing key is None. ``compare_and_set`` is the lock
primitive: Redis SET NX and a SQL row compare are the same contract.
"""

from __future__ import annotations

import threading
from typing import Protocol


class StateStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def compare_and_set(self, key: str, expected: str | None, value: str) -> bool: ...


class InMemoryStateStore:
    """Process-local default. Not shared across machines."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        with self._guard:
            return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        with self._guard:
            self._data[key] = value

    def delete(self, key: str) -> None:
        with self._guard:
            self._data.pop(key, None)

    def compare_and_set(self, key: str, expected: str | None, value: str) -> bool:
        with self._guard:
            current = self._data.get(key)
            if current != expected:
                return False
            self._data[key] = value
            return True
