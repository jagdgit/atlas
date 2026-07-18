"""Checkpoint store (Phase 0 · §2.8, P1/P4) — resume-point foundation.

A thin, durable key/value over ``system.checkpoints`` so long-running work can save its
progress and, after a power loss, resume *exactly there* instead of restarting. Phase 0
ships the primitive; Phase A workers/jobs adopt it in their step loops.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.repositories.recovery_repo import CheckpointRepository


class CheckpointStore:
    name = "checkpoints"
    VERSION = "1"

    def __init__(
        self,
        repo: "CheckpointRepository",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._logger = logger or logging.getLogger("atlas.recovery.checkpoints")

    def save(
        self,
        owner_type: str,
        owner_id: str,
        state: dict[str, Any],
        *,
        label: str = "default",
    ) -> dict[str, Any]:
        """Persist (upsert) a checkpoint for ``(owner_type, owner_id, label)``."""
        return self._repo.save(owner_type, owner_id, state, label=label)

    def load(
        self, owner_type: str, owner_id: str, *, label: str = "default"
    ) -> dict[str, Any] | None:
        """Return the saved state dict, or ``None`` if there is no checkpoint."""
        row = self._repo.load(owner_type, owner_id, label=label)
        return dict(row["state"]) if row else None

    def clear(
        self, owner_type: str, owner_id: str, *, label: str | None = None
    ) -> int:
        """Delete checkpoint(s) for an owner (one label, or all when label is None)."""
        return self._repo.clear(owner_type, owner_id, label=label)

    def most_recent(self) -> dict[str, Any] | None:
        """The most recently updated checkpoint (owner + timestamp) — dashboard use."""
        return self._repo.most_recent()

    # --- lifecycle ------------------------------------------------------

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok("checkpoint store ready")
