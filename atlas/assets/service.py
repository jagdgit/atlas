"""Asset Store (Phase 0 · ATLAS_OS_ROADMAP §5.9, principle P8).

**Assets are not knowledge.** An asset is a raw, versioned *source artifact* — a git
repo, a PDF, a DWG/CAD drawing, a MATLAB project, an image — from which knowledge is
later extracted. This keeps re-parsing cheap: the bytes stay put, only the extracted
knowledge is re-derived when a reader/extractor improves.

The Asset Store is a **thin layer over the Storage Manager**: bytes are stored (and
checksum-verified) by :class:`~atlas.storage.service.StorageManager`; this service owns
the logical registry (``asset.assets`` + ``asset.versions``) so knowledge/provenance can
reference a stable ``(asset_id, version)`` instead of a raw path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.exceptions import AtlasError
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.assets.repository import AssetRepository
    from atlas.storage.service import StorageManager


class AssetError(AtlasError):
    """An asset operation failed (unknown asset/version, storage failure, …)."""


class AssetStore:
    """The ``assets`` capability/service — versioned source artifacts over storage."""

    name = "assets"

    # Artifact version (P2): bump on a material change to asset layout/behaviour.
    VERSION = "1"

    def __init__(
        self,
        storage: "StorageManager",
        repo: "AssetRepository",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._storage = storage
        self._repo = repo
        self._logger = logger or logging.getLogger("atlas.assets")

    # --- register / read -----------------------------------------------

    def register(
        self,
        kind: str,
        name: str,
        data: bytes | str | Path,
        *,
        source_uri: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a new *version* of an asset (creating the asset on first sight).

        Bytes are written + checksummed by the Storage Manager; a new
        ``asset.versions`` row records how to re-fetch them. Returns
        ``{"asset": <asset row>, "version": <version row>}``.
        """
        asset = self._repo.get_by_natural(kind, name)
        if asset is None:
            asset = self._repo.create_asset(
                kind=kind,
                name=name,
                source_uri=source_uri,
                content_type=content_type,
                metadata=metadata,
            )
        asset_id = str(asset["id"])

        # Deterministic, collision-free storage coordinates: the asset id makes the
        # storage (scope, name) unique, so storage versioning == asset versioning.
        scope = f"asset-{kind}"
        sname = f"{asset_id}-{name}"
        stored = self._storage.put_file(
            scope, sname, data,
            content_type=content_type,
            metadata={"asset_id": asset_id, "kind": kind},
        )

        version_row = self._repo.add_version(
            asset_id=asset_id,
            version=int(stored["version"]),
            storage_scope=scope,
            storage_name=sname,
            storage_version=int(stored["version"]),
            storage_file_id=stored.get("id"),
            checksum=str(stored["checksum"]),
            size_bytes=int(stored["size_bytes"]),
            content_type=content_type,
            metadata=metadata,
        )
        updated = self._repo.set_current_version(asset_id, int(stored["version"]))
        self._logger.info(
            "registered asset %s/%s v%s (%d bytes)",
            kind, name, stored["version"], stored["size_bytes"],
        )
        return {"asset": updated or asset, "version": version_row}

    def get_bytes(self, asset_id: str, version: int | None = None) -> bytes:
        """Read an asset's bytes (latest version unless given), checksum-verified."""
        row = self._require_version(asset_id, version)
        return self._storage.get_bytes(
            str(row["storage_scope"]),
            str(row["storage_name"]),
            int(row["storage_version"]),
        )

    def path_of(self, asset_id: str, version: int | None = None) -> Path:
        row = self._require_version(asset_id, version)
        return self._storage.path_of(
            str(row["storage_scope"]),
            str(row["storage_name"]),
            int(row["storage_version"]),
        )

    def verify(self, asset_id: str, version: int | None = None) -> bool:
        """True if the underlying stored blob exists and its checksum matches."""
        row = self._repo.get_version(asset_id, version)
        if row is None:
            return False
        return self._storage.verify(
            str(row["storage_scope"]),
            str(row["storage_name"]),
            int(row["storage_version"]),
        )

    # --- lookups --------------------------------------------------------

    def get(self, asset_id: str) -> dict[str, Any] | None:
        return self._repo.get_asset(asset_id)

    def get_by_name(self, kind: str, name: str) -> dict[str, Any] | None:
        return self._repo.get_by_natural(kind, name)

    def list_assets(self, kind: str | None = None) -> list[dict[str, Any]]:
        return self._repo.list_assets(kind)

    def versions(self, asset_id: str) -> list[dict[str, Any]]:
        return self._repo.list_versions(asset_id)

    # --- groups / relationships (§C.2) ----------------------------------

    def create_group(
        self, kind: str, name: str, *, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Get-or-create a named group of related assets (a repo + its design doc + a chat)."""
        group = self._repo.create_group(kind=kind, name=name, metadata=metadata)
        self._logger.info("asset group %s/%s ready (%s)", kind, name, group["id"])
        return group

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        return self._repo.get_group(group_id)

    def get_group_by_name(self, kind: str, name: str) -> dict[str, Any] | None:
        return self._repo.get_group_by_natural(kind, name)

    def list_groups(self, kind: str | None = None) -> list[dict[str, Any]]:
        return self._repo.list_groups(kind)

    def add_to_group(
        self,
        group_id: str,
        asset_id: str,
        *,
        role: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add an asset to a group (grouping is relationship, not ownership — P12)."""
        if self._repo.get_group(group_id) is None:
            raise AssetError(f"no such asset group: {group_id}")
        if self._repo.get_asset(asset_id) is None:
            raise AssetError(f"no such asset: {asset_id}")
        return self._repo.add_member(
            group_id=group_id, asset_id=asset_id, role=role, metadata=metadata
        )

    def remove_from_group(self, group_id: str, asset_id: str) -> bool:
        return self._repo.remove_member(group_id, asset_id)

    def group_members(self, group_id: str) -> list[dict[str, Any]]:
        """The assets in a group (each carries its membership ``member_role``)."""
        return self._repo.list_members(group_id)

    def groups_for_asset(self, asset_id: str) -> list[dict[str, Any]]:
        """The groups an asset belongs to."""
        return self._repo.list_groups_for_asset(asset_id)

    # --- lifecycle ------------------------------------------------------

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok("asset store ready")

    # --- helpers --------------------------------------------------------

    def _require_version(
        self, asset_id: str, version: int | None
    ) -> dict[str, Any]:
        row = self._repo.get_version(asset_id, version)
        if row is None:
            v = f" v{version}" if version is not None else ""
            raise AssetError(f"no such asset version: {asset_id}{v}")
        return row
