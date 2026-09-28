"""OI-LAB-LOOP0 Steps 8–9 — repair chunk embed drain and dense/hybrid retrieve.

Does not smash findings into the chunk index. Does not dump trades into pgvector.
Reuses the existing ``embed_document`` handler.
"""

from __future__ import annotations

from atlas.knowledge.service import KnowledgeService
from tests.test_knowledge import _service


def test_dense_retrieve_uses_embedding_search():
    svc, _docs, chunks, embs = _service()
    r = svc.ingest_text("note", "the cat sat on the mat")
    for ch in chunks.list_for_document(r["document_id"]):
        embs.register_chunk(ch["id"], ch["document_id"], ch["ordinal"], ch["content"])
    ranked = svc.retrieve("cat", k=1, role="chat", mode="dense")
    assert ranked.hits
    assert ranked.meta["dense_candidates"] >= 1
    assert "cat" in ranked.hits[0].content


def test_embed_backfill_task_reuses_embed_document():
    svc, docs, _chunks, embs = _service()
    summary = svc.ingest_text("note", "cats purr often", embed=False)
    assert summary["status"] == "chunked"
    calls = []
    svc.bind_scheduler(enqueue=lambda t, p, **kw: calls.append((t, p)))
    out = svc.embed_backfill_task({"limit": 2})
    assert calls == [("embed_document", {"document_id": summary["document_id"]})]
    assert out["enqueued"] == [summary["document_id"]]
    assert docs.get(summary["document_id"]).status == "chunked"
    assert not embs.vectors  # enqueue only — handler not run yet

    svc.embed_document_task({"document_id": summary["document_id"]})
    assert docs.get(summary["document_id"]).status == "embedded"
    assert embs.vectors


def test_backfill_does_not_touch_findings():
    """Step 8 backfill stays on document chunks. Findings are a separate index."""
    svc, _docs, _chunks, embs = _service()
    smashed = []

    class BoomFindings:
        def upsert(self, *a, **k):
            smashed.append("upsert")
            raise AssertionError("must not smash findings into chunk backfill")

        def search(self, *a, **k):
            smashed.append("search")
            return []

    svc._finding_embeddings = BoomFindings()  # noqa: SLF001
    svc._findings = object()  # noqa: SLF001
    out = svc.backfill_missing_embeddings(limit=1)
    assert "finding" not in str(out).lower()
    rows = svc._dense_rows("anything", limit=3, domains=None)
    assert isinstance(rows, list)
    assert smashed == []
    assert all(not str(k[0]).startswith("finding:") for k in embs.vectors)


def test_knowledge_service_exposes_embed_backfill_constants():
    assert KnowledgeService.EMBED_BACKFILL_LIMIT >= 1
    assert KnowledgeService.EMBED_BACKFILL_MAX_PENDING >= KnowledgeService.EMBED_BACKFILL_LIMIT
