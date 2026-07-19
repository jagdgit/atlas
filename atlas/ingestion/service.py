"""Unified ingestion bridge (Phase C · PHASE_C_PLAN §C.2, CC2 / constitution P11/P12).

One path in, one path out: ``Asset → Reader → Artifact → chunks/embeddings``. This service wires
the three C.2 pieces together so a single call takes raw bytes/a file and lands:

1. a content-addressed **Asset** (:class:`atlas.ingestion.acquire.AssetAcquirer`) — dedup + provenance;
2. a cached text **Artifact** (:class:`atlas.readers.document.DocumentReader`);
3. searchable **chunks/embeddings** (:class:`atlas.knowledge.service.KnowledgeService`), with the
   resulting ``knowledge.documents`` row linked back to ``(asset_id, asset_version)`` (migration 0028).

It owns no knowledge itself (P11) — it orchestrates stateless translators. Distilled *findings*
from prose are the next slice (C.3, via the Knowledge Consolidator); this bridge deliberately stops
at the RAG/chunks product so C.3 can add the finding path without reworking the seam.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas.ingestion.acquire import AcquiredAsset, AssetAcquirer
    from atlas.knowledge.service import KnowledgeService
    from atlas.readers.document import DocumentReader


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of ingesting one source through the unified pipeline."""

    asset_id: str
    asset_version: int
    asset_reused: bool
    outcome: str            # ok | empty | unsupported | error (from the reader)
    document_id: str | None
    chunks: int
    deduped: bool
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_version": self.asset_version,
            "asset_reused": self.asset_reused,
            "outcome": self.outcome,
            "document_id": self.document_id,
            "chunks": self.chunks,
            "deduped": self.deduped,
            "reason": self.reason,
        }


class IngestionService:
    """Acquire → read → chunk/embed a document in one call (the C.2 spine)."""

    name = "ingestion"

    def __init__(
        self,
        acquirer: "AssetAcquirer",
        reader: "DocumentReader",
        knowledge: "KnowledgeService",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._acq = acquirer
        self._reader = reader
        self._knowledge = knowledge
        self._logger = logger or logging.getLogger("atlas.ingestion.service")

    def ingest_file(
        self,
        path: str | Path,
        *,
        kind: str = "document",
        domain: str = "external",
        title: str | None = None,
        embed: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        """Acquire a file as an asset, read it, and ingest its text into the knowledge base."""
        p = Path(path).expanduser()
        acquired = self._acq.acquire_file(p, kind=kind, metadata=metadata)
        return self._ingest(acquired, filename=p.name, domain=domain, title=title, embed=embed)

    def ingest_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        kind: str = "document",
        domain: str = "external",
        title: str | None = None,
        embed: bool = True,
        source_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        """Acquire raw bytes as an asset, read them, and ingest the text."""
        acquired = self._acq.acquire_bytes(
            data, kind=kind, filename=filename, source_uri=source_uri, metadata=metadata
        )
        return self._ingest(acquired, filename=filename, domain=domain, title=title, embed=embed)

    # --- internals ------------------------------------------------------
    def _ingest(
        self,
        acquired: "AcquiredAsset",
        *,
        filename: str,
        domain: str,
        title: str | None,
        embed: bool,
    ) -> IngestResult:
        artifact = self._reader.read(
            acquired.asset_id, acquired.asset_version, filename=filename
        )
        text = (artifact.get("text") or "").strip()
        if artifact.get("outcome") != "ok" or not text:
            # A scanned PDF / unsupported type / parse error is *reported*, never a crash (honesty).
            self._logger.info(
                "no ingestible text from %s (%s): %s",
                filename, artifact.get("outcome"), artifact.get("reason"),
            )
            return IngestResult(
                asset_id=acquired.asset_id,
                asset_version=acquired.asset_version,
                asset_reused=acquired.reused,
                outcome=str(artifact.get("outcome") or "error"),
                document_id=None,
                chunks=0,
                deduped=False,
                reason=artifact.get("reason"),
            )

        summary = self._knowledge.ingest_text(
            source="document",
            content=artifact["text"],
            uri=acquired.source_uri,
            title=title or filename,
            content_type=artifact.get("content_type") or "text/plain",
            metadata={
                "asset_id": acquired.asset_id,
                "asset_version": acquired.asset_version,
                "sha256": acquired.checksum,
                "reader": self._reader.id,
                "reader_version": self._reader.VERSION,
                "filename": filename,
            },
            domain=domain,
            embed=embed,
            asset_id=acquired.asset_id,
            asset_version=acquired.asset_version,
        )
        return IngestResult(
            asset_id=acquired.asset_id,
            asset_version=acquired.asset_version,
            asset_reused=acquired.reused,
            outcome="ok",
            document_id=summary.get("document_id"),
            chunks=int(summary.get("chunks") or 0),
            deduped=bool(summary.get("deduped")),
        )

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None
