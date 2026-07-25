"""OI-M3 live caption chunk ingest."""

from __future__ import annotations

from atlas.capabilities import CAP_LIVE_CAPTION_INGEST, CAPABILITY_CATALOG
from atlas.live_captions.buffer import (
    CAPABILITY_GAP,
    LIVE_OK,
    LIVE_UNAVAILABLE,
    LiveCaptionClient,
    chunks_to_transcript,
)
from atlas.readers.transcript_file import TranscriptFileReader


def test_capability_catalog():
    assert CAP_LIVE_CAPTION_INGEST in CAPABILITY_CATALOG


def test_disabled_gap():
    client = LiveCaptionClient(enabled=False)
    assert client.open()["capability_gap"] == CAPABILITY_GAP
    assert client.append("x", {"text": "hi"})["outcome"] == LIVE_UNAVAILABLE


def test_append_finalize_transcript():
    client = LiveCaptionClient(enabled=True)
    opened = client.open(session_id="live-1", title="demo")
    assert opened["outcome"] == LIVE_OK
    client.append("live-1", {"text": "Hello world", "start": 0.0, "end": 1.5})
    client.append("live-1", {"text": "Second cue", "start": 1.5, "end": 3.0, "speaker": "Host"})
    client.append("live-1", "Trailing line")
    out = client.finalize("live-1")
    assert out["outcome"] == LIVE_OK
    assert "Hello world" in out["text"]
    assert "Second cue" in out["text"]
    assert out["chunk_count"] == 3
    assert out["segments"][1]["speaker"] == "Host"
    assert out["vtt"].startswith("WEBVTT")


def test_chunks_to_transcript_helper():
    built = chunks_to_transcript([{"text": "a", "start": 0, "end": 1}])
    assert built["text"] == "a"
    assert built["segments"][0]["start"] == 0


def test_finalize_registers_asset_and_transcript_reader():
    class FakeAssets:
        def __init__(self):
            self.rows = {}

        def register(self, *, kind, name, data, content_type=None, metadata=None):
            aid = "asset-live"
            self.rows[aid] = {
                "id": aid,
                "kind": kind,
                "name": name,
                "data": data,
                "content_type": content_type,
                "metadata": metadata or {},
            }
            return {"id": aid, "version": 1}

        def get(self, asset_id):
            row = self.rows.get(asset_id)
            return dict(row) if row else None

        def get_bytes(self, asset_id, version=None):
            return self.rows[asset_id]["data"]

    class FakeArts:
        def get(self, *a):
            return None

        def put(self, *a):
            return None

    assets = FakeAssets()
    client = LiveCaptionClient(enabled=True, assets=assets)
    client.open(session_id="s2", title="stream")
    client.append("s2", {"text": "Live line one", "start": 0, "end": 2})
    fin = client.finalize("s2")
    assert fin["asset_id"] == "asset-live"
    assert assets.rows["asset-live"]["kind"] == "transcript"

    # Patch FakeAssets to look like AssetStore for TranscriptFileReader
    assets.rows["asset-live"].update(
        {
            "id": "asset-live",
            "kind": "transcript",
            "metadata": {"filename": "stream.vtt"},
        }
    )

    class _Assets:
        def get(self, asset_id):
            return assets.rows[asset_id]

        def get_bytes(self, asset_id, version=None):
            return assets.rows[asset_id]["data"]

        def get_version(self, asset_id, version=None):
            return {"version": 1, "metadata": {"filename": "stream.vtt"}}

    reader = TranscriptFileReader(_Assets(), FakeArts())
    # TranscriptFileReader needs get_version — if missing, may still work via filename
    art = reader.read("asset-live", 1, filename="stream.vtt")
    assert art.get("outcome") == "ok"
    assert "Live line one" in (art.get("text") or "")
