"""VideoFramesReader (OI-M6) — video Asset → frame artifact (+ optional OCR text)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.frames.engine import CAPABILITY_GAP, FRAME_OK, VideoFrameClient
from atlas.readers.media_kinds import ASSET_KIND_VIDEO

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

VIDEO_FRAMES_READER_ID = "video_frames"
VIDEO_FRAMES_READER_VERSION = "1.0.0"


class VideoFramesReader:
    id = VIDEO_FRAMES_READER_ID
    VERSION = VIDEO_FRAMES_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        client: VideoFrameClient,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts
        self._client = client
        self._logger = logger or logging.getLogger("atlas.readers.video_frames")

    def supported_extensions(self) -> list[str]:
        return [".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"]

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
        at_seconds: float = 1.0,
    ) -> dict[str, Any]:
        version = int(asset_version or 1)
        if not force and self._artifacts is not None:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None:
                return cached
        asset_row = self._assets.get(asset_id) if hasattr(self._assets, "get") else None
        kind = str((asset_row or {}).get("kind") or "")
        filename = filename or "video.mp4"
        base = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "artifact_kind": "video_frame",
            "filename": filename,
            "strategy": "video_frame_extract",
        }
        if kind and kind != ASSET_KIND_VIDEO:
            art = {
                **base,
                "outcome": "unsupported",
                "reason": f"video frames expect kind=video, got {kind!r}",
            }
            self._put(asset_id, version, art)
            return art

        data = self._assets.get_bytes(asset_id, version)
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".mp4") as tmp:
            tmp.write(data)
            tmp.flush()
            result = self._client.extract_frame(tmp.name, at_seconds=at_seconds)

        art = {
            **base,
            "outcome": result.get("outcome"),
            "capability_gap": result.get("capability_gap"),
            "reason": result.get("reason"),
            "ocr_text": result.get("ocr_text") or "",
            "chars": len(result.get("ocr_text") or ""),
            "at_seconds": result.get("at_seconds"),
            "has_image": bool(result.get("image_bytes")),
        }
        if result.get("outcome") == FRAME_OK and not art.get("capability_gap"):
            art["capability_gap"] = None
        elif not art.get("capability_gap") and art["outcome"] != FRAME_OK:
            art["capability_gap"] = CAPABILITY_GAP
        self._put(asset_id, version, art)
        return art

    def _put(self, asset_id: str, version: int, art: dict[str, Any]) -> None:
        if self._artifacts is None:
            return
        try:
            self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("video_frames cache skipped: %s", exc)
