"""C.3g: document → candidate → Consolidator → finding, and the P11 enforcement.

Prose readers/extractors emit CANDIDATES only; the CandidateConsumer is the single component that
turns them into findings via the Consolidator. These tests prove the pipeline, its cumulative dedup
(P13), and that the ingestion bridge never writes findings directly (P11).
"""

from __future__ import annotations

from atlas.knowledge.candidate_consumer import CandidateConsumer, InMemoryCandidateStore
from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.knowledge.prose_extraction import ProseKnowledgeExtractor
from atlas.ingestion.service import IngestionService
from tests.test_ingestion_bridge import FakeAcquirer, FakeKnowledge, FakeReader, _acquired, _artifact

_DOC = (
    "Atlas keeps knowledge global rather than scoped to a single mission or job. "
    "The Knowledge Consolidator merges corroborating evidence into one cumulative finding. "
    "Readers are stateless translators and never write findings directly.\n\n"
    "Short bit.\n"
    "Atlas keeps knowledge global rather than scoped to a single mission or job."  # dup sentence
)


# --- extractor -----------------------------------------------------------
def test_extractor_returns_bounded_candidates_only():
    extractor = ProseKnowledgeExtractor(max_claims=2)
    cands = extractor.extract(_DOC, evidence_ref={"asset_id": "a1", "source": "document"})
    assert len(cands) == 2                       # bounded by max_claims
    assert all(c["claim_type"] == "prose" for c in cands)
    assert all("id" not in c for c in cands)     # candidate payloads, not findings
    assert all(c["evidence_ref"]["asset_id"] == "a1" for c in cands)


def test_extractor_drops_trivial_and_duplicate_sentences():
    extractor = ProseKnowledgeExtractor(max_claims=12)
    cands = extractor.extract(_DOC, evidence_ref={"asset_id": "a1"})
    statements = [c["statement"] for c in cands]
    assert "Short bit." not in statements               # too short
    assert len(statements) == len(set(statements))       # de-duplicated


# --- consumer ------------------------------------------------------------
def test_consumer_consolidates_candidates_and_marks_consumed():
    store = InMemoryCandidateStore()
    findings = InMemoryFindingStore()
    consumer = CandidateConsumer(store, KnowledgeLifecycleService(findings))

    extractor = ProseKnowledgeExtractor(max_claims=3)
    consumer.emit_many(extractor.extract(_DOC, evidence_ref={"asset_id": "a1", "source": "document"}))
    assert len(store.list_pending()) == 3

    results = consumer.consume_pending()
    assert all(r["transition"] == "create" for r in results)
    assert len(findings.rows) == 3
    assert store.list_pending() == []            # all consumed
    assert all(r["consolidated_finding_id"] for r in store.rows.values())


def test_same_fact_from_two_assets_becomes_one_cumulative_finding():
    store = InMemoryCandidateStore()
    findings = InMemoryFindingStore()
    consumer = CandidateConsumer(store, KnowledgeLifecycleService(findings))

    stmt = "Atlas keeps knowledge global rather than scoped to a mission."
    consumer.emit({"statement": stmt, "domain": "external", "evidence_ref": {"asset_id": "a1"}})
    consumer.emit({"statement": stmt, "domain": "external", "evidence_ref": {"asset_id": "a2"}})

    results = consumer.consume_pending()
    transitions = [r["transition"] for r in results]
    assert transitions[0] == "create"
    assert transitions[1] == "merge_evidence"    # same fact, different source → strengthen in place
    assert len(findings.rows) == 1               # one finding, not two
    head = next(iter(findings.rows.values()))
    assert len(head["supporting"]) == 2          # two evidence entries
    assert head["confidence"] == "MEDIUM"        # corroboration grew confidence


# --- P11 enforcement: the bridge emits candidates, never findings --------
def test_ingestion_emits_candidates_not_findings():
    findings = InMemoryFindingStore()
    consolidator = KnowledgeLifecycleService(findings)
    candidate_store = InMemoryCandidateStore()
    consumer = CandidateConsumer(candidate_store, consolidator)
    extractor = ProseKnowledgeExtractor(max_claims=5)

    ingestion = IngestionService(
        FakeAcquirer(_acquired()),
        FakeReader(_artifact(text=_DOC)),
        FakeKnowledge({"document_id": "d1", "chunks": 3, "deduped": False}),
        extractor=extractor,
        candidates=consumer,
    )

    result = ingestion.ingest_bytes(b"raw bytes", filename="note.txt", extract_findings=True)
    assert result.ok
    assert result.candidates > 0
    # The bridge/readers wrote ZERO findings — only candidates (P11).
    assert len(findings.rows) == 0
    assert len(candidate_store.list_pending()) == result.candidates

    # Findings appear ONLY once the Consolidator drains the inbox.
    consumer.consume_pending()
    assert len(findings.rows) == result.candidates


def test_ingestion_without_extractor_emits_no_candidates():
    ingestion = IngestionService(
        FakeAcquirer(_acquired()),
        FakeReader(_artifact(text=_DOC)),
        FakeKnowledge({"document_id": "d1", "chunks": 3}),
    )
    # extract_findings defaults off, and no extractor/consumer wired → C.2 behavior unchanged.
    result = ingestion.ingest_bytes(b"raw bytes", filename="note.txt", extract_findings=True)
    assert result.ok
    assert result.candidates == 0
