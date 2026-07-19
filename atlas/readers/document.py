"""Document Reader (Phase C · PHASE_C_PLAN §C.2, BB10/BB11 / constitution P11).

The first **non-code** reader: it turns a document **Asset** (pdf/docx/txt/md/html/…) into a
structured text **Artifact** — the derived product that later feeds both RAG chunking and prose
finding extraction. It reuses the shared extractor engine (:class:`atlas.documents.DocumentService`
over ``atlas.ingestion.extractors``) and caches the artifact in the **Derived Artifact Store**
keyed by ``{asset_id, asset_version, reader, reader_version}`` (BB11), so re-reading an unchanged
asset is a cheap cache hit and improving the *extractor* re-runs without re-fetching the asset.

Per constitution **P11** this reader owns no knowledge or state: it reads bytes and returns an
artifact. It is deliberately duck-typed against the Asset Store (needs ``get_bytes``/``versions``)
and the artifact cache (needs ``get``/``put``) so it does not couple to the engineering package.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.documents.service import DocumentService

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

DOCUMENT_READER_ID = "document"
DOCUMENT_READER_VERSION = "1.0.0"


class DocumentReader:
    """Read a document asset → cached text artifact (BB11); reuse when unchanged."""

    id = DOCUMENT_READER_ID
    VERSION = DOCUMENT_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        documents: DocumentService | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts  # DerivedArtifactStore (duck-typed: get/put)
        self._docs = documents or DocumentService()
        self._logger = logger or logging.getLogger("atlas.readers.document")

    def supported_extensions(self) -> list[str]:
        """File extensions this reader can extract (e.g. ``.pdf``, ``.md``)."""
        return self._docs.supported()

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Return the text artifact for ``(asset_id, version)`` — from cache unless ``force``.

        ``filename`` supplies the extension the extractor dispatches on; when omitted it is read
        from the asset version's ``metadata.filename`` (stamped by the Asset Acquirer).
        """
        version = self._resolve_version(asset_id, asset_version)

        if not force:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None:
                self._logger.debug(
                    "artifact hit for %s v%s (%s@%s)",
                    asset_id, version, self.id, self.VERSION,
                )
                return cached

        filename = filename or self._filename_from_metadata(asset_id, version)
        data = self._assets.get_bytes(asset_id, version)
        artifact = self._extract(data, filename, asset_id, version)
        self._artifacts.put(asset_id, version, self.id, self.VERSION, artifact)
        return artifact

    # --- internals ------------------------------------------------------
    def _extract(
        self, data: bytes, filename: str | None, asset_id: str, version: int
    ) -> dict[str, Any]:
        # Extractors dispatch on file extension, so materialize the bytes with the right suffix.
        suffix = Path(filename).suffix.lower() if filename else ""
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(data)
            tmp.flush()
            result = self._docs.extract(tmp.name)
        text = result.text or ""
        return {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "outcome": result.outcome,
            "content_type": result.content_type,
            "extension": suffix,
            "text": text,
            "chars": len(text),
            "reason": result.reason,
            # A minimal section model; richer page/section splitting can land later without a
            # reader_version bump for callers that only read `text`.
            "sections": [{"ordinal": 0, "text": text}] if text else [],
        }

    def _resolve_version(self, asset_id: str, asset_version: int | None) -> int:
        if asset_version is not None:
            return int(asset_version)
        versions = self._assets.versions(asset_id)
        if not versions:
            raise ValueError(f"asset has no versions: {asset_id}")
        return int(versions[0]["version"])

    def _filename_from_metadata(self, asset_id: str, version: int) -> str | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) == version:
                meta = row.get("metadata") or {}
                name = meta.get("filename")
                return str(name) if name else None
        return None
