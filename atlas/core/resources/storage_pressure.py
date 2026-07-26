"""Storage pressure (IR-RO6) — mirror RAM pressure for durable disk growth.

Levels:
  ok    — normal
  warn  — operator should notice; prefer low-growth work
  high  — stop new high storage-growth admissions (embeddings / bulk extracts)

Consumed by ReservationManager before acquire, and exposed on Ops / Host Guard.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class StoragePressureStatus:
    level: str  # ok | warn | high
    percent: float | None
    free_bytes: int | None
    total_bytes: int | None
    path: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "percent": self.percent,
            "free_bytes": self.free_bytes,
            "total_bytes": self.total_bytes,
            "path": self.path,
            "reason": self.reason,
        }


class StoragePressureService:
    """Disk watermark monitor for Resource OS (IR-RO6)."""

    name = "storage_pressure"
    VERSION = "ro6.1"

    def __init__(
        self,
        *,
        disk_path: str = "/",
        warn_percent: float = 80.0,
        high_percent: float = 92.0,
        host_snapshot: Callable[[], dict[str, Any]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._path = disk_path
        self._warn = float(warn_percent)
        self._high = float(high_percent)
        self._host_snapshot = host_snapshot
        self._logger = logger or logging.getLogger("atlas.resources.storage")
        self._lock = threading.Lock()
        self._last: StoragePressureStatus | None = None

    def status(self) -> StoragePressureStatus:
        percent = None
        free_b = None
        total_b = None
        if self._host_snapshot is not None:
            try:
                snap = self._host_snapshot() or {}
                disk = snap.get("disk") or {}
                percent = disk.get("percent")
                free_b = disk.get("free")
                total_b = disk.get("total")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("host disk snapshot failed: %s", exc)
        if percent is None:
            try:
                import shutil

                usage = shutil.disk_usage(self._path)
                total_b = int(usage.total)
                free_b = int(usage.free)
                used = total_b - free_b
                percent = round(100.0 * used / total_b, 1) if total_b else None
            except OSError as exc:
                st = StoragePressureStatus(
                    level="ok",
                    percent=None,
                    free_bytes=None,
                    total_bytes=None,
                    path=self._path,
                    reason=f"unreadable: {exc}",
                )
                with self._lock:
                    self._last = st
                return st

        level = "ok"
        reason = "ok"
        if percent is not None:
            if percent >= self._high:
                level = "high"
                reason = f"disk {percent}% ≥ high watermark {self._high}%"
            elif percent >= self._warn:
                level = "warn"
                reason = f"disk {percent}% ≥ warn watermark {self._warn}%"

        st = StoragePressureStatus(
            level=level,
            percent=percent,
            free_bytes=free_b,
            total_bytes=total_b,
            path=self._path,
            reason=reason,
        )
        with self._lock:
            self._last = st
        return st

    def allows_growth(self, *, level: str = "low", growth_mb: float = 0.0) -> tuple[bool, str]:
        """Refuse high-growth work under high pressure; medium under high if sizable."""
        st = self.status()
        growth_level = (level or "low").strip().lower()
        if st.level == "high":
            if growth_level == "high" or growth_mb >= 64:
                return False, f"storage_pressure_high ({st.reason})"
            if growth_level == "medium" and growth_mb >= 16:
                return False, f"storage_pressure_high_medium_growth ({st.reason})"
        if st.level == "warn" and growth_level == "high" and growth_mb >= 256:
            return False, f"storage_pressure_warn_large_growth ({st.reason})"
        return True, st.reason

    def snapshot(self) -> dict[str, Any]:
        st = self.status()
        return {
            "version": self.VERSION,
            "watermarks": {"warn_percent": self._warn, "high_percent": self._high},
            **st.as_dict(),
            "note": (
                "High watermark stops new high storage-growth work "
                "(embeddings / bulk extracts). Host Guard still protects RAM/CPU."
            ),
        }
