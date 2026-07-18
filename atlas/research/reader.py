"""Reader — normalize any acquired artifact to a common ``Document`` (§5e, C1).

Stage 3, Step 3 (the READ stage). Whatever the origin — a PDF, an arXiv/ar5iv HTML
page, a Word doc, a spreadsheet — the Reader turns it into **one shape** so the later
Extraction stage (Step 4) is source-agnostic.

Stage 3.2a extends the contract with ``reader_id`` / ``format`` / ``quality`` /
``failure_code`` / ``failure_reason`` and a PDF→OCR fallback when the text layer is empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.ingestion.extractors import (
    EXTRACTORS,
    extract,
    html_to_main_text,
    looks_paywalled,
)
from atlas.research.pdf_ocr import (
    CODE_EMPTY_TEXT,
    CODE_OCR_UNAVAILABLE,
    QUALITY_EMPTY,
    QUALITY_ERROR,
    QUALITY_FULL,
    QUALITY_PARTIAL,
    READ_OCR,
    ocr_pdf,
)

# Read methods (recorded on the Document + manifest for honesty about *how* we read).
READ_PDF = "pdf"
READ_HTML = "html"
READ_TEXT = "text"
READ_NONE = "none"  # downloaded but no extractable text (scanned/empty)

# Reader ids (which strategy produced the Document).
READER_PDF_TEXT = "pdf_text"
READER_HTML = "html"
READER_TEXT = "text"
READER_PDF_OCR = "pdf_ocr"
READER_NONE = "none"

# Formats (coarse).
FORMAT_PDF = "pdf"
FORMAT_HTML = "html"
FORMAT_TEXT = "text"
FORMAT_UNKNOWN = "unknown"

# Minimum PDF text-layer chars before we skip OCR (weak / scanned PDFs).
_MIN_PDF_TEXT_CHARS = 200

# A read that returned some text but reads like a subscribe/login gate rather than
# an article body (publisher landing pages). Informational: we keep whatever text
# there is (an abstract may still yield a low-evidence claim) but flag *why* a
# peer-reviewed source produced little, so the pipeline trace can say "paywall"
# instead of a vague "no claim patterns matched".
CODE_PAYWALL = "paywall"

# Canonical section labels we care about for extraction scoping (D3.9 / A5).
SECTION_ABSTRACT = "abstract"
SECTION_RESULTS = "results"
SECTION_CONCLUSION = "conclusion"
SECTION_METHODS = "methods"
SECTION_INTRO = "introduction"
SECTION_REFERENCES = "references"
SECTION_BODY = "body"

# Heading → canonical label. Order matters (first match wins per line).
_SECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*#*\s*abstract\b", re.IGNORECASE), SECTION_ABSTRACT),
    (re.compile(r"^\s*#*\s*(?:\d+\.?\s*)?introduction\b", re.IGNORECASE), SECTION_INTRO),
    (re.compile(r"^\s*#*\s*(?:\d+\.?\s*)?(?:materials?\s+and\s+)?methods?\b", re.IGNORECASE), SECTION_METHODS),
    (re.compile(r"^\s*#*\s*(?:\d+\.?\s*)?methodology\b", re.IGNORECASE), SECTION_METHODS),
    (re.compile(r"^\s*#*\s*(?:\d+\.?\s*)?results?(?:\s+and\s+discussion)?\b", re.IGNORECASE), SECTION_RESULTS),
    (re.compile(r"^\s*#*\s*(?:\d+\.?\s*)?discussion\b", re.IGNORECASE), SECTION_RESULTS),
    (re.compile(r"^\s*#*\s*(?:\d+\.?\s*)?conclusions?\b", re.IGNORECASE), SECTION_CONCLUSION),
    (re.compile(r"^\s*#*\s*(?:\d+\.?\s*)?summary\b", re.IGNORECASE), SECTION_CONCLUSION),
    (re.compile(r"^\s*#*\s*references?\b", re.IGNORECASE), SECTION_REFERENCES),
    (re.compile(r"^\s*#*\s*bibliography\b", re.IGNORECASE), SECTION_REFERENCES),
    (re.compile(r"^\s*#*\s*acknowledge?ments?\b", re.IGNORECASE), SECTION_REFERENCES),
]


@dataclass(frozen=True, slots=True)
class Section:
    label: str      # canonical label (abstract/results/…) or "body"
    heading: str    # the raw heading line as it appeared
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "heading": self.heading, "text": self.text}


@dataclass
class Document:
    """A normalized, source-agnostic document (§5e / Stage 3.2a)."""

    source_id: str
    title: str = ""
    url: str = ""
    content_type: str = ""
    text: str = ""
    sections: list[Section] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    read_method: str = READ_NONE
    truncated: bool = False
    # Stage 3.2a contract extensions (D32.2 / D32.8).
    reader_id: str = READER_NONE
    format: str = FORMAT_UNKNOWN
    quality: str = QUALITY_EMPTY
    failure_code: str = ""
    failure_reason: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    def section(self, label: str) -> str:
        """Concatenated text of all sections with ``label`` (empty if none)."""
        return "\n\n".join(s.text for s in self.sections if s.label == label).strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "content_type": self.content_type,
            "chars": self.chars,
            "read_method": self.read_method,
            "truncated": self.truncated,
            "reader_id": self.reader_id,
            "format": self.format,
            "quality": self.quality,
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "warnings": list(self.warnings),
            "sections": [s.as_dict() for s in self.sections],
            "metadata": self.metadata,
        }


def _label_for_heading(line: str) -> str | None:
    for pattern, label in _SECTION_PATTERNS:
        if pattern.match(line) and len(line.strip()) <= 80:
            return label
    return None


def split_sections(text: str) -> list[Section]:
    """Split document text into labeled sections on recognized headings.

    Deterministic and cheap: scans line by line, starting a new section whenever a
    line looks like a known heading (``Abstract``, ``4. Results``, ``## Conclusion``,
    …). Text before the first heading becomes a ``body`` section. When no headings are
    found, returns a single ``body`` section with the whole text.
    """
    if not text or not text.strip():
        return []
    lines = text.splitlines()
    sections: list[Section] = []
    cur_label = SECTION_BODY
    cur_heading = ""
    cur_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(cur_lines).strip()
        if body:
            sections.append(Section(cur_label, cur_heading, body))

    for line in lines:
        label = _label_for_heading(line)
        if label is not None:
            flush()
            cur_label = label
            cur_heading = line.strip()
            cur_lines = []
        else:
            cur_lines.append(line)
    flush()
    if not sections:
        return [Section(SECTION_BODY, "", text.strip())]
    return sections


def detect_format(path: Path, content_type: str = "") -> str:
    """Coarse format from path suffix / content-type (Stage 3.2a router)."""
    suffix = path.suffix.lower()
    ct = (content_type or "").lower()
    if suffix == ".pdf" or "pdf" in ct:
        return FORMAT_PDF
    if suffix in (".html", ".htm") or "html" in ct or "xml" in ct:
        return FORMAT_HTML
    if suffix in (".txt", ".md", ".csv", ".json") or "text" in ct:
        return FORMAT_TEXT
    if suffix in EXTRACTORS:
        return FORMAT_PDF if suffix == ".pdf" else (
            FORMAT_HTML if suffix in (".html", ".htm") else FORMAT_TEXT
        )
    return FORMAT_UNKNOWN


def _read_text_from_path(path: Path, content_type: str) -> tuple[str | None, str, str, str]:
    """Return (text, read_method, reader_id, format) for an acquired file."""
    fmt = detect_format(path, content_type)
    suffix = path.suffix.lower()
    ct = (content_type or "").lower()
    if suffix in EXTRACTORS:
        text = extract(path)
        method = READ_PDF if suffix == ".pdf" else (
            READ_HTML if suffix in (".html", ".htm") else READ_TEXT
        )
        reader_id = (
            READER_PDF_TEXT if method == READ_PDF else
            READER_HTML if method == READ_HTML else READER_TEXT
        )
        return text, method, reader_id, fmt
    if "html" in ct or "xml" in ct:
        return (
            html_to_main_text(path.read_text(encoding="utf-8", errors="replace")),
            READ_HTML,
            READER_HTML,
            FORMAT_HTML,
        )
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None, READ_NONE, READER_NONE, fmt
    return (raw or None), (READ_TEXT if raw else READ_NONE), (
        READER_TEXT if raw else READER_NONE
    ), fmt


class Reader:
    """Turns an acquired file into a normalized :class:`Document`."""

    def __init__(
        self,
        *,
        max_chars: int | None = 200_000,
        ocr_max_pages: int = 50,
        ocr_max_minutes: float = 15.0,
        ocr_dpi: int = 300,
        ocr_enabled: bool = True,
        min_pdf_text_chars: int = _MIN_PDF_TEXT_CHARS,
    ) -> None:
        # A generous cap so a pathological document can't blow up memory; the section
        # scoping in Step 4 does the real cost control (D3.9).
        self._max_chars = max_chars
        self._ocr_max_pages = ocr_max_pages
        self._ocr_max_minutes = ocr_max_minutes
        self._ocr_dpi = ocr_dpi
        self._ocr_enabled = ocr_enabled
        self._min_pdf_text_chars = min_pdf_text_chars

    def read_path(
        self,
        path: str | Path,
        *,
        source_id: str,
        title: str = "",
        url: str = "",
        content_type: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        path = Path(path)
        text, method, reader_id, fmt = _read_text_from_path(path, content_type)
        meta = dict(metadata or {})
        warnings: list[str] = []
        failure_code = ""
        failure_reason = ""
        quality = QUALITY_FULL if (text or "").strip() else QUALITY_EMPTY

        # PDF with weak/empty text layer → full OCR fallback (A32.3).
        if (
            self._ocr_enabled
            and fmt == FORMAT_PDF
            and len((text or "").strip()) < self._min_pdf_text_chars
        ):
            ocr = ocr_pdf(
                path,
                max_pages=self._ocr_max_pages,
                max_minutes=self._ocr_max_minutes,
                dpi=self._ocr_dpi,
            )
            meta["ocr"] = ocr.as_dict()
            warnings.extend(ocr.warnings)
            if ocr.text:
                text = ocr.text
                method = READ_OCR
                reader_id = READER_PDF_OCR
                quality = ocr.quality
                failure_code = ocr.failure_code
                failure_reason = ocr.failure_reason
            else:
                # Keep any thin text layer we had; still surface OCR failure.
                quality = QUALITY_PARTIAL if (text or "").strip() else QUALITY_EMPTY
                failure_code = ocr.failure_code or CODE_EMPTY_TEXT
                failure_reason = ocr.failure_reason or "No extractable PDF text"
                if ocr.failure_code == CODE_OCR_UNAVAILABLE and not (text or "").strip():
                    failure_code = CODE_OCR_UNAVAILABLE
                    failure_reason = ocr.failure_reason
                reader_id = READER_PDF_OCR if ocr.failure_code else reader_id
                method = READ_NONE if not (text or "").strip() else method

        if not (text or "").strip() and not failure_code:
            failure_code = CODE_EMPTY_TEXT
            failure_reason = "No extractable text"
            quality = QUALITY_EMPTY

        # Publisher landing/paywall gate: text present but it reads like a login
        # wall, not an article. Keep the text (abstract may help) but record why.
        if fmt == FORMAT_HTML and (text or "").strip() and looks_paywalled(text):
            warnings.append("paywall/login markers detected in page text")
            meta["paywall_suspected"] = True
            if not failure_code:
                failure_code = CODE_PAYWALL
                failure_reason = (
                    "paywall/login gate detected — article body may be inaccessible"
                )
            if quality == QUALITY_FULL:
                quality = QUALITY_PARTIAL

        return self._build(
            source_id,
            title,
            url,
            content_type,
            text,
            method,
            meta,
            reader_id=reader_id,
            fmt=fmt,
            quality=quality,
            failure_code=failure_code,
            failure_reason=failure_reason,
            warnings=warnings,
        )

    def read_text(
        self,
        text: str | None,
        *,
        source_id: str,
        title: str = "",
        url: str = "",
        content_type: str = "text/plain",
        read_method: str = READ_TEXT,
        metadata: dict[str, Any] | None = None,
        reader_id: str = READER_TEXT,
        format: str = FORMAT_TEXT,
    ) -> Document:
        """Normalize already-extracted text (e.g. an abstract, a transcript)."""
        cleaned = (text or "").strip()
        return self._build(
            source_id,
            title,
            url,
            content_type,
            cleaned,
            read_method if cleaned else READ_NONE,
            metadata,
            reader_id=reader_id if cleaned else READER_NONE,
            fmt=format,
            quality=QUALITY_FULL if cleaned else QUALITY_EMPTY,
            failure_code="" if cleaned else CODE_EMPTY_TEXT,
            failure_reason="" if cleaned else "No extractable text",
            warnings=[],
        )

    def _build(
        self,
        source_id: str,
        title: str,
        url: str,
        content_type: str,
        text: str | None,
        method: str,
        metadata: dict[str, Any] | None,
        *,
        reader_id: str,
        fmt: str,
        quality: str,
        failure_code: str,
        failure_reason: str,
        warnings: list[str],
    ) -> Document:
        text = (text or "").strip()
        truncated = False
        if self._max_chars is not None and len(text) > self._max_chars:
            text = text[: self._max_chars]
            truncated = True
            if quality == QUALITY_FULL:
                quality = QUALITY_PARTIAL
            warnings = list(warnings) + ["text truncated to max_chars"]
        sections = split_sections(text) if text else []
        return Document(
            source_id=source_id,
            title=title,
            url=url,
            content_type=content_type,
            text=text,
            sections=sections,
            metadata=dict(metadata or {}),
            read_method=method if text else READ_NONE,
            truncated=truncated,
            reader_id=reader_id if text else (reader_id or READER_NONE),
            format=fmt,
            quality=quality if text or failure_code else QUALITY_EMPTY,
            failure_code=failure_code,
            failure_reason=failure_reason,
            warnings=list(warnings),
        )
