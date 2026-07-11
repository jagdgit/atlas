"""Base repository.

Repositories are the ONLY layer in Atlas permitted to contain SQL (ADR-0027).
Services, APIs, and agents call repositories; repositories use DatabaseManager.

The base class provides small query helpers so concrete repositories stay
focused on their SQL statements.
"""

from __future__ import annotations

from typing import Any, Sequence

from psycopg.rows import dict_row

from atlas.database.connection import DatabaseManager

Params = Sequence[Any] | dict[str, Any] | None


class BaseRepository:
    def __init__(self, db: DatabaseManager | None = None) -> None:
        self._db = db or DatabaseManager()

    def execute(self, sql: str, params: Params = None) -> int:
        """Run a write statement. Returns affected row count."""
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount

    def fetch_one(self, sql: str, params: Params = None) -> dict[str, Any] | None:
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return cur.fetchone()

    def fetch_all(self, sql: str, params: Params = None) -> list[dict[str, Any]]:
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    def fetch_val(self, sql: str, params: Params = None) -> Any:
        """Return the first column of the first row (or None)."""
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row[0] if row else None
