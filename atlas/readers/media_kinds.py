"""Media asset kind conventions (Media Reader Family · M.3 / MD2).

Media is **non-special**: these are ordinary Asset Store ``kind`` strings. Provider-specific
logic must stop at registration; after that everything is ``Asset → Reader → Artifact``.
"""

from __future__ import annotations

from pathlib import Path

ASSET_KIND_VIDEO = "video"
ASSET_KIND_AUDIO = "audio"
ASSET_KIND_TRANSCRIPT = "transcript"

MEDIA_ASSET_KINDS = frozenset({ASSET_KIND_VIDEO, ASSET_KIND_AUDIO, ASSET_KIND_TRANSCRIPT})

_VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"})
_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"})
_TRANSCRIPT_EXTENSIONS = frozenset({".vtt", ".srt", ".txt", ".json"})  # .json = sidecar meta

_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".vtt": "text/vtt",
    ".srt": "application/x-subrip",
    ".txt": "text/plain",
    ".json": "application/json",
}


def infer_media_kind(filename: str | Path | None) -> str | None:
    """Map a filename extension → ``video`` / ``audio`` / ``transcript``, or ``None``."""
    if not filename:
        return None
    suffix = Path(str(filename)).suffix.lower()
    if suffix in _VIDEO_EXTENSIONS:
        return ASSET_KIND_VIDEO
    if suffix in _AUDIO_EXTENSIONS:
        return ASSET_KIND_AUDIO
    if suffix in _TRANSCRIPT_EXTENSIONS:
        return ASSET_KIND_TRANSCRIPT
    return None


def content_type_for(filename: str | Path | None) -> str | None:
    if not filename:
        return None
    return _CONTENT_TYPES.get(Path(str(filename)).suffix.lower())


def media_extensions(*, kind: str | None = None) -> list[str]:
    """Extensions this Media Reader family understands (optionally filtered by kind)."""
    if kind == ASSET_KIND_VIDEO:
        return sorted(_VIDEO_EXTENSIONS)
    if kind == ASSET_KIND_AUDIO:
        return sorted(_AUDIO_EXTENSIONS)
    if kind == ASSET_KIND_TRANSCRIPT:
        return sorted(_TRANSCRIPT_EXTENSIONS)
    return sorted(_VIDEO_EXTENSIONS | _AUDIO_EXTENSIONS | _TRANSCRIPT_EXTENSIONS)
