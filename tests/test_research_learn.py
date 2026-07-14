"""Tests for domain-tagged research learning (Stage 3, C6 / RS / A6)."""

from __future__ import annotations

from atlas.knowledge.domains import DOMAIN_EXTERNAL, DOMAIN_RESEARCH
from atlas.jobs.workspace import JobWorkspace
from atlas.research.learn import promote_research
from atlas.services.learning_service import _experience_from_job


class FakeKnowledge:
    def __init__(self):
        self.ingested = []

    def ingest_text(self, source, content, **kw):
        self.ingested.append({"source": source, "content": content, **kw})
        return {"document_id": f"d-{len(self.ingested)}", "status": "chunked",
                "chunks": 1, "deduped": False}


class FakeLearning:
    def __init__(self):
        self.proposed = []

    def propose(self, source_type, store, **kw):
        self.proposed.append({"source_type": source_type, "store": store, **kw})
        return {"event": {"id": f"e-{len(self.proposed)}"}, "applied": False}


def test_promote_ingests_read_docs_as_external(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "learn-1")
    ws.init_manifest(objective="soiling")
    path = ws.document_path("paper1")
    path.write_text(
        "Abstract\nWe measured soiling loss of 0.35 %/day across many sites.\n" * 2,
        encoding="utf-8",
    )
    knowledge = FakeKnowledge()
    summary = promote_research(
        knowledge=knowledge, workspace=ws, job_id="learn-1",
        objective="soiling", embed=False,
    )
    assert summary["external_docs"] == 1
    assert knowledge.ingested[0]["domain"] == DOMAIN_EXTERNAL


def test_promote_ingests_claims_as_research(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "learn-2")
    ws.init_manifest(objective="soiling")
    ws.write_json("claims.json", [
        {"id": "c1", "statement": "soiling is 0.3%/day", "confidence": "HIGH"}
    ])
    ws.write_json("evidence.json", {"sources": [], "claims": []})
    knowledge = FakeKnowledge()
    learning = FakeLearning()
    summary = promote_research(
        knowledge=knowledge, learning=learning, workspace=ws,
        job_id="learn-2", objective="soiling",
    )
    domains = [i["domain"] for i in knowledge.ingested]
    assert DOMAIN_RESEARCH in domains
    assert summary["research_docs"] >= 1
    assert learning.proposed
    assert learning.proposed[0]["store"] == "knowledge"
    assert learning.proposed[0]["payload"]["domain"] == DOMAIN_RESEARCH


def test_experience_tags_domain_and_provisional_on_low_confidence():
    payload = _experience_from_job(
        "research soiling",
        [],
        {"answer": "x", "overall_confidence": "LOW", "report_sections": {}},
        job_id="j1",
    )
    assert "experience" in payload["tags"]
    assert "provisional" in payload["tags"]
    assert payload["provisional"] is True
    assert payload["domain"] == "experience"


def test_experience_not_provisional_on_medium():
    payload = _experience_from_job(
        "research soiling",
        [],
        {"answer": "x", "overall_confidence": "MEDIUM", "report_sections": {}},
        job_id="j1",
    )
    assert "provisional" not in payload["tags"]
    assert payload["provisional"] is False


def test_ingest_text_passes_domain():
    from atlas.knowledge.service import KnowledgeService
    from atlas.models import Document
    import dataclasses
    import hashlib

    class DocRepo:
        def __init__(self):
            self.last = None
            self.by_id = {}

        def create(self, source, content, **kw):
            digest = hashlib.sha256(content.encode()).hexdigest()
            doc = Document(
                id="d1", source=source, content=content, checksum=digest,
                status="pending", domain=kw.get("domain", "external"),
            )
            self.last = kw
            self.by_id["d1"] = doc
            return doc

        def get(self, doc_id):
            return self.by_id.get(str(doc_id))

        def set_status(self, doc_id, status):
            self.by_id[str(doc_id)] = dataclasses.replace(
                self.by_id[str(doc_id)], status=status
            )

    class Chunks:
        def add_many(self, *a, **k):
            return []

        def count_for_document(self, *a):
            return 0

        def list_for_document(self, *a):
            return []

    class Emb:
        def upsert(self, *a, **k):
            return {}

    class LLM:
        def embed(self, texts, **kw):
            class R:
                vectors = [[0.0] * 3 for _ in texts]
            return R()

    docs = DocRepo()
    svc = KnowledgeService(docs, Chunks(), Emb(), LLM(), embedding_model="fake")
    svc.ingest_text("research", "hello world content here", domain=DOMAIN_RESEARCH, embed=False)
    assert docs.last["domain"] == DOMAIN_RESEARCH
