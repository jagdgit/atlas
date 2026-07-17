"""Tests for the kernel primitives (registry, container) and bootstrap wiring.

These use fakes where possible; a live DB is only needed for the health test,
which skips gracefully if unavailable.
"""

from __future__ import annotations

import pytest

from atlas.kernel import ServiceContainer, ServiceRegistry, build_application
from atlas.services.base import HealthStatus


class FakeService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok()


def test_registry_register_and_get():
    reg = ServiceRegistry()
    svc = FakeService("alpha")
    reg.register(svc)
    assert reg.has("alpha")
    assert reg.get("alpha") is svc
    assert reg.names() == ["alpha"]


def test_registry_rejects_duplicate():
    reg = ServiceRegistry()
    reg.register(FakeService("dup"))
    with pytest.raises(ValueError):
        reg.register(FakeService("dup"))


def test_registry_missing_raises():
    reg = ServiceRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_container_instance_and_factory():
    c = ServiceContainer()
    c.register_instance("x", 123)
    assert c.resolve("x") == 123

    calls = []

    def factory():
        calls.append(1)
        return object()

    c.register_factory("y", factory, singleton=True)
    a = c.resolve("y")
    b = c.resolve("y")
    assert a is b  # singleton cached
    assert len(calls) == 1


def test_build_application_wires_core():
    app = build_application()
    assert app.registry.has("database")
    assert app.container.has("config")
    assert app.container.has("events")
    assert app.container.has("database_manager")
    assert app.container.has("resources")
    assert app.container.has("execution")
    assert app.registry.has("resources")
    assert app.registry.has("execution")


def test_application_health_reports_database():
    app = build_application()
    try:
        app.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not start (DB?): {exc}")
    try:
        report = app.health()
        assert "database" in report
    finally:
        app.stop()
