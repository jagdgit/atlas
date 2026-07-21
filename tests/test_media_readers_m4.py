"""TranscriptFileReader, AudioDemuxReader, MediaIngestor (Media Reader Family · M.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.engineering.readers import (
    CAP_AUDIO,
    CAP_METADATA,
    CAP_TRANSCRIPT,
    ReaderRegistry,
    default_media_readers,
)
from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.media import MediaIngestor
from atlas.readers.audio_demux import AudioDemuxReader
from atlas.readers.media_kinds import ASSET_KIND_AUDIO, ASSET_KIND_TRANSCRIPT, ASSET_KIND_VIDEO
from atlas.readers.media_metadata import MediaMetadataReader
from atlas.readers.transcript_file import TranscriptFileReader


class _FakeAssets:
    def __init__(
        self,
        data: bytes,
        *,
        kind: str,
        filename: str,
        metadata: dict[str, Any] | None = None,
        path: Path | None = None,
    ) -> None:
        self._data = data
        self._path = path
        meta = {"filename": filename, **(metadata or {})}
        self._asset = {
            "id": "a1",
            "kind": kind,
            "name": filename,
            "content_type": "application/octet-stream",
            "metadata": meta,
            "source_uri": f"/tmp/{filename}",
        }
        self._version = {
            "version": 1,
            "size_bytes": len(data),
            "content_type": "application/octet-stream",
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

    def get(self, asset_id, version, reader, reader_version):
        return self.store.get((asset_id, version, reader, reader_version))

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.store[(asset_id, version, reader, reader_version)] = artifact


_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello Atlas

00:00:02.000 --> 00:00:04.000
from a local transcript
"""

_SRT = """1
00:00:00,000 --> 00:00:02,000
Hello Atlas

2
00:00:02,000 --> 00:00:04,000
from SRT
"""


def test_transcript_file_reader_vtt():
    assets = _FakeAssets(_VTT.encode(), kind=ASSET_KIND_TRANSCRIPT, filename="talk.vtt")
    art = TranscriptFileReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "ok"
    assert art["artifact_kind"] == "transcript"
    assert "Hello Atlas" in art["text"]
    assert "local transcript" in art["text"]
    assert len(art["segments"]) == 2
    assert art["segments"][0]["text"] == "Hello Atlas"


def test_transcript_file_reader_srt():
    assets = _FakeAssets(_SRT.encode(), kind=ASSET_KIND_TRANSCRIPT, filename="talk.srt")
    art = TranscriptFileReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "ok"
    assert "Hello Atlas" in art["text"]
    assert "from SRT" in art["text"]


def test_transcript_file_reader_txt():
    assets = _FakeAssets(b"plain spoken notes", kind=ASSET_KIND_TRANSCRIPT, filename="notes.txt")
    art = TranscriptFileReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "ok"
    assert art["text"] == "plain spoken notes"
    assert art["segments"] == []


def test_audio_demux_injected_fn_registers_audio_asset(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    assets = _FakeAssets(
        video.read_bytes(), kind=ASSET_KIND_VIDEO, filename="clip.mp4", path=video
    )
    acquired_audio = []

    class _Acq:
        def acquire_bytes(self, data, **kw):
            acquired_audio.append((data, kw))
            return AcquiredAsset(
                asset_id="audio-1",
                asset_version=1,
                kind=ASSET_KIND_AUDIO,
                name="sha",
                checksum="sha",
                content_type="audio/wav",
                source_uri="derived",
                size_bytes=len(data),
                reused=False,
                source="clip.wav",
            )

    def fake_demux(src: Path, dst: Path) -> None:
        assert src == video
        dst.write_bytes(b"PCM-AUDIO")

    art = AudioDemuxReader(assets, _FakeArtifacts(), acquirer=_Acq(), demux=fake_demux).read("a1")
    assert art["outcome"] == "ok"
    assert art["audio_asset_id"] == "audio-1"
    assert art["audio_bytes"] == len(b"PCM-AUDIO")
    assert acquired_audio[0][0] == b"PCM-AUDIO"
    assert acquired_audio[0][1]["kind"] == ASSET_KIND_AUDIO


def test_audio_demux_unavailable_without_ffmpeg(monkeypatch):
    assets = _FakeAssets(b"x", kind=ASSET_KIND_VIDEO, filename="clip.mp4", path=Path("/nope"))
    monkeypatch.setattr("atlas.readers.audio_demux.shutil.which", lambda _: None)
    art = AudioDemuxReader(assets, _FakeArtifacts()).read("a1")
    assert art["outcome"] == "unsupported"
    assert art["capability_gap"] == "audio_demux"


def test_media_readers_registered_with_honest_coverage():
    reg = ReaderRegistry()
    assert reg.get("transcript_file") is not None
    assert reg.get("audio_demux") is not None
    assert reg.get("media_metadata") is not None
    assert reg.supports(CAP_TRANSCRIPT, extension=".vtt") is True
    assert reg.supports(CAP_METADATA, extension=".mp4") is True
    # Highest priority for .mp4 among media: metadata (40) > demux (30) for reader_for_extension
    # but can_produce uses language="media" → highest priority media reader with that lang.
    assert any(r.supports(CAP_AUDIO) for r in default_media_readers())


# --- MediaIngestor orchestration -----------------------------------------
class _FakeAcquirer:
    def __init__(self, kind: str, filename: str):
        self.kind = kind
        self.filename = filename
        self.calls: list = []

    def acquire_file(self, path, *, kind="document", content_type=None, metadata=None):
        self.calls.append((str(path), kind, content_type))
        return AcquiredAsset(
            asset_id="asset-m",
            asset_version=1,
            kind=kind,
            name="sha",
            checksum="sha256",
            content_type=content_type or "application/octet-stream",
            source_uri=str(path),
            size_bytes=10,
            reused=False,
            source=self.filename,
        )


class _FakeKnowledge:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def ingest_text(self, source, content, **kw):
        self.calls.append({"source": source, "content": content, **kw})
        return {"document_id": "doc-m", "status": "chunked", "chunks": 1, "deduped": False}


def test_media_ingestor_vtt_reaches_knowledge_without_youtube(tmp_path: Path):
    vtt = tmp_path / "lecture.vtt"
    vtt.write_text(_VTT, encoding="utf-8")
    assets = _FakeAssets(_VTT.encode(), kind=ASSET_KIND_TRANSCRIPT, filename="lecture.vtt")
    arts = _FakeArtifacts()
    know = _FakeKnowledge()
    ingestor = MediaIngestor(
        _FakeAcquirer(ASSET_KIND_TRANSCRIPT, "lecture.vtt"),
        know,
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        transcript_reader=TranscriptFileReader(assets, arts),
    )
    out = ingestor.ingest_file(vtt, embed=False)
    assert out["kind"] == ASSET_KIND_TRANSCRIPT
    assert out["ingest"]["document_id"] == "doc-m"
    assert know.calls[0]["source"] == "media_transcript"
    assert "Hello Atlas" in know.calls[0]["content"]
    assert "youtube" not in know.calls[0]["content"].lower()
    meta = know.calls[0]["metadata"]
    assert meta["asset_id"] == "asset-m"
    assert meta["reader"] == "transcript_file"
    assert "youtube" not in str(meta).lower()


def test_media_ingestor_mp4_metadata_note_no_fabricated_speech(tmp_path: Path):
    mp4 = tmp_path / "talk.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    assets = _FakeAssets(
        mp4.read_bytes(),
        kind=ASSET_KIND_VIDEO,
        filename="talk.mp4",
        metadata={"title": "Local Talk"},
        path=mp4,
    )
    arts = _FakeArtifacts()
    know = _FakeKnowledge()

    def fake_demux(src: Path, dst: Path) -> None:
        dst.write_bytes(b"PCM")

    class _Acq(_FakeAcquirer):
        def acquire_bytes(self, data, **kw):
            return AcquiredAsset(
                asset_id="audio-x",
                asset_version=1,
                kind=ASSET_KIND_AUDIO,
                name="sha",
                checksum="sha",
                content_type="audio/wav",
                source_uri="derived",
                size_bytes=len(data),
                reused=False,
                source="talk.wav",
            )

    acq = _Acq(ASSET_KIND_VIDEO, "talk.mp4")
    ingestor = MediaIngestor(
        acq,
        know,
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        demux_reader=AudioDemuxReader(assets, arts, acquirer=acq, demux=fake_demux),
    )
    out = ingestor.ingest_file(mp4, embed=False)
    assert out["kind"] == ASSET_KIND_VIDEO
    assert out["demux"]["outcome"] == "ok"
    assert out["ingest"]["document_id"] == "doc-m"
    content = know.calls[0]["content"]
    assert "Local Talk" in content or "talk.mp4" in content
    assert "not a speech transcript" in content
    assert know.calls[0]["source"] == "media_metadata"
    # No YouTube-specific Knowledge branch.
    assert "youtube" not in content.lower()
