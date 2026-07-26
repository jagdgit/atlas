"""Power / deeper thermals posture (IR-RO9).

Honest until a real UPS/NUT (or battery) source is present. Never pretends
Atlas is protected by power monitoring when it is not.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PowerSnapshot:
    monitored: bool
    source: str | None = None  # nut | sysfs_power_supply | none
    present: bool = False
    on_battery: bool | None = None
    charge_percent: float | None = None
    status_text: str | None = None
    note: str = "power/battery not monitored"

    def as_dict(self) -> dict[str, Any]:
        return {
            "monitored": self.monitored,
            "source": self.source,
            "present": self.present,
            "on_battery": self.on_battery,
            "charge_percent": self.charge_percent,
            "status_text": self.status_text,
            "note": self.note,
            "version": "ro9.1",
        }


@dataclass(frozen=True)
class ThermalZone:
    name: str
    celsius: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "celsius": self.celsius}


def read_thermal_zones(root: Path | None = None) -> list[ThermalZone]:
    base = root or Path("/sys/class/thermal")
    if not base.is_dir():
        return []
    out: list[ThermalZone] = []
    try:
        for zone in sorted(base.glob("thermal_zone*")):
            try:
                milli = (zone / "temp").read_text().strip()
                if not milli.lstrip("-").isdigit():
                    continue
                celsius = int(milli) / 1000.0
                type_path = zone / "type"
                name = type_path.read_text().strip() if type_path.is_file() else zone.name
                out.append(ThermalZone(name=name or zone.name, celsius=round(celsius, 1)))
            except OSError:
                continue
    except OSError:
        return []
    return out


def probe_power(*, logger: logging.Logger | None = None) -> PowerSnapshot:
    """Best-effort UPS/battery probe. Fail closed to *not monitored*."""
    log = logger or logging.getLogger("atlas.resources.power")
    # Optional NUT: ATLAS_RESOURCES_UPS_NAME or default "ups"
    ups_name = (os.environ.get("ATLAS_RESOURCES_UPS_NAME") or "").strip() or "ups"
    upsc = shutil.which("upsc")
    if upsc:
        try:
            proc = subprocess.run(  # noqa: S603 - fixed binary from PATH
                [upsc, ups_name],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                fields = _parse_upsc(proc.stdout)
                status = (fields.get("ups.status") or "").upper()
                on_battery = "OB" in status.split() if status else None
                charge = fields.get("battery.charge")
                charge_f = float(charge) if charge is not None else None
                return PowerSnapshot(
                    monitored=True,
                    source="nut",
                    present=True,
                    on_battery=on_battery,
                    charge_percent=charge_f,
                    status_text=fields.get("ups.status"),
                    note=f"NUT upsc {ups_name}",
                )
        except Exception as exc:  # noqa: BLE001
            log.debug("upsc probe failed: %s", exc)

    # Linux power_supply (laptop battery) — informational only.
    ps = Path("/sys/class/power_supply")
    if ps.is_dir():
        try:
            for entry in sorted(ps.iterdir()):
                try:
                    typ = (entry / "type").read_text().strip().lower()
                except OSError:
                    continue
                if typ != "battery":
                    continue
                status = None
                try:
                    status = (entry / "status").read_text().strip()
                except OSError:
                    pass
                capacity = None
                try:
                    raw = (entry / "capacity").read_text().strip()
                    if raw.isdigit():
                        capacity = float(raw)
                except OSError:
                    pass
                on_ac = None
                if status:
                    low = status.lower()
                    if "discharg" in low:
                        on_ac = False
                    elif "charg" in low or low == "full":
                        on_ac = True
                return PowerSnapshot(
                    monitored=True,
                    source="sysfs_power_supply",
                    present=True,
                    on_battery=(False if on_ac else True) if on_ac is not None else None,
                    charge_percent=capacity,
                    status_text=status,
                    note=f"sysfs battery {entry.name}",
                )
        except OSError as exc:
            log.debug("power_supply probe failed: %s", exc)

    return PowerSnapshot(
        monitored=False,
        source=None,
        present=False,
        note="power/battery not monitored (no NUT upsc / sysfs battery)",
    )


def _parse_upsc(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip()
    return out


def power_ops_card(snap: PowerSnapshot | None = None) -> dict[str, Any]:
    snap = snap or probe_power()
    return snap.as_dict()
