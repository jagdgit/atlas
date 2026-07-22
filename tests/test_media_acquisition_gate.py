"""Media Reader Family end-to-end gate (MEDIA_ACQUISITION_PLAN · M.7).

Acceptance:
  (1) captions URL → Document/Knowledge
  (2) local mp4 + Whisper on → Knowledge
  (3) robots-blocked URL → honest failure + 0 fabricated docs
  (4) no Knowledge-layer ``if youtube`` / ``if mp4`` branches in new media paths
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from atlas.evidence.models import Source
from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.media import MediaIngestor
from atlas.ingestion.media_events import (
    EVENT_MEDIA_METADATA_ACQUIRED,
    EVENT_MEDIA_READ_FAILED,
    EVENT_SPEECH_TO_TEXT_GAP,
    EVENT_TRANSCRIPT_ACQUIRED,
)
from atlas.ingestion.source_fetch import SourceFetcher
from atlas.net.client import FetchResult
from atlas.readers.media_metadata import MediaMetadataReader
from atlas.readers.speech_to_text import SpeechToTextReader
from atlas.readers.transcript_file import TranscriptFileReader
from atlas.research.acquire import Librarian
from atlas.speech.engine import SpeechClient
from atlas.transcripts.acquisition import (
    REASON_ROBOTS_DISALLOWED,
    STRATEGY_YOUTUBE_CAPTION_TRACKS,
    AcquisitionAttempt,
    AcquisitionRecord,
)
from atlas.transcripts.youtube import TranscriptResult


class _RecordingEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, *, source: str | None = None) -> None:
        self.emitted.append((event_type, payload))

    def types(self) -> set[str]:
        return {t for (t, _) in self.emitted}


class FakeAcquirer:
    def __init__(self) -> None:
        self._n = 0

    def acquire_file(self, path, *, kind="document", content_type=None, metadata=None):
        self._n += 1
        data = Path(path).read_bytes()
        return AcquiredAsset(
            asset_id=f"a{self._n}", asset_version=1, kind=kind, name="sha", checksum="sha",
            content_type=content_type, source_uri=str(path), size_bytes=len(data),
            reused=False, source=Path(path).name,
        )

    def acquire_bytes(
        self, data, *, kind="document", filename=None, source_uri=None, content_type=None, metadata=None
    ):
        self._n += 1
        return AcquiredAsset(
            asset_id=f"a{self._n}", asset_version=1, kind=kind, name="sha", checksum="sha",
            content_type=content_type, source_uri=source_uri, size_bytes=len(data),
            reused=False, source=filename or "bytes",
        )


class FakeFetch:
    def __init__(self, *, allowed: bool = True, result: FetchResult | None = None) -> None:
        self._allowed = allowed
        self._result = result

    def allowed(self, url: str) -> bool:
        return self._allowed

    def get(self, url: str, *, use_cache: bool = True) -> FetchResult:
        if self._result is not None:
            return self._result
        return FetchResult(url, "error", reason="no result")


class FakeKnowledge:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def ingest_text(self, source, content, **kw):
        self.docs.append({"source": source, "content": content, **kw})
        return {
            "document_id": f"doc-{len(self.docs)}",
            "status": "chunked",
            "chunks": 1,
            "deduped": False,
        }


class _FakeAssets:
    def __init__(self) -> None:
        self._by_id: dict[str, tuple[bytes, dict, Path | None]] = {}

    def put(self, asset_id: str, data: bytes, *, kind: str, filename: str, path: Path | None = None):
        self._by_id[asset_id] = (
            data,
            {"id": asset_id, "kind": kind, "name": filename, "metadata": {"filename": filename}},
            path,
        )

    def get_bytes(self, asset_id, version=None):
        return self._by_id[asset_id][0]

    def get(self, asset_id):
        return self._by_id[asset_id][1]

    def versions(self, asset_id):
        data, asset, _ = self._by_id[asset_id]
        return [{"version": 1, "size_bytes": len(data), "metadata": asset["metadata"]}]

    def path_of(self, asset_id, version=None):
        path = self._by_id[asset_id][2]
        if path is None:
            raise FileNotFoundError(asset_id)
        return path


class _FakeArtifacts:
    def __init__(self) -> None:
        self.store: dict = {}

    def get(self, *a):
        return self.store.get(a)

    def put(self, *a):
        self.store[a[:4]] = a[4]


class BridgingAcquirer(FakeAcquirer):
    def __init__(self, assets: _FakeAssets) -> None:
        super().__init__()
        self.assets = assets

    def acquire_file(self, path, *, kind="document", content_type=None, metadata=None):
        acquired = super().acquire_file(path, kind=kind, content_type=content_type, metadata=metadata)
        self.assets.put(
            acquired.asset_id, Path(path).read_bytes(),
            kind=kind, filename=Path(path).name, path=Path(path),
        )
        return acquired

    def acquire_bytes(self, data, **kw):
        acquired = super().acquire_bytes(data, **kw)
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        self.assets.put(
            acquired.asset_id, raw,
            kind=kw.get("kind") or "document",
            filename=kw.get("filename") or "bytes",
        )
        return acquired


class FakeEngine:
    name = "fake"

    def __init__(self, text: str) -> None:
        self._text = text

    def available(self) -> bool:
        return True

    def transcribe(self, path, *, model, language):
        return {
            "text": self._text,
            "segments": [],
            "model": f"fake:{model}",
            "language": language or "en",
        }


def _src(url: str) -> Source:
    return Source(id="s1", title="t", url=url, evidence_level=1)


# --- Gate (1): captions URL → knowledge/document -------------------------
def test_gate_captions_url_reaches_document_and_emits_transcript_event():
    events = _RecordingEvents()
    attempt = AcquisitionAttempt(
        STRATEGY_YOUTUBE_CAPTION_TRACKS, "ok", reason_code="ok", bytes_read=20,
    )
    acq = AcquisitionRecord.from_attempts([attempt])

    def fetch(_url):
        return TranscriptResult(
            "abcdefghijk",
            "https://www.youtube.com/watch?v=abcdefghijk",
            "ok",
            title="Captioned Talk",
            text="soiling loss is 0.3 percent per day",
            acquisition=acq,
        )

    lib = Librarian(FakeFetch(), transcript_fetcher=fetch, events=events)
    result = lib.acquire([_src("https://www.youtube.com/watch?v=abcdefghijk")])
    assert len(result.documents) == 1
    assert "0.3 percent" in result.documents[0].text
    assert result.documents[0].reader_id == "media_transcript"
    assert result.documents[0].metadata["source_id"] == "youtube:abcdefghijk"
    assert EVENT_TRANSCRIPT_ACQUIRED in events.types()
    assert EVENT_MEDIA_READ_FAILED not in events.types()


# --- Gate (2): local mp4 + Whisper on → Knowledge ------------------------
def test_gate_local_audio_with_whisper_reaches_knowledge(tmp_path: Path):
    events = _RecordingEvents()
    wav = tmp_path / "lecture.wav"
    wav.write_bytes(b"PCM-AUDIO")
    assets = _FakeAssets()
    arts = _FakeArtifacts()
    know = FakeKnowledge()
    acq = BridgingAcquirer(assets)
    client = SpeechClient(FakeEngine("spoken words from local media"), enabled=True)
    ingestor = MediaIngestor(
        acq,
        know,
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        speech_reader=SpeechToTextReader(assets, arts, client),
        events=events,
    )
    out = ingestor.ingest_file(wav, embed=False)
    assert out["ingest"]["document_id"]
    assert know.docs[0]["source"] == "media_speech_to_text"
    assert "spoken words" in know.docs[0]["content"]
    assert know.docs[0]["metadata"]["source_id"].startswith("file:")
    assert EVENT_MEDIA_METADATA_ACQUIRED in events.types()
    assert EVENT_TRANSCRIPT_ACQUIRED in events.types()
    assert "youtube" not in know.docs[0]["content"].lower()


# --- Gate (3): robots-blocked → honest failure, 0 fabricated docs --------
def test_gate_robots_blocked_zero_fabricated_docs():
    events = _RecordingEvents()
    attempt = AcquisitionAttempt(
        STRATEGY_YOUTUBE_CAPTION_TRACKS, "skipped",
        reason="robots.txt disallows this URL",
        reason_code=REASON_ROBOTS_DISALLOWED, bytes_read=0,
    )
    acq = AcquisitionRecord.from_attempts(
        [attempt], source_url="https://www.youtube.com/watch?v=abcdefghijk"
    )

    def fetch(_url):
        return TranscriptResult(
            "abcdefghijk",
            "https://www.youtube.com/watch?v=abcdefghijk",
            "skipped",
            reason="robots.txt disallows this URL",
            acquisition=acq,
        )

    know = FakeKnowledge()
    assets = _FakeAssets()
    arts = _FakeArtifacts()
    media = MediaIngestor(
        FakeAcquirer(),
        know,
        source_fetcher=SourceFetcher(FakeAcquirer(), FakeFetch(allowed=False)),
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        events=events,
    )
    lib = Librarian(
        FakeFetch(allowed=False),
        transcript_fetcher=fetch,
        media_ingestor=media,
        events=events,
    )
    result = lib.acquire([_src("https://www.youtube.com/watch?v=abcdefghijk")])
    assert result.documents == []
    assert result.blocked
    assert know.docs == []  # 0 fabricated knowledge docs
    assert EVENT_MEDIA_READ_FAILED in events.types()


def test_gate_robots_blocked_http_media_zero_knowledge():
    events = _RecordingEvents()
    know = FakeKnowledge()
    media = MediaIngestor(
        FakeAcquirer(),
        know,
        source_fetcher=SourceFetcher(FakeAcquirer(), FakeFetch(allowed=False)),
        events=events,
    )
    out = media.ingest_url("https://cdn.example/secret.mp4", embed=False)
    assert out["outcome"] == "blocked"
    assert out["ingest"] is None
    assert know.docs == []
    assert EVENT_MEDIA_READ_FAILED in events.types()


def test_gate_speech_off_emits_gap_not_fabricated_speech(tmp_path: Path):
    events = _RecordingEvents()
    wav = tmp_path / "lecture.wav"
    wav.write_bytes(b"PCM")
    assets = _FakeAssets()
    arts = _FakeArtifacts()
    know = FakeKnowledge()
    acq = BridgingAcquirer(assets)
    client = SpeechClient(FakeEngine("should not appear"), enabled=False)
    MediaIngestor(
        acq,
        know,
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        speech_reader=SpeechToTextReader(assets, arts, client),
        events=events,
    ).ingest_file(wav, embed=False)
    assert EVENT_SPEECH_TO_TEXT_GAP in events.types()
    assert all("should not appear" not in d["content"] for d in know.docs)


# --- Gate (4): no Knowledge-layer provider branches ----------------------
_FORBIDDEN_PATTERNS = (
    ("if", "youtube"),
    ("if", "mp4"),
)

_SCAN_ROOTS = (
    Path("atlas/knowledge"),
    Path("atlas/ingestion/media.py"),
    Path("atlas/ingestion/media_events.py"),
)


def _iter_py_files(root: Path):
    if root.is_file():
        yield root
        return
    yield from root.rglob("*.py")


def test_gate_no_knowledge_layer_youtube_or_mp4_branches():
    """Static check: Knowledge + media ingest orchestration must not special-case providers."""
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        for path in _iter_py_files(root):
            src = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.If):
                    continue
                chunk = ast.get_source_segment(src, node.test) or ""
                low = chunk.lower()
                if "youtube" in low or (".mp4" in low or "mp4" in low and "==" in low):
                    # Allow comments-only / string docs via ignoring Assign; focus on conditions.
                    offenders.append(f"{path}:{node.lineno}: if {chunk.strip()}")
    assert offenders == [], "Knowledge/media path must not branch on youtube/mp4:\n" + "\n".join(
        offenders
    )
