"""Speaker diarization Reader (OI-M2) — enrich transcripts with ``segments[].speaker``.

Does not replace speech_to_text. When disabled/missing labels → P15 capability gap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.diarization.engine import CAPABILITY_GAP, DIA_OK, DiarizationClient

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

SPEAKER_DIARIZATION_READER_ID = "speaker_diarization"
SPEAKER_DIARIZATION_READER_VERSION = "1.0.0"


class SpeakerDiarizationReader:
    """Enrich a transcript artifact (or segments) with speaker labels."""

    id = SPEAKER_DIARIZATION_READER_ID
    VERSION = SPEAKER_DIARIZATION_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore | None",
        artifacts: Any,
        client: DiarizationClient,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts
        self._client = client
        self._logger = logger or logging.getLogger("atlas.readers.speaker_diarization")

    def supported_extensions(self) -> list[str]:
        return [".vtt", ".srt", ".txt", ".mp3", ".wav", ".mp4", ".mkv", ".webm"]

    def enrich(
        self,
        transcript: dict[str, Any],
        *,
        path: str | None = None,
        asset_id: str | None = None,
        asset_version: int | None = None,
    ) -> dict[str, Any]:
        """Return a diarized transcript artifact derived from an existing transcript dict."""
        text = str(transcript.get("text") or "")
        segments = list(transcript.get("segments") or [])
        result = self._client.diarize(path, segments=segments, text=text)
        out = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id or transcript.get("asset_id"),
            "asset_version": asset_version
            if asset_version is not None
            else transcript.get("asset_version"),
            "artifact_kind": "transcript",
            "strategy": "speaker_diarization",
            "outcome": result.get("outcome"),
            "text": result.get("text") or text,
            "segments": result.get("segments") or segments,
            "speakers": result.get("speakers") or [],
            "model": result.get("model"),
            "model_versions": {"speaker_diarization": result.get("model")},
            "capability_gap": result.get("capability_gap"),
            "reason": result.get("reason"),
            "evidence_level": 1,
            "source_transcript_strategy": transcript.get("strategy"),
        }
        if out["outcome"] == DIA_OK and self._artifacts is not None and out.get("asset_id"):
            try:
                self._artifacts.put(
                    str(out["asset_id"]),
                    int(out.get("asset_version") or 1),
                    self.id,
                    self.VERSION,
                    out,
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("diarization artifact cache skipped: %s", exc)
        return out

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        segments: list[dict[str, Any]] | None = None,
        text: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        """Diarize provided segments/text (Asset path reserved for future ML engines)."""
        version = asset_version or 1
        if not force and self._artifacts is not None:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None and cached.get("outcome") == DIA_OK:
                return cached
        return self.enrich(
            {
                "text": text,
                "segments": list(segments or []),
                "asset_id": asset_id,
                "asset_version": version,
                "filename": filename,
            },
            asset_id=asset_id,
            asset_version=version,
        )
