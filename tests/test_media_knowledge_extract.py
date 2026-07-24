"""KE.0–KE.2 — Knowledge metrics honesty + typed media extraction."""

from __future__ import annotations

from atlas.ingestion.media_learn import (
    MediaLearnOrchestrator,
    build_knowledge_breakdown,
    format_knowledge_breakdown,
)
from atlas.knowledge.candidate_consumer import CandidateConsumer, InMemoryCandidateStore
from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.knowledge.lifecycle import finding_identity_key
from atlas.knowledge.media_extraction import (
    ConceptLexicon,
    MediaKnowledgeExtractor,
    build_extraction_quality,
    count_candidates_by_type,
)
from atlas.readers.media_kinds import ASSET_KIND_AUDIO
from atlas.reports.generator import LEARNING_STATUS_COMPLETE, ReportGenerator

_TRANSCRIPT = (
    "Inflation reduces purchasing power over time for households. "
    "Robert Kiyosaki argues that assets are preferred over liabilities. "
    "Rich Dad Poor Dad written by Robert Kiyosaki teaches cash flow thinking. "
    "The current monetary system can create poverty for the middle class. "
    "Cash flow from investments matters more than earned salary alone. "
    "Buy assets that put money in your pocket every month steadily."
)


class FakeSpeechMedia:
    """Asset + STT transcript + RAG ingest (chunks), no semantic extract of its own."""

    def ingest_url(self, url, **kwargs):
        return {
            "outcome": "ok",
            "asset_id": "asset-stt-1",
            "asset_version": 1,
            "kind": ASSET_KIND_AUDIO,
            "filename": "media.m4a",
            "text": _TRANSCRIPT,
            "fetch": {
                "outcome": "ok",
                "asset_id": "asset-stt-1",
                "kind": ASSET_KIND_AUDIO,
                "bytes_read": 1000,
                "reason_code": "ok",
                "strategies_tried": [
                    {
                        "name": "youtube_media",
                        "outcome": "ok",
                        "reason_code": "ok",
                        "bytes_read": 1000,
                    },
                ],
            },
            "metadata": {"outcome": "ok", "fields": {"title": "Investing talk"}},
            "speech": {"outcome": "ok", "reason": "ok", "reason_code": "ok"},
            "ingest": {
                "outcome": "ok",
                "document_id": "doc-1",
                "chunks": 71,
                "source_id": "youtube:zHt5",
            },
        }


def test_ke0_format_breakdown_separates_chunks_from_categories():
    bd = build_knowledge_breakdown(
        metadata_artifacts=1,
        transcript_artifacts=1,
        transcript_chunks=71,
        concepts=4,
        entities=2,
        relationships=2,
        facts=1,
        claims=5,
    )
    text = format_knowledge_breakdown(bd, knowledge_produced=71)
    assert "RAG transcript chunks: 71" in text
    assert "not equal to chunk total" in text
    assert "claims" in text
    assert "concepts" in text


def test_ke0_learning_report_labels_rag_chunks():
    report = ReportGenerator().generate(
        "learn investing video",
        termination={
            "mode": "learning",
            "learning_status": LEARNING_STATUS_COMPLETE,
            "knowledge_produced": 71,
            "knowledge_breakdown": {
                "metadata": 1,
                "transcript": 1,
                "transcript_chunks": 71,
                "concepts": 4,
                "entities": 2,
                "relationships": 2,
                "facts": 1,
                "claims": 5,
                "summaries": 0,
            },
            "source": "https://youtu.be/zHt5Mdr0QFk",
            "asset_id": "a1",
            "stages": {
                "acquire": "success",
                "metadata": "success",
                "transcript": "success",
                "speech": "success",
                "knowledge": "success",
            },
        },
    )
    md = report["markdown"]
    assert "Knowledge Produced (RAG transcript chunks): **71**" in md
    assert "do not sum to RAG chunk total" in md
    assert "| transcript_chunks (RAG) | 71 |" in md
    assert "| facts (structured) | 1 |" in md
    assert "| claims (speaker assertions) | 5 |" in md
    assert "| concepts | 4 |" in md
    assert "concepts=4" in report["sections"]["executive_summary"]
    assert "claims=5" in report["sections"]["executive_summary"]


def test_concept_lexicon_layers_union():
    lex = ConceptLexicon(builtin={"inflation"}, user={"sovereignty"}, domain={"rupee"})
    lex = lex.with_planner(["financial freedom"])
    all_c = lex.all_concepts()
    assert "inflation" in all_c
    assert "sovereignty" in all_c
    assert "rupee" in all_c
    assert "financial freedom" in all_c


def test_q5_extractor_omits_confidence_scores():
    """Extractor emits observations only — no scored confidence (KE5 / Q5)."""
    extractor = MediaKnowledgeExtractor(max_claims=4)
    payloads = extractor.extract(_TRANSCRIPT, evidence_ref={"asset_id": "a1"})
    assert payloads
    for p in payloads:
        assert "confidence" not in p
        assert "confidence_score" not in p
        assert p["value"].get("epistemic") in {
            "concept",
            "entity",
            "relationship",
            "fact",
            "claim",
        }
        assert "speaker" in p["value"]
        assert "timestamp" in p["value"]

    store = InMemoryCandidateStore()
    findings = InMemoryFindingStore()
    consumer = CandidateConsumer(store, KnowledgeLifecycleService(findings))
    emitted = consumer.emit_many(payloads)
    for c in emitted:
        consumer.consume(c)
    for row in findings.rows.values():
        assert row["confidence"] == "UNVERIFIED"
        assert float(row["confidence_score"] or 0) == 0.0


def test_user_lexicon_layer_affects_concepts():
    lex = ConceptLexicon().with_user(["sovereignty"])
    extractor = MediaKnowledgeExtractor(lexicon=lex, max_claims=2)
    text = "Monetary sovereignty matters for national currency policy in practice today."
    payloads = extractor.extract(text)
    concepts = [
        p["value"]["name"]
        for p in payloads
        if p["claim_type"] == "concept"
    ]
    assert "sovereignty" in concepts


def test_media_extractor_emits_typed_candidates():
    extractor = MediaKnowledgeExtractor(max_claims=6)
    payloads = extractor.extract(_TRANSCRIPT, evidence_ref={"asset_id": "a1"})
    counts = count_candidates_by_type(payloads)
    assert counts["concepts"] >= 3
    assert counts["entities"] >= 1
    assert counts["relationships"] >= 1
    assert counts["facts"] >= 1
    assert counts["claims"] >= 1
    types = {p["claim_type"] for p in payloads}
    assert "concept" in types
    assert "entity" in types
    assert "relationship" in types
    assert "fact" in types
    assert "claim" in types


def test_typed_identity_keys_do_not_collide():
    concept = {
        "claim_type": "concept",
        "domain": "external",
        "statement": "Concept: Inflation",
        "value": {"kind": "concept", "name": "inflation"},
    }
    claim = {
        "claim_type": "claim",
        "domain": "external",
        "statement": "Inflation reduces purchasing power over time for households.",
        "value": {"kind": "claim"},
    }
    assert finding_identity_key(concept) != finding_identity_key(claim)
    assert finding_identity_key(concept)[0] == "typed"
    assert finding_identity_key(concept)[2] == "concept"


def test_ke2_speech_path_extracts_typed_knowledge():
    store = InMemoryCandidateStore()
    findings = InMemoryFindingStore()
    consumer = CandidateConsumer(store, KnowledgeLifecycleService(findings))
    orch = MediaLearnOrchestrator(
        media_ingestor=FakeSpeechMedia(),
        extractor=MediaKnowledgeExtractor(max_claims=6),
        candidates=consumer,
        speech_status=lambda: "ready",
    )
    result = orch.learn("https://youtu.be/zHt5Mdr0QFk")
    assert result["outcome"] == "ok"
    assert result["knowledge_produced"] == 71
    bd = result["knowledge_breakdown"]
    assert bd["transcript"] == 1
    assert bd["transcript_chunks"] == 71
    assert bd["metadata"] == 1
    assert bd["concepts"] >= 1
    assert bd["entities"] >= 1
    assert bd["relationships"] >= 1
    assert bd["facts"] >= 1
    assert bd["claims"] >= 1
    assert any(a["strategy"] == "knowledge_extract" for a in result["strategies"])
    assert any(a.get("reason_code") == "typed_extracted" for a in result["strategies"])
    assert len(findings.rows) >= (
        bd["concepts"] + bd["entities"] + bd["relationships"] + bd["facts"] + bd["claims"]
    )
    preview = result.get("knowledge_preview") or {}
    assert preview.get("concepts")
    assert preview.get("claims")
    quality = result.get("extraction_quality") or {}
    assert int(quality.get("candidates_emitted") or 0) >= 1
    assert "claims_linked" in quality


def test_claim_graph_links_related_concepts():
    extractor = MediaKnowledgeExtractor(max_claims=6)
    payloads = extractor.extract(_TRANSCRIPT)
    claims = [p for p in payloads if p["claim_type"] == "claim"]
    assert claims
    quality = build_extraction_quality(_TRANSCRIPT, payloads)
    assert quality["claims_linked"] >= 1
    assert quality["claims_orphan"] < quality["by_type"]["claims"]
    linked = [
        c
        for c in claims
        if (c.get("value") or {}).get("related_concepts")
        or (c.get("value") or {}).get("related_entities")
    ]
    assert linked, "expected at least one claim linked to concepts/entities"
    assert any((c.get("value") or {}).get("links") for c in linked)
    # Speaker should count as an entity link even when not repeated in the sentence.
    assert any(
        "Robert Kiyosaki" in ((c.get("value") or {}).get("related_entities") or [])
        for c in claims
    )


def test_south_africa_is_place_not_person():
    text = (
        "Investors met in South Africa to discuss inflation and cash flow strategies. "
        "Robert Kiyosaki argued assets are preferred over liabilities for households."
    )
    extractor = MediaKnowledgeExtractor(max_claims=2)
    payloads = extractor.extract(text)
    entities = {
        (p["value"]["name"], p["value"]["entity_type"])
        for p in payloads
        if p["claim_type"] == "entity"
    }
    assert ("South Africa", "place") in entities
    assert ("South Africa", "person") not in entities


def test_relationship_spo_rejects_clause_fragments():
    text = (
        "They're going to print as much money as they need tomorrow morning. "
        "Inflation reduces purchasing power for the middle class over time. "
        "Entrepreneurship creates wealth when cash flow compounds steadily. "
        "What baffles me is that teaches nothing useful about investing today."
    )
    extractor = MediaKnowledgeExtractor(max_claims=2)
    payloads = extractor.extract(text)
    rels = [p for p in payloads if p["claim_type"] == "relationship"]
    assert rels
    for rel in rels:
        value = rel["value"]
        subj = str(value.get("subject") or "")
        obj = str(value.get("object") or "")
        assert len(subj.split()) <= 4
        assert len(obj.split()) <= 4
        assert "going to" not in subj.lower()
        assert "baffles" not in subj.lower()
        assert "what " not in subj.lower()
        assert value.get("predicate") in {
            "reduces",
            "increases",
            "creates",
            "causes",
            "protects_against",
            "leads_to",
            "depends_on",
            "enables",
            "teaches",
            "preferred_over",
            "written_by",
        }
    # Prefer structured triples like Inflation reduces Purchasing Power.
    statements = {p["statement"] for p in rels}
    assert any("reduces" in s for s in statements)
    assert not any("baffles" in s.lower() for s in statements)


def test_relationship_spo_rejects_teach_clause_fragment():
    """KE.2.5 — 'what baffles me is that teaches…' must not become an edge."""
    text = (
        "What baffles me is that teaches people to chase salary instead of assets. "
        "Assets are preferred over liabilities for long-term wealth."
    )
    extractor = MediaKnowledgeExtractor(max_claims=2)
    payloads = extractor.extract(text)
    rels = [p for p in payloads if p["claim_type"] == "relationship"]
    assert rels
    for rel in rels:
        blob = f"{rel.get('statement')} {rel['value'].get('subject')} {rel['value'].get('object')}"
        assert "baffles" not in blob.lower()
        assert "what baffles" not in blob.lower()
    preds = {(p.get("value") or {}).get("predicate") for p in rels}
    assert "preferred_over" in preds


def test_provenance_attached_to_claims():
    extractor = MediaKnowledgeExtractor(max_claims=6)
    payloads = extractor.extract(
        _TRANSCRIPT,
        evidence_ref={"asset_id": "asset-1", "source_url": "https://youtu.be/x"},
        duration_seconds=4119.0,
    )
    claims = [p for p in payloads if p["claim_type"] == "claim"]
    assert claims
    for claim in claims:
        value = claim["value"]
        assert value.get("asset_id") == "asset-1"
        assert value.get("source_url") == "https://youtu.be/x"
        assert value.get("status") == "UNVERIFIED"
        assert value.get("speaker") == "Robert Kiyosaki"
    # At least one claim should get a character offset / estimated timestamp.
    assert any(c["value"].get("char_start") is not None for c in claims)


def test_expanded_relationship_patterns():
    text = (
        "Gold protects against inflation for long-term savers. "
        "Entrepreneurship leads to wealth when cash flow compounds. "
        "Financial education teaches cash flow thinking to young adults."
    )
    extractor = MediaKnowledgeExtractor(max_claims=2)
    payloads = extractor.extract(text)
    rels = [p for p in payloads if p["claim_type"] == "relationship"]
    preds = {(p.get("value") or {}).get("predicate") for p in rels}
    assert "protects_against" in preds or "leads_to" in preds or "teaches" in preds
    assert len(rels) >= 2


def test_learning_report_includes_knowledge_preview():
    report = ReportGenerator().generate(
        "learn investing video",
        termination={
            "mode": "learning",
            "learning_status": LEARNING_STATUS_COMPLETE,
            "knowledge_produced": 71,
            "knowledge_breakdown": {
                "metadata": 1,
                "transcript": 1,
                "transcript_chunks": 71,
                "concepts": 24,
                "entities": 24,
                "relationships": 2,
                "facts": 0,
                "claims": 12,
                "summaries": 0,
            },
            "knowledge_preview": {
                "concepts": ["Investing", "Inflation", "Assets"],
                "entities": ["Robert Kiyosaki (person)", "Rich Dad Poor Dad (work)"],
                "claims": [
                    "Traditional education does not teach financial literacy."
                ],
                "relationships": ["assets preferred_over liabilities"],
                "facts": [],
            },
            "extraction_quality": {
                "candidates_emitted": 62,
                "caps_hit": ["concepts", "entities"],
                "claims_linked": 9,
                "claims_orphan": 3,
                "transcript_chars": 50000,
            },
            "source": "https://youtu.be/zHt5Mdr0QFk",
            "asset_id": "a1",
            "stages": {
                "acquire": "success",
                "metadata": "success",
                "transcript": "success",
                "speech": "success",
                "knowledge": "success",
            },
        },
    )
    md = report["markdown"]
    assert "### Knowledge preview" in md
    assert "**Top Concepts**" in md
    assert "Investing" in md
    assert "**Top Claims**" in md
    assert "### Extraction quality" in md
    assert "Claims linked to concepts/entities: 9" in md
    assert "not truth confidence" in md
    assert "top_concepts" in report["sections"]["observations"][0].get("label", "") or any(
        isinstance(o, dict) and o.get("label") == "top_concepts"
        for o in report["sections"]["observations"]
    )