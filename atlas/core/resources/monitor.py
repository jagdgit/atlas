"""Thin system monitor for Stage 3.2c (CPU/RAM; thermal when OS exposes it).

Honest about what is and is not monitored — never pretends sensors exist.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SystemSnapshot:
    """Best-effort machine snapshot. Missing sensors are explicit, not invented."""

    load_1m: float | None = None
    cpu_count: int | None = None
    # Approximate load pressure 0..1+ (load_1m / cpu_count); None if unknown.
    load_pressure: float | None = None
    mem_total_kb: int | None = None
    mem_available_kb: int | None = None
    # Used fraction 0..1; None if unknown.
    ram_used_fraction: float | None = None
    # Hottest zone in Celsius when /sys thermal is readable.
    thermal_c: float | None = None
    thermal_monitored: bool = False
    power_monitored: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "load_1m": self.load_1m,
            "cpu_count": self.cpu_count,
            "load_pressure": (
                round(self.load_pressure, 3) if self.load_pressure is not None else None
            ),
            "ram_used_fraction": (
                round(self.ram_used_fraction, 3)
                if self.ram_used_fraction is not None
                else None
            ),
            "thermal_c": self.thermal_c,
            "thermal_monitored": self.thermal_monitored,
            "power_monitored": self.power_monitored,
            "notes": list(self.notes),
        }


def read_snapshot(logger: logging.Logger | None = None) -> SystemSnapshot:
    """Collect a snapshot using stdlib /proc and /sys only (no new deps)."""
    log = logger or logging.getLogger("atlas.resources.monitor")
    snap = SystemSnapshot()

    try:
        load1, _, _ = os.getloadavg()
        snap.load_1m = float(load1)
    except (OSError, AttributeError):
        snap.notes.append("loadavg not available")

    try:
        snap.cpu_count = os.cpu_count() or 1
    except Exception:  # noqa: BLE001
        snap.cpu_count = 1

    if snap.load_1m is not None and snap.cpu_count:
        snap.load_pressure = snap.load_1m / max(1, snap.cpu_count)

    mem = _read_meminfo()
    if mem:
        snap.mem_total_kb = mem.get("MemTotal")
        snap.mem_available_kb = mem.get("MemAvailable")
        if snap.mem_total_kb and snap.mem_available_kb is not None:
            used = max(0, snap.mem_total_kb - snap.mem_available_kb)
            snap.ram_used_fraction = used / snap.mem_total_kb
    else:
        snap.notes.append("meminfo not available")

    thermal = _read_thermal_c()
    if thermal is not None:
        snap.thermal_c = thermal
        snap.thermal_monitored = True
    else:
        snap.notes.append("thermal sensors not monitored")

    # Power/battery hard stops deepen in Stage 4; be honest now.
    snap.power_monitored = False
    snap.notes.append("power/battery not monitored")

    log.debug("resource snapshot: %s", snap.as_dict())
    return snap


def _read_meminfo() -> dict[str, int]:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return {}
    out: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            parts = rest.strip().split()
            if parts and parts[0].isdigit():
                out[key] = int(parts[0])
    except OSError:
        return {}
    return out


def _read_thermal_c() -> float | None:
    root = Path("/sys/class/thermal")
    if not root.is_dir():
        return None
    temps: list[float] = []
    try:
        for zone in sorted(root.glob("thermal_zone*")):
            tfile = zone / "temp"
            if not tfile.is_file():
                continue
            raw = tfile.read_text(encoding="utf-8", errors="replace").strip()
            if not raw.isdigit() and not (raw.lstrip("-").isdigit()):
                continue
            # Kernel reports millidegrees Celsius.
            val = int(raw) / 1000.0
            if -50.0 < val < 150.0:
                temps.append(val)
    except OSError:
        return None
    return max(temps) if temps else None
