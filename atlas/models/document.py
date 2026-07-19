"""Knowledge-domain models: Document, Chunk, Embedding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from atlas.models.base import Model


@dataclass(frozen=True, slots=True)
class Document(Model):
    """A source item ingested into the knowledge base (``knowledge.documents``)."""

    id: str
    source: str
    checksum: str
    content_type: str = "text/plain"
    uri: str | None = None
    title: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    domain: str = "external"  # Stage 3 / D3.13 — knowledge universe tag
    # Unified ingestion (Phase C / §C.2): soft provenance link back to the source Asset this
    # document was read from (NULL for inline notes / web text / pre-Phase-C rows).
    asset_id: str | None = None
    asset_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Chunk(Model):
    """An ordered segment of a document (``knowledge.chunks``)."""

    id: str
    document_id: str
    ordinal: int
    content: str
    token_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Embedding(Model):
    """A vector for a chunk under a model (``knowledge.embeddings``).

    The vector itself is not carried on the model (it lives in pgvector and is
    used only for similarity search); this captures the row's metadata.
    """

    id: str
    chunk_id: str
    model: str
    dim: int
    created_at: datetime | None = None
