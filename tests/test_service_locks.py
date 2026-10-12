"""OI-OPS-1INST L3 — advisory lock manager (I7–I9, shadow/enforce)."""

from __future__ import annotations

from atlas.ops.service_locks import (
    MODE_ENFORCE,
    MODE_SHADOW,
    SERVICE_KEYS,
    ServiceLockManager,
    advisory_key,
    require_service,
    set_service_lock_manager,
)


class _FakeCursor:
    def __init__(self, held: bool) -> None:
        self._held = held
        self.closed = False

    def execute(self, sql, params=None):  # noqa: ANN001
        self._sql = sql

    def fetchone(self):
        if "pg_try_advisory_lock" in getattr(self, "_sql", ""):
            return (self._held,)
        return (1,)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, held: bool = True) -> None:
        self.held = held
        self.closed = False

    def cursor(self):
        return _FakeCursor(self.held)

    def close(self):
        self.closed = True


def test_advisory_keys_stable_and_distinct() -> None:
    keys = [advisory_key(s) for s in SERVICE_KEYS]
    assert len(keys) == len(set(keys))
    assert advisory_key(SERVICE_KEYS[0]) == keys[0]


def test_i7_second_instance_same_service_passive_in_enforce() -> None:
    connections = [_FakeConn(held=True), _FakeConn(held=False)]

    def connect():
        return connections.pop(0)

    a = ServiceLockManager(conninfo="x", mode=MODE_ENFORCE, _connect=connect)
    b = ServiceLockManager(conninfo="x", mode=MODE_ENFORCE, _connect=connect)
    la = a.acquire("atlas.svc.scheduler")
    lb = b.acquire("atlas.svc.scheduler")
    assert la.held and not la.passive
    assert not lb.held and lb.passive
    assert a.owns("atlas.svc.scheduler")
    assert not b.owns("atlas.svc.scheduler")


def test_i7_different_services_do_not_block() -> None:
    def connect():
        return _FakeConn(held=True)

    mgr = ServiceLockManager(conninfo="x", mode=MODE_ENFORCE, _connect=connect)
    assert mgr.acquire("atlas.svc.scheduler").held
    assert mgr.acquire("atlas.svc.schedules").held


def test_shadow_allows_side_effects_when_not_held() -> None:
    def connect():
        return _FakeConn(held=False)

    mgr = ServiceLockManager(conninfo="x", mode=MODE_SHADOW, _connect=connect)
    lock = mgr.acquire("atlas.svc.investor_mailer")
    assert not lock.held
    assert not lock.passive
    assert mgr.owns("atlas.svc.investor_mailer")


def test_i9_require_rejects_when_enforce_passive() -> None:
    def connect():
        return _FakeConn(held=False)

    mgr = ServiceLockManager(conninfo="x", mode=MODE_ENFORCE, _connect=connect)
    set_service_lock_manager(mgr)
    try:
        mgr.acquire("atlas.svc.investor_mailer")
        assert require_service("atlas.svc.investor_mailer") is False
    finally:
        set_service_lock_manager(None)
