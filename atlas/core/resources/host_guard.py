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
    VERSION = "hg.1.3-archive-cap"

    def __init__(
        self,
        *,
        resources: Any,
        workers: Any | None = None,
        arbiter: Any | None = None,
        missions: Any | None = None,
        max_concurrent_ticks: int = 4,
        max_archive_workers: int = 1,
        archive_one_in_rth: bool = True,
        archive_one_evening: bool = True,
        archive_evening_until_hour_ist: int = 22,
        host_ram_reserve_mb: int = 2048,
        tick_ram_mb: int = 512,
        logger: logging.Logger | None = None,
        clock: Any | None = None,
    ) -> None:
        self._resources = resources
        self._workers = workers
        self._arbiter = arbiter
        self._missions = missions
        self._max_ticks = max(1, int(max_concurrent_ticks or 4))
        self._max_archive = max(1, int(max_archive_workers or 1))
        self._archive_one_in_rth = bool(archive_one_in_rth)
        self._archive_one_evening = bool(archive_one_evening)
        self._archive_evening_until_hour_ist = max(
            16, min(23, int(archive_evening_until_hour_ist or 22))
        )
        self._ram_reserve_mb = max(256, int(host_ram_reserve_mb or 2048))
        self._tick_ram_mb = max(64, int(tick_ram_mb or 512))
        self._logger = logger or logging.getLogger("atlas.host_guard")
        self._clock = clock
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

    def _effective_max_archive(self) -> int:
        """OI-STAB0 / DP-BATCH1: clamp archive during RTH and evening densify."""
        if self._max_archive <= 1:
            return 1
        now = self._clock() if callable(self._clock) else None
        if self._archive_one_in_rth:
            try:
                from atlas.trading.sessions import is_session_open

                if is_session_open("nse_equity", now=now):
                    return 1
            except Exception:  # noqa: BLE001
                self._logger.debug("RTH archive clamp check failed", exc_info=True)
        if self._archive_one_evening:
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo

                from atlas.trading.sessions import is_session_open

                if not is_session_open("nse_equity", now=now):
                    if now is None:
                        dt = datetime.now(ZoneInfo("Asia/Kolkata"))
                    elif getattr(now, "tzinfo", None) is None:
                        dt = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(
                            ZoneInfo("Asia/Kolkata")
                        )
                    else:
                        dt = now.astimezone(ZoneInfo("Asia/Kolkata"))
                    # Post-close evening densify (15:30–until_hour IST): leave
                    # a host slot for fundamentals_enrich / market NORMAL work.
                    after_close = dt.hour > 15 or (dt.hour == 15 and dt.minute >= 30)
                    if after_close and dt.hour < self._archive_evening_until_hour_ist:
                        return 1
            except Exception:  # noqa: BLE001
                self._logger.debug("evening archive clamp failed", exc_info=True)
        return self._max_archive

    def archive_slots_free(self) -> int:
        active = self._count_workers(type_name="owner_knowledge", statuses={WORKER_RUNNING})
        return max(0, self._effective_max_archive() - active)

    def should_queue_archive_start(self) -> bool:
        return self.archive_slots_free() <= 0

    def mark_queued_start(self) -> None:
        self._queued_starts += 1

    # --- periodic resume of capacity-queued workers ----------------------

    def _list_running_archive(self) -> list[Any]:
        if self._workers is None:
            return []
        try:
            rows = self._workers.list_workers()
        except Exception:  # noqa: BLE001
            return []
        out: list[Any] = []
        for w in rows:
            st = getattr(w, "status", None) or (
                w.get("status") if isinstance(w, dict) else None
            )
            wt = getattr(w, "type", None) or (
                w.get("type") if isinstance(w, dict) else None
            )
            if st == WORKER_RUNNING and wt == "owner_knowledge":
                out.append(w)
        return out

    def _enforce_archive_cap(self) -> list[str]:
        """Demote excess archive runners when RTH/evening clamp shrinks the max.

        Admit/display clamp alone is not enough: overnight can start 2 with
        configured max=2, then RTH shows running=2 / max=1. Invariant:
        archive_running <= _effective_max_archive() after every guard tick.
        """
        if self._workers is None or not hasattr(self._workers, "pause"):
            return []
        limit = self._effective_max_archive()
        running = self._list_running_archive()
        if len(running) <= limit:
            return []

        def _created(item: Any) -> str:
            return str(
                getattr(item, "created_at", None)
                or (item.get("created_at") if isinstance(item, dict) else "")
                or ""
            )

        # Keep oldest (stable); pause newest excess and queue for later resume.
        ordered = sorted(running, key=_created)
        excess = ordered[limit:]
        paused: list[str] = []
        for w in excess:
            wid = getattr(w, "id", None) or (
                w.get("id") if isinstance(w, dict) else None
            )
            if not wid:
                continue
            meta = getattr(w, "metadata", None) or (
                w.get("metadata") if isinstance(w, dict) else {}
            )
            if not isinstance(meta, dict):
                meta = {}
            meta = dict(meta)
            meta["queued_for_capacity"] = True
            meta["queue_reason"] = "archive_slots_clamped"
            try:
                if hasattr(self._workers, "update_metadata"):
                    self._workers.update_metadata(wid, meta)
                elif hasattr(self._workers, "_repo") and hasattr(
                    self._workers._repo, "update_metadata"
                ):
                    self._workers._repo.update_metadata(wid, meta)
                else:
                    # Best-effort for fakes / thin stubs
                    if isinstance(w, dict):
                        w["metadata"] = meta
                    else:
                        w.metadata = meta
            except Exception:  # noqa: BLE001
                self._logger.debug("archive cap metadata update failed", exc_info=True)
            try:
                self._workers.pause(str(wid), reason="host_guard: archive cap")
                paused.append(str(wid))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "host_guard archive demotion failed for %s: %s", wid, exc
                )
        if paused:
            self._logger.info(
                "archive cap enforced: paused %s (limit=%s)", paused, limit
            )
        return paused

    def tick(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resume oldest capacity-queued workers when the host is safe.

        Registered as ``host_guard_tick``. Never fails jobs — only starts work
        that was accepted earlier but held until capacity freed.
        """
        del payload  # unused; schedule payload optional
        if self._workers is None:
            return {"skipped": "no workers"}
        demoted = self._enforce_archive_cap()
        ok, reason = self.can_run_tick()
        if not ok:
            return {
                "skipped": "host_pressure",
                "reason": reason,
                "resumed": 0,
                "archive_demoted": demoted,
            }

        free_archive = self.archive_slots_free()
        prefer_market = self._effective_max_archive() < self._max_archive
        resumed: list[str] = []
        for worker in self._list_capacity_queued(prefer_non_archive=prefer_market):
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
            "archive_demoted": demoted,
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
        eff_archive = self._effective_max_archive()
        return {
            "version": self.VERSION,
            "policy": "slow_but_reliable",
            "max_concurrent_ticks": self._max_ticks,
            "max_archive_workers": eff_archive,
            "configured_max_archive_workers": self._max_archive,
            "archive_one_in_rth": self._archive_one_in_rth,
            "archive_one_evening": self._archive_one_evening,
            "archive_evening_until_hour_ist": self._archive_evening_until_hour_ist,
            "archive_rth_clamped": eff_archive < self._max_archive,
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
                "defers — it does not drop the job. OI-STAB0/DP-BATCH1: archive "
                "lane forced to 1 during NSE RTH and evening densify window."
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

    def _list_capacity_queued(
        self, *, prefer_non_archive: bool = False
    ) -> list[Any]:
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

        def _created(item: Any) -> str:
            return str(
                getattr(item, "created_at", None)
                or (item.get("created_at") if isinstance(item, dict) else "")
                or ""
            )

        def _type(item: Any) -> str:
            return str(
                getattr(item, "type", None)
                or (item.get("type") if isinstance(item, dict) else "")
                or ""
            )

        if prefer_non_archive:
            # DP-BATCH1 — market enrich before archive when evening/RTH clamped.
            return sorted(
                out,
                key=lambda item: (
                    0 if _type(item) != "owner_knowledge" else 1,
                    _created(item),
                ),
            )
        return sorted(out, key=_created)
