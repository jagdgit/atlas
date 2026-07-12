"""OCR plugin (S20c): extract text from an image file.

Exposes one tool (registered as the ``ocr`` capability):
    ocr.image(path, lang=?)  -> {"outcome", "text", "chars", "lang", "engine", ...}

Backed by an injectable engine (default Tesseract). **Degrades gracefully**: if the OCR
engine or its system dependencies are missing, calls return an ``unavailable`` outcome
rather than raising (R2/R3). Sources are confined to a sandbox root.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.ocr.engine import OCRClient, TesseractEngine
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class OCRPlugin(BasePlugin):
    name = "ocr"
    version = "0.1.0"

    def __init__(self, client: OCRClient, *, logger: logging.Logger | None = None) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.ocr")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_OCR, OCRCapability

        kernel.capabilities.register(
            CAP_OCR, self, contract=OCRCapability, kind="plugin"
        )
        kernel.tools.register(
            "ocr.image", self.image,
            description="Extract text from an image file (screenshot, photo, scan).",
            params={
                "path": "image path under the OCR sandbox root",
                "lang": "tesseract language code (default 'eng')",
            },
            plugin=self.name,
        )

    # --- capability -----------------------------------------------------
    def image(self, path: str, lang: str | None = None) -> dict[str, Any]:
        return self._client.image(path, lang=lang)

    def health_check(self) -> HealthStatus:
        engine = getattr(self._client, "_engine", None)
        available = bool(engine and engine.available())
        return HealthStatus(
            healthy=True,  # a missing OCR backend is a degraded, not failed, state
            detail=("ocr engine ready" if available
                    else "ocr engine unavailable (tesseract not installed)"),
            data={"available": available},
        )


def build(config: "AtlasConfig") -> OCRPlugin:
    ocr = config.plugins.ocr
    root = ocr.root or config.paths.documents
    client = OCRClient(
        TesseractEngine(), root, max_bytes=ocr.max_bytes, default_lang=ocr.lang
    )
    return OCRPlugin(client)
