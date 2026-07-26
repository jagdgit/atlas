"""Host Guard — keep Atlas slow-but-reliable under machine limits.

Design (aligned with Stage 3.2 detect→slow):
* Accept work always (missions/workers/archive jobs are durable).
* Run only when host capacity allows (global tick slots + RAM/CPU/thermal).
* Defer (never fail) when the host is under pressure; resume when safe.
* Prefer finishing the job over speed — the queue/schedules keep work alive.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.models.worker import WORKER_PAUSED, WORKER_RUNNING


class HostGuardService:
    """Admit / defer / resume worker activity against host limits."""

    name = "host_guard"
    VERSION = "hg.1"

    def __init__(
        self,
        *,
        resources: Any,
        workers: Any | None = None,
        arbiter: Any | None = None,
        missions: Any | None = None,
        max_concurrent_ticks: int = 4,
        max_archive_workers: int = 1,
        host_ram_reserve_mb: int = 2048,
        tick_ram_mb: int = 512,
        logger: logging.Logger | None = None,
    ) -> None:
        self._resources = resources
        self._workers = workers
        self._arbiter = arbiter
        self._missions = missions
        self._max_ticks = max(1, int(max_concurrent_ticks or 4))
        self._max_archive = max(1, int(max_archive_workers or 1))
        self._ram_reserve_mb = max(256, int(host_ram_reserve_mb or 2048))
        self._tick_ram_mb = max(64, int(tick_ram_mb or 512))
        self._logger = logger or logging.getLogger("atlas.host_guard")
        self._deferred_ticks = 0
        self._resumed = 0
        self._queued_starts = 0
        self._last_defer_reason = ""

    # --- admission (called from WorkerManager before a tick) -------------

    def can_run_tick(self, *, worker_type: str | None = None) -> tuple[bool, str]:
        """Return (ok, reason). False ⇒ defer this tick; schedule keeps the job."""
        decision = self._resources.can_admit_tick(
            expected_ram_mb=self._tick_ram_mb,
            reserve_mb=self._ram_reserve_mb,
        )
        if not decision.allowed:
            self._deferred_ticks += 1
            self._last_defer_reason = decision.reason
            return False, decision.reason
        return True, "admitted"

    def note_deferred(self, reason: str) -> None:
        self._deferred_ticks += 1
        self._last_defer_reason = reason or "deferred"

    # --- archive / spawn queueing ----------------------------------------

    def archive_slots_free(self) -> int:
        active = self._count_workers(type_name="owner_knowledge", statuses={WORKER_RUNNING})
        return max(0, self._max_archive - active)

    def should_queue_archive_start(self) -> bool:
        return self.archive_slots_free() <= 0

    def mark_queued_start(self) -> None:
        self._queued_starts += 1

    # --- periodic resume of capacity-queued workers ----------------------

    def tick(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resume oldest capacity-queued workers when the host is safe.

        Registered as ``host_guard_tick``. Never fails jobs — only starts work
        that was accepted earlier but held until capacity freed.
        """
        del payload  # unused; schedule payload optional
        if self._workers is None:
            return {"skipped": "no workers"}
        ok, reason = self.can_run_tick()
        if not ok:
            return {"skipped": "host_pressure", "reason": reason, "resumed": 0}

        free_archive = self.archive_slots_free()
        resumed: list[str] = []
        for worker in self._list_capacity_queued():
            wtype = getattr(worker, "type", None) or (worker.get("type") if isinstance(worker, dict) else None)
            wid = getattr(worker, "id", None) or (worker.get("id") if isinstance(worker, dict) else None)
            if not wid:
                continue
            if wtype == "owner_knowledge":
                if free_archive <= 0:
                    continue
                free_archive -= 1
            try:
                self._workers.resume(wid, reason="host_guard: capacity available")
                resumed.append(str(wid))
                self._resumed += 1
                # IR-RO2: clear WAITING_HOST on the owning mission when known.
                if self._missions is not None and hasattr(self._missions, "clear_queue_wait"):
                    mission_id = getattr(worker, "mission_id", None) or (
                        worker.get("mission_id") if isinstance(worker, dict) else None
                    )
                    if mission_id:
                        try:
                            self._missions.clear_queue_wait(
                                mission_id, reason="host_guard resumed"
                            )
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as exc:  # noqa: BLE001 - keep draining the queue
                self._logger.warning("host_guard resume failed for %s: %s", wid, exc)
            # One resume per guard tick keeps the ramp gentle.
            break
        return {
            "resumed": len(resumed),
            "worker_ids": resumed,
            "archive_slots_free": free_archive,
            "version": self.VERSION,
        }

    def status(self) -> dict[str, Any]:
        """Operator-facing host-respect posture for Ops / Archive UI."""
        posture = {}
        try:
            posture = self._resources.host_guard_status(
                reserve_mb=self._ram_reserve_mb,
                tick_ram_mb=self._tick_ram_mb,
            )
        except Exception as exc:  # noqa: BLE001
            posture = {"error": str(exc)}
        arbiter = {}
        if self._arbiter is not None and hasattr(self._arbiter, "snapshot"):
            try:
                arbiter = self._arbiter.snapshot()
            except Exception:  # noqa: BLE001
                arbiter = {}
        running = self._count_workers(statuses={WORKER_RUNNING})
        archive_running = self._count_workers(
            type_name="owner_knowledge", statuses={WORKER_RUNNING}
        )
        queued = len(self._list_capacity_queued())
        return {
            "version": self.VERSION,
            "policy": "slow_but_reliable",
            "max_concurrent_ticks": self._max_ticks,
            "max_archive_workers": self._max_archive,
            "host_ram_reserve_mb": self._ram_reserve_mb,
            "tick_ram_mb": self._tick_ram_mb,
            "running_workers": running,
            "archive_workers_running": archive_running,
            "capacity_queued_workers": queued,
            "deferred_ticks_total": self._deferred_ticks,
            "resumed_total": self._resumed,
            "queued_starts_total": self._queued_starts,
            "last_defer_reason": self._last_defer_reason,
            "arbiter": arbiter,
            "resources": posture,
            "note": (
                "Work is accepted and kept durable; ticks run only when host "
                "capacity and global tick slots allow. Under pressure Atlas "
                "defers — it does not drop the job."
            ),
        }

    # --- helpers ---------------------------------------------------------

    def _count_workers(
        self, *, type_name: str | None = None, statuses: set[str] | None = None
    ) -> int:
        if self._workers is None:
            return 0
        try:
            rows = self._workers.list_workers()
        except Exception:  # noqa: BLE001
            return 0
        n = 0
        for w in rows:
            st = getattr(w, "status", None) or (w.get("status") if isinstance(w, dict) else None)
            wt = getattr(w, "type", None) or (w.get("type") if isinstance(w, dict) else None)
            if statuses and st not in statuses:
                continue
            if type_name and wt != type_name:
                continue
            n += 1
        return n

    def _list_capacity_queued(self) -> list[Any]:
        if self._workers is None:
            return []
        try:
            rows = self._workers.list_workers(status=WORKER_PAUSED)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for w in rows:
            meta = getattr(w, "metadata", None) or (w.get("metadata") if isinstance(w, dict) else {}) or {}
            if meta.get("queued_for_capacity"):
                out.append(w)
        # Oldest first if created_at present.
        def _key(item: Any) -> str:
            return str(
                getattr(item, "created_at", None)
                or (item.get("created_at") if isinstance(item, dict) else "")
                or ""
            )

        return sorted(out, key=_key)
