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

import csv
import json
from pathlib import Path

CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".json": "application/json",
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


def _extract_docx(path: Path) -> str | None:
    """Word document → paragraph text + flattened table cells (python-docx)."""
    from docx import Document

    doc = Document(str(path))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts).strip()
    return text or None


def _extract_pptx(path: Path) -> str | None:
    """Presentation → text of every shape on every slide (python-pptx)."""
    from pptx import Presentation

    prs = Presentation(str(path))
    parts: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        slide_parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in para.runs).strip()
                    if line:
                        slide_parts.append(line)
        if slide_parts:
            parts.append(f"# Slide {i}\n" + "\n".join(slide_parts))
    text = "\n\n".join(parts).strip()
    return text or None


def _extract_xlsx(path: Path) -> str | None:
    """Spreadsheet → per-sheet, tab-separated rows (openpyxl, values only)."""
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    try:
        for ws in wb.worksheets:
            rows: list[str] = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    rows.append("\t".join(cells).rstrip())
            if rows:
                parts.append(f"# Sheet: {ws.title}\n" + "\n".join(rows))
    finally:
        wb.close()
    text = "\n\n".join(parts).strip()
    return text or None


def _extract_csv(path: Path) -> str | None:
    """CSV → tab-separated rows (dialect-sniffed, robust to odd delimiters)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        return None
    try:
        dialect = csv.Sniffer().sniff(raw[:4096])
    except csv.Error:
        dialect = csv.excel
    rows = ["\t".join(row) for row in csv.reader(raw.splitlines(), dialect)]
    text = "\n".join(r for r in rows if r.strip()).strip()
    return text or None


def _extract_json(path: Path) -> str | None:
    """JSON → pretty-printed text (falls back to raw if it doesn't parse)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw.strip() or None
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False).strip() or None


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
    ".docx": _extract_docx,
    ".pptx": _extract_pptx,
    ".xlsx": _extract_xlsx,
    ".csv": _extract_csv,
    ".json": _extract_json,
}


def supported_extensions() -> list[str]:
    """Sorted list of file extensions with a registered extractor."""
    return sorted(EXTRACTORS)


def extract(path: Path) -> str | None:
    """Extract plain text from ``path`` by file type, or None if unsupported/empty."""
    extractor = EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        return None
    return extractor(path)
