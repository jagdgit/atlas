"""Database service: adapts DatabaseManager to the Service lifecycle.

Keeps infrastructure (the psycopg pool in DatabaseManager) separate from the
service abstraction the kernel manages.
"""

from __future__ import annotations

from atlas.database.connection import DatabaseManager
from atlas.services.base import HealthStatus


class DatabaseService:
    name = "database"

    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or DatabaseManager()

    def start(self) -> None:
        self.manager.connect()

    def stop(self) -> None:
        self.manager.close()

    def health_check(self) -> HealthStatus:
        try:
            if self.manager.health_check():
                return HealthStatus.ok("database reachable")
            return HealthStatus.fail("SELECT 1 did not return 1")
        except Exception as exc:  # noqa: BLE001
            return HealthStatus.fail(f"database unreachable: {exc}")
