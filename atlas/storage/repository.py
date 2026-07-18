"""Repository for the Storage Manager (Phase 0 · ATLAS_OS_ROADMAP §5.8).

The only layer permitted to hold SQL (ADR-0027). Backs ``storage.files`` (versioned,
checksummed file registry) and ``storage.quotas`` (per-scope advisory quotas).
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository


class StorageRepository(BaseRepository):
    def next_version(self, scope: str, name: str) -> int:
        """Next version number for a (scope, name) — 1 for a brand-new file."""
        n = self.fetch_val(
            """
            SELECT COALESCE(MAX(version), 0) + 1
            FROM storage.files
            WHERE scope = %s AND name = %s
            """,
            (scope, name),
        )
        return int(n or 1)

    def insert_file(
        self,
        *,
        scope: str,
        name: str,
        version: int,
        relpath: str,
        size_bytes: int,
        checksum: str,
        tier: str = "hot",
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO storage.files (
                scope, name, version, relpath, size_bytes, checksum,
                tier, content_type, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                scope, name, version, relpath, size_bytes, checksum,
                tier, content_type, Jsonb(metadata or {}),
            ),
        )

    def get_file(
        self, scope: str, name: str, version: int | None = None
    ) -> dict[str, Any] | None:
        if version is not None:
            return self.fetch_one(
                """
                SELECT * FROM storage.files
                WHERE scope = %s AND name = %s AND version = %s
                """,
                (scope, name, version),
            )
        return self.fetch_one(
            """
            SELECT * FROM storage.files
            WHERE scope = %s AND name = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (scope, name),
        )

    def list_files(self, scope: str) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT * FROM storage.files
            WHERE scope = %s
            ORDER BY name, version DESC
            """,
            (scope,),
        )

    def all_files(self) -> list[dict[str, Any]]:
        return self.fetch_all("SELECT * FROM storage.files ORDER BY created_at")

    def scope_size(self, scope: str) -> int:
        """Total bytes stored for a scope (all versions) — the advisory quota base."""
        n = self.fetch_val(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM storage.files WHERE scope = %s",
            (scope,),
        )
        return int(n or 0)

    def get_quota(self, scope: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM storage.quotas WHERE scope = %s", (scope,)
        )

    def set_quota(
        self, scope: str, limit_bytes: int, *, enforce: bool = False
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO storage.quotas (scope, limit_bytes, enforce)
            VALUES (%s, %s, %s)
            ON CONFLICT (scope) DO UPDATE
                SET limit_bytes = EXCLUDED.limit_bytes,
                    enforce = EXCLUDED.enforce,
                    updated_at = now()
            RETURNING *
            """,
            (scope, limit_bytes, enforce),
        )
