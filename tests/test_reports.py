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


def test_conflicting_views_flag_contradictions_and_weak():
    gen = ReportGenerator()
    claims = [
        _claim("solid", CONFIDENCE_HIGH),
        _claim("disputed", CONFIDENCE_HIGH, contradicting=2),
        _claim("weak", CONFIDENCE_LOW, convergence=0.2),
    ]
    report = gen.generate("obj", claims=claims)
    conflicts = report["sections"]["conflicting_views"]
    statements = {c["statement"] for c in conflicts}
    assert "disputed" in statements
    assert "weak" in statements
    assert "solid" not in statements


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
    assert report["sections"]["executive_summary"] == "Polished executive summary."


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
