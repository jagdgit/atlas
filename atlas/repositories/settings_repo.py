"""Repository for ``system.settings`` (key -> JSONB value)."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository


class SettingsRepository(BaseRepository):
    def get(self, key: str) -> Any | None:
        """Return the JSON value for a key, or None if absent."""
        row = self.fetch_one(
            "SELECT value FROM system.settings WHERE key = %s", (key,)
        )
        return row["value"] if row else None

    def set(self, key: str, value: Any, description: str | None = None) -> None:
        """Insert or update a setting."""
        self.execute(
            """
            INSERT INTO system.settings (key, value, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    description = COALESCE(EXCLUDED.description, system.settings.description),
                    updated_at = now()
            """,
            (key, Jsonb(value), description),
        )

    def all(self) -> dict[str, Any]:
        rows = self.fetch_all("SELECT key, value FROM system.settings ORDER BY key")
        return {row["key"]: row["value"] for row in rows}

    def delete(self, key: str) -> bool:
        return self.execute("DELETE FROM system.settings WHERE key = %s", (key,)) > 0
