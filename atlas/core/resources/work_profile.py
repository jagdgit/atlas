"""Per-work Resource Profiles + service classes (IR-RO3).

Distinct from *machine* profiles (``conservative`` / ``balanced`` / ``maximum`` in
``profiles.py``). This module describes **what a mission/worker needs** and **how
urgently it must run** — inputs for Admission, Mission Queue, and the Resource Scheduler.

Service classes (OS-style):

    REALTIME → INTERACTIVE → NORMAL → BATCH

Future room: ``REALTIME_CRITICAL`` / ``REALTIME_STANDARD`` — not used in v1.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SERVICE_REALTIME = "REALTIME"
SERVICE_INTERACTIVE = "INTERACTIVE"
SERVICE_NORMAL = "NORMAL"
SERVICE_BATCH = "BATCH"

# Reserved for later (do not assign on builtins yet).
SERVICE_REALTIME_CRITICAL = "REALTIME_CRITICAL"
SERVICE_REALTIME_STANDARD = "REALTIME_STANDARD"

SERVICE_CLASSES = frozenset(
    {
        SERVICE_REALTIME,
        SERVICE_INTERACTIVE,
        SERVICE_NORMAL,
        SERVICE_BATCH,
        SERVICE_REALTIME_CRITICAL,
        SERVICE_REALTIME_STANDARD,
    }
)

SERVICE_CLASS_ORDER = (
    SERVICE_REALTIME_CRITICAL,
    SERVICE_REALTIME,
    SERVICE_REALTIME_STANDARD,
    SERVICE_INTERACTIVE,
    SERVICE_NORMAL,
    SERVICE_BATCH,
)

# Deadline policy names (scheduler consumes later in IR-RO5).
DEADLINE_NONE = "none"
DEADLINE_SIGNAL_TTL = "signal_ttl"  # Market: miss → simulation wrong
DEADLINE_SESSION = "session_close"
DEADLINE_SOFT = "soft"

CHECKPOINT_PER_FILE = "per_file"
CHECKPOINT_PER_TICK = "per_tick"
CHECKPOINT_NONE = "none"


@dataclass(frozen=True, slots=True)
class WorkResourceProfile:
    """Resource + scheduling declaration for a mission template / work item."""

    service_class: str = SERVICE_NORMAL
    latency_tolerance_seconds: float | None = None
    deadline_policy: str = DEADLINE_NONE
    criticality: str = "normal"
    scheduling_policy: str = "background"
    cpu: str = "low"  # low | medium | high
    ram_mb: int = 512
    disk_io: str = "low"  # low | medium | high
    storage_growth: str = "low"  # low | medium | high
    network: str = "low"
    checkpointability: str = CHECKPOINT_PER_TICK
    expected_tick_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def budget_defaults(self) -> dict[str, Any]:
        return {
            "max_concurrent_tasks": 1,
            "ram_mb": max(64, int(self.ram_mb or 512)),
        }

    def metadata_fields(self) -> dict[str, Any]:
        """Fields copied onto mission/worker metadata for Ops + scheduler."""
        return {
            "service_class": self.service_class,
            "latency_tolerance_seconds": self.latency_tolerance_seconds,
            "deadline_policy": self.deadline_policy,
            "resource_profile": {
                "cpu": self.cpu,
                "ram_mb": self.ram_mb,
                "disk_io": self.disk_io,
                "storage_growth": self.storage_growth,
                "network": self.network,
                "checkpointability": self.checkpointability,
                "expected_tick_ms": self.expected_tick_ms,
            },
        }


def normalize_service_class(value: str | None) -> str:
    key = (value or SERVICE_NORMAL).strip().upper()
    if key in SERVICE_CLASSES:
        return key
    aliases = {
        "REAL_TIME": SERVICE_REALTIME,
        "RT": SERVICE_REALTIME,
        "BACKGROUND": SERVICE_BATCH,
        "IDLE": SERVICE_BATCH,
    }
    return aliases.get(key, SERVICE_NORMAL)


def service_class_rank(value: str | None) -> int:
    """Lower rank = higher scheduling preference."""
    key = normalize_service_class(value)
    try:
        return SERVICE_CLASS_ORDER.index(key)
    except ValueError:
        return SERVICE_CLASS_ORDER.index(SERVICE_NORMAL)


def profile_from_dict(data: dict[str, Any] | None) -> WorkResourceProfile:
    if not data:
        return WorkResourceProfile()
    return WorkResourceProfile(
        service_class=normalize_service_class(data.get("service_class")),
        latency_tolerance_seconds=data.get("latency_tolerance_seconds"),
        deadline_policy=str(data.get("deadline_policy") or DEADLINE_NONE),
        criticality=str(data.get("criticality") or "normal"),
        scheduling_policy=str(data.get("scheduling_policy") or "background"),
        cpu=str(data.get("cpu") or "low"),
        ram_mb=int(data.get("ram_mb") or 512),
        disk_io=str(data.get("disk_io") or "low"),
        storage_growth=str(data.get("storage_growth") or "low"),
        network=str(data.get("network") or "low"),
        checkpointability=str(data.get("checkpointability") or CHECKPOINT_PER_TICK),
        expected_tick_ms=(
            int(data["expected_tick_ms"])
            if data.get("expected_tick_ms") is not None
            else None
        ),
    )
