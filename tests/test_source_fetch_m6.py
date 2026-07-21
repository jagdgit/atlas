"""SourceFetcher — provider-agnostic URL/path → Asset (Media Reader Family · M.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.media import MediaIngestor
from atlas.ingestion.source_fetch import (
    OPERATOR_HINT,
    SourceFetcher,
    is_youtube_url,
    stable_source_id,
    youtube_video_id,
)
from atlas.net.client import FetchResult
from atlas.readers.media_kinds import ASSET_KIND_AUDIO, ASSET_KIND_TRANSCRIPT, ASSET_KIND_VIDEO
from atlas.readers.media_metadata import MediaMetadataReader
from atlas.readers.transcript_file import TranscriptFileReader


class FakeAcquirer:
    def __init__(self) -> None:
        self.calls: list = []
        self._n = 0

    def acquire_file(self, path, *, kind="document", content_type=None, metadata=None):
        self.calls.append(("file", str(path), kind, metadata))
        self._n += 1
        data = Path(path).read_bytes()
        return AcquiredAsset(
            asset_id=f"a{self._n}",
            asset_version=1,
            kind=kind,
            name="sha",
            checksum="sha",
            content_type=content_type,
            source_uri=str(path),
            size_bytes=len(data),
            reused=False,
            source=Path(path).name,
        )

    def acquire_bytes(
        self, data, *, kind="document", filename=None, source_uri=None, content_type=None, metadata=None
    ):
        self.calls.append(("bytes", filename, kind, metadata))
        self._n += 1
        return AcquiredAsset(
            asset_id=f"a{self._n}",
            asset_version=1,
            kind=kind,
            name="sha",
            checksum="sha",
            content_type=content_type,
            source_uri=source_uri,
            size_bytes=len(data),
            reused=False,
            source=filename or "bytes",
        )


class FakeFetch:
    def __init__(self, *, allowed: bool = True, result: FetchResult | None = None) -> None:
        self._allowed = allowed
        self._result = result
        self.allowed_urls: list[str] = []
        self.get_urls: list[str] = []

    def allowed(self, url: str) -> bool:
        self.allowed_urls.append(url)
        return self._allowed

    def get(self, url: str, *, use_cache: bool = True) -> FetchResult:
        self.get_urls.append(url)
        if self._result is not None:
            return self._result
        return FetchResult(url, "error", reason="no result configured")


def test_stable_source_id_youtube_and_url():
    assert stable_source_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube:dQw4w9WgXcQ"
    assert youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert stable_source_id("https://cdn.example/a.mp3").startswith("url:")


def test_local_file_strategy(tmp_path: Path):
    vtt = tmp_path / "talk.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    fetcher = SourceFetcher(FakeAcquirer(), FakeFetch())
    result = fetcher.fetch(str(vtt))
    assert result.ok
    assert result.kind == ASSET_KIND_TRANSCRIPT
    assert result.filename == "talk.vtt"
    assert any(t["name"] == "local_file" and t["ok"] for t in result.strategies_tried)


def test_http_direct_allowed_yields_asset():
    body = b"ID3fake-audio-bytes"
    fetch = FakeFetch(
        allowed=True,
        result=FetchResult(
            "https://cdn.example/lecture.mp3",
            "ok",
            content=body,
            content_type="audio/mpeg",
        ),
    )
    acq = FakeAcquirer()
    result = SourceFetcher(acq, fetch).fetch("https://cdn.example/lecture.mp3")
    assert result.ok
    assert result.kind == ASSET_KIND_AUDIO
    assert result.bytes_read == len(body)
    assert acq.calls[0][0] == "bytes"
    assert acq.calls[0][3]["source_url"] == "https://cdn.example/lecture.mp3"
    # Must have checked robots before fetching.
    assert fetch.allowed_urls == ["https://cdn.example/lecture.mp3"]


def test_http_robots_blocked_never_fetches():
    fetch = FakeFetch(allowed=False)
    result = SourceFetcher(FakeAcquirer(), fetch).fetch("https://cdn.example/secret.mp4")
    assert result.outcome == "blocked"
    assert result.reason_code == "robots_disallowed"
    assert result.operator_hint == OPERATOR_HINT
    assert fetch.get_urls == []  # never bypassed robots
    assert "upload a local file" in (result.operator_hint or "")


def test_youtube_robots_blocked_with_hint():
    fetch = FakeFetch(allowed=False)
    result = SourceFetcher(FakeAcquirer(), fetch).fetch(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    assert result.outcome == "blocked"
    assert result.reason_code == "robots_disallowed"
    assert result.operator_hint == OPERATOR_HINT
    assert result.source_id == "youtube:dQw4w9WgXcQ"
    assert fetch.get_urls == []


def test_youtube_without_fetcher_blocked_with_operator_hint():
    """Even when robots allow, default policy requires operator asset (no silent scrape)."""
    fetch = FakeFetch(allowed=True)
    result = SourceFetcher(FakeAcquirer(), fetch).fetch(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    assert result.outcome == "blocked"
    assert result.reason_code == "policy_requires_operator_asset"
    assert result.operator_hint == OPERATOR_HINT


def test_youtube_injectable_fetch_registers_asset():
    fetch = FakeFetch(allowed=True)

    def yt_fetch(url: str) -> dict[str, Any]:
        return {
            "outcome": "ok",
            "content": b"\x00\x00\x00\x18ftypmp42",
            "filename": "clip.mp4",
            "kind": ASSET_KIND_VIDEO,
            "content_type": "video/mp4",
        }

    acq = FakeAcquirer()
    result = SourceFetcher(acq, fetch, youtube_fetch=yt_fetch).fetch(
        "https://youtu.be/dQw4w9WgXcQ"
    )
    assert result.ok
    assert result.kind == ASSET_KIND_VIDEO
    assert result.source_id == "youtube:dQw4w9WgXcQ"
    assert acq.calls[-1][3]["youtube_video_id"] == "dQw4w9WgXcQ"


# --- MediaIngestor.ingest_url --------------------------------------------
class _FakeAssets:
    def __init__(self, data: bytes, *, kind: str, filename: str) -> None:
        self._data = data
        meta = {"filename": filename}
        self._asset = {"id": "a1", "kind": kind, "name": filename, "metadata": meta}
        self._version = {"version": 1, "size_bytes": len(data), "metadata": meta}

    def get_bytes(self, asset_id, version=None):
        return self._data

    def versions(self, asset_id):
        return [self._version]

    def get(self, asset_id):
        return self._asset

    def path_of(self, asset_id, version=None):
        raise FileNotFoundError("n/a")


class _FakeArtifacts:
    def __init__(self) -> None:
        self.store: dict = {}

    def get(self, *a):
        return self.store.get(a)

    def put(self, *a):
        self.store[a[:4]] = a[4]


class _FakeKnowledge:
    def __init__(self) -> None:
        self.calls: list = []

    def ingest_text(self, source, content, **kw):
        self.calls.append({"source": source, "content": content, **kw})
        return {"document_id": "doc-1", "chunks": 1, "deduped": False}


def test_ingest_url_http_media_reaches_knowledge_no_youtube_branch():
    vtt = (
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello from CDN\n"
    ).encode()
    fetch = FakeFetch(
        allowed=True,
        result=FetchResult(
            "https://cdn.example/talk.vtt",
            "ok",
            content=vtt,
            content_type="text/vtt",
        ),
    )
    acq = FakeAcquirer()
    # Transcript reader needs asset bytes — wire fake assets that return the VTT
    # after acquire. Simpler: use ingest_url fetch ok then process with transcript
    # reader backed by assets holding the same bytes.
    assets = _FakeAssets(vtt, kind=ASSET_KIND_TRANSCRIPT, filename="talk.vtt")
    arts = _FakeArtifacts()
    know = _FakeKnowledge()

    class BridgingAcquirer(FakeAcquirer):
        def acquire_bytes(self, data, **kw):
            assets._data = data if isinstance(data, (bytes, bytearray)) else bytes(data)
            assets._asset["kind"] = kw.get("kind")
            assets._asset["metadata"] = {"filename": kw.get("filename"), **(kw.get("metadata") or {})}
            return super().acquire_bytes(data, **kw)

    bridge = BridgingAcquirer()
    fetcher = SourceFetcher(bridge, fetch)
    ingestor = MediaIngestor(
        bridge,
        know,
        metadata_reader=MediaMetadataReader(assets, arts, probe=lambda p: {}),
        transcript_reader=TranscriptFileReader(assets, arts),
        source_fetcher=fetcher,
    )
    out = ingestor.ingest_url("https://cdn.example/talk.vtt", embed=False)
    assert out["fetch"]["ok"] is True
    assert out["ingest"]["document_id"] == "doc-1"
    assert "Hello from CDN" in know.calls[0]["content"]
    assert "youtube" not in know.calls[0]["content"].lower()
    assert know.calls[0]["source"] == "media_transcript"


def test_ingest_url_robots_blocked_zero_knowledge():
    fetch = FakeFetch(allowed=False)
    know = _FakeKnowledge()
    ingestor = MediaIngestor(
        FakeAcquirer(),
        know,
        source_fetcher=SourceFetcher(FakeAcquirer(), fetch),
    )
    out = ingestor.ingest_url("https://cdn.example/nope.mp4", embed=False)
    assert out["outcome"] == "blocked"
    assert out["operator_hint"] == OPERATOR_HINT
    assert out["ingest"] is None
    assert know.calls == []
