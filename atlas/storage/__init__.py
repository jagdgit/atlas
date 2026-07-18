"""Storage Manager subsystem (Phase 0 · ATLAS_OS_ROADMAP §5.8, P8).

All durable files flow through the :class:`~atlas.storage.service.StorageManager`:
versioned + checksummed file registry, workspace allocation, advisory quotas, and
backup orchestration. Hot/warm/cold tiering is deferred (single disk today).
"""

from __future__ import annotations

from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageError, StorageManager

__all__ = ["StorageManager", "StorageRepository", "StorageError"]
