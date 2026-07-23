"""Policy-gated YouTube media obtain (Browser / SourceFetch BA.v2).

Produces Video/Audio **bytes** for ``SourceFetcher.youtube_media`` when the operator
explicitly enables obtain **and** ``yt-dlp`` (or configured binary) is on PATH.

Does **not** bypass robots — callers must gate with ``FetchClient.allowed`` first
(SourceFetcher already does). Never raises; returns outcome dicts.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from atlas.readers.media_kinds import (
    ASSET_KIND_AUDIO,
    ASSET_KIND_VIDEO,
    content_type_for,
    infer_media_kind,
)


class YoutubeMediaObtain:
    """Injectable ``youtube_fetch`` for SourceFetcher (BA.v2)."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        binary: str = "yt-dlp",
        # Prefer audio for STT; fall back to progressive video.
        format_spec: str = "bestaudio/best",
        timeout: float = 300.0,
        max_bytes: int = 52_428_800,
        run: Any | None = None,
        which: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._binary = (binary or "yt-dlp").strip() or "yt-dlp"
        self._format = format_spec or "bestaudio/best"
        self._timeout = float(timeout)
        self._max_bytes = int(max_bytes)
        self._run = run or subprocess.run
        self._which = which or shutil.which
        self._logger = logger or logging.getLogger("atlas.ingestion.youtube_media_obtain")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def available(self) -> bool:
        return bool(self._which(self._binary))

    @property
    def configured(self) -> bool:
        """Ready to run as an automatic strategy."""
        return self._enabled and self.available()

    def readiness_status(self) -> str:
        """Capability matrix status for ``media_obtain``."""
        if not self._enabled:
            return "not_configured"
        if not self.available():
            return "missing"
        return "ready"

    def fetch(self, url: str) -> dict[str, Any]:
        """Download media bytes for ``url``. Never raises."""
        if not self._enabled:
            return {
                "outcome": "blocked",
                "reason": "youtube media obtain disabled (set plugins.youtube.media_obtain_enabled)",
                "reason_code": "not_configured",
            }
        if not self.available():
            return {
                "outcome": "unsupported",
                "reason": f"{self._binary} not found on PATH",
                "reason_code": "binary_missing",
            }

        src = (url or "").strip()
        if not src:
            return {
                "outcome": "error",
                "reason": "empty url",
                "reason_code": "invalid_source",
            }

        with tempfile.TemporaryDirectory(prefix="atlas-yt-obtain-") as tmp:
            out_tmpl = str(Path(tmp) / "media.%(ext)s")
            cmd = [
                self._binary,
                "--no-playlist",
                "--quiet",
                "--no-warnings",
                "-f",
                self._format,
                "-o",
                out_tmpl,
                "--max-filesize",
                str(self._max_bytes),
                src,
            ]
            try:
                proc = self._run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {
                    "outcome": "error",
                    "reason": f"media obtain timed out after {self._timeout}s",
                    "reason_code": "timeout",
                }
            except OSError as exc:
                return {
                    "outcome": "error",
                    "reason": str(exc),
                    "reason_code": "spawn_failed",
                }

            if getattr(proc, "returncode", 1) != 0:
                err = (getattr(proc, "stderr", None) or getattr(proc, "stdout", None) or "").strip()
                return {
                    "outcome": "error",
                    "reason": err or f"{self._binary} exit {getattr(proc, 'returncode', '?')}",
                    "reason_code": "obtain_failed",
                }

            files = [p for p in Path(tmp).iterdir() if p.is_file()]
            if not files:
                return {
                    "outcome": "empty",
                    "reason": "obtain produced no file",
                    "reason_code": "empty",
                }
            path = max(files, key=lambda p: p.stat().st_size)
            size = path.stat().st_size
            if size <= 0:
                return {
                    "outcome": "empty",
                    "reason": "obtain produced empty file",
                    "reason_code": "empty",
                }
            if size > self._max_bytes:
                return {
                    "outcome": "error",
                    "reason": f"body exceeds max_bytes ({self._max_bytes})",
                    "reason_code": "too_large",
                    "bytes_read": size,
                }
            try:
                content = path.read_bytes()
            except OSError as exc:
                return {
                    "outcome": "error",
                    "reason": str(exc),
                    "reason_code": "read_failed",
                }

            filename = path.name
            kind = infer_media_kind(filename) or ASSET_KIND_VIDEO
            # bestaudio often yields .webm; treat as audio for the STT path.
            if kind == ASSET_KIND_VIDEO and filename.lower().endswith(".webm"):
                if "audio" in (self._format or "").lower() or self._format.startswith("bestaudio"):
                    kind = ASSET_KIND_AUDIO
            self._logger.info(
                "youtube media obtain ok bytes=%s kind=%s file=%s",
                len(content),
                kind,
                filename,
            )
            return {
                "outcome": "ok",
                "content": content,
                "filename": filename,
                "kind": kind,
                "content_type": content_type_for(filename),
                "bytes_read": len(content),
                "reason_code": "asset_produced",
            }
