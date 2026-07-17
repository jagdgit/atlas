"""Tests for evidence-gap targeting (§5h / C5 / D3.2)."""

from __future__ import annotations

from atlas.evidence.models import (
    Claim,
    ClaimValue,
    EvidenceGraph,
    EvidenceItem,
    LEVEL_GOVERNMENT,
    LEVEL_PEER_REVIEWED,
    LEVEL_TECHNICAL,
    Source,
    STANCE_SUPPORT,
)
from atlas.research.gaps import (
    GAP_GOVERNMENT,
    GAP_PEER_REVIEWED,
    analyze_gaps,
    gap_queries,
    recommend_reading,
)
from atlas.verification.engine import EvidenceBudget


def _src(sid, level, *, kind="", title="", url=""):
    return Source(id=sid, title=title or sid, url=url or f"https://ex/{sid}",
                  evidence_level=level, kind=kind)


def _claim_with(sources: list[Source], *, cid="c1", number=1.0):
    evidence = [
        EvidenceItem(
            source_id=s.id, evidence_level=s.evidence_level,
            extracted_value=number, unit="%", stance=STANCE_SUPPORT,
        )
        for s in sources
    ]
    return Claim(
        id=cid, statement="value is X%",
        value=ClaimValue(number=number, unit="%", kind="rmse"),
        evidence=evidence,
    )


def test_analyze_gaps_names_missing_peer_and_gov():
    # Only L2 blogs — missing peer-reviewed and government.
    blogs = [_src(f"b{i}", LEVEL_TECHNICAL) for i in range(5)]
    graph = EvidenceGraph()
    for s in blogs:
        graph.add_source(s)
    graph.add_claim(_claim_with(blogs))
    status = analyze_gaps(graph, EvidenceBudget())
    kinds = {g.kind for g in status.gaps}
    assert GAP_PEER_REVIEWED in kinds
    assert GAP_GOVERNMENT in kinds


def test_analyze_gaps_inventory_not_claim_backed_peers():
    # IEEE in inventory counts toward peer-reviewed even with 0 extracted claims.
    from atlas.research.gaps import GAP_CLAIMS, GAP_PEER_REVIEWED

    graph = EvidenceGraph()
    for i in range(3):
        graph.add_source(_src(f"p{i}", LEVEL_PEER_REVIEWED))
    graph.add_source(_src("g1", LEVEL_GOVERNMENT))
    status = analyze_gaps(graph, EvidenceBudget())
    kinds = {g.kind for g in status.gaps}
    assert GAP_PEER_REVIEWED not in kinds  # inventory satisfied
    assert GAP_CLAIMS in kinds             # but extraction produced nothing


def test_analyze_gaps_cleared_when_budget_met():
    peers = [_src(f"p{i}", LEVEL_PEER_REVIEWED) for i in range(3)]
    gov = [_src("g1", LEVEL_GOVERNMENT)]
    extra = [_src("e1", LEVEL_TECHNICAL)]
    sources = peers + gov + extra
    graph = EvidenceGraph()
    for s in sources:
        graph.add_source(s)
    # Same value across sources → high local convergence.
    graph.add_claim(_claim_with(sources, number=42.0))
    status = analyze_gaps(
        graph,
        EvidenceBudget(min_sources=5, min_peer_reviewed=3, min_government=1, convergence=0.9),
    )
    assert not status.has_gaps
    assert all(status.met.values())


def test_gap_queries_target_named_gaps_not_synonyms():
    gaps = analyze_gaps(EvidenceGraph(), EvidenceBudget()).gaps  # everything unmet
    plan = gap_queries("soiling loss", gaps, base="soiling loss")
    queries = " ".join(q for _, q in plan)
    # Named targets, not vague synonyms like "data"/"study"/"statistics".
    assert "nrel.gov" in queries or "government" in queries.lower() or "NREL" in queries
    assert "peer" in queries.lower() or "IEEE" in queries
    # Must not be the old synonym-cross-product suffixes.
    assert not any(q.strip() == "soiling loss data" for _, q in plan)
    assert not any(q.strip() == "soiling loss study" for _, q in plan)


def test_recommend_reading_prefers_gap_fillers():
    from atlas.research.gaps import Gap

    unread = [
        _src("blog", LEVEL_TECHNICAL, title="Random blog"),
        _src("ieee", LEVEL_PEER_REVIEWED, title="IEEE paper"),
        _src("nrel", LEVEL_GOVERNMENT, title="NREL report"),
    ]
    gaps = [
        Gap(GAP_PEER_REVIEWED, 3, 0, "need peers"),
        Gap(GAP_GOVERNMENT, 1, 0, "need gov"),
    ]
    recs = recommend_reading(unread, gaps, limit=3)
    assert recs[0]["id"] in {"ieee", "nrel"}  # gap-fillers first
    assert "peer" in recs[0]["why"].lower() or "government" in recs[0]["why"].lower()
    assert len(recs) == 3
