"""Resource Reservations / leases (IR-RO7).

Lifecycle: Acquire → Run → (optional Renew) → Release.

Accounts for CPU class, RAM, Network, Disk IO, and Storage Growth separately so the
scheduler can refuse work that would not fit *before* starting a tick. Distinct from
Host Guard (machine safety) and MissionArbiter (tick slots).
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

_LEVEL_WEIGHT = {"low": 1, "medium": 2, "high": 3}


def _level(value: str | None, default: str = "low") -> str:
    key = (value or default).strip().lower()
    return key if key in _LEVEL_WEIGHT else default


@dataclass(frozen=True)
class ReservationRequest:
    worker_id: str
    mission_id: str | None = None
    cpu: str = "low"
    ram_mb: int = 512
    network: str = "low"
    disk_io: str = "low"
    storage_growth: str = "low"  # low|medium|high — durable growth intent
    storage_growth_mb: float = 0.0  # optional estimated MB this tick/run
    ttl_seconds: float = 600.0
    service_class: str | None = None

    @classmethod
    def from_worker_meta(
        cls,
        worker: Any,
        *,
        ttl_seconds: float = 600.0,
    ) -> "ReservationRequest":
        meta = getattr(worker, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        rp = meta.get("resource_profile") if isinstance(meta.get("resource_profile"), dict) else {}
        wid = str(getattr(worker, "id", "") or "")
        mid = getattr(worker, "mission_id", None)
        return cls(
            worker_id=wid,
            mission_id=str(mid) if mid else None,
            cpu=_level(rp.get("cpu") or meta.get("cpu")),
            ram_mb=int(rp.get("ram_mb") or meta.get("ram_mb") or 512),
            network=_level(rp.get("network")),
            disk_io=_level(rp.get("disk_io")),
            storage_growth=_level(rp.get("storage_growth")),
            storage_growth_mb=float(rp.get("storage_growth_mb") or 0.0),
            ttl_seconds=ttl_seconds,
            service_class=meta.get("service_class") or (meta.get("ops") or {}).get("service_class"),
        )


@dataclass
class ResourceLease:
    token: str
    worker_id: str
    mission_id: str | None
    cpu: str
    ram_mb: int
    network: str
    disk_io: str
    storage_growth: str
    storage_growth_mb: float
    service_class: str | None
    acquired_at: float
    expires_at: float
    renewals: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "worker_id": self.worker_id,
            "mission_id": self.mission_id,
            "cpu": self.cpu,
            "ram_mb": self.ram_mb,
            "network": self.network,
            "disk_io": self.disk_io,
            "storage_growth": self.storage_growth,
            "storage_growth_mb": self.storage_growth_mb,
            "service_class": self.service_class,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "renewals": self.renewals,
            "holding": True,
        }


@dataclass
class ReservationDecision:
    allowed: bool
    reason: str
    lease: ResourceLease | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "lease": self.lease.as_dict() if self.lease else None,
        }


@dataclass
class _Budgets:
    ram_mb: int = 4096
    disk_io_units: int = 6  # sum of level weights
    network_units: int = 6
    storage_growth_mb: float = 2048.0


class ReservationManager:
    """Account resources for in-flight / holding leases (IR-RO7)."""

    name = "reservation_manager"
    VERSION = "ro7.1"

    def __init__(
        self,
        *,
        ram_budget_mb: int = 4096,
        disk_io_budget: int = 6,
        network_budget: int = 6,
        storage_growth_budget_mb: float = 2048.0,
        storage_pressure: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._budgets = _Budgets(
            ram_mb=max(512, int(ram_budget_mb)),
            disk_io_units=max(1, int(disk_io_budget)),
            network_units=max(1, int(network_budget)),
            storage_growth_mb=max(64.0, float(storage_growth_budget_mb)),
        )
        self._storage_pressure = storage_pressure
        self._logger = logger or logging.getLogger("atlas.resources.reservations")
        self._lock = threading.RLock()
        self._leases: dict[str, ResourceLease] = {}  # token → lease
        self._by_worker: dict[str, str] = {}  # worker_id → token

    def acquire(self, request: ReservationRequest) -> ReservationDecision:
        self.expire_stale()
        # Storage pressure gate (IR-RO6) — high growth refused when disk is critical.
        if self._storage_pressure is not None:
            try:
                ok, reason = self._storage_pressure.allows_growth(
                    level=request.storage_growth,
                    growth_mb=request.storage_growth_mb,
                )
                if not ok:
                    return ReservationDecision(False, reason)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("storage pressure check failed: %s", exc)

        with self._lock:
            # One active lease per worker.
            existing = self._by_worker.get(request.worker_id)
            if existing and existing in self._leases:
                lease = self._leases[existing]
                lease.expires_at = time.time() + max(0.01, float(request.ttl_seconds))
                lease.renewals += 1
                return ReservationDecision(True, "renewed_existing", lease)

            used_ram = sum(l.ram_mb for l in self._leases.values())
            used_dio = sum(_LEVEL_WEIGHT[_level(l.disk_io)] for l in self._leases.values())
            used_net = sum(_LEVEL_WEIGHT[_level(l.network)] for l in self._leases.values())
            used_growth = sum(float(l.storage_growth_mb or 0) for l in self._leases.values())

            need_dio = _LEVEL_WEIGHT[_level(request.disk_io)]
            need_net = _LEVEL_WEIGHT[_level(request.network)]
            need_ram = max(64, int(request.ram_mb))
            need_growth = max(0.0, float(request.storage_growth_mb or 0.0))
            # High storage_growth without explicit MB still reserves a symbolic budget.
            if need_growth <= 0 and _level(request.storage_growth) == "high":
                need_growth = 64.0
            elif need_growth <= 0 and _level(request.storage_growth) == "medium":
                need_growth = 16.0

            reasons: list[str] = []
            if used_ram + need_ram > self._budgets.ram_mb:
                reasons.append(
                    f"ram_budget {used_ram + need_ram}>{self._budgets.ram_mb}"
                )
            if used_dio + need_dio > self._budgets.disk_io_units:
                reasons.append(
                    f"disk_io_budget {used_dio + need_dio}>{self._budgets.disk_io_units}"
                )
            if used_net + need_net > self._budgets.network_units:
                reasons.append(
                    f"network_budget {used_net + need_net}>{self._budgets.network_units}"
                )
            if used_growth + need_growth > self._budgets.storage_growth_mb:
                reasons.append(
                    f"storage_growth_budget {used_growth + need_growth:.0f}"
                    f">{self._budgets.storage_growth_mb:.0f}"
                )
            if reasons:
                return ReservationDecision(False, "; ".join(reasons))

            now = time.time()
            token = secrets.token_urlsafe(12)
            lease = ResourceLease(
                token=token,
                worker_id=request.worker_id,
                mission_id=request.mission_id,
                cpu=_level(request.cpu),
                ram_mb=need_ram,
                network=_level(request.network),
                disk_io=_level(request.disk_io),
                storage_growth=_level(request.storage_growth),
                storage_growth_mb=need_growth,
                service_class=request.service_class,
                acquired_at=now,
                expires_at=now + max(0.01, float(request.ttl_seconds)),
            )
            self._leases[token] = lease
            self._by_worker[request.worker_id] = token
            return ReservationDecision(True, "acquired", lease)

    def renew(self, token: str, *, ttl_seconds: float = 600.0) -> bool:
        with self._lock:
            lease = self._leases.get(token)
            if lease is None:
                return False
            lease.expires_at = time.time() + max(0.01, float(ttl_seconds))
            lease.renewals += 1
            return True

    def release(self, token: str | None = None, *, worker_id: str | None = None) -> bool:
        with self._lock:
            if token is None and worker_id:
                token = self._by_worker.get(worker_id)
            if not token:
                return False
            lease = self._leases.pop(token, None)
            if lease is None:
                return False
            if self._by_worker.get(lease.worker_id) == token:
                self._by_worker.pop(lease.worker_id, None)
            return True

    def expire_stale(self) -> list[str]:
        """Drop vanished/expired leases (kill -9 / missed release)."""
        now = time.time()
        gone: list[str] = []
        with self._lock:
            for token, lease in list(self._leases.items()):
                if lease.expires_at < now:
                    self._leases.pop(token, None)
                    if self._by_worker.get(lease.worker_id) == token:
                        self._by_worker.pop(lease.worker_id, None)
                    gone.append(token)
                    self._logger.info(
                        "expired vanished lease %s worker=%s", token, lease.worker_id
                    )
        return gone

    def holding_worker_ids(self) -> set[str]:
        self.expire_stale()
        with self._lock:
            return set(self._by_worker.keys())

    def lease_for_worker(self, worker_id: str) -> ResourceLease | None:
        with self._lock:
            token = self._by_worker.get(worker_id)
            return self._leases.get(token) if token else None

    def snapshot(self) -> dict[str, Any]:
        self.expire_stale()
        with self._lock:
            leases = [l.as_dict() for l in self._leases.values()]
            used_ram = sum(l.ram_mb for l in self._leases.values())
            used_dio = sum(_LEVEL_WEIGHT[_level(l.disk_io)] for l in self._leases.values())
            used_net = sum(_LEVEL_WEIGHT[_level(l.network)] for l in self._leases.values())
            used_growth = sum(float(l.storage_growth_mb or 0) for l in self._leases.values())
            return {
                "version": self.VERSION,
                "leases": leases,
                "holding_count": len(leases),
                "holding_worker_ids": list(self._by_worker.keys()),
                "used": {
                    "ram_mb": used_ram,
                    "disk_io_units": used_dio,
                    "network_units": used_net,
                    "storage_growth_mb": round(used_growth, 2),
                },
                "budgets": asdict(self._budgets),
            }
