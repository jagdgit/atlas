"""Tests for Evidence Synthesizer → Findings (Stage 3B.2)."""

from __future__ import annotations

from atlas.eval.fixtures import load_cases
from atlas.eval.metrics import contradiction_recall, false_merge_rate, merge_accuracy
from atlas.eval.synthesis import score_synthesis_corpus
from atlas.evidence.models import (
    FINDING_CONTESTED,
    LEVEL_PEER_REVIEWED,
    LEVEL_TECHNICAL,
    STANCE_SUPPORT,
    Claim,
    ClaimValue,
    EvidenceItem,
    Finding,
)
from atlas.reports.generator import ReportGenerator
from atlas.research.synthesis import EvidenceSynthesizer, claim_to_finding


def _claim(cid, statement, *, number=None, unit="", kind="", source="s", level=LEVEL_TECHNICAL):
    value = ClaimValue(number=number, unit=unit, kind=kind) if number is not None else None
    ev = EvidenceItem(
        source_id=source,
        evidence_level=level,
        extracted_value=number,
        unit=unit,
        snippet=statement,
        stance=STANCE_SUPPORT,
    )
    return Claim(id=cid, statement=statement, value=value, evidence=[ev])


def test_synthesize_merges_agreeing_quant_into_finding():
    claims = [
        _claim("a", "RMSE 1.2%", number=1.2, unit="%", kind="rmse", source="p1", level=4),
        _claim("b", "RMSE 1.25%", number=1.25, unit="%", kind="rmse", source="p2", level=4),
    ]
    findings = EvidenceSynthesizer().synthesize(claims)
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.id
    assert f.revision == 1
    assert f.canonical_id == ""  # allocated on durable promote
    assert len(f.supporting) == 2
    assert f.quality["evidence"] > 0
    assert "synthesizer:v1" in f.provenance.get("component", "")


def test_synthesize_surfaces_contradiction_as_contested():
    claims = [
        _claim("a", "loss 0.3%/day", number=0.3, unit="%/day", kind="soiling_loss", source="p1"),
        _claim("b", "loss 0.32%/day", number=0.32, unit="%/day", kind="soiling_loss", source="p2"),
        _claim("c", "loss 5.0%/day", number=5.0, unit="%/day", kind="soiling_loss", source="p3"),
    ]
    findings = EvidenceSynthesizer().synthesize(claims)
    assert len(findings) == 1
    f = findings[0]
    assert f.status == FINDING_CONTESTED
    assert {e.source_id for e in f.contradicting} == {"p3"}


def test_claim_to_finding_preserves_verified_confidence():
    claim = _claim("a", "x", number=1.0, unit="%", kind="rmse", source="s1", level=LEVEL_PEER_REVIEWED)
    claim.confidence = "HIGH"
    claim.confidence_score = 0.91
    f = claim_to_finding(claim, job_id="job-1", objective="soiling")
    assert f.confidence == "HIGH"
    assert f.confidence_score == 0.91
    assert f.provenance["job_id"] == "job-1"
    assert f.as_dict()["supporting_sources"]


def test_report_prefers_findings_over_claims():
    gen = ReportGenerator()
    report = gen.generate(
        "obj",
        claims=[{"statement": "from claim", "confidence": "LOW", "supporting_sources": []}],
        findings=[
            {
                "statement": "from finding",
                "confidence": "HIGH",
                "supporting_sources": [{"source_id": "s1", "evidence_level": 4}],
                "contradicting_sources": [],
                "canonical_id": "F-000001",
            }
        ],
    )
    assert report["used_findings"] is True
    assert "from finding" in report["sections"]["answer"]
    assert "from claim" not in report["sections"]["answer"]


def test_synthesizer_does_not_regress_eval_fixtures():
    """3B.2 must hold 3B.0 merge/contradiction baselines via group_claims path."""
    dup = score_synthesis_corpus(load_cases("synthesis_duplicates.json"))
    con = score_synthesis_corpus(load_cases("synthesis_contradictions.json"))
    assert dup["merge_accuracy"] == 1.0
    assert dup["false_merge_rate"] == 0.0
    assert con["contradiction_recall"] == 1.0

    # Findings path: cluster by source_ids must match gold on same fixtures.
    synth = EvidenceSynthesizer()
    for case in load_cases("synthesis_duplicates.json"):
        claims = [Claim.from_dict(c) for c in case["claims"]]
        findings = synth.synthesize(claims)
        predicted = [frozenset(e.source_id for e in f.evidence) for f in findings]
        gold = [frozenset(c) for c in case["gold_clusters"]]
        assert merge_accuracy(predicted, gold) == 1.0
        assert false_merge_rate(predicted, gold) == 0.0

    for case in load_cases("synthesis_contradictions.json"):
        claims = [Claim.from_dict(c) for c in case["claims"]]
        findings = synth.synthesize(claims)
        predicted_contradict = {
            e.source_id for f in findings for e in f.contradicting
        }
        assert (
            contradiction_recall(predicted_contradict, case["gold_contradict_sources"])
            == 1.0
        )
