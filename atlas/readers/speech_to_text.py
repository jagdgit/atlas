"""Speech-to-text Reader (Media Reader Family · M.5, constitution P8/P11/P15).

``audio|video Asset → SpeechToTextReader → transcript artifact`` via the optional
``speech_to_text`` capability (Whisper by default). Stateless w.r.t. Knowledge.
Model/version stamped on the artifact (P9); evidence L1. Missing/disabled →
``capability_gap: speech_to_text`` (never fabricates speech).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.readers.media_kinds import ASSET_KIND_AUDIO, ASSET_KIND_VIDEO
from atlas.speech.engine import CAPABILITY_GAP, STT_OK, SpeechClient

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

SPEECH_TO_TEXT_READER_ID = "speech_to_text"
SPEECH_TO_TEXT_READER_VERSION = "1.0.0"


class SpeechToTextReader:
    """Read an audio/video asset → cached transcript artifact via SpeechClient."""

    id = SPEECH_TO_TEXT_READER_ID
    VERSION = SPEECH_TO_TEXT_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        client: SpeechClient,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts
        self._client = client
        self._logger = logger or logging.getLogger("atlas.readers.speech_to_text")

    def supported_extensions(self) -> list[str]:
        return [
            ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus",
            ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v",
        ]

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        version = self._resolve_version(asset_id, asset_version)
        if not force:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None:
                return cached

        asset_row = self._assets.get(asset_id) if hasattr(self._assets, "get") else None
        kind = str((asset_row or {}).get("kind") or "")
        filename = filename or self._filename(asset_id, version)
        base = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "artifact_kind": "transcript",
            "strategy": "speech_to_text",
            "filename": filename,
            "evidence_level": 1,
            "kind": kind or None,
        }

        if kind and kind not in (ASSET_KIND_AUDIO, ASSET_KIND_VIDEO):
            art = {
                **base,
                "outcome": "unsupported",
                "text": "",
                "segments": [],
                "reason": f"speech_to_text expects audio/video, got {kind!r}",
                "capability_gap": CAPABILITY_GAP,
            }
            self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
            return art

        try:
            path = self._assets.path_of(asset_id, version)
        except Exception as exc:  # noqa: BLE001
            art = {
                **base,
                "outcome": "error",
                "text": "",
                "segments": [],
                "reason": f"cannot resolve media path: {exc}",
                "capability_gap": CAPABILITY_GAP,
            }
            self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
            return art

        result = self._client.transcribe(path)
        art = {
            **base,
            "outcome": result.get("outcome"),
            "text": result.get("text") or "",
            "segments": result.get("segments") or [],
            "char_count": result.get("char_count") or len(result.get("text") or ""),
            "reason": result.get("reason"),
            "model": result.get("model"),
            "model_versions": {"speech_to_text": result.get("model")},
            "language": result.get("language"),
            "engine": result.get("engine"),
            "capability_gap": (
                None if result.get("outcome") == STT_OK else (result.get("capability_gap") or CAPABILITY_GAP)
            ),
        }
        self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
        return art

    def _resolve_version(self, asset_id: str, asset_version: int | None) -> int:
        if asset_version is not None:
            return int(asset_version)
        versions = self._assets.versions(asset_id)
        if not versions:
            raise FileNotFoundError(f"no versions for asset {asset_id}")
        return int(versions[-1]["version"])

    def _filename(self, asset_id: str, version: int) -> str | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) != version:
                continue
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if meta.get("filename"):
                return str(meta["filename"])
        return None
