"""Knowledge errors (ingest, embed mismatch, search)."""

from __future__ import annotations

from atlas.exceptions.base import AtlasError


class KnowledgeError(AtlasError):
    """Any failure in the knowledge pipeline."""


class IngestError(KnowledgeError):
    """A document could not be ingested (extraction/chunking failure)."""


class EmbeddingMismatchError(KnowledgeError):
    """The provider returned a different number of vectors than inputs."""


class SearchError(KnowledgeError):
    """Semantic search failed."""
