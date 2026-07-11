"""Storage provider interface (ADR-0038) — the surface repositories depend on.

Repositories today use ``DatabaseManager`` directly. This protocol captures the
minimal surface they actually need (a connection context manager + health), so a
non-PostgreSQL backend could be substituted far in the future without touching
repository call sites. ``DatabaseManager`` satisfies it structurally already.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StorageProvider(Protocol):
    def connection(self) -> AbstractContextManager[Any]:
        """Yield a live connection/session for the duration of a ``with`` block."""
        ...

    def health_check(self) -> bool: ...

    def close(self) -> None: ...
