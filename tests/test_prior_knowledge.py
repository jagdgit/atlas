"""Prior-knowledge recall uses the global Access Layer (role=research)."""

from __future__ import annotations

from atlas.knowledge.access import RankedContext, RankedHit
from atlas.research.prior_knowledge import recall_prior_knowledge


class FakeAccess:
    def __init__(self):
        self.calls = []

    def retrieve(self, query, **kwargs):
        self.calls.append((query, kwargs))
        hit = RankedHit(
            chunk_id="c1",
            document_id="d1",
            ordinal=0,
            content="prior soiling findings",
            rrf_score=0.05,
            score=0.05,
            similarity=0.8,
            dense_score=0.8,
            lexical_score=0.2,
        )
        return RankedContext(
            query=query,
            hits=(hit,),
            context="[1] prior soiling findings",
            citations=({"index": 1, "chunk_id": "c1", "document_id": "d1"},),
            role=kwargs.get("role", "research"),
            mode="hybrid",
        )


def test_recall_prior_knowledge_uses_research_role():
    kb = FakeAccess()
    ranked = recall_prior_knowledge(kb, "PV soiling loss", k=3)
    assert ranked.hits[0].chunk_id == "c1"
    query, kwargs = kb.calls[0]
    assert query == "PV soiling loss"
    assert kwargs["role"] == "research"
    assert kwargs["k"] == 3
    assert "research" in kwargs["domains"]
