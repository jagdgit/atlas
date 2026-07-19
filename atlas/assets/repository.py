"""Repository for the Asset Store (Phase 0 · ATLAS_OS_ROADMAP §5.9).

The only layer permitted to hold SQL (ADR-0027). Backs ``asset.assets`` (logical,
versioned source artifacts) and ``asset.versions`` (each concrete stored blob). Bytes
themselves live in the Storage Manager (``storage.files``); rows here only reference
them by ``(storage_scope, storage_name, storage_version)`` + a soft ``storage_file_id``.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository


class AssetRepository(BaseRepository):
    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM asset.assets WHERE id = %s", (asset_id,))

    def get_by_natural(self, kind: str, name: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM asset.assets WHERE kind = %s AND name = %s",
            (kind, name),
        )

    def create_asset(
        self,
        *,
        kind: str,
        name: str,
        source_uri: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO asset.assets (kind, name, source_uri, content_type, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (kind, name, source_uri, content_type, Jsonb(metadata or {})),
        )

    def set_current_version(self, asset_id: str, version: int) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            UPDATE asset.assets
            SET current_version = %s, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (version, asset_id),
        )

    def next_version(self, asset_id: str) -> int:
        n = self.fetch_val(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM asset.versions WHERE asset_id = %s",
            (asset_id,),
        )
        return int(n or 1)

    def add_version(
        self,
        *,
        asset_id: str,
        version: int,
        storage_scope: str,
        storage_name: str,
        storage_version: int,
        storage_file_id: str | None,
        checksum: str,
        size_bytes: int,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO asset.versions (
                asset_id, version, storage_scope, storage_name, storage_version,
                storage_file_id, checksum, size_bytes, content_type, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                asset_id, version, storage_scope, storage_name, storage_version,
                storage_file_id, checksum, size_bytes, content_type,
                Jsonb(metadata or {}),
            ),
        )

    def get_version(
        self, asset_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        if version is not None:
            return self.fetch_one(
                "SELECT * FROM asset.versions WHERE asset_id = %s AND version = %s",
                (asset_id, version),
            )
        return self.fetch_one(
            """
            SELECT * FROM asset.versions
            WHERE asset_id = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (asset_id,),
        )

    def list_versions(self, asset_id: str) -> list[dict[str, Any]]:
        return self.fetch_all(
            "SELECT * FROM asset.versions WHERE asset_id = %s ORDER BY version DESC",
            (asset_id,),
        )

    def list_assets(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is not None:
            return self.fetch_all(
                "SELECT * FROM asset.assets WHERE kind = %s ORDER BY created_at DESC",
                (kind,),
            )
        return self.fetch_all("SELECT * FROM asset.assets ORDER BY created_at DESC")

    # --- groups / relationships (§C.2, migration 0029) -----------------

    def create_group(
        self, *, kind: str, name: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Get-or-create a group by its natural key ``(kind, name)``."""
        row = self.fetch_one(
            """
            INSERT INTO asset.groups (kind, name, metadata)
            VALUES (%s, %s, %s)
            ON CONFLICT (kind, name) DO NOTHING
            RETURNING *
            """,
            (kind, name, Jsonb(metadata or {})),
        )
        if row is None:  # already present
            existing = self.get_group_by_natural(kind, name)
            assert existing is not None  # conflict implies the row exists
            return existing
        return row

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM asset.groups WHERE id = %s", (group_id,))

    def get_group_by_natural(self, kind: str, name: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM asset.groups WHERE kind = %s AND name = %s", (kind, name)
        )

    def list_groups(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is not None:
            return self.fetch_all(
                "SELECT * FROM asset.groups WHERE kind = %s ORDER BY created_at DESC",
                (kind,),
            )
        return self.fetch_all("SELECT * FROM asset.groups ORDER BY created_at DESC")

    def add_member(
        self,
        *,
        group_id: str,
        asset_id: str,
        role: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add an asset to a group (idempotent: re-adding updates its role/metadata)."""
        return self.fetch_one(
            """
            INSERT INTO asset.group_members (group_id, asset_id, role, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (group_id, asset_id)
            DO UPDATE SET role = EXCLUDED.role, metadata = EXCLUDED.metadata
            RETURNING *
            """,
            (group_id, asset_id, role, Jsonb(metadata or {})),
        )

    def remove_member(self, group_id: str, asset_id: str) -> bool:
        return (
            self.execute(
                "DELETE FROM asset.group_members WHERE group_id = %s AND asset_id = %s",
                (group_id, asset_id),
            )
            > 0
        )

    def list_members(self, group_id: str) -> list[dict[str, Any]]:
        """Assets in a group (each asset row + its membership ``role``/``member_metadata``)."""
        return self.fetch_all(
            """
            SELECT a.*, gm.role AS member_role, gm.metadata AS member_metadata,
                   gm.added_at AS member_added_at
            FROM asset.group_members gm
            JOIN asset.assets a ON a.id = gm.asset_id
            WHERE gm.group_id = %s
            ORDER BY gm.added_at ASC
            """,
            (group_id,),
        )

    def list_groups_for_asset(self, asset_id: str) -> list[dict[str, Any]]:
        """Groups an asset belongs to (each group row + this membership's ``role``)."""
        return self.fetch_all(
            """
            SELECT g.*, gm.role AS member_role
            FROM asset.group_members gm
            JOIN asset.groups g ON g.id = gm.group_id
            WHERE gm.asset_id = %s
            ORDER BY g.created_at DESC
            """,
            (asset_id,),
        )
