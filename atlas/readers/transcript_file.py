"""Transcript-file Reader (Media Reader Family · M.4, constitution P8/P11).

``Asset → TranscriptFileReader → transcript artifact`` for operator-provided
``.vtt`` / ``.srt`` / ``.txt`` (and plain text). Stateless: reads bytes, returns an
artifact with ``text`` + optional ``segments[]``. No Knowledge writes (P11).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.readers.media_kinds import ASSET_KIND_TRANSCRIPT

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

TRANSCRIPT_FILE_READER_ID = "transcript_file"
TRANSCRIPT_FILE_READER_VERSION = "1.0.0"

_SUPPORTED = (".vtt", ".srt", ".txt")
_VTT_TS = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*"
    r"(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
)
_SRT_TS = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


class TranscriptFileReader:
    """Read a transcript asset → cached text/segments artifact (BB11)."""

    id = TRANSCRIPT_FILE_READER_ID
    VERSION = TRANSCRIPT_FILE_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts
        self._logger = logger or logging.getLogger("atlas.readers.transcript_file")

    def supported_extensions(self) -> list[str]:
        return list(_SUPPORTED)

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
        filename = filename or self._filename(asset_id, version)
        data = self._assets.get_bytes(asset_id, version)
        artifact = self._extract(data, filename, asset_id, version)
        self._artifacts.put(asset_id, version, self.id, self.VERSION, artifact)
        return artifact

    def _extract(
        self, data: bytes, filename: str | None, asset_id: str, version: int
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower() if filename else ""
        base = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "artifact_kind": "transcript",
            "extension": suffix,
            "content_type": "text/plain",
        }
        if suffix and suffix not in _SUPPORTED:
            return {
                **base,
                "outcome": "unsupported",
                "text": "",
                "segments": [],
                "reason": f"unsupported transcript format: {suffix}",
            }
        try:
            raw = data.decode("utf-8-sig", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {
                **base,
                "outcome": "error",
                "text": "",
                "segments": [],
                "reason": str(exc),
            }

        if suffix == ".vtt":
            text, segments = _parse_vtt(raw)
        elif suffix == ".srt":
            text, segments = _parse_srt(raw)
        else:
            text = raw.strip()
            segments = []

        if not text:
            return {
                **base,
                "outcome": "empty",
                "text": "",
                "segments": [],
                "reason": "transcript file had no extractable text",
            }
        return {
            **base,
            "outcome": "ok",
            "text": text,
            "segments": segments,
            "char_count": len(text),
            "kind": ASSET_KIND_TRANSCRIPT,
        }

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


def _parse_vtt(raw: str) -> tuple[str, list[dict[str, Any]]]:
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[dict[str, Any]] = []
    buf: list[str] = []
    start = end = None
    for line in lines:
        if line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE"):
            continue
        m = _VTT_TS.match(line.strip())
        if m:
            if buf and start is not None:
                segments.append(_seg(start, end, buf))
            buf = []
            start, end = m.group(1), m.group(2)
            continue
        if not line.strip():
            if buf and start is not None:
                segments.append(_seg(start, end, buf))
            buf, start, end = [], None, None
            continue
        if start is not None:
            cleaned = _TAG_RE.sub("", line).strip()
            if cleaned:
                buf.append(cleaned)
    if buf and start is not None:
        segments.append(_seg(start, end, buf))
    if segments:
        text = " ".join(s["text"] for s in segments).strip()
    else:
        # Plain text dropped into a .vtt without cues.
        text = "\n".join(
            ln for ln in lines
            if ln.strip() and not ln.startswith("WEBVTT") and "-->" not in ln
        ).strip()
    return text, segments


def _parse_srt(raw: str) -> tuple[str, list[dict[str, Any]]]:
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n").strip())
    segments: list[dict[str, Any]] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        # Optional index line.
        idx = 0
        if lines[0].strip().isdigit():
            idx = 1
        if idx >= len(lines):
            continue
        m = _SRT_TS.match(lines[idx].strip())
        if not m:
            continue
        body = [_TAG_RE.sub("", ln).strip() for ln in lines[idx + 1 :]]
        body = [b for b in body if b]
        if body:
            segments.append(_seg(m.group(1).replace(",", "."), m.group(2).replace(",", "."), body))
    text = " ".join(s["text"] for s in segments).strip()
    return text, segments


def _seg(start: str | None, end: str | None, lines: list[str]) -> dict[str, Any]:
    return {
        "start": start or "",
        "end": end or "",
        "text": " ".join(lines).strip(),
    }
