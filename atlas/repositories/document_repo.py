"""Repository for ``knowledge.documents``.

A document is a source item ingested into the knowledge base. Content is
deduplicated by sha256 checksum so re-ingesting the same text is a no-op.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models import Document
from atlas.repositories.base import BaseRepository

VALID_STATUSES = {"pending", "chunked", "embedded", "failed"}


def checksum_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class DocumentRepository(BaseRepository):
    def create(
        self,
        source: str,
        content: str,
        *,
        uri: str | None = None,
        title: str | None = None,
        content_type: str = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        """Insert a document, or return the existing one with the same content.

        Dedup is by checksum; identical content never creates a duplicate.
        """
        digest = checksum_of(content)
        row = self.fetch_one(
            """
            INSERT INTO knowledge.documents
                (source, uri, title, content_type, content, checksum, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (checksum) DO NOTHING
            RETURNING *
            """,
            (
                source,
                uri,
                title,
                content_type,
                content,
                digest,
                Jsonb(metadata or {}),
            ),
        )
        if row is None:  # already present
            existing = self.get_by_checksum(digest)
            assert existing is not None  # conflict implies the row exists
            return existing
        return Document.from_row(row)

    def get(self, document_id: UUID | str) -> Document | None:
        row = self.fetch_one(
            "SELECT * FROM knowledge.documents WHERE id = %s", (str(document_id),)
        )
        return Document.from_row(row) if row else None

    def get_by_checksum(self, checksum: str) -> Document | None:
        row = self.fetch_one(
            "SELECT * FROM knowledge.documents WHERE checksum = %s", (checksum,)
        )
        return Document.from_row(row) if row else None

    def list_by_status(self, status: str, limit: int = 100) -> list[Document]:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        rows = self.fetch_all(
            """
            SELECT * FROM knowledge.documents
            WHERE status = %s
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (status, limit),
        )
        return Document.from_rows(rows)

    def recent(self, *, limit: int = 50) -> list[Document]:
        """List documents newest-first (excludes the large ``content`` column)."""
        rows = self.fetch_all(
            """
            SELECT id, source, uri, title, content_type, checksum, metadata,
                   status, created_at, updated_at
            FROM knowledge.documents
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return Document.from_rows(rows)

    def count(self) -> int:
        return self.fetch_val("SELECT count(*) FROM knowledge.documents") or 0

    def set_status(self, document_id: UUID | str, status: str) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        return (
            self.execute(
                """
                UPDATE knowledge.documents
                SET status = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, str(document_id)),
            )
            > 0
        )

    def delete(self, document_id: UUID | str) -> bool:
        return (
            self.execute(
                "DELETE FROM knowledge.documents WHERE id = %s", (str(document_id),)
            )
            > 0
        )
