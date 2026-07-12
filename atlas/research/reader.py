"""Reader — normalize any acquired artifact to a common ``Document`` (§5e, C1).

Stage 3, Step 3 (the READ stage). Whatever the origin — a PDF, an arXiv/ar5iv HTML
page, a Word doc, a spreadsheet — the Reader turns it into **one shape** so the later
Extraction stage (Step 4) is source-agnostic:

    Document(source_id, title, url, content_type, text, sections[], metadata, ...)

It reuses the existing ``ingestion.extractors`` (pypdf/BeautifulSoup/python-docx/…),
so no new parsing dependency is introduced. ``split_sections`` is a cheap, deterministic
heuristic that lets Step 4 scope extraction to the sections that matter (abstract,
results, conclusions) instead of the whole body — the D3.9 cost control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.ingestion.extractors import EXTRACTORS, extract, html_to_text

# Read methods (recorded on the Document + manifest for honesty about *how* we read).
READ_PDF = "pdf"
READ_HTML = "html"
READ_TEXT = "text"
READ_NONE = "none"  # downloaded but no extractable text (scanned/empty)

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
    """A normalized, source-agnostic document (§5e)."""

    source_id: str
    title: str = ""
    url: str = ""
    content_type: str = ""
    text: str = ""
    sections: list[Section] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    read_method: str = READ_NONE
    truncated: bool = False

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


def _read_text_from_path(path: Path, content_type: str) -> tuple[str | None, str]:
    """Return (text, read_method) for an acquired file, format-aware.

    Prefers the extension-keyed extractors; falls back to content-type sniffing when a
    file was saved without a helpful suffix (e.g. an HTML page fetched at a bare URL).
    """
    suffix = path.suffix.lower()
    ct = (content_type or "").lower()
    if suffix in EXTRACTORS:
        text = extract(path)
        method = READ_PDF if suffix == ".pdf" else (
            READ_HTML if suffix in (".html", ".htm") else READ_TEXT
        )
        return text, method
    if "html" in ct or "xml" in ct:
        return html_to_text(path.read_text(encoding="utf-8", errors="replace")), READ_HTML
    # Unknown/plain: best-effort decode as text.
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None, READ_NONE
    return (raw or None), (READ_TEXT if raw else READ_NONE)


class Reader:
    """Turns an acquired file into a normalized :class:`Document`."""

    def __init__(self, *, max_chars: int | None = 200_000) -> None:
        # A generous cap so a pathological document can't blow up memory; the section
        # scoping in Step 4 does the real cost control (D3.9).
        self._max_chars = max_chars

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
        text, method = _read_text_from_path(path, content_type)
        return self._build(source_id, title, url, content_type, text, method, metadata)

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
    ) -> Document:
        """Normalize already-extracted text (e.g. an abstract, a transcript)."""
        return self._build(source_id, title, url, content_type, text, read_method, metadata)

    def _build(
        self,
        source_id: str,
        title: str,
        url: str,
        content_type: str,
        text: str | None,
        method: str,
        metadata: dict[str, Any] | None,
    ) -> Document:
        text = (text or "").strip()
        truncated = False
        if self._max_chars is not None and len(text) > self._max_chars:
            text = text[: self._max_chars]
            truncated = True
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
        )
