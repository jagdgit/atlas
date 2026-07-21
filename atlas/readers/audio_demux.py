"""Audio demux Reader (Media Reader Family · M.4, constitution P8/P11).

``video Asset → AudioDemuxReader → audio Asset (+ demux artifact)``.

Uses an optional ffmpeg-backed ``demux`` callable (default: ``ffmpeg`` on PATH). When
ffmpeg is absent the reader reports ``capability_gap``-style ``outcome=unsupported``
with reason ``audio_demux unavailable`` — never crashes (P15). Stateless w.r.t. Knowledge.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from atlas.readers.media_kinds import ASSET_KIND_AUDIO, ASSET_KIND_VIDEO, content_type_for

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore
    from atlas.ingestion.acquire import AssetAcquirer

AUDIO_DEMUX_READER_ID = "audio_demux"
AUDIO_DEMUX_READER_VERSION = "1.0.0"

DemuxFn = Callable[[Path, Path], None]  # src video path → dst audio path


class AudioDemuxReader:
    """Demux audio from a video asset into a sibling audio asset + demux artifact."""

    id = AUDIO_DEMUX_READER_ID
    VERSION = AUDIO_DEMUX_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        acquirer: "AssetAcquirer | None" = None,
        demux: DemuxFn | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts
        self._acq = acquirer
        self._demux = demux  # None → default ffmpeg; inject for hermetic tests
        self._logger = logger or logging.getLogger("atlas.readers.audio_demux")

    def supported_extensions(self) -> list[str]:
        return [".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"]

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
            "artifact_kind": "audio_demux",
            "filename": filename,
        }
        if kind and kind != ASSET_KIND_VIDEO:
            art = {
                **base,
                "outcome": "unsupported",
                "reason": f"audio demux expects kind=video, got {kind!r}",
            }
            self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
            return art

        demux_fn = self._demux if self._demux is not None else _resolve_default_demux()
        if demux_fn is None:
            art = {
                **base,
                "outcome": "unsupported",
                "reason": "audio_demux unavailable (ffmpeg not installed)",
                "capability_gap": "audio_demux",
            }
            self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
            return art

        try:
            src = self._assets.path_of(asset_id, version)
        except Exception as exc:  # noqa: BLE001
            art = {**base, "outcome": "error", "reason": f"cannot resolve video path: {exc}"}
            self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
            return art

        with tempfile.TemporaryDirectory(prefix="atlas-demux-") as tmp:
            dst = Path(tmp) / "audio.wav"
            try:
                demux_fn(Path(src), dst)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("demux failed for %s: %s", asset_id, exc)
                art = {
                    **base,
                    "outcome": "error",
                    "reason": f"demux failed: {exc}",
                    "capability_gap": "audio_demux",
                }
                self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
                return art
            if not dst.exists() or dst.stat().st_size == 0:
                art = {
                    **base,
                    "outcome": "empty",
                    "reason": "demux produced no audio",
                }
                self._artifacts.put(asset_id, version, self.id, self.VERSION, art)
                return art
            audio_bytes = dst.read_bytes()

        audio_asset_id = None
        audio_asset_version = None
        if self._acq is not None:
            stem = Path(filename or "video").stem
            acquired = self._acq.acquire_bytes(
                audio_bytes,
                kind=ASSET_KIND_AUDIO,
                filename=f"{stem}.wav",
                content_type=content_type_for(".wav") or "audio/wav",
                metadata={
                    "filename": f"{stem}.wav",
                    "parent_asset_id": asset_id,
                    "parent_asset_version": version,
                    "derived_by": self.id,
                    "derived_by_version": self.VERSION,
                },
            )
            audio_asset_id = acquired.asset_id
            audio_asset_version = acquired.asset_version

        art = {
            **base,
            "outcome": "ok",
            "audio_asset_id": audio_asset_id,
            "audio_asset_version": audio_asset_version,
            "audio_bytes": len(audio_bytes),
            "audio_kind": ASSET_KIND_AUDIO,
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


def _resolve_default_demux() -> DemuxFn | None:
    if not shutil.which("ffmpeg"):
        return None
    return _default_ffmpeg_demux


def _default_ffmpeg_demux(src: Path, dst: Path) -> None:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("ffmpeg not found on PATH")
    proc = subprocess.run(
        [
            binary, "-y", "-i", str(src),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(dst),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"ffmpeg exit {proc.returncode}")
