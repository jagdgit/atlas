"""Hermetic tests for knowledge verification (KV.0.5–KV.3 / KV.6)."""

from __future__ import annotations

from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.knowledge.normalize import (
    apply_entity_aliases,
    canonical_entity_key,
    display_entity_name,
)
from atlas.planner.planner import Intent, Planner
from atlas.verification.adapt import finding_row_to_claim
from atlas.verification.engine import VerificationEngine
from atlas.verification.queue import KnowledgeVerificationService
from atlas.verification.service import VerificationService


def test_alias_normalize_kiosaki():
    assert canonical_entity_key("Robert Kiosaki") == "robert kiyosaki"
    assert display_entity_name("Robert Kiosaki") == "Robert Kiyosaki"
    assert "Kiyosaki" in apply_entity_aliases("Robert Kiosaki teaches cash flow.")


def test_finding_row_to_claim_handles_media_value():
    row = {
        "id": "f1",
        "statement": "Robert Kiosaki says the rich buy assets.",
        "claim_type": "claim",
        "value": {
            "kind": "claim",
            "epistemic": "UNVERIFIED",
            "related_concepts": ["Assets"],
            "related_entities": ["Robert Kiyosaki"],
        },
        "supporting": [{"source_id": "asset-1", "evidence_level": 2, "snippet": "…"}],
        "contradicting": [],
        "provenance": {"asset_id": "asset-1", "source_url": "https://youtu.be/zHt5Mdr0QFk"},
        "confidence": "UNVERIFIED",
    }
    claim = finding_row_to_claim(row)
    assert claim.value is None  # media value is not ClaimValue
    assert "Kiyosaki" in claim.statement
    assert claim.confidence == "UNVERIFIED"
    assert len(claim.supporting) == 1
    # Engine must accept the claim without KeyError.
    VerificationEngine().verify_claim(claim)
    assert claim.confidence in {"HIGH", "MEDIUM", "LOW", "INSUFFICIENT"}


def test_verify_batch_writeback_and_report_shape():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    row = life.consolidate(
        {
            "statement": "The rich buy assets.",
            "claim_type": "claim",
            "domain": "external",
            "confidence": "UNVERIFIED",
            "confidence_score": 0,
            "value": {
                "kind": "claim",
                "related_concepts": ["Assets", "Cash Flow"],
                "related_entities": ["Robert Kiyosaki"],
            },
            "supporting_sources": [
                {
                    "source_id": "yt-1",
                    "evidence_level": 2,
                    "snippet": "The rich buy assets.",
                }
            ],
            "provenance": {
                "asset_id": "a1",
                "source_url": "https://youtu.be/zHt5Mdr0QFk",
            },
        }
    )
    # A peer finding that can corroborate via shared concepts (KV.3).
    life.consolidate(
        {
            "statement": "Assets produce cash flow over time.",
            "claim_type": "claim",
            "domain": "external",
            "confidence": "MEDIUM",
            "confidence_score": 0.5,
            "value": {"kind": "claim", "related_concepts": ["Assets", "Cash Flow"]},
            "supporting_sources": [
                {"source_id": "blog-1", "evidence_level": 2, "snippet": "Assets…"}
            ],
            "provenance": {"source": "blog"},
        }
    )

    svc = KnowledgeVerificationService(store, VerificationService(VerificationEngine()))
    pending = svc.list_pending(asset_id="a1")
    assert len(pending) == 1
    assert pending[0]["id"] == row["id"]

    out = svc.verify_batch(asset_id="a1", limit=5)
    assert out["verification"] == "executed"
    assert out["selected"] == 1
    assert out["before_after"]
    updated = store.get(row["id"])
    assert updated["confidence"] != "UNVERIFIED"
    assert updated["last_verified"]
    assert (updated.get("quality") or {}).get("trust", {}).get("verification_label")


def test_verify_with_gather_stub_adds_evidence():
    from atlas.evidence.models import EvidenceItem

    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    row = life.consolidate(
        {
            "statement": "Inflation reduces purchasing power for households.",
            "claim_type": "claim",
            "confidence": "UNVERIFIED",
            "value": {"kind": "claim", "related_concepts": ["Inflation"]},
            "supporting_sources": [
                {"source_id": "yt-1", "evidence_level": 2, "snippet": "Inflation…"}
            ],
            "provenance": {
                "asset_id": "a2",
                "source_url": "https://youtu.be/zHt5Mdr0QFk",
            },
        }
    )

    def stub_gather(claim, *, max_iterations=3, **_):
        claim.evidence.append(
            EvidenceItem(
                source_id="stub:gov-1",
                evidence_level=3,
                snippet="BLS inflation erodes purchasing power.",
            )
        )
        claim.evidence.append(
            EvidenceItem(
                source_id="stub:peer-1",
                evidence_level=4,
                snippet="Peer-reviewed: inflation reduces real wages.",
            )
        )
        return {"outcome": "ok", "added": 2, "iterations": min(2, max_iterations)}

    svc = KnowledgeVerificationService(
        store,
        VerificationService(VerificationEngine()),
        gather=stub_gather,
    )
    out = svc.verify_batch(asset_id="a2", gather=True, max_gather_iterations=2)
    assert out["gather_requested"] is True
    result = out["results"][0]
    assert result["gather"]["added"] == 2
    assert result["supporting_count"] >= 3
    updated = store.get(row["id"])
    assert len(updated.get("supporting") or []) >= 3


def test_planner_routes_verify_with_gather():
    plan = Planner().plan(
        "Verify claims learned from https://youtu.be/zHt5Mdr0QFk with web search"
    )
    assert plan.intent == Intent.VERIFY_KNOWLEDGE
    assert plan.steps[0].args.get("gather") is True


def test_cross_source_polarity_contradiction_marks_contested():
    from atlas.verification.contradiction import contradiction_reason

    a = {
        "id": "a",
        "statement": "Inflation increases purchasing power for households.",
        "claim_type": "claim",
        "value": {"kind": "claim", "related_concepts": ["Inflation"]},
    }
    b = {
        "id": "b",
        "statement": "Inflation reduces purchasing power for households.",
        "claim_type": "claim",
        "value": {"kind": "claim", "related_concepts": ["Inflation"]},
    }
    assert contradiction_reason(a, b)

    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    row_a = life.consolidate(
        {
            **{k: v for k, v in a.items() if k != "id"},
            "confidence": "UNVERIFIED",
            "supporting_sources": [
                {"source_id": "yt-a", "evidence_level": 2, "snippet": a["statement"]}
            ],
            "provenance": {"asset_id": "ax", "source_url": "https://youtu.be/zHt5Mdr0QFk"},
        }
    )
    life.consolidate(
        {
            **{k: v for k, v in b.items() if k != "id"},
            "confidence": "MEDIUM",
            "confidence_score": 0.5,
            "supporting_sources": [
                {"source_id": "blog-b", "evidence_level": 2, "snippet": b["statement"]}
            ],
            "provenance": {"source": "blog"},
        }
    )
    svc = KnowledgeVerificationService(store, VerificationService(VerificationEngine()))
    out = svc.verify_batch(asset_id="ax", detect_contradictions=True)
    result = out["results"][0]
    assert result["contested"] is True
    assert result["contradictions"]
    assert result["contradicting_count"] >= 1
    updated = store.get(row_a["id"])
    assert updated["status"] == "contested"


def test_spo_antonym_contradiction():
    from atlas.verification.contradiction import contradiction_reason

    a = {
        "id": "r1",
        "statement": "Inflation increases Purchasing Power",
        "claim_type": "relationship",
        "value": {
            "kind": "relationship",
            "subject": "Inflation",
            "predicate": "increases",
            "object": "Purchasing Power",
        },
    }
    b = {
        "id": "r2",
        "statement": "Inflation reduces Purchasing Power",
        "claim_type": "relationship",
        "value": {
            "kind": "relationship",
            "subject": "Inflation",
            "predicate": "reduces",
            "object": "Purchasing Power",
        },
    }
    reason = contradiction_reason(a, b)
    assert reason and "antonym" in reason


def test_multi_dimensional_trust_labels_are_separate():
    from atlas.evidence.models import Claim, EvidenceItem
    from atlas.verification.trust import (
        build_trust_profile,
        overall_trust_from_finding,
    )

    claim = Claim(
        id="c1",
        statement="Inflation reduces purchasing power for households.",
        evidence=[
            EvidenceItem(source_id="yt", evidence_level=2, snippet="…"),
            EvidenceItem(source_id="gov", evidence_level=3, snippet="…"),
        ],
    )
    claim.confidence = "MEDIUM"
    claim.confidence_score = 0.55
    row = {
        "claim_type": "claim",
        "statement": claim.statement,
        "value": {
            "kind": "claim",
            "char_start": 10,
            "speaker": "Robert Kiyosaki",
            "related_concepts": ["Inflation"],
            "related_entities": ["Robert Kiyosaki"],
        },
    }
    trust = build_trust_profile(claim, row=row)
    assert trust["extraction_confidence"] is not None
    assert trust["verification_confidence"] == 0.55
    assert trust["source_reliability"] is not None
    assert trust["overall_trust"] is not None
    assert "dimensions" in trust
    assert trust["dimensions"]["overall_trust"]["meaning"]
    # Extraction (provenance-rich) should not equal verification score — separate measurements.
    assert trust["extraction_confidence"] != trust["verification_confidence"]
    assert 0.0 <= trust["overall_trust"] <= 1.0

    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    finding = life.consolidate(
        {
            "statement": claim.statement,
            "claim_type": "claim",
            "confidence": "UNVERIFIED",
            "value": row["value"],
            "supporting_sources": [
                {"source_id": "yt", "evidence_level": 2, "snippet": "…"},
                {"source_id": "gov", "evidence_level": 3, "snippet": "…"},
            ],
            "provenance": {"asset_id": "t1"},
        }
    )
    svc = KnowledgeVerificationService(store, VerificationService(VerificationEngine()))
    out = svc.verify_batch(asset_id="t1")
    updated = store.get(finding["id"])
    trust_row = (updated.get("quality") or {}).get("trust") or {}
    assert trust_row.get("extraction_confidence") is not None
    assert trust_row.get("source_reliability") is not None
    assert trust_row.get("overall_trust") is not None
    assert trust_row.get("verification_label") in {
        "HIGH",
        "MEDIUM",
        "LOW",
        "INSUFFICIENT",
    }
    assert overall_trust_from_finding(updated) == trust_row["overall_trust"]
    assert out["before_after"][0].get("overall_trust") is not None


def test_review_finding_uses_adapter_for_media_rows():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    row = life.consolidate(
        {
            "statement": "Inflation reduces purchasing power.",
            "claim_type": "claim",
            "confidence": "UNVERIFIED",
            "value": {"kind": "claim", "related_concepts": ["Inflation"]},
            "supporting_sources": [
                {"source_id": "s1", "evidence_level": 2, "snippet": "Inflation…"}
            ],
            "provenance": {"component": "media.learn", "component_version": "ke.2.4"},
        }
    )
    result = life.review_finding({"finding_id": row["id"]})
    assert result["status"] == "done"
    assert result["confidence"] in {"HIGH", "MEDIUM", "LOW", "INSUFFICIENT"}


def test_planner_routes_verify_claims_from_youtube():
    plan = Planner().plan(
        "Verify claims learned from https://youtu.be/zHt5Mdr0QFk"
    )
    assert plan.intent == Intent.VERIFY_KNOWLEDGE
    assert plan.steps[0].args.get("source_url")
    assert plan.steps[0].args.get("gather") is False
