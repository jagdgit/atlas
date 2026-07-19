"""Persistent Worker subsystem (Phase A · PHASE_A_PLAN §A.4).

Long-running, mission-owned workers that run as short-task + checkpoint loops driven by the
schedule table, so they survive kill -9 + reboot and resume exactly where they left off. Workers
are the "keep doing this over time" primitive — never a new intelligence (P5/P7).
"""

from __future__ import annotations

from atlas.workers.base import PersistentWorker, TickContext, TickResult
from atlas.workers.hello import HelloWatcher
from atlas.workers.manager import WorkerError, WorkerManager
from atlas.workers.repo_watcher import RepoWatcher

__all__ = [
    "WorkerManager",
    "WorkerError",
    "PersistentWorker",
    "TickContext",
    "TickResult",
    "HelloWatcher",
    "RepoWatcher",
]
