"""Text extractors for the filesystem ingestion source (ADR-0033).

Each extractor turns a file into plain text. New formats are additive: add a
function and register its extensions in ``EXTRACTORS``. Heavy parsers (pypdf,
BeautifulSoup) are imported lazily so a missing optional dependency only affects
its own file type.

``extract(path)`` returns the text, or ``None`` when the file has no usable text
(e.g. a scanned/image-only PDF), so the caller can skip it. Scanned PDFs are a
future OCRService concern.
"""

from __future__ import annotations

from pathlib import Path

CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
}


def content_type_for(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "text/plain")


def _extract_text(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def _extract_pdf(path: Path) -> str | None:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p.strip() for p in pages if p.strip()).strip()
    return text or None  # None => no text layer (scanned) -> skip for future OCR


def html_to_text(html: str) -> str | None:
    """Strip an HTML document down to readable plain text (script/style removed)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse blank lines and surrounding whitespace.
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line).strip()
    return cleaned or None


def _extract_html(path: Path) -> str | None:
    return html_to_text(path.read_text(encoding="utf-8", errors="replace"))


EXTRACTORS = {
    ".txt": _extract_text,
    ".md": _extract_text,
    ".pdf": _extract_pdf,
    ".html": _extract_html,
    ".htm": _extract_html,
}


def extract(path: Path) -> str | None:
    """Extract plain text from ``path`` by file type, or None if unsupported/empty."""
    extractor = EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        return None
    return extractor(path)
