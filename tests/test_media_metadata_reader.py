"""MediaMetadataReader + media kind conventions (Media Reader Family · M.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas.readers.media_kinds import (
    ASSET_KIND_AUDIO,
    ASSET_KIND_TRANSCRIPT,
    ASSET_KIND_VIDEO,
    content_type_for,
    infer_media_kind,
)
from atlas.readers.media_metadata import MediaMetadataReader


class _FakeAssets:
    def __init__(
        self,
        data: bytes,
        *,
        kind: str,
        filename: str,
        metadata: dict[str, Any] | None = None,
        content_type: str | None = None,
        path: Path | None = None,
    ) -> None:
        self._data = data
        self._kind = kind
        self._path = path
        meta = {"filename": filename, **(metadata or {})}
        self._asset = {
            "id": "a1",
            "kind": kind,
            "name": filename,
            "content_type": content_type or content_type_for(filename),
            "metadata": meta,
            "source_uri": meta.get("source_url"),
        }
        self._version = {
            "version": 1,
            "size_bytes": len(data),
            "content_type": self._asset["content_type"],
            "metadata": meta,
        }

    def get_bytes(self, asset_id: str, version: int | None = None) -> bytes:
        return self._data

    def versions(self, asset_id: str) -> list[dict[str, Any]]:
        return [self._version]

    def get(self, asset_id: str) -> dict[str, Any]:
        return self._asset

    def path_of(self, asset_id: str, version: int | None = None) -> Path:
        if self._path is None:
            raise FileNotFoundError("no path")
        return self._path


class _FakeArtifacts:
    def __init__(self) -> None:
        self.store: dict[tuple, dict[str, Any]] = {}
        self.puts = 0

    def get(self, asset_id, version, reader, reader_version):
        return self.store.get((asset_id, version, reader, reader_version))

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.puts += 1
        self.store[(asset_id, version, reader, reader_version)] = artifact


def test_infer_media_kind_from_extension():
    assert infer_media_kind("talk.mp4") == ASSET_KIND_VIDEO
    assert infer_media_kind("note.mp3") == ASSET_KIND_AUDIO
    assert infer_media_kind("captions.vtt") == ASSET_KIND_TRANSCRIPT
    assert infer_media_kind("readme.md") is None


def test_mp4_metadata_without_transcription():
    """Acceptance: local mp4 → metadata artifact; no transcript required."""
    assets = _FakeAssets(
        b"\x00\x00\x00\x18ftypmp42",  # tiny fake mp4 header bytes
        kind=ASSET_KIND_VIDEO,
        filename="lecture.mp4",
        metadata={"title": "Intro to Atlas", "channel": "Atlas Talks"},
    )
    art = MediaMetadataReader(assets, _FakeArtifacts(), probe=lambda p: {}).read("a1")
    assert art["outcome"] == "ok"
    assert art["artifact_kind"] == "media_metadata"
    fields = art["fields"]
    assert fields["kind"] == ASSET_KIND_VIDEO
    assert fields["filename"] == "lecture.mp4"
    assert fields["extension"] == ".mp4"
    assert fields["title"] == "Intro to Atlas"
    assert fields["channel"] == "Atlas Talks"
    assert fields["size_bytes"] == len(assets._data)
    assert "text" not in fields  # not a transcript


def test_mp3_metadata_from_sidecar_only():
    assets = _FakeAssets(
        b"ID3fake",
        kind=ASSET_KIND_AUDIO,
        filename="voice.mp3",
        metadata={"duration_seconds": 42.5, "language": "en"},
    )
    art = MediaMetadataReader(assets, _FakeArtifacts(), probe=lambda p: {}).read("a1")
    assert art["outcome"] == "ok"
    assert art["fields"]["kind"] == ASSET_KIND_AUDIO
    assert art["fields"]["duration"] == 42.5
    assert art["fields"]["language"] == "en"


def test_probe_fields_merged_without_inventing():
    assets = _FakeAssets(
        b"bytes",
        kind=ASSET_KIND_VIDEO,
        filename="x.mp4",
        path=Path("/tmp/does-not-matter"),
    )

    def probe(_path: Path) -> dict[str, Any]:
        return {"duration_seconds": 12.0, "video_codec": "h264", "resolution": "1280x720"}

    # path_of must succeed for probe to run
    assets.path_of = lambda asset_id, version=None: Path(".")  # noqa: E731

    art = MediaMetadataReader(assets, _FakeArtifacts(), probe=probe).read("a1")
    assert art["fields"]["duration"] == 12.0
    assert art["fields"]["video_codec"] == "h264"
    assert art["fields"]["resolution"] == "1280x720"
    assert "fps" not in art["fields"]  # not invented


def test_json_sidecar_asset_merges_fields():
    payload = {"title": "From JSON", "uploader": "op", "tags": ["talk"]}
    assets = _FakeAssets(
        json.dumps(payload).encode(),
        kind=ASSET_KIND_TRANSCRIPT,
        filename="meta.json",
    )
    art = MediaMetadataReader(assets, _FakeArtifacts(), probe=lambda p: {}).read("a1")
    assert art["outcome"] == "ok"
    assert art["fields"]["title"] == "From JSON"
    assert art["fields"]["uploader"] == "op"
    assert art["fields"]["tags"] == ["talk"]


def test_unsupported_kind_is_honest():
    assets = _FakeAssets(b"hi", kind="document", filename="note.md")
    art = MediaMetadataReader(assets, _FakeArtifacts(), probe=lambda p: {}).read("a1")
    assert art["outcome"] == "unsupported"
    assert art["fields"] == {}


def test_cache_hit_avoids_reparse():
    artifacts = _FakeArtifacts()
    assets = _FakeAssets(b"x", kind=ASSET_KIND_AUDIO, filename="a.wav")
    reader = MediaMetadataReader(assets, artifacts, probe=lambda p: {})
    reader.read("a1")
    reader.read("a1")
    assert artifacts.puts == 1
