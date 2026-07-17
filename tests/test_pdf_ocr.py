"""Tests for PDF OCR fallback and Document quality contract (Stage 3.2a)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from atlas.research.pdf_ocr import (
    CODE_OCR_PARTIAL,
    CODE_OCR_UNAVAILABLE,
    QUALITY_FULL,
    QUALITY_PARTIAL,
    ocr_pdf,
)
from atlas.research.reader import (
    QUALITY_EMPTY,
    READ_OCR,
    READER_PDF_OCR,
    Reader,
)


class FakeOCREngine:
    name = "fake"

    def __init__(self, texts: dict[str, str] | None = None, *, available: bool = True):
        self._texts = texts or {}
        self._available = available
        self.calls: list[str] = []

    def available(self) -> bool:
        return self._available

    def image_to_text(self, path: str, *, lang: str) -> str:
        self.calls.append(path)
        # Return text keyed by basename, else a default page string.
        name = Path(path).name
        return self._texts.get(name, f"soiling loss is 0.35 percent on {name}")


def _empty_pdf(path: Path, pages: int = 2) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_ocr_pdf_unavailable_without_engine(tmp_path, monkeypatch):
    pdf = _empty_pdf(tmp_path / "a.pdf")
    eng = FakeOCREngine(available=False)
    res = ocr_pdf(pdf, engine=eng, work_dir=tmp_path / "ocr")
    assert res.failure_code == CODE_OCR_UNAVAILABLE
    assert not res.text


def test_ocr_pdf_with_fake_engine_and_pdftoppm(tmp_path):
    pdf = _empty_pdf(tmp_path / "scan.pdf", pages=2)
    eng = FakeOCREngine()
    res = ocr_pdf(
        pdf,
        engine=eng,
        max_pages=50,
        max_minutes=5,
        dpi=72,
        work_dir=tmp_path / "ocr",
    )
    if res.failure_code == CODE_OCR_UNAVAILABLE:
        # Environment without pdftoppm — still an honest failure, not silent.
        assert "pdftoppm" in (res.failure_reason or "")
        return
    assert res.text
    assert res.quality in (QUALITY_FULL, QUALITY_PARTIAL)
    assert res.pages_ocrd >= 1
    assert eng.calls


def test_ocr_respects_page_budget(tmp_path):
    pdf = _empty_pdf(tmp_path / "long.pdf", pages=3)
    eng = FakeOCREngine()
    res = ocr_pdf(
        pdf,
        engine=eng,
        max_pages=1,
        max_minutes=5,
        dpi=72,
        work_dir=tmp_path / "ocr",
    )
    if res.failure_code == CODE_OCR_UNAVAILABLE:
        return
    assert res.pages_ocrd <= 1
    if res.text:
        assert res.failure_code in ("", CODE_OCR_PARTIAL)
        assert res.quality in (QUALITY_FULL, QUALITY_PARTIAL)


def test_reader_pdf_ocr_fallback(tmp_path, monkeypatch):
    pdf = _empty_pdf(tmp_path / "blank.pdf")

    def fake_ocr(path, **kwargs):
        from atlas.research.pdf_ocr import PdfOcrResult

        return PdfOcrResult(
            text="Abstract\nSoiling loss is 0.4%/day.\n",
            pages_ocrd=1,
            quality=QUALITY_FULL,
            reader_id="pdf_ocr",
        )

    monkeypatch.setattr("atlas.research.reader.ocr_pdf", fake_ocr)
    doc = Reader(ocr_enabled=True).read_path(pdf, source_id="s1", content_type="application/pdf")
    assert doc.has_text
    assert doc.read_method == READ_OCR
    assert doc.reader_id == READER_PDF_OCR
    assert "0.4%" in doc.text
    assert doc.quality == QUALITY_FULL
    assert doc.format == "pdf"


def test_reader_surfaces_empty_when_ocr_unavailable(tmp_path, monkeypatch):
    pdf = _empty_pdf(tmp_path / "blank.pdf")

    def fake_ocr(path, **kwargs):
        from atlas.research.pdf_ocr import PdfOcrResult

        return PdfOcrResult(
            failure_code=CODE_OCR_UNAVAILABLE,
            failure_reason="tesseract missing",
            quality=QUALITY_EMPTY,
        )

    monkeypatch.setattr("atlas.research.reader.ocr_pdf", fake_ocr)
    doc = Reader().read_path(pdf, source_id="s1", content_type="application/pdf")
    assert not doc.has_text
    assert doc.failure_code == CODE_OCR_UNAVAILABLE
    assert "tesseract" in doc.failure_reason
    assert doc.quality == QUALITY_EMPTY
