"""Tests for C.3f hybrid identity — embedding NN dedup for prose findings.

Hermetic tests cover the Consolidator's NN branch (via a fake resolver) and the resolver's threshold
logic (via a fake embedder/repo). A live-DB test covers the pgvector search + active-only filter.
"""

from __future__ import annotations

from typing import Any

import pytest

from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.knowledge.nn_identity import EmbeddingIdentityResolver


class FakeLineage:
    def __init__(self) -> None:
        self.edges: list[dict[str, Any]] = []

    def record(self, finding_id: str, edge_type: str, **kw: Any) -> dict[str, Any]:
        self.edges.append({"finding_id": finding_id, "edge_type": edge_type, **kw})
        return {}


class FakeNN:
    """Duck-typed NN resolver: matches when a configured substring appears in the statement."""

    def __init__(self) -> None:
        self.match_map: dict[str, dict[str, Any]] = {}
        self.indexed: list[tuple[str, str]] = []
        self.resolve_calls: list[str] = []

    def resolve(self, statement: str, *, domain: str | None = None, exclude_id: str | None = None):
        self.resolve_calls.append(statement)
        for key, val in self.match_map.items():
            if key in statement:
                return val
        return None

    def index(self, finding_id: str, statement: str) -> None:
        self.indexed.append((finding_id, statement))


def _prose(statement: str, **extra: Any) -> dict[str, Any]:
    data = {
        "statement": statement,
        "domain": "external",
        "status": "active",
        "confidence": "UNVERIFIED",
        "supporting_sources": [{"source_id": "doc1"}],
        "contradicting_sources": [],
    }
    data.update(extra)
    return data


# --- consolidate NN branch ----------------------------------------------
def test_paraphrase_merges_via_nn_not_duplicate():
    store = InMemoryFindingStore()
    nn = FakeNN()
    lineage = FakeLineage()
    life = KnowledgeLifecycleService(store, lineage=lineage, nn_resolver=nn)

    a = life.consolidate(_prose("Redis is required for the cache layer"))
    assert a["_transition"] == "create"
    assert nn.indexed and nn.indexed[0][0] == a["id"]  # new finding embedding indexed

    # A paraphrase (different words, different identity_key) that NN maps to `a`.
    nn.match_map = {"depends on Redis": {"finding_id": a["id"], "similarity": 0.94}}
    b = life.consolidate(
        _prose("the system depends on Redis for caching", supporting_sources=[{"source_id": "doc2"}])
    )
    assert b["_transition"] == "merge_evidence"
    assert b["id"] == a["id"]                # merged, not duplicated
    assert len(store.rows) == 1
    assert b["statement"] == a["statement"]  # established statement kept (paraphrase not revised)
    assert len(b["supporting"]) == 2
    assert b["confidence"] == "MEDIUM"

    edge = next(
        e for e in lineage.edges
        if e["finding_id"] == a["id"] and e["edge_type"] == "supported_by"
    )
    assert edge["detail"]["nn_similarity"] == 0.94


def test_no_nn_match_creates_new_finding():
    store = InMemoryFindingStore()
    nn = FakeNN()
    life = KnowledgeLifecycleService(store, nn_resolver=nn)
    life.consolidate(_prose("Redis is required"))
    b = life.consolidate(_prose("Postgres is the primary datastore"))  # unrelated, no NN match
    assert b["_transition"] == "create"
    assert len(store.rows) == 2


def test_nn_skipped_for_structured_identity():
    store = InMemoryFindingStore()
    nn = FakeNN()
    life = KnowledgeLifecycleService(store, nn_resolver=nn)
    # A code-domain finding has a deterministic identity → NN must not be consulted.
    life.consolidate({
        "statement": "svc is a python project",
        "domain": "code",
        "status": "active",
        "confidence": "HIGH",
        "provenance": {"repo_uid": "u1", "path": "", "symbol": "", "reader": "code"},
    })
    assert nn.resolve_calls == []


# --- EmbeddingIdentityResolver threshold --------------------------------
class _FakeEmbedder:
    def embed(self, texts):
        from atlas.llm.provider import EmbeddingResponse

        return EmbeddingResponse(vectors=[[1.0, 0.0]], model="fake")


class _FakeEmbRepo:
    def __init__(self, hits):
        self._hits = hits
        self.upserts: list[tuple[str, list[float]]] = []

    def search(self, vec, model, *, domains=None, limit=3):
        return self._hits

    def upsert(self, finding_id, model, vec):
        self.upserts.append((finding_id, list(vec)))


def test_resolver_returns_match_above_threshold():
    repo = _FakeEmbRepo([{"finding_id": "F1", "canonical_id": "F-1", "distance": 0.05}])
    resolver = EmbeddingIdentityResolver(_FakeEmbedder(), repo, threshold=0.88)
    match = resolver.resolve("something", domain="external")
    assert match is not None
    assert match["finding_id"] == "F1"
    assert match["similarity"] == pytest.approx(0.95)


def test_resolver_ignores_below_threshold_and_indexes():
    repo = _FakeEmbRepo([{"finding_id": "F1", "distance": 0.4}])  # similarity 0.6 < 0.88
    resolver = EmbeddingIdentityResolver(_FakeEmbedder(), repo, threshold=0.88)
    assert resolver.resolve("something") is None
    resolver.index("F9", "a statement")
    assert repo.upserts and repo.upserts[0][0] == "F9"


# --- live DB: FindingEmbeddingRepository --------------------------------
def test_finding_embedding_search_active_only_live():
    import uuid

    from atlas.database.connection import DatabaseManager
    from atlas.repositories.finding_embedding_repo import FindingEmbeddingRepository
    from atlas.repositories.finding_repo import FindingRepository

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")

    def _vec(i: int) -> list[float]:
        v = [0.0] * 768
        v[i] = 1.0
        return v

    try:
        findings = FindingRepository(manager)
        emb = FindingEmbeddingRepository(manager)
        token = uuid.uuid4().hex
        f1 = findings.create(f"near vector one {token}", domain="external",
                             identity_key=["prose", "external", f"one-{token}"])
        f2 = findings.create(f"near vector two {token}", domain="external",
                             identity_key=["prose", "external", f"two-{token}"])
        try:
            emb.upsert(f1["id"], "nomic-embed-text", _vec(0))
            emb.upsert(f2["id"], "nomic-embed-text", _vec(1))

            # Query closest to _vec(0) → f1 ranks first.
            hits = emb.search(_vec(0), "nomic-embed-text", domains=["external"], limit=5)
            ranked = [str(h["finding_id"]) for h in hits]
            assert ranked and ranked[0] == str(f1["id"])

            # Archiving f1 removes it from the active-only NN search.
            findings.set_status(str(f1["id"]), "archived")
            hits2 = {str(h["finding_id"]) for h in emb.search(_vec(0), "nomic-embed-text", limit=50)}
            assert str(f1["id"]) not in hits2
        finally:
            findings.set_status(str(f1["id"]), "archived")
            findings.set_status(str(f2["id"]), "archived")
    finally:
        manager.close()
