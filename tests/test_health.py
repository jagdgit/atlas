"""Tests for the health monitor service.

The monitor logic is tested with a fake registry/repo (no DB). One integration
test exercises the real HealthRepository and skips if the DB is unavailable.
"""

from __future__ import annotations

import psycopg
import pytest

from atlas.config import get_config
from atlas.database.connection import DatabaseManager
from atlas.kernel.registry import ServiceRegistry
from atlas.repositories.health_repo import HealthRepository
from atlas.services.base import HealthStatus
from atlas.services.health import HealthMonitor


class FakeService:
    def __init__(self, name: str, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy

    def start(self) -> None:  # pragma: no cover - not used here
        pass

    def stop(self) -> None:  # pragma: no cover
        pass

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok() if self._healthy else HealthStatus.fail("down")


class RecordingRepo:
    def __init__(self) -> None:
        self.records: list[tuple] = []

    def record(self, service, healthy, detail="", data=None) -> None:
        self.records.append((service, healthy, detail))


class CapturingEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple] = []

    def emit(self, event_type, payload=None, source=None) -> int:
        self.emitted.append((event_type, payload, source))
        return 1


def test_check_all_records_each_service():
    reg = ServiceRegistry()
    reg.register(FakeService("alpha"))
    reg.register(FakeService("beta"))
    repo = RecordingRepo()
    monitor = HealthMonitor(reg, repo, interval=999)

    results = monitor.check_all()

    assert set(results) == {"alpha", "beta"}
    recorded = {r[0] for r in repo.records}
    assert recorded == {"alpha", "beta"}


def test_unhealthy_emits_event():
    reg = ServiceRegistry()
    reg.register(FakeService("bad", healthy=False))
    events = CapturingEvents()
    monitor = HealthMonitor(reg, RecordingRepo(), events=events, interval=999)

    monitor.check_all()

    assert any(e[0] == "ServiceUnhealthy" for e in events.emitted)


def test_monitor_skips_itself():
    reg = ServiceRegistry()
    repo = RecordingRepo()
    monitor = HealthMonitor(reg, repo, interval=999)
    reg.register(monitor)  # register the monitor itself

    monitor.check_all()

    assert all(r[0] != "health_monitor" for r in repo.records)


def test_health_repo_integration():
    conninfo = get_config().database.conninfo
    try:
        with psycopg.connect(conninfo, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")

    db = DatabaseManager()
    repo = HealthRepository(db)
    repo.record("test_service", True, "integration ok", {"n": 1})
    latest = repo.latest("test_service")
    assert latest is not None
    assert latest.status == "healthy"
    assert latest.healthy is True
    assert latest.details["detail"] == "integration ok"
    repo.execute("DELETE FROM system.health WHERE service = %s", ("test_service",))
    db.close()
