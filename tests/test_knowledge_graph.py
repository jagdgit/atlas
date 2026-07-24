"""Knowledge Graph derived from findings (KG.1)."""

from __future__ import annotations

from atlas.knowledge.graph import KnowledgeGraphService, build_knowledge_graph
from atlas.missions.programs import ProgramService


_FINDINGS = [
    {
        "id": "f1",
        "claim_type": "concept",
        "statement": "Cash Flow",
        "value": {"name": "Cash Flow"},
        "domain": "finance",
    },
    {
        "id": "f2",
        "claim_type": "entity",
        "statement": "Robert Kiyosaki",
        "value": {"name": "Robert Kiyosaki", "entity_type": "person"},
        "domain": "finance",
    },
    {
        "id": "f3",
        "claim_type": "claim",
        "statement": "Cash flow is more important than income.",
        "value": {
            "related_concepts": ["Cash Flow"],
            "related_entities": ["Robert Kiyosaki"],
            "links": [
                {"rel": "mentions", "target_type": "concept", "target": "Cash Flow"},
            ],
        },
        "domain": "finance",
    },
    {
        "id": "f4",
        "claim_type": "relationship",
        "statement": "Kiyosaki wrote Rich Dad Poor Dad",
        "value": {
            "subject": "Robert Kiyosaki",
            "predicate": "wrote",
            "object": "Rich Dad Poor Dad",
        },
        "domain": "finance",
    },
]


def test_build_graph_spo_and_mentions():
    g = build_knowledge_graph(_FINDINGS)
    kinds = {n["kind"] for n in g["nodes"]}
    assert "concept" in kinds and "entity" in kinds and "claim" in kinds
    assert "relationship" in kinds
    rels = {e["rel"] for e in g["edges"]}
    assert "mentions" in rels
    assert "spo" in rels
    spo = next(e for e in g["edges"] if e["rel"] == "spo")
    assert spo["predicate"] == "wrote"


def test_build_graph_query_filter():
    g = build_knowledge_graph(_FINDINGS, q="kiyosaki")
    assert g["stats"]["nodes"] >= 1
    labels = " ".join(n["label"].lower() for n in g["nodes"])
    assert "kiyosaki" in labels or "rich dad" in labels


def test_graph_service_snapshot():
    class _K:
        def list_findings(self, *, domain=None, limit=50, include_archive=False):
            return _FINDINGS

    svc = KnowledgeGraphService(_K())
    snap = svc.snapshot(q="cash")
    assert snap["version"] == "kg.1"
    assert snap["stats"]["nodes"] >= 1


def test_program_context_includes_graph_nodes():
    class _K:
        def list_findings(self, *, domain=None, limit=50, include_archive=False):
            return _FINDINGS

        def retrieve(self, *a, **k):
            return []

    graph = KnowledgeGraphService(_K())
    svc = ProgramService(knowledge=_K(), knowledge_graph=graph)
    out = svc.context("Cash Flow", limit=12)
    assert any(i.get("item_kind") == "graph_node" for i in out["items"])
    assert "graph" in out["note"].lower()
