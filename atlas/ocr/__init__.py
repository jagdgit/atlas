"""Optical Character Recognition (Stage 2, S20c).

Extracts text from **images** (and scanned material) so Atlas can read a screenshot,
photo, or scanned page — completing the Document Reader story (S13a noted scanned PDFs
as "future OCR"). Built on an injectable ``OCREngine`` seam: the default
``TesseractEngine`` degrades **gracefully** (reports ``unavailable``, never crashes) when
Pillow/pytesseract or the system ``tesseract`` binary are absent, and tests inject a
fake engine for hermetic coverage. Sources are confined to a sandbox root; every
operation returns a structured outcome and **never raises** (R2/R3).
"""

from __future__ import annotations

from atlas.ocr.engine import (
    OCR_EMPTY,
    OCR_ERROR,
    OCR_OK,
    OCR_UNAVAILABLE,
    OCR_UNSUPPORTED,
    OCRClient,
    OCREngine,
    OCREngineError,
    OCRUnavailable,
    OCRUnsupported,
    TesseractEngine,
)

__all__ = [
    "OCRClient",
    "OCREngine",
    "TesseractEngine",
    "OCREngineError",
    "OCRUnavailable",
    "OCRUnsupported",
    "OCR_OK",
    "OCR_EMPTY",
    "OCR_UNSUPPORTED",
    "OCR_UNAVAILABLE",
    "OCR_ERROR",
]
