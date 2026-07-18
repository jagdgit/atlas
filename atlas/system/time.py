"""Clock / Time service (Phase 0 · ATLAS_OS_ROADMAP §5.7, principle P1).

One trustworthy source of time for the whole system: **UTC internally**, local
timezone only for display, a **monotonic** clock for durations, and a *best-effort*
NTP drift monitor (R1/Q9 — never blocks startup, never fails the system).

Why this exists: today timestamps are minted ad hoc via ``datetime.now(timezone.utc)``
and SQL ``now()`` — two unreconciled clocks. Every durable object (findings,
experiences, benchmarks, schedules, journals) depends on good time, so this lands
first and later subsystems mint time through it.

Design notes:
- ``now_utc()`` returns a timezone-aware UTC ``datetime`` — the canonical wall clock.
- ``monotonic()`` is for measuring *durations* only (immune to clock steps/NTP).
- Drift is measured with a tiny SNTP (RFC 4330) query on a **daemon thread**; the
  initial measurement happens on that thread, so ``start()`` never blocks on the
  network. All network errors are swallowed and surfaced as a *degraded* (not failed)
  health status.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from atlas.services.base import HealthStatus

# Seconds between the NTP epoch (1900-01-01) and the Unix epoch (1970-01-01).
_NTP_UNIX_DELTA = 2_208_988_800


@dataclass(frozen=True, slots=True)
class NtpStatus:
    """Snapshot of the last drift measurement (or the reason there isn't one)."""

    enabled: bool
    synced: bool
    offset_seconds: float | None  # server_time - local_time (positive => local is behind)
    server: str | None
    checked_at: datetime | None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "synced": self.synced,
            "offset_seconds": self.offset_seconds,
            "server": self.server,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "error": self.error,
        }


class ClockService:
    """The kernel's single time source. Registered as the ``clock`` capability."""

    name = "clock"

    def __init__(
        self,
        *,
        timezone_name: str = "UTC",
        ntp_enabled: bool = True,
        ntp_servers: list[str] | None = None,
        ntp_timeout: float = 2.0,
        check_interval: int = 3600,
        drift_warn_seconds: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._tz_name = timezone_name or "UTC"
        self._ntp_enabled = ntp_enabled
        self._ntp_servers = list(ntp_servers or ["pool.ntp.org", "time.google.com"])
        self._ntp_timeout = float(ntp_timeout)
        self._check_interval = max(0, int(check_interval))
        self._drift_warn = float(drift_warn_seconds)
        self._logger = logger or logging.getLogger("atlas.system.clock")

        self._local_tz = self._resolve_tz(self._tz_name)
        self._lock = threading.Lock()
        self._status = NtpStatus(
            enabled=ntp_enabled,
            synced=False,
            offset_seconds=None,
            server=None,
            checked_at=None,
            error=None if ntp_enabled else "ntp disabled",
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ----- canonical time -------------------------------------------------

    def now_utc(self) -> datetime:
        """Timezone-aware UTC now — the canonical wall clock for durable records."""
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        """Monotonic seconds for measuring durations (immune to clock steps)."""
        return time.monotonic()

    def to_local(self, dt: datetime) -> datetime:
        """Convert a datetime to the configured display timezone.

        Naive datetimes are assumed to be UTC (that is Atlas's internal convention).
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self._local_tz)

    def iso(self, dt: datetime | None = None) -> str:
        """ISO-8601 string for ``dt`` (defaults to UTC now)."""
        return (dt or self.now_utc()).isoformat()

    @property
    def timezone_name(self) -> str:
        return self._tz_name

    # ----- drift / NTP ----------------------------------------------------

    def drift_seconds(self) -> float | None:
        """Last measured offset (server - local), or ``None`` if unknown."""
        with self._lock:
            return self._status.offset_seconds

    def ntp_status(self) -> NtpStatus:
        with self._lock:
            return self._status

    def check_drift(self) -> NtpStatus:
        """Measure drift now (synchronous). Safe to call; never raises."""
        if not self._ntp_enabled:
            status = NtpStatus(
                enabled=False,
                synced=False,
                offset_seconds=None,
                server=None,
                checked_at=self.now_utc(),
                error="ntp disabled",
            )
            with self._lock:
                self._status = status
            return status

        last_error = "no ntp servers configured"
        for server in self._ntp_servers:
            offset = self._query_offset(server)
            if offset is not None:
                status = NtpStatus(
                    enabled=True,
                    synced=True,
                    offset_seconds=offset,
                    server=server,
                    checked_at=self.now_utc(),
                    error=None,
                )
                with self._lock:
                    self._status = status
                if abs(offset) > self._drift_warn:
                    self._logger.warning(
                        "clock drift %.3fs exceeds %.3fs (ntp=%s)",
                        offset, self._drift_warn, server,
                    )
                return status
            last_error = f"unreachable: {server}"

        status = NtpStatus(
            enabled=True,
            synced=False,
            offset_seconds=None,
            server=None,
            checked_at=self.now_utc(),
            error=last_error,
        )
        with self._lock:
            self._status = status
        self._logger.info("ntp drift check failed (%s); running on local clock", last_error)
        return status

    def _query_offset(self, server: str) -> float | None:
        """Minimal SNTP client. Returns offset (server - local) seconds, or None."""
        packet = b"\x1b" + 47 * b"\0"  # LI=0, VN=3, Mode=3 (client)
        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self._ntp_timeout)
            t1 = time.time()
            sock.sendto(packet, (server, 123))
            data, _ = sock.recvfrom(48)
            t4 = time.time()
        except (OSError, socket.timeout):  # noqa: UP041 - explicit for clarity
            return None
        finally:
            if sock is not None:
                sock.close()
        if len(data) < 48:
            return None
        secs, frac = struct.unpack("!II", data[40:48])  # transmit timestamp
        if secs == 0:
            return None
        server_time = (secs - _NTP_UNIX_DELTA) + frac / 2**32
        return server_time - (t1 + t4) / 2.0

    # ----- lifecycle ------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        if not self._ntp_enabled or self._check_interval <= 0:
            return
        self._thread = threading.Thread(
            target=self._loop, name="atlas-clock", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        # First measurement happens here (not in start()) so startup never blocks.
        self.check_drift()
        while not self._stop.wait(self._check_interval):
            self.check_drift()

    def health_check(self) -> HealthStatus:
        status = self.ntp_status()
        if not status.enabled:
            return HealthStatus.ok("clock ok (ntp monitor disabled)", tz=self._tz_name)
        if not status.synced:
            return HealthStatus.degraded_status(
                "clock ok; ntp unreachable (using local clock)",
                tz=self._tz_name,
                ntp_error=status.error,
            )
        offset = status.offset_seconds or 0.0
        if abs(offset) > self._drift_warn:
            return HealthStatus.degraded_status(
                f"clock drift {offset:.3f}s exceeds {self._drift_warn:.3f}s",
                tz=self._tz_name,
                offset_seconds=offset,
                server=status.server,
            )
        return HealthStatus.ok(
            "clock synced",
            tz=self._tz_name,
            offset_seconds=offset,
            server=status.server,
        )

    # ----- helpers --------------------------------------------------------

    def _resolve_tz(self, name: str) -> tzinfo:
        if name.upper() == "UTC":
            return timezone.utc
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            self._logger.warning("unknown timezone %r; falling back to UTC", name)
            return timezone.utc
