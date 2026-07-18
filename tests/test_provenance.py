"""Tests for provenance parent edges (Stage 3B close-out)."""

from __future__ import annotations

from atlas.evidence.models import Claim, ClaimValue, EvidenceItem, LEVEL_TECHNICAL
from atlas.knowledge.provenance import (
    build_finding_provenance,
    required_provenance_fields_present,
)
from atlas.research.synthesis import claim_to_finding


def test_finding_provenance_includes_parent_edges_and_min_fields():
    claim = Claim(
        id="c1",
        statement="RMSE 1.2%",
        value=ClaimValue(1.2, "%", "rmse"),
        evidence=[
            EvidenceItem(
                source_id="src1",
                evidence_level=LEVEL_TECHNICAL,
                extracted_value=1.2,
                unit="%",
                snippet="RMSE 1.2%",
                locator="chunk:ch1 document:d1",
            )
        ],
    )
    finding = claim_to_finding(
        claim,
        job_id="job-1",
        documents={
            "src1": {"id": "d1", "reader_id": "html", "chunk_id": "ch1"},
        },
    )
    prov = finding.provenance
    present = required_provenance_fields_present(prov)
    for field in (
        "entity_id",
        "transform",
        "component_id",
        "component_version",
        "ts",
        "parent_ids",
    ):
        assert field in present
    parents = set(prov["parent_ids"])
    assert "claim:c1" in parents
    assert "source:src1" in parents
    assert "document:d1" in parents
    assert "chunk:ch1" in parents
    assert "reader:html@1" in parents
    assert any(e.get("rel") == "derived_from" for e in prov["edges"])


def test_build_finding_provenance_reader_ocr_alias():
    claim = Claim(
        id="c2",
        statement="text",
        evidence=[
            EvidenceItem(source_id="s", evidence_level=3, snippet="x", locator="")
        ],
    )
    prov = build_finding_provenance(
        claim,
        finding_id="fid",
        documents={"s": {"id": "doc", "reader_id": "pdf_ocr"}},
    )
    assert "reader:ocr@1" in prov["parent_ids"]
