"""Operations Dashboard aggregator (Phase 0 · ATLAS_OS_ROADMAP §5.11, A4).

Assembles the **single-screen** operator snapshot: Atlas status, live counts, host
metrics (CPU/RAM/disk/internet, temp/UPS best-effort), last backup, capability
inventory, and SSE subscriber count. Every section is guarded so one broken source
degrades to an empty/absent value rather than failing the whole dashboard.

Counts for workers/missions are 0 until Phase A introduces them; ``recovery`` reports the
last startup-recovery pass and ``last_checkpoint`` the most recent resume point (both from
§2.8). The design leaves keys in place so the UI doesn't change when values start flowing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, TypeVar

if TYPE_CHECKING:
    from atlas.kernel.application import Application
    from atlas.system.host import HostMetrics
    from atlas.system.time import ClockService

T = TypeVar("T")


class OperationsDashboard:
    name = "ops_dashboard"

    def __init__(
        self,
        app: "Application",
        host: "HostMetrics",
        *,
        clock: "ClockService | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._app = app
        self._host = host
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.ops.dashboard")

    def snapshot(self) -> dict[str, Any]:
        return {
            "atlas": self._guard(self._atlas, {}),
            "counts": self._guard(self._counts, {}),
            "host": self._guard(self._host.snapshot, {}),
            "backup": self._guard(self._backup, {}),
            "storage": self._guard(self._storage, {}),
            "capabilities": self._guard(self._capabilities, []),
            "sse_subscribers": self._guard(self._sse_subscribers, 0),
            "recovery": self._guard(self._recovery, {}),
            "last_checkpoint": self._guard(self._last_checkpoint, None),
            "generated_at": self._now(),
        }

    # --- sections -------------------------------------------------------

    def _atlas(self) -> dict[str, Any]:
        return self._app.status()

    def _counts(self) -> dict[str, Any]:
        counts: dict[str, Any] = {
            "jobs_total": 0,
            "jobs_active": 0,
            "jobs_queued": 0,
            "workers": 0,     # Phase A
            "missions": 0,    # Phase A
        }
        jobs = self._resolve("jobs")
        if jobs is not None and hasattr(jobs, "list_jobs"):
            rows = jobs.list_jobs(limit=500)
            counts["jobs_total"] = len(rows)
            active = queued = 0
            for j in rows:
                status = getattr(j, "status", None) or (
                    j.get("status") if isinstance(j, dict) else None
                )
                if status in ("queued", "running", "planning", "planning_queued"):
                    active += 1
                if status == "queued":
                    queued += 1
            counts["jobs_active"] = active
            counts["jobs_queued"] = queued
        return counts

    def _backup(self) -> dict[str, Any]:
        backup = self._resolve("backup")
        if backup is None or not hasattr(backup, "list_backups"):
            return {"last": None, "count": 0}
        dumps = backup.list_backups()
        return {
            "last": dumps[0].name if dumps else None,
            "count": len(dumps),
        }

    def _storage(self) -> dict[str, Any]:
        storage = self._resolve("storage")
        if storage is None:
            return {}
        health = storage.health_check()
        return {"detail": health.detail, **(health.data or {})}

    def _capabilities(self) -> list[dict[str, Any]]:
        registry = getattr(self._app, "capabilities", None)
        if registry is None or not hasattr(registry, "describe"):
            return []
        out: list[dict[str, Any]] = []
        for name, meta in registry.describe().items():
            out.append(
                {
                    "name": name,
                    "kind": meta.get("kind"),
                    "version": meta.get("version"),
                    "enabled": meta.get("enabled", True),
                }
            )
        return out

    def _recovery(self) -> dict[str, Any]:
        rec = self._resolve("recovery")
        if rec is None or not hasattr(rec, "last_report"):
            return {}
        report = rec.last_report()
        if not report:
            return {"status": None}
        return {
            "status": report.get("status"),
            "ok": report.get("ok"),
            "run_id": report.get("run_id"),
            "steps": [
                {"name": s.get("name"), "ok": s.get("ok"), "detail": s.get("detail")}
                for s in report.get("steps", [])
            ],
        }

    def _last_checkpoint(self) -> dict[str, Any] | None:
        cp = self._resolve("checkpoints")
        if cp is None or not hasattr(cp, "most_recent"):
            return None
        row = cp.most_recent()
        if not row:
            return None
        updated = row.get("updated_at")
        return {
            "owner_type": row.get("owner_type"),
            "owner_id": row.get("owner_id"),
            "label": row.get("label"),
            "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
        }

    def _sse_subscribers(self) -> int:
        notifier = self._resolve("notifier")
        if notifier is not None and hasattr(notifier, "broker"):
            return int(notifier.broker.subscriber_count())
        return 0

    # --- helpers --------------------------------------------------------

    def _now(self) -> str | None:
        if self._clock is not None:
            return self._clock.iso()
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def _resolve(self, key: str):
        container = getattr(self._app, "container", None)
        if container is None:
            return None
        try:
            return container.resolve(key)
        except Exception:  # noqa: BLE001 - a missing/unregistered service is not fatal
            return None

    def _guard(self, fn: Callable[[], T], default: T) -> T:
        try:
            return fn()
        except Exception:  # noqa: BLE001 - one broken section must not break the dashboard
            self._logger.exception("dashboard section %s failed", getattr(fn, "__name__", "?"))
            return default
