"""Policy-gated YouTube media obtain (Browser / SourceFetch BA.v2).

Produces Video/Audio **bytes** for ``SourceFetcher.youtube_media`` when the operator
explicitly enables obtain **and** ``yt-dlp`` (or configured binary) is on PATH.

Does **not** bypass robots — callers must gate with ``FetchClient.allowed`` first
(SourceFetcher already does). Never raises; returns outcome dicts.

Incomplete yt-dlp leftovers (``*.part``, ``*.ytdl``, …) are **never** registered as Assets.
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

# yt-dlp / downloader temp suffixes — never treat as finished media.
_INCOMPLETE_SUFFIXES = (
    ".part",
    ".ytdl",
    ".temp",
    ".tmp",
    ".download",
)


class YoutubeMediaObtain:
    """Injectable ``youtube_fetch`` for SourceFetcher (BA.v2)."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        binary: str = "yt-dlp",
        # Prefer compact audio for STT; fall back to progressive A/V.
        format_spec: str = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        timeout: float = 0.0,
        max_bytes: int = 209_715_200,  # 200 MiB — long lectures need headroom
        run: Any | None = None,
        which: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._binary = (binary or "yt-dlp").strip() or "yt-dlp"
        self._format = format_spec or "bestaudio[ext=m4a]/bestaudio/best"
        # 0 / None ⇒ no wall-clock timeout (operator preference for long YouTube downloads).
        self._timeout = None if timeout is None or float(timeout) <= 0 else float(timeout)
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
            # Do not use --max-filesize mid-download (leaves *.part that look like success).
            # Enforce size after a completed file is written.
            cmd = [
                self._binary,
                "--no-playlist",
                "--no-warnings",
                "-f",
                self._format,
                "-o",
                out_tmpl,
                "--newline",
                src,
            ]
            try:
                run_kwargs: dict[str, Any] = {
                    "capture_output": True,
                    "text": True,
                    "check": False,
                }
                if self._timeout is not None:
                    run_kwargs["timeout"] = self._timeout
                proc = self._run(cmd, **run_kwargs)
            except subprocess.TimeoutExpired:
                return {
                    "outcome": "error",
                    "reason": (
                        f"media obtain timed out after {self._timeout}s "
                        "(set plugins.youtube.media_obtain_timeout: 0 to wait indefinitely)"
                    ),
                    "reason_code": "timeout",
                }
            except OSError as exc:
                return {
                    "outcome": "error",
                    "reason": str(exc),
                    "reason_code": "spawn_failed",
                }

            err = (getattr(proc, "stderr", None) or getattr(proc, "stdout", None) or "").strip()
            if getattr(proc, "returncode", 1) != 0:
                return {
                    "outcome": "error",
                    "reason": err or f"{self._binary} exit {getattr(proc, 'returncode', '?')}",
                    "reason_code": "obtain_failed",
                }

            finished = [
                p
                for p in Path(tmp).iterdir()
                if p.is_file() and not _is_incomplete(p)
            ]
            incomplete = [
                p
                for p in Path(tmp).iterdir()
                if p.is_file() and _is_incomplete(p)
            ]
            if not finished:
                if incomplete:
                    biggest = max(incomplete, key=lambda p: p.stat().st_size)
                    return {
                        "outcome": "error",
                        "reason": (
                            f"incomplete download only ({biggest.name}, "
                            f"{biggest.stat().st_size} B) — refused to register Asset"
                        ),
                        "reason_code": "incomplete_download",
                        "bytes_read": biggest.stat().st_size,
                    }
                return {
                    "outcome": "empty",
                    "reason": "obtain produced no file",
                    "reason_code": "empty",
                }

            path = max(finished, key=lambda p: p.stat().st_size)
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
            # bestaudio often yields .webm / .m4a; treat as audio for the STT path.
            if kind == ASSET_KIND_VIDEO and filename.lower().endswith((".webm", ".m4a", ".opus")):
                if "audio" in (self._format or "").lower() or "bestaudio" in (self._format or ""):
                    kind = ASSET_KIND_AUDIO
            if filename.lower().endswith((".m4a", ".mp3", ".opus", ".ogg", ".wav", ".flac")):
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
                "content_type": content_type_for(filename) or (
                    "audio/mp4" if kind == ASSET_KIND_AUDIO else "video/webm"
                ),
                "bytes_read": len(content),
                "reason_code": "asset_produced",
            }


def _is_incomplete(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suf) for suf in _INCOMPLETE_SUFFIXES)
