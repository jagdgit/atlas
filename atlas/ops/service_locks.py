"""L3 per-service PostgreSQL advisory locks (OI-OPS-1INST).

Each side-effecting singleton opens a **dedicated** DB connection (not the pool)
and holds ``pg_try_advisory_lock(key)`` for its lifetime. Session locks release
when that connection closes — never check a lease on a different connection.

Modes (env ``ATLAS_SERVICE_LOCK_MODE``):
  * ``shadow`` (default) — log ``would be passive`` on failure; still run.
  * ``enforce`` — service stays passive; side effects must call ``require``.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("atlas.ops.service_locks")

MODE_ENV = "ATLAS_SERVICE_LOCK_MODE"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"

# Final L3 list from OI-DELI0 §9.4.1
SERVICE_KEYS: tuple[str, ...] = (
    "atlas.svc.scheduler",
    "atlas.svc.schedules",
    "atlas.svc.workers",
    "atlas.svc.investor_mailer",
    "atlas.svc.zerodha_token_mail",
    "atlas.svc.recovery",
    "atlas.svc.backup",
)


def lock_mode() -> str:
    raw = (os.environ.get(MODE_ENV) or MODE_SHADOW).strip().lower()
    return MODE_ENFORCE if raw == MODE_ENFORCE else MODE_SHADOW


def advisory_key(service: str) -> int:
    digest = hashlib.sha256(service.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


@dataclass
class ServiceLock:
    service: str
    key: int
    held: bool
    mode: str
    conn: Any = None
    passive: bool = False

    def alive(self) -> bool:
        if not self.held or self.conn is None:
            return False
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception:  # noqa: BLE001
            return False

    def release(self) -> None:
        if self.conn is None:
            return
        try:
            if self.held:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (self.key,))
        except Exception:  # noqa: BLE001
            pass
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
        self.conn = None
        self.held = False


@dataclass
class ServiceLockManager:
    """Process-wide registry of L3 locks."""

    conninfo: str | None = None
    mode: str = field(default_factory=lock_mode)
    logger: logging.Logger = field(default_factory=lambda: _log)
    _locks: dict[str, ServiceLock] = field(default_factory=dict)
    _connect: Any = None  # injectable for tests

    def acquire(self, service: str) -> ServiceLock:
        if service in self._locks and self._locks[service].held:
            return self._locks[service]

        key = advisory_key(service)
        mode = self.mode
        lock = ServiceLock(service=service, key=key, held=False, mode=mode)

        if not self.conninfo and self._connect is None:
            self.logger.warning(
                "service lock %s skipped (no conninfo); treating as held in %s",
                service,
                mode,
            )
            lock.held = True
            self._locks[service] = lock
            return lock

        try:
            if self._connect is not None:
                conn = self._connect()
            else:
                import psycopg

                conn = psycopg.connect(self.conninfo, autocommit=True)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
                row = cur.fetchone()
            ok = bool(row and row[0])
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("service lock %s acquire failed: %s", service, exc)
            ok = False
            conn = None  # type: ignore[assignment]

        if ok and conn is not None:
            lock.conn = conn
            lock.held = True
            lock.passive = False
            self.logger.info("service lock acquired %s key=%s mode=%s", service, key, mode)
        else:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            if mode == MODE_SHADOW:
                self.logger.warning(
                    "service lock %s not acquired — would be passive (shadow)",
                    service,
                )
                lock.held = False
                lock.passive = False  # shadow still runs
            else:
                self.logger.error(
                    "service lock %s not acquired — staying passive (enforce)",
                    service,
                )
                lock.held = False
                lock.passive = True

        self._locks[service] = lock
        return lock

    def get(self, service: str) -> ServiceLock | None:
        return self._locks.get(service)

    def owns(self, service: str) -> bool:
        lock = self._locks.get(service)
        if lock is None:
            return False
        if lock.mode == MODE_SHADOW and not lock.held:
            # Shadow failure still allows side effects; ownership check passes.
            return True
        if lock.passive:
            return False
        if not lock.held:
            return False
        if lock.conn is not None and not lock.alive():
            self.logger.error("service lock %s connection lost", service)
            lock.held = False
            lock.passive = lock.mode == MODE_ENFORCE
            return lock.mode == MODE_SHADOW
        return True

    def require(self, service: str) -> bool:
        """Return True if a side effect may proceed."""
        lock = self._locks.get(service)
        if lock is None:
            # Lazy acquire on first side effect.
            lock = self.acquire(service)
        return self.owns(service)

    def release_all(self) -> None:
        for lock in list(self._locks.values()):
            lock.release()
        self._locks.clear()


_MANAGER: ServiceLockManager | None = None


def get_service_lock_manager() -> ServiceLockManager | None:
    return _MANAGER


def set_service_lock_manager(manager: ServiceLockManager | None) -> None:
    global _MANAGER
    _MANAGER = manager


def require_service(service: str) -> bool:
    mgr = _MANAGER
    if mgr is None:
        return True
    return mgr.require(service)
