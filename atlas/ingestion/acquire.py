"""Generic (non-git) Asset Acquirer (Phase C · PHASE_C_PLAN §C.2, P8/P11/P12).

The non-repo counterpart of :class:`atlas.engineering.ingest.RepoAcquirer` (BB1): given raw
**bytes** or a **file**, register them as a versioned, checksummed **Asset** in the Asset Store so
that everything Atlas ingests — documents, PDFs, transcripts, chats — flows through the *one*
pipeline ``Asset → Reader → Artifact → Extraction → Knowledge`` (P11). Knowledge extracted later
references a stable ``(asset_id, version)`` instead of a raw path (P8, Assets ≠ Knowledge).

**Identity = content sha256** (matches today's ``DocumentRepository`` dedup): identical bytes
resolve to the **same** asset (no duplicate storage); different bytes are a different asset. This
makes re-ingesting an unchanged file a cheap no-op and keeps the store content-addressed.

Per constitution **P11** the acquirer is a *stateless translator*: it registers an asset and
returns provenance; it never writes findings, knowledge, missions, or decisions.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.exceptions import AtlasError

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

# Default asset kind for generic documents; callers may override (e.g. "pdf", "transcript").
DEFAULT_ASSET_KIND = "document"


class AssetAcquireError(AtlasError):
    """A generic asset could not be acquired (missing file, empty bytes, …)."""


@dataclass(frozen=True, slots=True)
class AcquiredAsset:
    """The result of acquiring a generic asset: where it is + its identity/provenance."""

    asset_id: str
    asset_version: int
    kind: str
    name: str            # the content sha256 (the asset's natural key within its kind)
    checksum: str        # == name; kept explicit for symmetry with AcquiredRepo
    content_type: str | None
    source_uri: str | None
    size_bytes: int
    reused: bool
    source: str          # a human label: source_uri or filename or checksum


def sha256_bytes(data: bytes) -> str:
    """Content hash used as the asset's identity (content-addressed dedup)."""
    return hashlib.sha256(data).hexdigest()


class AssetAcquirer:
    """Acquire arbitrary bytes/files → register a content-addressed Asset (C.2)."""

    def __init__(
        self,
        asset_store: "AssetStore",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = asset_store
        self._logger = logger or logging.getLogger("atlas.ingestion.acquire")

    def acquire_bytes(
        self,
        data: bytes | bytearray,
        *,
        kind: str = DEFAULT_ASSET_KIND,
        filename: str | None = None,
        source_uri: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AcquiredAsset:
        """Register ``data`` as an asset (content-addressed); reuse if identical bytes exist."""
        if not isinstance(data, (bytes, bytearray)):
            raise AssetAcquireError("acquire_bytes requires bytes")
        data = bytes(data)
        if not data:
            raise AssetAcquireError("refusing to acquire empty bytes")

        checksum = sha256_bytes(data)

        # Content-addressed identity: the sha256 *is* the natural key, so the mere existence of the
        # asset means byte-identical content — reuse the current version (no duplicate storage).
        existing = self._assets.get_by_name(kind, checksum)
        if existing is not None:
            versions = self._assets.versions(str(existing["id"]))
            if versions:
                current = versions[0]
                self._logger.info(
                    "asset %s/%s… unchanged — reusing v%s",
                    kind, checksum[:12], current["version"],
                )
                return AcquiredAsset(
                    asset_id=str(existing["id"]),
                    asset_version=int(current["version"]),
                    kind=kind,
                    name=checksum,
                    checksum=checksum,
                    content_type=existing.get("content_type"),
                    source_uri=existing.get("source_uri"),
                    size_bytes=int(current.get("size_bytes") or len(data)),
                    reused=True,
                    source=source_uri or filename or checksum,
                )

        ct = content_type or (
            mimetypes.guess_type(filename)[0] if filename else None
        )
        meta: dict[str, Any] = {"sha256": checksum}
        if filename:
            meta["filename"] = filename
        if metadata:
            meta.update(metadata)

        result = self._assets.register(
            kind, checksum, data,
            source_uri=source_uri, content_type=ct, metadata=meta,
        )
        asset_id = str(result["asset"]["id"])
        version = int(result["version"]["version"])
        self._logger.info(
            "registered %s asset %s… v%s (%d bytes)",
            kind, checksum[:12], version, len(data),
        )
        return AcquiredAsset(
            asset_id=asset_id,
            asset_version=version,
            kind=kind,
            name=checksum,
            checksum=checksum,
            content_type=ct,
            source_uri=source_uri,
            size_bytes=len(data),
            reused=False,
            source=source_uri or filename or checksum,
        )

    def acquire_file(
        self,
        path: str | Path,
        *,
        kind: str = DEFAULT_ASSET_KIND,
        source_uri: str | None = None,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AcquiredAsset:
        """Read a file and register it as a content-addressed asset."""
        p = Path(path).expanduser()
        if not p.is_file():
            raise AssetAcquireError(f"not a file: {p}")
        try:
            data = p.read_bytes()
        except OSError as exc:
            raise AssetAcquireError(f"could not read {p}: {exc}") from exc
        return self.acquire_bytes(
            data,
            kind=kind,
            filename=p.name,
            source_uri=source_uri or str(p),
            content_type=content_type,
            metadata=metadata,
        )
