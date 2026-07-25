"""OI-B3 Knowledge Conflict Resolver — structured conflict + resolve + DE recommend."""

from __future__ import annotations

from atlas.decision.contracts import DecisionRequest
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.knowledge.conflict import (
    KnowledgeConflictDecisionRule,
    MISSION_TYPE_KNOWLEDGE_CONFLICT,
    conflict_record,
)
from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.knowledge.lifecycle import STATUS_CONTESTED, STATUS_DEPRECATED


def test_conflict_record_shape():
    rec = conflict_record(kind="same_time", signal="body_change", peer_ids=["s1"])
    assert rec["kind"] == "same_time"
    assert rec["peer_ids"] == ["s1"]
    assert "recorded_at" in rec


def test_cross_source_contest_writes_quality_conflict():
    store = InMemoryFindingStore()
    svc = KnowledgeLifecycleService(store)
    first = svc.consolidate(
        {
            "statement": "X is true",
            "domain": "research",
            "supporting_sources": [{"source_id": "a"}],
            "confidence": "LOW",
            "confidence_score": 0.4,
        }
    )
    contested = svc.consolidate(
        {
            "statement": "X is true",
            "domain": "research",
            "canonical_id": first["canonical_id"],
            "supporting_sources": [{"source_id": "a"}],
            "contradicting_sources": [{"source_id": "b"}],
            "confidence": "LOW",
            "confidence_score": 0.4,
        }
    )
    assert contested["status"] == STATUS_CONTESTED
    quality = contested.get("quality") or store.get(contested["id"]).get("quality") or {}
    # merge_quality may be on the store row after update_evidence
    row = store.get(contested["id"])
    q = row.get("quality") or {}
    assert q.get("conflict", {}).get("kind") == "cross_source"


def test_list_contested_and_resolve_hold_supersede_reactivate():
    store = InMemoryFindingStore()
    svc = KnowledgeLifecycleService(store)
    first = svc.consolidate(
        {
            "statement": "Y holds",
            "domain": "research",
            "supporting_sources": [{"source_id": "a"}],
            "confidence": "LOW",
            "confidence_score": 0.3,
        }
    )
    svc.consolidate(
        {
            "statement": "Y holds",
            "domain": "research",
            "canonical_id": first["canonical_id"],
            "contradicting_sources": [{"source_id": "c"}],
            "confidence": "LOW",
            "confidence_score": 0.3,
        }
    )
    contested = svc.list_contested()
    assert len(contested) == 1
    fid = contested[0]["id"]

    held = svc.resolve_conflict(fid, action="hold", note="wait for more sources")
    assert held["ok"] is True
    assert held["action"] == "hold"
    assert (held["finding"].get("quality") or {}).get("conflict", {}).get("resolution", {}).get(
        "action"
    ) == "hold"

    # Fresh contested for supersede
    store2 = InMemoryFindingStore()
    svc2 = KnowledgeLifecycleService(store2)
    f2 = svc2.consolidate(
        {
            "statement": "Z holds",
            "domain": "research",
            "supporting_sources": [{"source_id": "a"}],
            "confidence": "LOW",
            "confidence_score": 0.3,
        }
    )
    c2 = svc2.consolidate(
        {
            "statement": "Z holds",
            "domain": "research",
            "canonical_id": f2["canonical_id"],
            "contradicting_sources": [{"source_id": "d"}],
            "confidence": "LOW",
            "confidence_score": 0.3,
        }
    )
    out = svc2.resolve_conflict(c2["id"], action="supersede", note="peer wins")
    assert out["finding"]["status"] == STATUS_DEPRECATED

    # Reactivate with clear
    store3 = InMemoryFindingStore()
    svc3 = KnowledgeLifecycleService(store3)
    f3 = svc3.consolidate(
        {
            "statement": "W holds",
            "domain": "research",
            "supporting_sources": [{"source_id": "a"}],
            "confidence": "LOW",
            "confidence_score": 0.3,
        }
    )
    c3 = svc3.consolidate(
        {
            "statement": "W holds",
            "domain": "research",
            "canonical_id": f3["canonical_id"],
            "contradicting_sources": [{"source_id": "e"}],
            "confidence": "LOW",
            "confidence_score": 0.3,
        }
    )
    out3 = svc3.resolve_conflict(
        c3["id"], action="reactivate", clear_contradicting=True, note="operator override"
    )
    assert out3["finding"]["status"] == "active"
    assert out3["finding"].get("contradicting") in ([], None)


def test_conflict_decision_rule_recommends_options():
    class _Repo:
        def record(self, decision):
            return {"id": "d1", "created_at": None}

    registry = DecisionRuleRegistry()
    registry.register(KnowledgeConflictDecisionRule())
    engine = DecisionEngine(repo=_Repo(), rules=registry)
    finding = {
        "id": "f1",
        "statement": "Inflation is rising",
        "status": STATUS_CONTESTED,
        "contradicting": [{"source_id": "x"}, {"source_id": "y"}],
        "quality": {"conflict": {"kind": "cross_source", "signal": "new_contradicting_evidence"}},
    }
    decision = engine.decide(
        DecisionRequest(
            mission_id=None,
            mission_type=MISSION_TYPE_KNOWLEDGE_CONFLICT,
            context={"finding": finding},
        )
    )
    assert decision.action_kind == "recommend"
    assert decision.action.get("key") == "hold"  # 2 contra → hold tops
    rejected_keys = {a["key"] for a in decision.alternatives_rejected}
    assert "reactivate" in rejected_keys
    assert "supersede" in rejected_keys
