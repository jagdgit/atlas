"""Speech-to-text capability + SpeechToTextReader + MediaIngestor (M.5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.capabilities import CAP_SPEECH_TO_TEXT, CAPABILITY_CATALOG, SpeechToTextCapability
from atlas.engineering.readers import ReaderRegistry
from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.media import MediaIngestor
from atlas.plugins.speech_plugin import SpeechPlugin
from atlas.readers.media_kinds import ASSET_KIND_AUDIO
from atlas.readers.media_metadata import MediaMetadataReader
from atlas.readers.speech_to_text import SpeechToTextReader
from atlas.speech.engine import (
    CAPABILITY_GAP,
    STT_OK,
    STT_UNAVAILABLE,
    SpeechClient,
    SpeechEngineError,
    WhisperEngine,
)


class FakeEngine:
    name = "fake"

    def __init__(self, *, text="", segments=None, exc=None, available=True):
        self._text = text
        self._segments = segments or []
        self._exc = exc
        self._available = available
        self.calls: list = []

    def available(self):
        return self._available

    def transcribe(self, path, *, model, language):
        self.calls.append((path, model, language))
        if self._exc is not None:
            raise self._exc
        return {
            "text": self._text,
            "segments": self._segments,
            "model": f"fake:{model}",
            "language": language or "en",
        }


class _FakeAssets:
    def __init__(
        self,
        data: bytes,
        *,
        kind: str,
        filename: str,
        path: Path | None = None,
        metadata: dict[str, Any] | None = None,
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

    def get_bytes(self, asset_id, version=None):
        return self._data

    def versions(self, asset_id):
        return [self._version]

    def get(self, asset_id):
        return self._asset

    def path_of(self, asset_id, version=None):
        if self._path is None:
            raise FileNotFoundError("no path")
        return self._path


class _FakeArtifacts:
    def __init__(self) -> None:
        self.store: dict = {}

    def get(self, asset_id, version, reader, reader_version):
        return self.store.get((asset_id, version, reader, reader_version))

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.store[(asset_id, version, reader, reader_version)] = artifact


# --- SpeechClient --------------------------------------------------------
def test_client_disabled_reports_gap(tmp_path: Path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    res = SpeechClient(FakeEngine(text="hi"), enabled=False).transcribe(audio)
    assert res["outcome"] == STT_UNAVAILABLE
    assert res["capability_gap"] == CAPABILITY_GAP
    assert "disabled" in res["reason"]


def test_client_unavailable_engine_reports_gap(tmp_path: Path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    res = SpeechClient(FakeEngine(available=False), enabled=True).transcribe(audio)
    assert res["outcome"] == STT_UNAVAILABLE
    assert res["capability_gap"] == CAPABILITY_GAP


def test_client_ok_stamps_model(tmp_path: Path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    res = SpeechClient(
        FakeEngine(text="  hello atlas ", segments=[{"start": 0, "end": 1, "text": "hello atlas"}]),
        enabled=True,
        model="tiny",
    ).transcribe(audio)
    assert res["outcome"] == STT_OK
    assert res["text"] == "hello atlas"
    assert res["model"] == "fake:tiny"
    assert res["evidence_level"] == 1
    assert res["capability_gap"] is None


def test_client_engine_error_is_honest(tmp_path: Path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    res = SpeechClient(
        FakeEngine(exc=SpeechEngineError("boom")), enabled=True
    ).transcribe(audio)
    assert res["outcome"] == "error"
    assert "boom" in res["reason"]


def test_whisper_engine_available_false_without_binary(monkeypatch):
    monkeypatch.setattr("atlas.speech.engine.shutil.which", lambda _: None)
    # Force import failure path
    import builtins

    real_import = builtins.__import__

    def _block_whisper(name, *args, **kwargs):
        if name == "whisper" or name.startswith("whisper."):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_whisper)
    assert WhisperEngine().available() is False


# --- SpeechToTextReader --------------------------------------------------
def test_speech_reader_produces_transcript_artifact(tmp_path: Path):
    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"PCM")
    assets = _FakeAssets(b"PCM", kind=ASSET_KIND_AUDIO, filename="talk.wav", path=audio)
    client = SpeechClient(FakeEngine(text="spoken words"), enabled=True, model="base")
    art = SpeechToTextReader(assets, _FakeArtifacts(), client).read("a1")
    assert art["outcome"] == STT_OK
    assert art["artifact_kind"] == "transcript"
    assert art["strategy"] == "speech_to_text"
    assert art["text"] == "spoken words"
    assert art["model"] == "fake:base"
    assert art["evidence_level"] == 1
    assert art["model_versions"]["speech_to_text"] == "fake:base"


def test_speech_reader_gap_when_disabled(tmp_path: Path):
    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"PCM")
    assets = _FakeAssets(b"PCM", kind=ASSET_KIND_AUDIO, filename="talk.wav", path=audio)
    client = SpeechClient(FakeEngine(text="x"), enabled=False)
    art = SpeechToTextReader(assets, _FakeArtifacts(), client).read("a1")
    assert art["outcome"] == STT_UNAVAILABLE
    assert art["capability_gap"] == CAPABILITY_GAP


# --- MediaIngestor -------------------------------------------------------
class _FakeAcquirer:
    def __init__(self, kind: str, filename: str):
        self.kind = kind
        self.filename = filename

    def acquire_file(self, path, *, kind="document", content_type=None, metadata=None):
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


def test_media_ingestor_speech_on_audio_reaches_knowledge(tmp_path: Path):
    wav = tmp_path / "lecture.wav"
    wav.write_bytes(b"PCM")
    assets = _FakeAssets(b"PCM", kind=ASSET_KIND_AUDIO, filename="lecture.wav", path=wav)
    arts = _FakeArtifacts()
    know = _FakeKnowledge()
    client = SpeechClient(FakeEngine(text="Atlas learns from speech"), enabled=True)
    ingestor = MediaIngestor(
        _FakeAcquirer(ASSET_KIND_AUDIO, "lecture.wav"),
        know,
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        speech_reader=SpeechToTextReader(assets, arts, client),
    )
    out = ingestor.ingest_file(wav, embed=False)
    assert out["speech"]["outcome"] == STT_OK
    assert out["ingest"]["document_id"] == "doc-m"
    assert know.calls[0]["source"] == "media_speech_to_text"
    assert "Atlas learns from speech" in know.calls[0]["content"]
    assert know.calls[0]["metadata"]["strategy"] == "speech_to_text"
    assert "youtube" not in know.calls[0]["content"].lower()


def test_media_ingestor_speech_off_explicit_gap(tmp_path: Path):
    wav = tmp_path / "lecture.wav"
    wav.write_bytes(b"PCM")
    assets = _FakeAssets(b"PCM", kind=ASSET_KIND_AUDIO, filename="lecture.wav", path=wav)
    arts = _FakeArtifacts()
    know = _FakeKnowledge()
    client = SpeechClient(FakeEngine(text="should not run"), enabled=False)
    ingestor = MediaIngestor(
        _FakeAcquirer(ASSET_KIND_AUDIO, "lecture.wav"),
        know,
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        speech_reader=SpeechToTextReader(assets, arts, client),
    )
    out = ingestor.ingest_file(wav, embed=False)
    assert out["speech"]["capability_gap"] == CAPABILITY_GAP
    assert know.calls[0]["source"] == "media_metadata"
    content = know.calls[0]["content"]
    assert "capability_gap: speech_to_text" in content
    assert "should not run" not in content


# --- Registry + capability catalog ---------------------------------------
def test_speech_reader_in_registry():
    reg = ReaderRegistry()
    assert reg.get("speech_to_text") is not None
    assert CAP_SPEECH_TO_TEXT in CAPABILITY_CATALOG
    assert CAPABILITY_CATALOG[CAP_SPEECH_TO_TEXT].contract is SpeechToTextCapability


def test_speech_plugin_health_when_disabled():
    plugin = SpeechPlugin(SpeechClient(FakeEngine(), enabled=False))
    health = plugin.health_check()
    assert health.healthy is True
    assert health.data["enabled"] is False
    assert "disabled" in health.detail
