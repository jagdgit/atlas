"""Video frame extraction (OI-M6) — sample frames for Image/OCR.

Default **off** / missing ffmpeg → P15 ``capability_gap: video_frame_extract``.
Injectable ``extract`` keeps CI hermetic (Fake writes a PNG; optional OCR text).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

FRAME_OK = "ok"
FRAME_UNAVAILABLE = "unavailable"
FRAME_UNSUPPORTED = "unsupported"
CAPABILITY_GAP = "video_frame_extract"

ExtractFn = Callable[[Path, Path], None]  # video path → image path


class VideoFrameClient:
    """Gate + optional extract/OCR composition for video → frame → text."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        extract: ExtractFn | None = None,
        ocr: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self._extract = extract
        self._ocr = ocr
        self._logger = logger or logging.getLogger("atlas.frames")

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._extract is not None:
            return True
        return shutil.which("ffmpeg") is not None

    def extract_frame(
        self, video_path: str | Path, *, at_seconds: float = 1.0
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "outcome": FRAME_UNAVAILABLE,
            "capability_gap": CAPABILITY_GAP,
            "image_bytes": None,
            "ocr_text": "",
            "reason": "",
            "at_seconds": at_seconds,
        }
        if not self.enabled:
            base["reason"] = "video_frame_extract disabled (set plugins.frames.enabled)"
            return base
        if not self.available():
            base["reason"] = "video_frame_extract unavailable (ffmpeg not installed)"
            return base

        src = Path(video_path)
        if not src.is_file():
            return {
                **base,
                "outcome": "error",
                "capability_gap": None,
                "reason": f"not a file: {src}",
            }

        try:
            with tempfile.TemporaryDirectory(prefix="atlas-frame-") as tmp:
                dst = Path(tmp) / "frame.png"
                if self._extract is not None:
                    self._extract(src, dst)
                else:
                    _ffmpeg_extract(src, dst, at_seconds=at_seconds)
                if not dst.is_file() or dst.stat().st_size <= 0:
                    return {
                        **base,
                        "outcome": FRAME_UNSUPPORTED,
                        "reason": "frame extract produced empty image",
                    }
                image_bytes = dst.read_bytes()
                ocr_text = ""
                if self._ocr is not None and hasattr(self._ocr, "image_to_text"):
                    try:
                        ocr_text = str(self._ocr.image_to_text(str(dst)) or "")
                    except Exception as exc:  # noqa: BLE001
                        self._logger.debug("frame OCR skipped: %s", exc)
                return {
                    "outcome": FRAME_OK,
                    "capability_gap": None,
                    "image_bytes": image_bytes,
                    "ocr_text": ocr_text,
                    "reason": None,
                    "at_seconds": at_seconds,
                }
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("frame extract failed: %s", exc)
            return {**base, "outcome": "error", "reason": str(exc)}


def _ffmpeg_extract(src: Path, dst: Path, *, at_seconds: float = 1.0) -> None:
    cmd = [
        "ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(src),
        "-frames:v", "1", str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
