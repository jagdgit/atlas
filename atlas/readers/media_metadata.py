"""Media Metadata Reader (Media Reader Family · M.3 / MD4, constitution P8/P11).

``Asset → MediaMetadataReader → metadata artifact`` — structured facts *about* the media
(duration, title, codec, …), **not** Knowledge claims. Downstream extractors may later promote
selected fields; this reader never invents values (absent fields are omitted).

Sources of truth, in order (later wins only when the earlier is absent):

1. Asset / version ``metadata`` sidecar keys the operator or a source-fetch strategy stamped.
2. Filename / kind / size / content_type from the Asset Store.
3. Optional JSON bytes when the asset itself is a ``.json`` metadata sidecar.
4. Optional ``probe`` callable (default: ffprobe when on ``PATH``) for container-level props.

Transcription is **out of scope** here (M.4/M.5). A local ``mp4``/``mp3`` can yield a metadata
artifact with zero transcript work.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from atlas.readers.media_kinds import (
    MEDIA_ASSET_KINDS,
    infer_media_kind,
    media_extensions,
)

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

MEDIA_METADATA_READER_ID = "media_metadata"
MEDIA_METADATA_READER_VERSION = "1.0.0"

# Keys we may surface on the artifact when present (never invent).
_SIDECAR_KEYS = (
    "title",
    "description",
    "language",
    "duration",
    "duration_seconds",
    "tags",
    "channel",
    "uploader",
    "upload_date",
    "created_at",
    "resolution",
    "width",
    "height",
    "fps",
    "codec",
    "audio_codec",
    "video_codec",
    "bitrate",
    "source_url",
    "youtube_id",
    "provider",
)

ProbeFn = Callable[[Path], dict[str, Any]]


class MediaMetadataReader:
    """Read a media asset → cached metadata artifact (BB11); reuse when unchanged."""

    id = MEDIA_METADATA_READER_ID
    VERSION = MEDIA_METADATA_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        probe: ProbeFn | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts  # DerivedArtifactStore (duck-typed: get/put)
        self._probe = probe  # None → best-effort ffprobe; explicit callable for tests
        self._logger = logger or logging.getLogger("atlas.readers.media_metadata")

    def supported_extensions(self) -> list[str]:
        return media_extensions()

    def supported_kinds(self) -> list[str]:
        return sorted(MEDIA_ASSET_KINDS)

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

        asset_row = self._asset_row(asset_id)
        ver_row = self._version_row(asset_id, version)
        filename = filename or self._filename_from(asset_row, ver_row)
        kind = str((asset_row or {}).get("kind") or "") or (infer_media_kind(filename) or "")
        data = self._assets.get_bytes(asset_id, version)
        artifact = self._extract(
            data,
            filename=filename,
            kind=kind,
            asset_id=asset_id,
            version=version,
            asset_row=asset_row or {},
            ver_row=ver_row or {},
        )
        self._artifacts.put(asset_id, version, self.id, self.VERSION, artifact)
        return artifact

    # --- internals ------------------------------------------------------
    def _extract(
        self,
        data: bytes,
        *,
        filename: str | None,
        kind: str,
        asset_id: str,
        version: int,
        asset_row: dict[str, Any],
        ver_row: dict[str, Any],
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower() if filename else ""
        base: dict[str, Any] = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "artifact_kind": "media_metadata",
        }
        if kind and kind not in MEDIA_ASSET_KINDS:
            return {
                **base,
                "outcome": "unsupported",
                "reason": f"not a media asset kind: {kind!r}",
                "fields": {},
            }

        fields: dict[str, Any] = {}
        if kind:
            fields["kind"] = kind
        if filename:
            fields["filename"] = Path(filename).name
        if suffix:
            fields["extension"] = suffix
        ct = asset_row.get("content_type") or ver_row.get("content_type")
        if ct:
            fields["content_type"] = ct
        size = ver_row.get("size_bytes")
        if size is None:
            size = len(data)
        if size is not None:
            fields["size_bytes"] = int(size)
        if asset_row.get("source_uri"):
            fields["source_uri"] = asset_row["source_uri"]

        # Sidecar metadata on the asset / version (operator or source-fetch strategy).
        for meta in (asset_row.get("metadata"), ver_row.get("metadata")):
            if isinstance(meta, dict):
                self._merge_sidecar(fields, meta)

        # JSON asset bytes as an explicit metadata sidecar file.
        if suffix == ".json":
            self._merge_json_bytes(fields, data)

        # Optional container probe (ffprobe or injected).
        probed = self._run_probe(asset_id, version, filename)
        if probed:
            self._merge_sidecar(fields, probed)

        if not fields:
            return {**base, "outcome": "empty", "reason": "no media metadata available", "fields": {}}

        # Normalize duration alias.
        if "duration" not in fields and "duration_seconds" in fields:
            fields["duration"] = fields["duration_seconds"]

        return {
            **base,
            "outcome": "ok",
            "kind": fields.get("kind") or kind or None,
            "fields": fields,
            "field_count": len(fields),
        }

    def _merge_sidecar(self, fields: dict[str, Any], meta: dict[str, Any]) -> None:
        for key in _SIDECAR_KEYS:
            if key in fields:
                continue
            if key not in meta:
                continue
            value = meta[key]
            if value is None or value == "" or value == []:
                continue
            fields[key] = value
        # Common nested shapes from downloaders.
        for nest_key in ("metadata", "info", "tags"):
            nested = meta.get(nest_key)
            if isinstance(nested, dict):
                self._merge_sidecar(fields, nested)

    def _merge_json_bytes(self, fields: dict[str, Any], data: bytes) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001 - bad JSON is not fatal; omit
            return
        if isinstance(payload, dict):
            self._merge_sidecar(fields, payload)

    def _run_probe(
        self, asset_id: str, version: int, filename: str | None
    ) -> dict[str, Any]:
        probe = self._probe if self._probe is not None else _default_ffprobe
        if probe is None:
            return {}
        try:
            path = self._assets.path_of(asset_id, version)
        except Exception:  # noqa: BLE001
            return {}
        if path is None or not Path(path).exists():
            return {}
        # Skip probe for pure text/json sidecars.
        suffix = Path(filename or path).suffix.lower()
        if suffix in {".json", ".vtt", ".srt", ".txt"}:
            return {}
        try:
            return dict(probe(Path(path)) or {})
        except Exception as exc:  # noqa: BLE001 - probe is best-effort
            self._logger.debug("media probe failed for %s: %s", asset_id, exc)
            return {}

    def _resolve_version(self, asset_id: str, asset_version: int | None) -> int:
        if asset_version is not None:
            return int(asset_version)
        versions = self._assets.versions(asset_id)
        if not versions:
            raise FileNotFoundError(f"no versions for asset {asset_id}")
        return int(versions[-1]["version"])

    def _version_row(self, asset_id: str, version: int) -> dict[str, Any] | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) == version:
                return row
        return None

    def _asset_row(self, asset_id: str) -> dict[str, Any] | None:
        get = getattr(self._assets, "get", None)
        if callable(get):
            return get(asset_id)
        return None

    @staticmethod
    def _filename_from(
        asset_row: dict[str, Any] | None, ver_row: dict[str, Any] | None
    ) -> str | None:
        for row in (ver_row, asset_row):
            if not row:
                continue
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if meta.get("filename"):
                return str(meta["filename"])
            if row.get("name") and Path(str(row["name"])).suffix:
                return str(row["name"])
        return None


def _default_ffprobe(path: Path) -> dict[str, Any]:
    """Best-effort ffprobe → flat metadata fields. Returns {} if ffprobe is absent."""
    binary = shutil.which("ffprobe")
    if not binary:
        return {}
    try:
        proc = subprocess.run(
            [
                binary,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:  # noqa: BLE001
        return {}
    if proc.returncode != 0 or not proc.stdout:
        return {}
    try:
        payload = json.loads(proc.stdout)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, Any] = {}
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    if fmt.get("duration"):
        try:
            out["duration_seconds"] = float(fmt["duration"])
        except (TypeError, ValueError):
            pass
    if fmt.get("bit_rate"):
        try:
            out["bitrate"] = int(fmt["bit_rate"])
        except (TypeError, ValueError):
            pass
    tags = fmt.get("tags") if isinstance(fmt.get("tags"), dict) else {}
    for src, dst in (("title", "title"), ("language", "language"), ("DESCRIPTION", "description")):
        if tags.get(src) and dst not in out:
            out[dst] = tags[src]
    for stream in payload.get("streams") or []:
        if not isinstance(stream, dict):
            continue
        codec = stream.get("codec_name")
        if stream.get("codec_type") == "video":
            if codec and "video_codec" not in out:
                out["video_codec"] = codec
                out.setdefault("codec", codec)
            if stream.get("width") and stream.get("height"):
                out.setdefault("width", int(stream["width"]))
                out.setdefault("height", int(stream["height"]))
                out.setdefault("resolution", f"{stream['width']}x{stream['height']}")
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
            if rate and "fps" not in out:
                fps = _parse_rate(rate)
                if fps:
                    out["fps"] = fps
        elif stream.get("codec_type") == "audio":
            if codec and "audio_codec" not in out:
                out["audio_codec"] = codec
            lang = (stream.get("tags") or {}).get("language") if isinstance(stream.get("tags"), dict) else None
            if lang and "language" not in out:
                out["language"] = lang
    return out


def _parse_rate(rate: str) -> float | None:
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return round(float(num) / den_f, 3)
        return float(rate)
    except (TypeError, ValueError):
        return None
