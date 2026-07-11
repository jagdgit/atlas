"""Tests for the memory system (Sprint 6).

Model + service are tested hermetically with fakes (no DB/Ollama). Repository
tests require a live PostgreSQL with migration 0008 applied and are skipped when
the database is unreachable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from atlas.database.connection import DatabaseManager
from atlas.llm.provider import EmbeddingResponse
from atlas.models import MemoryItem
from atlas.repositories.memory_repo import MemoryRepository
from atlas.services.memory_service import MemoryService


# --- model ----------------------------------------------------------------
def test_memory_item_from_row_and_to_dict():
    row = {
        "id": uuid.uuid4(),
        "kind": "semantic",
        "scope": "global",
        "content": "the sky is blue",
        "importance": 0.5,
        "metadata": {"tag": "fact"},
        "occurred_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    item = MemoryItem.from_row(row)
    assert item.kind == "semantic"
    assert item.content == "the sky is blue"
    assert item.metadata == {"tag": "fact"}
    assert isinstance(item.id, str)  # UUID coerced to str
    assert item.to_dict()["kind"] == "semantic"


# --- service (fakes) -------------------------------------------------------
class FakeLLM:
    def __init__(self):
        self.embed_calls = 0

    def embed(self, texts, **options):
        self.embed_calls += 1
        return EmbeddingResponse(vectors=[[0.1] * 768 for _ in texts], model="fake")


class FakeMemoryRepo:
    def __init__(self):
        self.added = []
        self.search_result = []
        self.pruned = 0
        self.forgot = None

    def add(self, kind, content, **kwargs):
        self.added.append({"kind": kind, "content": content, **kwargs})
        return MemoryItem(
            id=str(uuid.uuid4()),
            kind=kind,
            content=content,
            scope=kwargs.get("scope", "global"),
            embedding_model=kwargs.get("embedding_model"),
            importance=kwargs.get("importance", 0.0),
            metadata=kwargs.get("metadata") or {},
            expires_at=kwargs.get("expires_at"),
        )

    def semantic_search(self, vector, *, kind=None, scope=None, limit=5):
        return self.search_result

    def recent(self, *, kind=None, scope=None, limit=20):
        return self.search_result

    def forget(self, memory_id):
        self.forgot = memory_id
        return True

    def prune_expired(self):
        return self.pruned


def _service(repo, llm, **kw):
    return MemoryService(repo, llm, embedding_model="fake", **kw)


def test_remember_semantic_embeds_and_stores():
    repo, llm = FakeMemoryRepo(), FakeLLM()
    svc = _service(repo, llm)
    item = svc.remember("Atlas is an AI OS", kind="semantic")
    assert llm.embed_calls == 1
    assert repo.added[0]["embedding"] is not None
    assert repo.added[0]["embedding_model"] == "fake"
    assert item.kind == "semantic"


def test_remember_working_gets_ttl_and_no_embed_by_default():
    repo, llm = FakeMemoryRepo(), FakeLLM()
    svc = _service(repo, llm, working_ttl_seconds=60)
    svc.remember("temporary note", kind="working")
    assert llm.embed_calls == 0
    assert repo.added[0]["embedding"] is None
    expires = repo.added[0]["expires_at"]
    assert expires is not None and expires > datetime.now(timezone.utc)


def test_remember_explicit_ttl_overrides():
    repo, llm = FakeMemoryRepo(), FakeLLM()
    svc = _service(repo, llm)
    svc.remember("expiring fact", kind="semantic", ttl_seconds=10)
    assert repo.added[0]["expires_at"] is not None


def test_recall_applies_similarity_floor():
    repo, llm = FakeMemoryRepo(), FakeLLM()
    repo.search_result = [
        MemoryItem(id="a", kind="semantic", content="hit", similarity=0.9),
        MemoryItem(id="b", kind="semantic", content="weak", similarity=0.1),
    ]
    svc = _service(repo, llm, similarity_floor=0.5)
    results = svc.recall("query")
    assert [r.id for r in results] == ["a"]


def test_forget_and_prune_passthrough():
    repo, llm = FakeMemoryRepo(), FakeLLM()
    repo.pruned = 3
    svc = _service(repo, llm)
    assert svc.forget("xyz") is True
    assert repo.forgot == "xyz"
    assert svc.prune() == 3


def test_health_reports_count():
    class CountingRepo(FakeMemoryRepo):
        def count(self):
            return 7

    svc = _service(CountingRepo(), FakeLLM())
    status = svc.health_check()
    assert status.healthy is True
    assert "7" in status.detail


# --- repository (integration; skipped without a live DB) -------------------
@pytest.fixture(scope="module")
def db():
    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def test_memory_repo_roundtrip(db):
    repo = MemoryRepository(db)
    vector = [0.05] * 768
    item = repo.add(
        "semantic",
        "integration test memory",
        embedding=vector,
        embedding_model="test",
        importance=0.7,
        metadata={"origin": "test"},
    )
    try:
        assert repo.get(item.id) is not None
        hits = repo.semantic_search(vector, kind="semantic", limit=5)
        assert any(h.id == item.id for h in hits)
        assert hits[0].similarity is not None
        assert any(r.id == item.id for r in repo.recent(kind="semantic", limit=50))
    finally:
        assert repo.forget(item.id) is True
        assert repo.get(item.id) is None


def test_memory_repo_prune_expired(db):
    repo = MemoryRepository(db)
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    item = repo.add("working", "already expired", expires_at=past)
    # Expired rows are excluded from recall even before a prune.
    assert all(r.id != item.id for r in repo.recent(kind="working", limit=100))
    removed = repo.prune_expired()
    assert removed >= 1
    assert repo.get(item.id) is None
