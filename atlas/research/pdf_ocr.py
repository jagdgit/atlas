"""PDF page render + OCR fallback (Stage 3.2a / A32.3).

When a PDF has no usable text layer, Atlas renders pages (``pdftoppm`` when
available) and runs Tesseract OCR under operator bounds:

    ATLAS_RESOURCES_OCR_MAX_PAGES / OCR_MAX_MINUTES / OCR_DPI

Over-limit documents become ``partial`` with a clear failure code — never a silent
empty read and never a hard job failure. Missing binaries degrade honestly
(``ocr_unavailable``).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# Stable failure codes (A32.14).
CODE_OCR_UNAVAILABLE = "ocr_unavailable"
CODE_OCR_FAILED = "ocr_failed"
CODE_OCR_PARTIAL = "ocr_partial"
CODE_EMPTY_TEXT = "empty_text"
CODE_TIMEOUT = "timeout"

QUALITY_FULL = "full"
QUALITY_PARTIAL = "partial"
QUALITY_EMPTY = "empty"
QUALITY_ERROR = "error"

READ_OCR = "ocr"


class _ImageOCR(Protocol):
    def image_to_text(self, path: str, *, lang: str) -> str: ...

    def available(self) -> bool: ...


@dataclass
class PdfOcrResult:
    text: str = ""
    pages_ocrd: int = 0
    pages_total: int | None = None
    quality: str = QUALITY_EMPTY
    failure_code: str = ""
    failure_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    dpi: int = 300
    elapsed_s: float = 0.0
    reader_id: str = "pdf_ocr"

    def as_dict(self) -> dict[str, Any]:
        return {
            "chars": len(self.text),
            "pages_ocrd": self.pages_ocrd,
            "pages_total": self.pages_total,
            "quality": self.quality,
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "warnings": list(self.warnings),
            "dpi": self.dpi,
            "elapsed_s": round(self.elapsed_s, 3),
            "reader_id": self.reader_id,
        }


def ocr_pdf(
    path: str | Path,
    *,
    max_pages: int = 50,
    max_minutes: float = 15.0,
    dpi: int = 300,
    lang: str = "eng",
    engine: _ImageOCR | None = None,
    work_dir: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> PdfOcrResult:
    """OCR up to ``max_pages`` of ``path`` within ``max_minutes``.

    Deterministic page order (ascending). Stops cleanly on page/time ceilings.
    """
    log = logger or logging.getLogger("atlas.research.pdf_ocr")
    path = Path(path)
    started = time.monotonic()
    deadline = started + max(1.0, float(max_minutes) * 60.0)
    result = PdfOcrResult(dpi=dpi)

    if not path.is_file():
        result.quality = QUALITY_ERROR
        result.failure_code = CODE_OCR_FAILED
        result.failure_reason = f"PDF not found: {path}"
        return result

    if shutil.which("pdftoppm") is None:
        result.quality = QUALITY_EMPTY
        result.failure_code = CODE_OCR_UNAVAILABLE
        result.failure_reason = "pdftoppm not installed (poppler-utils); cannot render PDF pages"
        return result

    eng = engine
    if eng is None:
        try:
            from atlas.ocr.engine import TesseractEngine

            eng = TesseractEngine()
        except Exception as exc:  # noqa: BLE001
            result.quality = QUALITY_EMPTY
            result.failure_code = CODE_OCR_UNAVAILABLE
            result.failure_reason = f"OCR engine unavailable: {exc}"
            return result
    if not eng.available():
        result.quality = QUALITY_EMPTY
        result.failure_code = CODE_OCR_UNAVAILABLE
        result.failure_reason = "Tesseract OCR engine/dependencies not available"
        return result

    max_pages = max(1, int(max_pages))
    dpi = max(72, int(dpi))
    tmp_owned = work_dir is None
    root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="atlas_ocr_"))
    try:
        root.mkdir(parents=True, exist_ok=True)
        prefix = root / "page"
        cmd = [
            "pdftoppm",
            "-png",
            "-r",
            str(dpi),
            "-f",
            "1",
            "-l",
            str(max_pages),
            str(path),
            str(prefix),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(5.0, deadline - time.monotonic()),
                check=False,
            )
        except subprocess.TimeoutExpired:
            result.quality = QUALITY_PARTIAL if result.text else QUALITY_EMPTY
            result.failure_code = CODE_TIMEOUT
            result.failure_reason = f"PDF render timed out after {max_minutes} minutes"
            result.elapsed_s = time.monotonic() - started
            return result
        if proc.returncode != 0:
            result.quality = QUALITY_ERROR
            result.failure_code = CODE_OCR_FAILED
            err = (proc.stderr or proc.stdout or "").strip()[:300]
            result.failure_reason = f"pdftoppm failed: {err or proc.returncode}"
            result.elapsed_s = time.monotonic() - started
            return result

        pages = sorted(root.glob("page-*.png"))
        if not pages:
            # Some pdftoppm builds use page-1.png; also try page1.png
            pages = sorted(root.glob("page*.png"))
        result.pages_total = len(pages)
        if not pages:
            result.quality = QUALITY_EMPTY
            result.failure_code = CODE_EMPTY_TEXT
            result.failure_reason = "PDF rendered zero pages"
            result.elapsed_s = time.monotonic() - started
            return result

        chunks: list[str] = []
        hit_time = False
        for i, page in enumerate(pages[:max_pages], start=1):
            if time.monotonic() >= deadline:
                hit_time = True
                result.warnings.append(
                    f"OCR stopped at page {i - 1}/{len(pages)} (time budget {max_minutes} min)"
                )
                break
            try:
                text = (eng.image_to_text(str(page), lang=lang) or "").strip()
            except Exception as exc:  # noqa: BLE001 - per-page failure is partial, not fatal
                result.warnings.append(f"page {i} OCR failed: {exc}")
                log.debug("ocr page %s failed: %s", i, exc)
                continue
            if text:
                chunks.append(f"[page {i}]\n{text}")
            result.pages_ocrd = i

        result.text = "\n\n".join(chunks).strip()
        result.elapsed_s = time.monotonic() - started
        hit_page_cap = len(pages) >= max_pages and result.pages_total is not None
        # If pdftoppm was capped with -l, we can't know true total; treat reaching
        # max_pages as a soft partial signal when time didn't also stop us.
        if hit_time:
            result.quality = QUALITY_PARTIAL if result.text else QUALITY_EMPTY
            result.failure_code = CODE_TIMEOUT
            result.failure_reason = (
                result.failure_reason
                or f"OCR time budget ({max_minutes} min) reached; document partially read"
            )
        elif hit_page_cap and result.pages_ocrd >= max_pages:
            result.quality = QUALITY_PARTIAL if result.text else QUALITY_EMPTY
            result.failure_code = CODE_OCR_PARTIAL
            result.failure_reason = (
                f"OCR page budget ({max_pages} pages) reached; document partially read"
            )
            result.warnings.append(result.failure_reason)
        elif result.text:
            result.quality = QUALITY_FULL
        else:
            result.quality = QUALITY_EMPTY
            result.failure_code = CODE_EMPTY_TEXT
            result.failure_reason = "OCR produced no extractable text"
        return result
    finally:
        if tmp_owned:
            # Best-effort cleanup of rendered pages.
            try:
                for p in root.glob("page*.png"):
                    p.unlink(missing_ok=True)
                root.rmdir()
            except OSError:
                pass
