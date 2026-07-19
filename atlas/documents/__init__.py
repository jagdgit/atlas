"""Document Reader (Stage 2, S13): structured text extraction across formats.

`DocumentService` implements the `DocumentCapability` contract — one place that
turns pdf/docx/pptx/xlsx/csv/md/txt/html/json into plain text (via the shared
`atlas.ingestion.extractors`), used by ingestion, the planner, and the API/CLI.
"""

from __future__ import annotations

from atlas.documents.service import DocumentService, ExtractedDocument

__all__ = ["DocumentService", "ExtractedDocument"]
