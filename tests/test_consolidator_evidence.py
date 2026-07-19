"""Hermetic tests for C.3d evidence accumulation in the Consolidator.

The same fact discovered N ways becomes ONE finding with N evidence entries + higher confidence +
rising maturity — not N rows and not N revisions. Contradictions mark ``contested``; genuine body
changes still revise; evolution (newer) vs conflict (same/older) is routed by timestamp.
"""

from __future__ import annotations

from typing import Any

from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService


class FakeLineage:
    """Duck-typed lineage recorder capturing edges for assertions."""

    def __init__(self) -> None:
        self.edges: list[dict[str, Any]] = []

    def record(self, finding_id: str, edge_type: str, **kw: Any) -> dict[str, Any]:
        self.edges.append({"finding_id": finding_id, "edge_type": edge_type, **kw})
        return {}

    def types_for(self, finding_id: str) -> list[str]:
        return [e["edge_type"] for e in self.edges if e["finding_id"] == finding_id]


def _prose(statement: str = "Atlas dedups assets by content hash", **extra: Any) -> dict[str, Any]:
    data = {
        "statement": statement,
        "domain": "external",
        "status": "active",
        "confidence": "UNVERIFIED",
        "supporting_sources": [{"source_id": "p1", "evidence_level": 3}],
        "contradicting_sources": [],
    }
    data.update(extra)
    return data


def _quant(number: float, **extra: Any) -> dict[str, Any]:
    data = {
        "statement": f"model RMSE is {number}%",
        "domain": "external",
        "status": "active",
        "value": {"number": number, "unit": "%", "kind": "rmse"},
        "confidence": "HIGH",
        "supporting_sources": [{"source_id": "p1", "evidence_level": 4}],
        "contradicting_sources": [],
    }
    data.update(extra)
    return data


def test_new_source_same_statement_merges_in_place():
    store = InMemoryFindingStore()
    lineage = FakeLineage()
    life = KnowledgeLifecycleService(store, lineage=lineage)

    a = life.consolidate(_prose())
    assert a["_transition"] == "create"

    b = life.consolidate(_prose(supporting_sources=[{"source_id": "p2", "evidence_level": 3}]))
    assert b["_transition"] == "merge_evidence"
    assert b["id"] == a["id"]          # one finding, not two
    assert b["revision"] == 1          # merge-in-place: no new revision
    assert len(b["supporting"]) == 2   # two evidence entries
    assert b["confidence"] == "MEDIUM"  # corroboration bumped confidence
    assert b["maturity"] == "verified"
    assert len(store.rows) == 1

    assert lineage.types_for(a["id"]) == ["created_by", "supported_by"]


def test_third_independent_source_reaches_established():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    life.consolidate(_prose())
    life.consolidate(_prose(supporting_sources=[{"source_id": "p2"}]))
    c = life.consolidate(_prose(supporting_sources=[{"source_id": "p3"}], confidence="HIGH"))
    assert c["_transition"] == "merge_evidence"
    assert len(c["supporting"]) == 3
    assert c["confidence"] == "HIGH"
    assert c["maturity"] == "established"


def test_same_source_repeated_is_noop():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    life.consolidate(_prose())
    again = life.consolidate(_prose())  # identical evidence
    assert again["_transition"] == "noop"
    assert len(store.rows) == 1


def test_contradiction_same_statement_marks_contested():
    store = InMemoryFindingStore()
    lineage = FakeLineage()
    life = KnowledgeLifecycleService(store, lineage=lineage)
    a = life.consolidate(_prose())
    c = life.consolidate(_prose(contradicting_sources=[{"source_id": "c1", "evidence_level": 3}]))
    assert c["_transition"] == "contested"
    assert c["status"] == "contested"
    assert c["id"] == a["id"]
    assert len(store.rows) == 1
    assert "contradicted_by" in lineage.types_for(a["id"])


def test_body_change_still_revises_not_merges():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    a = life.consolidate(_quant(1.2))
    assert a["_transition"] == "create"
    b = life.consolidate(_quant(1.25))  # value changed → genuine body change
    assert b["_transition"] == "revise"
    assert b["revision"] == 2
    assert b["canonical_id"] == a["canonical_id"]


def test_newer_body_change_is_evolution_revise():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    life.consolidate(_quant(1.2, last_verified="2025-01-01T00:00:00Z"))
    b = life.consolidate(
        _quant(2.0, last_verified="2027-01-01T00:00:00Z",
               contradicting_sources=[{"source_id": "c1"}])
    )
    assert b["_transition"] == "revise"  # newer claim → evolution, not a same-time conflict


def test_older_conflicting_body_change_is_contested():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    life.consolidate(_quant(1.2, last_verified="2027-01-01T00:00:00Z"))
    b = life.consolidate(
        _quant(2.0, last_verified="2025-01-01T00:00:00Z",
               contradicting_sources=[{"source_id": "c1"}])
    )
    assert b["_transition"] == "split_contested"
    assert b["status"] == "contested"


# --- live DB -------------------------------------------------------------
def test_evidence_merge_persists_and_writes_lineage_live():
    import uuid

    import pytest

    from atlas.database.connection import DatabaseManager
    from atlas.repositories.finding_repo import FindingRepository
    from atlas.repositories.lineage_repo import LineageRepository

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")

    try:
        repo = FindingRepository(manager)
        lineage = LineageRepository(manager)
        life = KnowledgeLifecycleService(repo, lineage=lineage)
        token = uuid.uuid4().hex
        stmt = f"Atlas keeps knowledge global not mission-scoped {token}"

        a = life.consolidate(_prose(statement=stmt, supporting_sources=[{"source_id": "p1"}]))
        assert a["_transition"] == "create"
        fid = str(a["id"])
        try:
            b = life.consolidate(_prose(statement=stmt, supporting_sources=[{"source_id": "p2"}]))
            assert b["_transition"] == "merge_evidence"
            assert str(b["id"]) == fid       # same row, persisted
            assert b["revision"] == 1
            assert len(b["supporting"]) == 2

            edges = {e["edge_type"] for e in lineage.list_for_finding(fid)}
            assert "created_by" in edges and "supported_by" in edges
        finally:
            repo.set_status(fid, "archived")
    finally:
        manager.close()
