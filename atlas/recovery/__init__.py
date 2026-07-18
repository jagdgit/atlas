"""Recovery subsystem (Phase 0 · §2.8, P1/P4).

Startup crash recovery that runs *before Atlas accepts new work* (:class:`RecoveryManager`)
plus the checkpoint foundation (:class:`CheckpointStore`) that lets long-running work resume
exactly where a power loss interrupted it. Design-for-failure: a computer with no UPS and a
flaky link should recover, not rebuild.
"""

from __future__ import annotations

from atlas.recovery.checkpoints import CheckpointStore
from atlas.recovery.manager import RecoveryManager

__all__ = ["RecoveryManager", "CheckpointStore"]
