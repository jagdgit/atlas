"""Tests for cross-document reasoning (Stage 3B.4)."""

from __future__ import annotations

from atlas.evidence.models import (
    CLAIM_TYPE_HYPOTHESIS,
    FINDING_CONTESTED,
    ClaimValue,
    EvidenceItem,
    Finding,
    LEVEL_TECHNICAL,
    STANCE_CONTRADICT,
    STANCE_SUPPORT,
)
from atlas.reports.generator import ReportGenerator
from atlas.research.gaps import GAP_CONVERGENCE, Gap, GapStatus
from atlas.research.reasoning import (
    REL_CONTRADICT,
    REL_SUPPORT,
    CrossDocumentReasoner,
    filter_out_hypotheses,
    reason_across_documents,
)


def _finding(fid, statement, *, number=None, unit="%", kind="rmse", contradict=False):
    value = ClaimValue(number=number, unit=unit, kind=kind) if number is not None else None
    evidence = [
        EvidenceItem(
            source_id="p1",
            evidence_level=LEVEL_TECHNICAL,
            extracted_value=number,
            unit=unit,
            snippet=statement,
            stance=STANCE_SUPPORT,
        )
    ]
    if contradict:
        evidence.append(
            EvidenceItem(
                source_id="p2",
                evidence_level=LEVEL_TECHNICAL,
                extracted_value=(number or 0) * 5,
                unit=unit,
                snippet="outlier",
                stance=STANCE_CONTRADICT,
            )
        )
    return Finding(
        id=fid,
        statement=statement,
        value=value,
        evidence=evidence,
        status=FINDING_CONTESTED if contradict else "active",
        claim_type="quantitative" if kind else "prose",
    )


def test_relationship_edges_support_and_contradict():
    a = _finding("a", "RMSE 1.2%", number=1.2)
    b = _finding("b", "RMSE 1.25%", number=1.25)
    c = _finding("c", "RMSE 5.0%", number=5.0)
    result = reason_across_documents([a, b, c])
    rels = {(e.source_id, e.target_id, e.relation) for e in result.edges}
    assert ("a", "b", REL_SUPPORT) in rels
    assert ("a", "c", REL_CONTRADICT) in rels or ("b", "c", REL_CONTRADICT) in rels


def test_pattern_cards_for_value_range_and_method():
    findings = [
        _finding("a", "Field measurement RMSE 1.2%", number=1.2),
        _finding("b", "Field measurement RMSE 1.3%", number=1.3),
    ]
    result = reason_across_documents(findings)
    kinds = {p.kind for p in result.patterns}
    assert "value_range" in kinds
    assert "method" in kinds


def test_theme_patterns_from_qualitative_claims():
    # Prose claims carry their cue kind in the evidence locator ("prose:<kind>").
    def _prose(fid, statement, kind):
        return Finding(
            id=fid,
            statement=statement,
            value=None,
            evidence=[
                EvidenceItem(
                    source_id=fid,
                    evidence_level=LEVEL_TECHNICAL,
                    snippet=statement,
                    locator=f"prose:{kind}",
                    stance=STANCE_SUPPORT,
                )
            ],
            claim_type="prose",
        )

    findings = [
        _prose("a", "SVR outperformed Ridge on unseen sites.", "comparison"),
        _prose("b", "CNN outperformed the linear baseline.", "comparison"),
    ]
    result = reason_across_documents(findings)
    themes = [p for p in result.patterns if p.kind == "theme"]
    assert any(p.label == "theme:comparison" for p in themes)
    assert any(len(p.member_ids) == 2 for p in themes)


def test_gaps_plus_contradiction_yield_opportunities_and_hypotheses():
    contested = _finding(
        "x", "loss 0.3%/day", number=0.3, kind="soiling_loss", contradict=True
    )
    gaps = GapStatus(
        gaps=[Gap(GAP_CONVERGENCE, 1, 0, "convergence below threshold")],
        met={GAP_CONVERGENCE: False},
    )
    result = CrossDocumentReasoner().reason(
        [contested], gaps=gaps, objective="soiling"
    )
    assert result.opportunities
    assert any(
        o.from_gap_kind in {"convergence", "contradiction"}
        for o in result.opportunities
    )
    assert result.hypotheses
    assert all(h.status == "open" for h in result.hypotheses)
    assert all(h.as_dict()["type"] == CLAIM_TYPE_HYPOTHESIS for h in result.hypotheses)


def test_hypotheses_never_promoted_as_findings():
    items = [
        {"statement": "real finding", "claim_type": "quantitative"},
        {
            "statement": "maybe X",
            "type": CLAIM_TYPE_HYPOTHESIS,
            "claim_type": CLAIM_TYPE_HYPOTHESIS,
        },
    ]
    kept = filter_out_hypotheses(items)
    assert len(kept) == 1
    assert kept[0]["statement"] == "real finding"


def test_report_surfaces_reasoning_sections_without_false_certainty():
    reasoning = {
        "patterns": [{"label": "rmse (%)", "detail": "range 1–2"}],
        "opportunities": [{"title": "Close convergence gap", "why": "need more L4"}],
        "hypotheses": [
            {
                "statement": "Unresolved: loss rate",
                "rationale": "contested",
                "status": "open",
                "type": CLAIM_TYPE_HYPOTHESIS,
            }
        ],
        "edges": [],
    }
    report = ReportGenerator().generate(
        "obj",
        findings=[
            {
                "statement": "RMSE ~1.2%",
                "confidence": "MEDIUM",
                "supporting_sources": [],
                "contradicting_sources": [],
            }
        ],
        reasoning=reasoning,
    )
    assert report["sections"]["patterns"]
    assert report["sections"]["opportunities"]
    assert report["sections"]["hypotheses"]
    assert "Open hypothesis" in report["sections"]["next_research"]
    assert "## Hypotheses" in report["markdown"]
    assert "open" in report["markdown"]
