"""OCR client + Tesseract engine (S20c).

``OCRClient`` reads text from an image file through an injectable ``OCREngine`` (default
``TesseractEngine``, backed by Pillow + pytesseract + the system ``tesseract`` binary).
The engine seam keeps the client fully hermetic in tests (inject a fake engine) while
the real engine **degrades gracefully**: if any dependency is missing it reports
``unavailable`` rather than raising, so a missing system package never crashes a job.

Sources are resolved under and confined to a sandbox root (like the filesystem plugin).
Outcomes are honest and never raise (R2/R3):
  ``ok`` | ``empty`` (no text found) | ``unsupported`` (not a readable image) |
  ``unavailable`` (engine/deps missing) | ``error``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

OCR_OK = "ok"
OCR_EMPTY = "empty"
OCR_UNSUPPORTED = "unsupported"
OCR_UNAVAILABLE = "unavailable"
OCR_ERROR = "error"

# Image suffixes the client will attempt (the engine has the final say).
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
)


class OCRUnavailable(Exception):
    """The engine or its dependencies are not installed → unavailable."""


class OCRUnsupported(Exception):
    """The file is not a readable image → unsupported."""


class OCREngineError(Exception):
    """The engine failed to process a valid image → error."""


class OCREngine(Protocol):
    name: str

    def available(self) -> bool:
        """True iff the engine can run (deps + binary present)."""
        ...

    def image_to_text(self, path: str, *, lang: str) -> str:
        """Return recognised text. Raise OCRUnavailable/OCRUnsupported/OCREngineError."""
        ...


class TesseractEngine:
    """Default engine: Pillow opens the image, pytesseract shells to ``tesseract``.

    All imports are lazy so importing this module never requires the optional deps;
    a missing dependency (or system binary) surfaces as ``OCRUnavailable``.
    """

    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401

            pytesseract.get_tesseract_version()
            return True
        except Exception:  # noqa: BLE001 - any failure means "not usable"
            return False

    def image_to_text(self, path: str, *, lang: str) -> str:
        try:
            import pytesseract
            from PIL import Image, UnidentifiedImageError
        except Exception as exc:  # noqa: BLE001 - deps missing
            raise OCRUnavailable(f"OCR dependencies unavailable: {exc}") from exc

        try:
            with Image.open(path) as img:
                img.load()
                recognised = pytesseract.image_to_string(img, lang=lang)
        except UnidentifiedImageError as exc:
            raise OCRUnsupported(f"not a readable image: {exc}") from exc
        except pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
            raise OCRUnavailable(f"tesseract binary not found: {exc}") from exc
        except OCRUnsupported:
            raise
        except Exception as exc:  # noqa: BLE001 - runtime OCR failure
            # A missing language pack / tesseract runtime error is reported honestly.
            if "tesseract" in str(exc).lower():
                raise OCRUnavailable(str(exc)) from exc
            raise OCREngineError(str(exc)) from exc
        return recognised


class OCRClient:
    def __init__(
        self,
        engine: OCREngine,
        root: Path | str,
        *,
        max_bytes: int = 10_485_760,
        default_lang: str = "eng",
        logger: logging.Logger | None = None,
    ) -> None:
        self._engine = engine
        self._root = Path(root).resolve()
        self._max_bytes = max_bytes
        self._default_lang = default_lang
        self._logger = logger or logging.getLogger("atlas.ocr")

    def image(self, path: str, *, lang: str | None = None) -> dict[str, Any]:
        lang = lang or self._default_lang
        base = {"path": path, "lang": lang, "engine": self._engine.name}
        try:
            target = self._resolve(path)
        except ValueError as exc:
            return {**base, "outcome": OCR_UNAVAILABLE, "reason": str(exc)}
        if not target.is_file():
            return {**base, "outcome": OCR_UNAVAILABLE,
                    "reason": f"image not found: {path}"}
        if target.suffix.lower() not in IMAGE_SUFFIXES:
            return {**base, "outcome": OCR_UNSUPPORTED,
                    "reason": f"not an image file: {target.suffix or '(no suffix)'}"}
        size = target.stat().st_size
        if size > self._max_bytes:
            return {**base, "outcome": OCR_UNSUPPORTED,
                    "reason": f"image too large ({size} > {self._max_bytes} bytes)"}
        # The concrete default engine can cheaply prove its dependencies are
        # missing. Injectable engines may deliberately report degraded health
        # while still serving a call, so preserve that seam.
        if isinstance(self._engine, TesseractEngine) and not self._engine.available():
            return {
                **base,
                "outcome": OCR_UNAVAILABLE,
                "reason": f"{self._engine.name} engine unavailable",
            }
        try:
            text = self._engine.image_to_text(str(target), lang=lang)
        except OCRUnavailable as exc:
            return {**base, "outcome": OCR_UNAVAILABLE, "reason": str(exc)}
        except OCRUnsupported as exc:
            return {**base, "outcome": OCR_UNSUPPORTED, "reason": str(exc)}
        except OCREngineError as exc:
            return {**base, "outcome": OCR_ERROR, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a bad engine must not crash the caller
            self._logger.exception("ocr engine crashed")
            return {**base, "outcome": OCR_ERROR, "reason": str(exc)}
        text = (text or "").strip()
        return {
            **base,
            "outcome": OCR_OK if text else OCR_EMPTY,
            "text": text,
            "chars": len(text),
        }

    def _resolve(self, path: str) -> Path:
        candidate = (self._root / path).resolve()
        if candidate != self._root and not candidate.is_relative_to(self._root):
            raise ValueError(f"path escapes OCR sandbox root: {path}")
        return candidate
