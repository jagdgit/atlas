"""OI-LAB-LOOP0 Step 10 — findings are a first-class RAG tier, not chunk smash."""

from __future__ import annotations

from atlas.knowledge.access import TIER_FINDINGS, TIER_KNOWLEDGE
from tests.test_knowledge import _cosine_distance, _service


class FakeFindingEmb:
    def __init__(self):
        self.vectors = {}
        self.meta = {}
        self.upserts = []

    def upsert(self, finding_id, model, vector):
        self.upserts.append(str(finding_id))
        self.vectors[(str(finding_id), model)] = list(vector)
        return {"finding_id": str(finding_id), "model": model}

    def search(self, query_vector, model, *, domains=None, limit=3):
        rows = []
        for (fid, m), vec in self.vectors.items():
            if m != model:
                continue
            meta = self.meta.get(fid, {})
            if meta.get("status", "active") not in {"active", "contested"}:
                continue
            if domains is not None and meta.get("domain", "external") not in domains:
                continue
            rows.append(
                {
                    "finding_id": fid,
                    "canonical_id": meta.get("canonical_id", fid),
                    "statement": meta.get("statement", ""),
                    "domain": meta.get("domain", "external"),
                    "created_at": meta.get("created_at"),
                    "distance": _cosine_distance(query_vector, vec),
                }
            )
        rows.sort(key=lambda r: r["distance"])
        return rows[:limit]


class FakeFindingRepo:
    def __init__(self):
        self.rows = []

    def search_lexical(self, query, *, limit=5, domains=None, include_archive=False):
        del include_archive
        q = {t for t in (query or "").lower().split() if t}
        out = []
        for row in self.rows:
            if domains is not None and row.get("domain", "external") not in domains:
                continue
            tokens = {t for t in str(row.get("statement") or "").lower().split() if t}
            overlap = len(q & tokens)
            if overlap <= 0:
                continue
            out.append({**row, "rank": float(overlap)})
        out.sort(key=lambda r: -r["rank"])
        return out[:limit]


def _wire_finding(svc, statement="validated finding: cats purr", finding_id="f-cat"):
    repo = FakeFindingRepo()
    repo.rows.append(
        {
            "finding_id": finding_id,
            "canonical_id": "F-000001",
            "statement": statement,
            "domain": "external",
            "status": "active",
            "created_at": "2026-09-18T12:25:31.703825+00:00",
        }
    )
    emb = FakeFindingEmb()
    vec = svc._llm.embed([statement], model="fake-embed").vectors[0]
    emb.meta[finding_id] = repo.rows[0]
    emb.upsert(finding_id, "fake-embed", vec)
    svc._findings = repo
    svc._finding_embeddings = emb
    return repo, emb


def test_retrieve_findings_tier_does_not_write_chunks():
    svc, _docs, chunks, embs = _service()
    _wire_finding(svc)
    n_chunk_vecs = len(embs.vectors)
    n_chunks = sum(len(v) for v in chunks.by_doc.values())
    ranked = svc.retrieve("cats", k=3, role="chat", mode="hybrid")
    assert ranked.meta["finding_candidates"] >= 1
    assert any(h.tier == TIER_FINDINGS for h in ranked.hits)
    assert any("cats purr" in h.content for h in ranked.hits)
    assert all(h.chunk_id.startswith("finding:") for h in ranked.hits if h.tier == TIER_FINDINGS)
    assert len(embs.vectors) == n_chunk_vecs
    assert sum(len(v) for v in chunks.by_doc.values()) == n_chunks


def test_knowledge_only_tiers_skip_findings():
    svc, _docs, chunks, embs = _service()
    cat = svc.ingest_text("note", "the cat sat on the mat")
    for ch in chunks.list_for_document(cat["document_id"]):
        embs.register_chunk(ch["id"], ch["document_id"], ch["ordinal"], ch["content"])
    _wire_finding(svc, statement="validated finding: cats purr")
    ranked = svc.retrieve(
        "cats", k=3, role="chat", mode="hybrid", tiers=["knowledge"]
    )
    assert TIER_FINDINGS not in ranked.tiers
    assert all(h.tier == TIER_KNOWLEDGE for h in ranked.hits)
    assert ranked.meta["finding_candidates"] == 0


def test_findings_only_retrieve_uses_finding_index():
    svc, _docs, _chunks, embs = _service()
    _wire_finding(svc)
    ranked = svc.retrieve(
        "cats", k=2, role="chat", mode="dense", tiers=["findings"]
    )
    assert ranked.hits
    assert ranked.hits[0].tier == TIER_FINDINGS
    assert ranked.hits[0].chunk_id.startswith("finding:")
    assert not embs.vectors


def test_default_retrieve_includes_findings_and_documents():
    svc, _docs, chunks, embs = _service()
    doc = svc.ingest_text("note", "the car drove down the road")
    for ch in chunks.list_for_document(doc["document_id"]):
        embs.register_chunk(ch["id"], ch["document_id"], ch["ordinal"], ch["content"])
    _wire_finding(svc, statement="validated finding: cats purr")
    ranked = svc.retrieve("cats", k=5, role="chat", mode="hybrid")
    tiers = {h.tier for h in ranked.hits}
    assert TIER_FINDINGS in ranked.meta["live_tiers"]
    assert TIER_KNOWLEDGE in ranked.meta["live_tiers"]
    assert TIER_FINDINGS in tiers
    assert ranked.meta["finding_candidates"] >= 1
