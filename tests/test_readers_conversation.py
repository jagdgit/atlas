"""Tests for the Conversation Reader (C.8a)."""

from __future__ import annotations

import json

from atlas.readers.conversation import ConversationReader


class _FakeAssets:
    def __init__(self, data: bytes, *, filename: str):
        self._data = data
        self._filename = filename

    def get_bytes(self, asset_id, version):
        return self._data

    def versions(self, asset_id):
        return [{"version": 1, "metadata": {"filename": self._filename}}]


class _FakeArtifacts:
    def __init__(self):
        self.store = {}

    def get(self, asset_id, version, reader, reader_version):
        return self.store.get((asset_id, version, reader, reader_version))

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.store[(asset_id, version, reader, reader_version)] = artifact


def _reader(data: bytes, filename: str):
    artifacts = _FakeArtifacts()
    return ConversationReader(_FakeAssets(data, filename=filename), artifacts), artifacts


def test_reads_jsonl_transcript():
    lines = [
        json.dumps({"role": "user", "content": "How do I use Celery?"}),
        json.dumps({"role": "assistant", "content": "Celery is a task queue."}),
    ]
    reader, _ = _reader("\n".join(lines).encode(), "chat.jsonl")
    art = reader.read("a1", 1)
    assert art["outcome"] == "ok"
    assert art["messages"] == 2
    assert art["sections"][0]["role"] == "user"
    assert "Celery is a task queue." in art["text"]


def test_reads_json_messages_container():
    doc = {"title": "t", "messages": [
        {"author": "me", "text": "I built a FastAPI service."},
        {"author": "bot", "text": "Nice."},
    ]}
    reader, _ = _reader(json.dumps(doc).encode(), "export.json")
    art = reader.read("a1", 1)
    assert art["outcome"] == "ok"
    assert art["messages"] == 2
    assert art["sections"][0]["role"] == "me"


def test_reads_json_list_and_content_parts():
    doc = [
        {"role": "user", "content": [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]},
    ]
    reader, _ = _reader(json.dumps(doc).encode(), "c.json")
    art = reader.read("a1", 1)
    assert art["outcome"] == "ok"
    assert "part one" in art["text"] and "part two" in art["text"]


def test_skips_malformed_jsonl_lines_but_keeps_rest():
    raw = 'not json\n' + json.dumps({"role": "user", "content": "hi"}) + "\n{bad"
    reader, _ = _reader(raw.encode(), "c.jsonl")
    art = reader.read("a1", 1)
    assert art["outcome"] == "ok"
    assert art["messages"] == 1


def test_empty_transcript_reports_empty():
    reader, _ = _reader(json.dumps([]).encode(), "c.json")
    art = reader.read("a1", 1)
    assert art["outcome"] == "empty"
    assert art["text"] == ""


def test_unsupported_extension():
    reader, _ = _reader(b"hello", "notes.txt")
    art = reader.read("a1", 1)
    assert art["outcome"] == "unsupported"


def test_artifact_is_cached_and_reused():
    reader, artifacts = _reader(json.dumps([{"role": "u", "text": "x"}]).encode(), "c.json")
    first = reader.read("a1", 1)
    assert (("a1", 1, "conversation", "1.0.0") in artifacts.store)
    # Corrupt the backing bytes would still return cached artifact (proves cache hit).
    second = reader.read("a1", 1)
    assert second is first
