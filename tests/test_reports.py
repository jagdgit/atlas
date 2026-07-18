"""Report generator + service tests (Sprint 17, §5a.5).

Pure/deterministic: no LLM (prose falls back to templates). Covers section assembly,
overall-confidence derivation, conflicting-views detection, references, and the
verify→render pipeline via a real VerificationService.
"""

from __future__ import annotations

from atlas.evidence.models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
)
from atlas.reports.generator import REPORT_SECTIONS, ReportGenerator
from atlas.reports.service import ReportService
from atlas.verification.service import VerificationService


def _claim(statement, confidence, *, supporting=1, contradicting=0, convergence=1.0):
    return {
        "statement": statement,
        "value": None,
        "confidence": confidence,
        "convergence": convergence,
        "verification_method": "test",
        "reasoning_trace": ["because"],
        "supporting_sources": [
            {"source_id": f"s{i}", "evidence_level": 4} for i in range(supporting)
        ],
        "contradicting_sources": [
            {"source_id": f"x{i}", "evidence_level": 2} for i in range(contradicting)
        ],
    }


# --- generator ------------------------------------------------------------
def test_report_has_all_sections():
    gen = ReportGenerator()
    report = gen.generate("Estimate X", claims=[_claim("X is 4%", CONFIDENCE_HIGH)])
    for section in REPORT_SECTIONS:
        assert section in report["sections"]
    assert "# Research Report:" in report["markdown"]


def test_overall_confidence_is_most_common_conservative():
    gen = ReportGenerator()
    claims = [
        _claim("a", CONFIDENCE_HIGH),
        _claim("b", CONFIDENCE_HIGH),
        _claim("c", CONFIDENCE_LOW, supporting=1, convergence=0.2),
    ]
    report = gen.generate("obj", claims=claims)
    assert report["overall_confidence"] == CONFIDENCE_HIGH


def test_overall_confidence_ties_break_conservative():
    gen = ReportGenerator()
    claims = [_claim("a", CONFIDENCE_HIGH), _claim("b", CONFIDENCE_LOW, convergence=0.1)]
    report = gen.generate("obj", claims=claims)
    # 1 HIGH, 1 LOW → tie → more conservative wins.
    assert report["overall_confidence"] == CONFIDENCE_LOW


def test_conflicts_and_weak_evidence_are_separate_sections():
    # §3B: a real conflict (sources disagree) is not the same as thin evidence.
    gen = ReportGenerator()
    claims = [
        _claim("solid", CONFIDENCE_HIGH),
        _claim("disputed", CONFIDENCE_HIGH, contradicting=2),
        _claim("weak", CONFIDENCE_LOW, convergence=0.2),
    ]
    report = gen.generate("obj", claims=claims)
    conflicts = {c["statement"] for c in report["sections"]["conflicting_views"]}
    weak = {c["statement"] for c in report["sections"]["weakly_supported"]}
    assert conflicts == {"disputed"}          # only the contradicted finding
    assert weak == {"weak"}                    # thin evidence, not a conflict
    assert "solid" not in conflicts and "solid" not in weak
    assert "## Weakly Supported Findings" in report["markdown"]


def test_empty_claims_is_insufficient_and_uses_answer_override():
    gen = ReportGenerator()
    report = gen.generate("obj", claims=[], answer="Gathered summary text.")
    assert report["overall_confidence"] == CONFIDENCE_INSUFFICIENT
    assert report["sections"]["answer"] == "Gathered summary text."


def test_references_dedupe_and_sort_by_level():
    gen = ReportGenerator()
    sources = [
        {"id": "s1", "title": "Blog", "evidence_level": 2},
        {"id": "s2", "title": "NREL", "evidence_level": 3},
        {"id": "s1", "title": "Blog", "evidence_level": 2},
    ]
    report = gen.generate("obj", claims=[], sources=sources)
    refs = report["sections"]["references"]
    assert len(refs) == 2
    assert refs[0]["id"] == "s2"  # higher level first


class _RoleStub:
    def chat(self, messages, **kw):
        from atlas.llm.provider import LLMResponse

        return LLMResponse(text="Polished executive summary.", model="fake")


class _FakeLLM:
    def for_role(self, role):
        return _RoleStub()


def test_llm_polishes_executive_summary():
    gen = ReportGenerator(llm=_FakeLLM())
    report = gen.generate("obj", claims=[_claim("a", CONFIDENCE_HIGH)])
    summary = report["sections"]["executive_summary"]
    # LLM narrative is appended to the authoritative deterministic count sentence
    # so the summary can never contradict the run's counters.
    assert "Polished executive summary." in summary
    assert "1 finding(s) assessed" in summary


def test_parameters_split_out_of_headline_evidence():
    result_claim = {
        "id": "r1", "statement": "RMSE reduced to 1.2%.", "claim_type": "result",
        "confidence": CONFIDENCE_HIGH, "supporting_sources": [{"source_id": "s1", "evidence_level": 4}],
        "contradicting_sources": [],
    }
    param_claim = {
        "id": "p1", "statement": "Train/test split was 80/20.", "claim_type": "parameter",
        "confidence": CONFIDENCE_HIGH, "supporting_sources": [{"source_id": "s1", "evidence_level": 4}],
        "contradicting_sources": [],
    }
    gen = ReportGenerator()
    report = gen.generate("obj", claims=[param_claim, result_claim])
    ev_statements = [e["statement"] for e in report["sections"]["evidence"]]
    assert "RMSE reduced to 1.2%." in ev_statements
    assert "Train/test split was 80/20." not in ev_statements
    assert any(e["statement"] == "Train/test split was 80/20." for e in report["sections"]["parameters"])
    # The headline answer leads with the result, not the parameter.
    assert report["sections"]["answer"].splitlines()[0].startswith("- RMSE reduced")
    assert "## Parameters & Configuration" in report["markdown"]


def test_inferred_claims_marked_in_report():
    claim = {
        "id": "c1",
        "statement": "Data-driven cleaning improves ROI.",
        "confidence": CONFIDENCE_HIGH,
        "supporting_sources": [
            {"source_id": "s1", "evidence_level": 4, "origin": "inferred"}
        ],
        "contradicting_sources": [],
    }
    gen = ReportGenerator()
    report = gen.generate("obj", claims=[claim])
    row = report["sections"]["evidence"][0]
    assert row["inferred"] is True
    assert "Atlas-inferred" in report["markdown"]


def test_funnel_rendered_deterministically_from_pipeline():
    gen = ReportGenerator()
    pipeline = {"found": 17, "acquired": 9, "read": 7, "reader_failures": 2,
                "extract_ok": 2, "extract_failed": 5, "extracted": 19,
                "numeric_claims": 15, "prose_claims": 4, "claims": 12,
                "verified": 6, "findings": 6, "patterns": 2, "contradictions": 1}
    report = gen.generate("obj", claims=[_claim("a", CONFIDENCE_HIGH)], pipeline=pipeline)
    md = report["markdown"]
    assert "## Research Funnel" in md
    assert "| Sources found | 17 |" in md
    assert "| Reader failures | 2 |" in md
    assert report["sections"]["funnel"]["extract_failed"] == 5


def test_exec_summary_is_honest_when_no_findings_extracted():
    # §3B honesty: with sources read but 0 verifiable claims, the summary must NOT
    # assert a general-knowledge conclusion — it reports what Atlas verified (nothing).
    gen = ReportGenerator()
    pipeline = {"found": 5, "acquired": 1, "read": 1, "extracted": 0, "claims": 0}
    report = gen.generate("Does soiling reduce PV output?", claims=[], pipeline=pipeline)
    summary = report["sections"]["executive_summary"].lower()
    assert "unable to extract" in summary
    assert "no conclusion can be drawn" in summary
    assert "confirms" not in summary  # no fabricated conclusion


def test_llm_polish_skipped_when_no_claims():
    # Even with an LLM wired, an empty evidence set must not invite a fabricated
    # conclusion from world knowledge.
    gen = ReportGenerator(llm=_FakeLLM())
    pipeline = {"found": 3, "read": 1, "claims": 0}
    report = gen.generate("obj", claims=[], pipeline=pipeline)
    summary = report["sections"]["executive_summary"]
    assert "Polished executive summary." not in summary
    assert "no conclusion can be drawn" in summary.lower()


def test_pipeline_trace_rendered_per_source():
    gen = ReportGenerator()
    pipeline = {
        "found": 2, "acquired": 2, "read": 1,
        "trace": [
            {
                "source_id": "s1", "title": "Good paper", "status": "ok",
                "reader": "html", "chars": 46800, "sections": 34,
                "numeric_claims": 3, "qualitative_claims": 12, "inferred_claims": 0,
                "distinct_claims": 13, "verified_claims": 8, "findings": 5,
                "failure_reason": "",
            },
            {
                "source_id": "s2", "title": "Landing", "status": "read_failed",
                "reader": "html", "chars": 300, "sections": 0,
                "numeric_claims": 0, "qualitative_claims": 0, "inferred_claims": 0,
                "distinct_claims": 0, "verified_claims": 0, "findings": 0,
                "failure_reason": "publisher landing page, no article body",
            },
        ],
    }
    report = gen.generate("obj", claims=[_claim("a", CONFIDENCE_HIGH)], pipeline=pipeline)
    assert report["sections"]["pipeline_trace"] == pipeline["trace"]
    # Trace must not leak into the funnel counts object.
    assert "trace" not in report["sections"]["funnel"]
    md = report["markdown"]
    assert "## Pipeline Trace (per source)" in md
    assert "Good paper" in md and "read_failed" in md
    assert "publisher landing page, no article body" in md


# --- service --------------------------------------------------------------
def test_service_report_verifies_then_renders():
    svc = ReportService(VerificationService(), ReportGenerator())
    graph = {
        "claims": [
            {
                "id": "c1",
                "statement": "Soiling loss ~ 4%",
                "evidence": [
                    {"source_id": "s1", "evidence_level": 4, "extracted_value": 3.9},
                    {"source_id": "s2", "evidence_level": 3, "extracted_value": 4.0},
                    {"source_id": "s3", "evidence_level": 4, "extracted_value": 3.8},
                ],
            }
        ]
    }
    out = svc.report("Estimate soiling", graph)
    assert out["verification"]["claims"][0]["confidence"] == CONFIDENCE_HIGH
    assert out["report"]["overall_confidence"] == CONFIDENCE_HIGH
    assert "Soiling loss" in out["report"]["markdown"]


def test_service_render_without_verification():
    svc = ReportService(None, ReportGenerator())
    out = svc.render("obj", claims=[], answer="just a summary")
    assert out["sections"]["answer"] == "just a summary"


def test_service_health_ok():
    assert ReportService().health_check().healthy
