"""Document Reader service (S13) — `DocumentCapability`.

A thin, honest wrapper over the shared extractors (`atlas.ingestion.extractors`)
that adds:
- a **capability surface** (`extract`, `supported`) registered as `document`;
- explicit **outcome classification** so callers (jobs, R2/R3) can tell *why* a
  file yielded no text: ``unsupported`` (no extractor), ``empty`` (no text layer —
  e.g. a scanned PDF, a future OCR concern), or ``error`` (parse failure), versus
  ``ok`` with text. It never raises for a bad file — it reports.

Kernel-managed service (start/stop/health). Formats:
pdf, docx, pptx, xlsx, csv, md, txt, html, json.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.ingestion.extractors import (
    content_type_for,
    extract,
    supported_extensions,
)
from atlas.services.base import HealthStatus


@dataclass(frozen=True)
class ExtractedDocument:
    """Result of extracting one file. ``outcome`` is one of ok/unsupported/empty/error."""

    path: str
    outcome: str
    text: str = ""
    content_type: str = ""
    extension: str = ""
    chars: int = 0
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "outcome": self.outcome,
            "text": self.text,
            "content_type": self.content_type,
            "extension": self.extension,
            "chars": self.chars,
            "reason": self.reason,
        }


class DocumentService:
    name = "documents"

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("atlas.documents")

    # --- capability -----------------------------------------------------
    def supported(self) -> list[str]:
        """File extensions this reader can extract (e.g. ``.pdf``)."""
        return supported_extensions()

    def can_extract(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() in set(supported_extensions())

    def extract(self, path: str | Path) -> ExtractedDocument:
        """Extract plain text from a file, classifying the outcome (never raises)."""
        p = Path(path).expanduser()
        ext = p.suffix.lower()
        if not p.is_file():
            return ExtractedDocument(str(p), "error", extension=ext,
                                     reason="not a file")
        if ext not in set(supported_extensions()):
            return ExtractedDocument(
                str(p), "unsupported", extension=ext,
                reason=f"no extractor for '{ext}'",
            )
        try:
            text = extract(p)
        except Exception as exc:  # noqa: BLE001 - a bad file must be reported, not crash
            self._logger.exception("extract failed for %s", p)
            return ExtractedDocument(
                str(p), "error", extension=ext,
                reason=f"{type(exc).__name__}: {exc}",
            )
        if not text:
            # e.g. a scanned/image-only PDF: no text layer (future OCR concern).
            return ExtractedDocument(
                str(p), "empty", extension=ext,
                content_type=content_type_for(p),
                reason="no extractable text (empty or image-only)",
            )
        return ExtractedDocument(
            str(p), "ok", text=text, content_type=content_type_for(p),
            extension=ext, chars=len(text),
        )

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        exts = self.supported()
        return HealthStatus.ok(f"{len(exts)} format(s): {', '.join(exts)}",
                               formats=exts)
