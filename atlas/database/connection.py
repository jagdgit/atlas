"""Database connection management for Atlas.

Wraps a psycopg3 connection pool. Nothing in Atlas creates raw connections;
everything goes through a DatabaseManager instance (and, later, the kernel).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from psycopg import Connection
from psycopg_pool import ConnectionPool

from atlas.config import DatabaseConfig, get_config


class DatabaseManager:
    """Owns the connection pool and exposes safe connection access."""

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self._config = config or get_config().database
        self._pool: ConnectionPool | None = None

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            self._pool = ConnectionPool(
                conninfo=self._config.conninfo,
                min_size=1,
                max_size=self._config.pool_size,
                open=True,
                name="atlas",
            )
        return self._pool

    def connect(self) -> ConnectionPool:
        """Open the pool eagerly and wait until it is usable."""
        pool = self.pool
        pool.wait(timeout=10.0)
        return pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        with self.pool.connection() as conn:
            yield conn

    def health_check(self) -> bool:
        """Return True if a trivial query succeeds."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                row = cur.fetchone()
                return row is not None and row[0] == 1

    def __enter__(self) -> "DatabaseManager":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
