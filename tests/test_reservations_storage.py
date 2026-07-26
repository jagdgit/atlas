"""IR-RO7 reservations + IR-RO6 storage pressure."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.core.resources.reservations import (
    ReservationManager,
    ReservationRequest,
)
from atlas.core.resources.storage_pressure import StoragePressureService


class _FakePressure:
    def __init__(self, *, allow=True, reason="ok"):
        self.allow = allow
        self.reason = reason

    def allows_growth(self, **_kwargs):
        return self.allow, self.reason


def test_acquire_and_release_lease():
    mgr = ReservationManager(ram_budget_mb=2048, storage_pressure=_FakePressure())
    req = ReservationRequest(
        worker_id="w1",
        mission_id="m1",
        ram_mb=256,
        disk_io="high",
        storage_growth="low",
    )
    dec = mgr.acquire(req)
    assert dec.allowed
    assert dec.lease is not None
    assert "w1" in mgr.holding_worker_ids()
    snap = mgr.snapshot()
    assert snap["holding_count"] == 1
    assert snap["used"]["ram_mb"] == 256
    assert mgr.release(worker_id="w1")
    assert mgr.holding_worker_ids() == set()


def test_ram_budget_blocks_second_lease():
    mgr = ReservationManager(ram_budget_mb=500, storage_pressure=_FakePressure())
    assert mgr.acquire(ReservationRequest(worker_id="a", ram_mb=400)).allowed
    dec = mgr.acquire(ReservationRequest(worker_id="b", ram_mb=400))
    assert not dec.allowed
    assert "ram_budget" in dec.reason


def test_storage_pressure_blocks_high_growth():
    mgr = ReservationManager(
        ram_budget_mb=8192,
        storage_pressure=_FakePressure(allow=False, reason="storage_pressure_high"),
    )
    dec = mgr.acquire(
        ReservationRequest(worker_id="w", storage_growth="high", storage_growth_mb=100)
    )
    assert not dec.allowed
    assert "storage_pressure" in dec.reason


def test_expire_stale_lease():
    mgr = ReservationManager(storage_pressure=_FakePressure())
    dec = mgr.acquire(ReservationRequest(worker_id="w", ttl_seconds=0.01))
    assert dec.allowed
    import time

    time.sleep(0.05)
    gone = mgr.expire_stale()
    assert gone
    assert mgr.holding_worker_ids() == set()


def test_from_worker_meta():
    worker = SimpleNamespace(
        id="w9",
        mission_id="m9",
        metadata={
            "service_class": "BATCH",
            "resource_profile": {
                "cpu": "medium",
                "ram_mb": 768,
                "disk_io": "high",
                "storage_growth": "high",
                "network": "low",
            },
        },
    )
    req = ReservationRequest.from_worker_meta(worker)
    assert req.ram_mb == 768
    assert req.disk_io == "high"
    assert req.service_class == "BATCH"


def test_storage_pressure_levels():
    svc = StoragePressureService(
        host_snapshot=lambda: {"disk": {"percent": 95.0, "free": 1, "total": 100}},
        warn_percent=80,
        high_percent=92,
    )
    st = svc.status()
    assert st.level == "high"
    ok, reason = svc.allows_growth(level="high", growth_mb=100)
    assert not ok

    svc2 = StoragePressureService(
        host_snapshot=lambda: {"disk": {"percent": 50.0, "free": 50, "total": 100}},
    )
    assert svc2.status().level == "ok"
    assert svc2.allows_growth(level="high", growth_mb=100)[0]
