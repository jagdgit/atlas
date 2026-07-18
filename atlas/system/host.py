"""Host metrics for the Operations Dashboard (Phase 0 · ATLAS_OS_ROADMAP §5.11, A4).

Stdlib-only, best-effort by design (A4): **CPU / RAM / disk / internet** in v1, plus
**temperature / UPS** when a sensor/agent is present (otherwise reported as
``present: false`` — "not present", never an error). Everything is wrapped so a metric
that can't be read degrades to ``None`` rather than breaking the dashboard.

Linux is the primary target (reads ``/proc``/``/sys``); on other platforms the metrics
that rely on those paths return ``None`` cleanly.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import time
from pathlib import Path
from typing import Any, Callable


class HostMetrics:
    def __init__(
        self,
        *,
        disk_path: Path | str = "/",
        internet_host: str = "1.1.1.1",
        internet_port: int = 53,
        internet_timeout: float = 1.0,
        internet_cache_seconds: float = 30.0,
        cpu_sample_seconds: float = 0.1,
        check_internet: Callable[[], bool] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._disk_path = str(disk_path)
        self._inet_host = internet_host
        self._inet_port = int(internet_port)
        self._inet_timeout = float(internet_timeout)
        self._inet_cache = float(internet_cache_seconds)
        self._cpu_sample = float(cpu_sample_seconds)
        self._check_internet = check_internet or self._default_internet_check
        self._logger = logger or logging.getLogger("atlas.system.host")
        self._inet_last: tuple[float, bool] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "cpu": self._safe(self.cpu),
            "memory": self._safe(self.memory),
            "disk": self._safe(self.disk),
            "load": self._safe(self.load_average),
            "internet": self._safe(self.internet),
            "temperature": self._safe(self.temperature),
            "ups": self._safe(self.ups),
        }

    # --- CPU ------------------------------------------------------------

    def cpu(self) -> dict[str, Any]:
        """CPU utilisation percent, sampled over a short interval (Linux /proc/stat)."""
        first = self._read_cpu_times()
        if first is None:
            return {"percent": None, "count": os.cpu_count()}
        time.sleep(self._cpu_sample)
        second = self._read_cpu_times()
        if second is None:
            return {"percent": None, "count": os.cpu_count()}
        idle_delta = second[0] - first[0]
        total_delta = second[1] - first[1]
        percent = None
        if total_delta > 0:
            percent = round(100.0 * (1.0 - idle_delta / total_delta), 1)
        return {"percent": percent, "count": os.cpu_count()}

    @staticmethod
    def _read_cpu_times() -> tuple[float, float] | None:
        try:
            with open("/proc/stat", "r", encoding="ascii") as fh:
                line = fh.readline()
        except OSError:
            return None
        if not line.startswith("cpu "):
            return None
        parts = [float(x) for x in line.split()[1:]]
        if len(parts) < 4:
            return None
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)  # idle + iowait
        total = sum(parts)
        return idle, total

    def load_average(self) -> dict[str, Any]:
        try:
            one, five, fifteen = os.getloadavg()
        except (OSError, AttributeError):
            return {"1m": None, "5m": None, "15m": None}
        return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}

    # --- memory ---------------------------------------------------------

    def memory(self) -> dict[str, Any]:
        """RAM usage from /proc/meminfo (Linux)."""
        info: dict[str, int] = {}
        try:
            with open("/proc/meminfo", "r", encoding="ascii") as fh:
                for line in fh:
                    key, _, rest = line.partition(":")
                    kb = rest.strip().split(" ")[0]
                    if kb.isdigit():
                        info[key] = int(kb) * 1024  # kB → bytes
        except OSError:
            return {"total": None, "available": None, "used": None, "percent": None}
        total = info.get("MemTotal")
        available = info.get("MemAvailable")
        if not total:
            return {"total": None, "available": None, "used": None, "percent": None}
        used = total - (available or 0)
        percent = round(100.0 * used / total, 1) if total else None
        return {"total": total, "available": available, "used": used, "percent": percent}

    # --- disk -----------------------------------------------------------

    def disk(self) -> dict[str, Any]:
        try:
            usage = shutil.disk_usage(self._disk_path)
        except OSError:
            return {"total": None, "used": None, "free": None, "percent": None}
        percent = round(100.0 * usage.used / usage.total, 1) if usage.total else None
        return {
            "path": self._disk_path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": percent,
        }

    # --- internet -------------------------------------------------------

    def internet(self) -> dict[str, Any]:
        """Best-effort connectivity check (cached), so the dashboard stays snappy."""
        now = time.monotonic()
        if self._inet_last is not None and (now - self._inet_last[0]) < self._inet_cache:
            reachable = self._inet_last[1]
        else:
            reachable = bool(self._check_internet())
            self._inet_last = (now, reachable)
        return {"reachable": reachable}

    def _default_internet_check(self) -> bool:
        try:
            with socket.create_connection(
                (self._inet_host, self._inet_port), timeout=self._inet_timeout
            ):
                return True
        except OSError:
            return False

    # --- temperature (best-effort) -------------------------------------

    def temperature(self) -> dict[str, Any]:
        """Highest thermal-zone reading (°C), or ``present: false`` when no sensor."""
        readings: list[float] = []
        try:
            zones = sorted(Path("/sys/class/thermal").glob("thermal_zone*"))
        except OSError:
            zones = []
        for zone in zones:
            try:
                milli = (zone / "temp").read_text().strip()
                if milli.lstrip("-").isdigit():
                    readings.append(int(milli) / 1000.0)
            except OSError:
                continue
        if not readings:
            return {"present": False, "celsius": None}
        return {"present": True, "celsius": round(max(readings), 1)}

    # --- UPS (best-effort) ---------------------------------------------

    def ups(self) -> dict[str, Any]:
        """UPS status. No standard sysfs source without NUT/apcupsd → not present (A4)."""
        return {"present": False}

    # --- helpers --------------------------------------------------------

    def _safe(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn()
        except Exception:  # noqa: BLE001 - one bad metric must not break the dashboard
            self._logger.exception("host metric %s failed", getattr(fn, "__name__", "?"))
            return {}
