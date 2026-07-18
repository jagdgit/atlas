"""Tests for chunking and the knowledge service.

Service logic is tested with in-memory fakes (no DB, no Ollama). Two integration
tests exercise the real stack (Postgres + Ollama) and skip if either is down.
"""

from __future__ import annotations

import dataclasses
import math

import httpx
import psycopg
import pytest

from atlas.config import get_config
from atlas.exceptions import EmbeddingMismatchError
from atlas.knowledge.chunking import chunk_text
from atlas.knowledge.service import KnowledgeService
from atlas.models import Document


# --- chunking -------------------------------------------------------------
def test_chunk_empty_text():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_single_window():
    chunks = chunk_text("one two three", max_words=10, overlap=2)
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert chunks[0].content == "one two three"
    assert chunks[0].token_count == 3


def test_chunk_multiple_with_overlap():
    words = " ".join(str(i) for i in range(10))  # "0 1 ... 9"
    chunks = chunk_text(words, max_words=4, overlap=1)
    # step = 3 -> windows [0:4], [3:7], [6:10]; last reaches the end.
    assert [c.ordinal for c in chunks] == [0, 1, 2]
    assert chunks[0].content == "0 1 2 3"
    assert chunks[1].content == "3 4 5 6"  # overlap word "3"
    assert chunks[2].content == "6 7 8 9"


def test_chunk_validation():
    with pytest.raises(ValueError):
        chunk_text("x", max_words=0)
    with pytest.raises(ValueError):
        chunk_text("x", max_words=5, overlap=5)


# --- knowledge service with fakes ----------------------------------------
class FakeDocRepo:
    def __init__(self):
        self.by_id = {}
        self.by_checksum = {}
        self._n = 0

    def create(self, source, content, *, uri=None, title=None,
               content_type="text/plain", metadata=None, domain="external"):
        import hashlib

        digest = hashlib.sha256(content.encode()).hexdigest()
        if digest in self.by_checksum:
            return self.by_checksum[digest]
        self._n += 1
        doc = Document(
            id=f"doc-{self._n}",
            source=source,
            content=content,
            checksum=digest,
            status="pending",
            domain=domain,
            title=title,
            uri=uri,
            metadata=metadata or {},
        )
        self.by_id[doc.id] = doc
        self.by_checksum[digest] = doc
        return doc

    def get(self, doc_id):
        return self.by_id.get(str(doc_id))

    def set_status(self, doc_id, status):
        doc = dataclasses.replace(self.by_id[str(doc_id)], status=status)
        self.by_id[doc.id] = doc
        self.by_checksum[doc.checksum] = doc
        return True


class FakeChunkRepo:
    def __init__(self):
        self.by_doc = {}
        self.doc_domains = {}
        self._n = 0

    def add_many(self, doc_id, chunks):
        rows = []
        for ch in chunks:
            self._n += 1
            row = {"id": f"chunk-{self._n}", "document_id": str(doc_id), **ch}
            rows.append(row)
        self.by_doc[str(doc_id)] = rows
        return rows

    def list_for_document(self, doc_id):
        return self.by_doc.get(str(doc_id), [])

    def count_for_document(self, doc_id):
        return len(self.by_doc.get(str(doc_id), []))

    def search_lexical(self, query, *, limit=5, domains=None):
        q = {t for t in (query or "").lower().split() if t}
        rows = []
        for doc_id, chunks in self.by_doc.items():
            if domains is not None:
                domain = self.doc_domains.get(str(doc_id), "external")
                if domain not in domains:
                    continue
            for ch in chunks:
                tokens = {t for t in ch["content"].lower().split() if t}
                overlap = len(q & tokens)
                if overlap <= 0:
                    continue
                rows.append(
                    {
                        "chunk_id": ch["id"],
                        "document_id": ch["document_id"],
                        "ordinal": ch["ordinal"],
                        "content": ch["content"],
                        "rank": float(overlap),
                    }
                )
        rows.sort(key=lambda r: -r["rank"])
        return rows[:limit]


def _cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 1.0
    return 1.0 - dot / (na * nb)


class FakeEmbeddingRepo:
    def __init__(self):
        self.vectors = {}  # (chunk_id, model) -> vector
        self.chunk_meta = {}  # chunk_id -> (document_id, ordinal, content)
        self.doc_domains = {}  # document_id -> domain

    def upsert(self, chunk_id, model, vector):
        self.vectors[(str(chunk_id), model)] = list(vector)
        return {"chunk_id": str(chunk_id), "model": model, "dim": len(vector)}

    def register_chunk(self, chunk_id, document_id, ordinal, content):
        self.chunk_meta[chunk_id] = (document_id, ordinal, content)

    def search(self, query_vector, model, *, limit=5, domains=None):
        rows = []
        for (chunk_id, m), vec in self.vectors.items():
            if m != model:
                continue
            if chunk_id not in self.chunk_meta:
                continue
            doc_id, ordinal, content = self.chunk_meta[chunk_id]
            if domains is not None:
                # Look up domain from a side map populated by tests (optional).
                domain = self.doc_domains.get(str(doc_id), "external")
                if domain not in domains:
                    continue
            rows.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "ordinal": ordinal,
                    "content": content,
                    "distance": _cosine_distance(query_vector, vec),
                }
            )
        rows.sort(key=lambda r: r["distance"])
        return rows[:limit]


class FakeEmbedResponse:
    def __init__(self, vectors):
        self.vectors = vectors


class FakeLLM:
    """Deterministic 3-dim embeddings keyed by simple keyword presence."""

    def __init__(self):
        self.embedding_model = "fake-embed"

    def embed(self, texts, **kw):
        vecs = []
        for t in texts:
            low = t.lower()
            vecs.append(
                [
                    1.0 if "cat" in low else 0.0,
                    1.0 if "dog" in low else 0.0,
                    1.0 if "car" in low else 0.0,
                ]
            )
        return FakeEmbedResponse(vecs)


def _service():
    docs, chunks, embs, llm = (
        FakeDocRepo(),
        FakeChunkRepo(),
        FakeEmbeddingRepo(),
        FakeLLM(),
    )
    svc = KnowledgeService(
        docs, chunks, embs, llm,
        embedding_model="fake-embed",
        chunk_max_words=5,
        chunk_overlap=1,
    )
    return svc, docs, chunks, embs


def test_ingest_creates_chunks_and_embeddings():
    svc, docs, chunks, embs = _service()
    summary = svc.ingest_text("note", "cats are great pets and cats purr often")
    doc_id = summary["document_id"]
    assert summary["status"] == "embedded"
    assert summary["chunks"] >= 1
    assert docs.get(doc_id).status == "embedded"
    assert len(embs.vectors) == chunks.count_for_document(doc_id)


def test_ingest_dedup_skips_when_already_embedded():
    svc, docs, chunks, embs = _service()
    svc.ingest_text("note", "same content here")
    n_before = len(embs.vectors)
    summary = svc.ingest_text("note", "same content here")  # identical
    assert summary["deduped"] is True
    assert len(embs.vectors) == n_before  # no re-embedding


def test_search_ranks_by_similarity():
    svc, docs, chunks, embs = _service()
    # Wire chunk metadata into the fake embedding repo so search can return content.
    r = svc.ingest_text("note", "the cat sat")
    for ch in chunks.list_for_document(r["document_id"]):
        embs.register_chunk(ch["id"], ch["document_id"], ch["ordinal"], ch["content"])
    svc2_doc = svc.ingest_text("note", "the car drove")
    for ch in chunks.list_for_document(svc2_doc["document_id"]):
        embs.register_chunk(ch["id"], ch["document_id"], ch["ordinal"], ch["content"])

    results = svc.search("cat", limit=1)
    assert results
    assert "cat" in results[0].content
    assert results[0].similarity > 0.9


def test_retrieve_hybrid_fuses_dense_and_lexical_with_scores():
    svc, docs, chunks, embs = _service()
    cat = svc.ingest_text("note", "the cat sat on the mat")
    car = svc.ingest_text("note", "the car drove down the road")
    for doc_id in (cat["document_id"], car["document_id"]):
        chunks.doc_domains[doc_id] = "external"
        for ch in chunks.list_for_document(doc_id):
            embs.register_chunk(ch["id"], ch["document_id"], ch["ordinal"], ch["content"])
            embs.doc_domains[doc_id] = "external"

    ranked = svc.retrieve("cat", k=2, role="chat", mode="hybrid", domains=["external"])
    assert ranked.mode == "hybrid"
    assert ranked.hits
    assert ranked.context.startswith("[1]")
    top = ranked.hits[0]
    assert top.rrf_score > 0
    assert top.dense_score is not None or top.lexical_score is not None
    assert "cat" in top.content


def test_retrieve_archive_excluded_by_default():
    from atlas.knowledge.access import archive_requested, normalize_tiers

    assert not archive_requested(normalize_tiers(None))
    assert archive_requested(normalize_tiers(["knowledge", "archive"]))


def test_embed_document_count_mismatch_raises():
    docs, chunks, embs = FakeDocRepo(), FakeChunkRepo(), FakeEmbeddingRepo()

    class BadLLM:
        embedding_model = "fake-embed"

        def embed(self, texts, **kw):
            return FakeEmbedResponse([[1.0, 0.0, 0.0]])  # always one vector

    svc = KnowledgeService(docs, chunks, embs, BadLLM(), embedding_model="fake-embed")
    doc = docs.create("note", "a b c d e f g h")
    chunks.add_many(doc.id, [
        {"ordinal": 0, "content": "a b"},
        {"ordinal": 1, "content": "c d"},
    ])
    with pytest.raises(EmbeddingMismatchError):
        svc.embed_document(doc.id)
    assert docs.get(doc.id).status == "failed"


# --- integration: real Postgres + Ollama ---------------------------------
def _stack_or_skip():
    conninfo = get_config().database.conninfo
    try:
        with psycopg.connect(conninfo, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    host = get_config().llm.host
    try:
        httpx.get(f"{host}/api/tags", timeout=2.0).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ollama unreachable: {exc}")


def _knowledge_service_real():
    from atlas.database.connection import DatabaseManager
    from atlas.llm.ollama_provider import OllamaProvider
    from atlas.llm.service import LLMService
    from atlas.repositories.chunk_repo import ChunkRepository
    from atlas.repositories.document_repo import DocumentRepository
    from atlas.repositories.embedding_repo import EmbeddingRepository

    cfg = get_config()
    db = DatabaseManager()
    provider = OllamaProvider(
        host=cfg.llm.host,
        model=cfg.llm.model,
        embedding_model=cfg.llm.embedding_model,
    )
    llm = LLMService(
        provider, model=cfg.llm.model, embedding_model=cfg.llm.embedding_model
    )
    svc = KnowledgeService(
        DocumentRepository(db),
        ChunkRepository(db),
        EmbeddingRepository(db),
        llm,
        embedding_model=cfg.llm.embedding_model,
    )
    return svc, db, provider, DocumentRepository(db)


def test_integration_ingest_and_search():
    _stack_or_skip()
    svc, db, provider, doc_repo = _knowledge_service_real()
    # Skip if the embedding model isn't installed.
    if not any(
        provider_model.startswith(get_config().llm.embedding_model)
        for provider_model in provider.list_models()
    ):
        provider.close()
        db.close()
        pytest.skip("embedding model not installed")

    text = (
        "Atlas is a personal knowledge system. It stores documents, splits them "
        "into chunks, and embeds them for semantic search. The scheduler runs "
        "background tasks with retries and crash recovery."
    )
    summary = svc.ingest_text("test_kb", text, title="atlas overview")
    doc_id = summary["document_id"]
    try:
        assert summary["status"] == "embedded"
        assert summary["chunks"] >= 1
        results = svc.search("How does Atlas run background jobs?", limit=3)
        assert results
        assert results[0].similarity > 0.3
        assert "scheduler" in " ".join(r.content for r in results).lower()
    finally:
        doc_repo.delete(doc_id)
        provider.close()
        db.close()
