"""Tests for artifact version stamping (Phase 0 · ATLAS_OS_ROADMAP §2.6, P2).

Model-independence: every durable Finding/Experience records the real component +
model versions that produced it, so a model swap is a scoped re-derivation.
"""

from __future__ import annotations

from atlas.evidence.models import (
    LEVEL_TECHNICAL,
    STANCE_SUPPORT,
    Claim,
    ClaimValue,
    EvidenceItem,
)
from atlas.knowledge.provenance import build_finding_provenance
from atlas.research.synthesis import EvidenceSynthesizer, claim_to_finding
from atlas.system.versioning import (
    KNOWLEDGE_SCHEMA_VERSION,
    ArtifactVersions,
    build_artifact_versions,
)

_VERSIONS = {
    "llm_id": "qwen3:8b",
    "embedding_id": "nomic-embed-text",
    "reader_version": "1",
    "extractor_version": "1",
    "verifier_version": "1",
    "synthesizer_version": "1",
    "knowledge_schema_version": KNOWLEDGE_SCHEMA_VERSION,
}


def _claim(cid="a", statement="RMSE 1.2%"):
    value = ClaimValue(number=1.2, unit="%", kind="rmse")
    ev = EvidenceItem(
        source_id="p1",
        evidence_level=LEVEL_TECHNICAL,
        extracted_value=1.2,
        unit="%",
        snippet=statement,
        stance=STANCE_SUPPORT,
    )
    return Claim(id=cid, statement=statement, value=value, evidence=[ev])


def test_artifact_versions_as_dict_has_all_keys():
    av = build_artifact_versions(
        llm_id="qwen3:8b",
        embedding_id="nomic-embed-text",
        reader_version="1",
        extractor_version="2",
        verifier_version="3",
        synthesizer_version="4",
    )
    assert isinstance(av, ArtifactVersions)
    d = av.as_dict()
    assert set(d) == set(_VERSIONS)
    assert d["extractor_version"] == "2"
    assert d["knowledge_schema_version"] == KNOWLEDGE_SCHEMA_VERSION


def test_provenance_embeds_versions_when_supplied():
    prov = build_finding_provenance(
        _claim(), finding_id="f1", versions=_VERSIONS
    )
    assert prov["versions"] == _VERSIONS
    # existing provenance fields are unchanged
    assert prov["component_id"] == "synthesizer:v1"
    assert prov["entity_id"] == "finding:f1"


def test_provenance_omits_versions_when_absent():
    prov = build_finding_provenance(_claim(), finding_id="f1")
    assert "versions" not in prov


def test_synthesizer_stamps_versions_onto_findings():
    synth = EvidenceSynthesizer(versions=_VERSIONS)
    findings = synth.synthesize([_claim()])
    assert len(findings) == 1
    assert findings[0].provenance["versions"]["llm_id"] == "qwen3:8b"


def test_synthesizer_without_versions_omits_block():
    findings = EvidenceSynthesizer().synthesize([_claim()])
    assert "versions" not in findings[0].provenance


def test_claim_to_finding_threads_versions():
    f = claim_to_finding(_claim(), versions=_VERSIONS)
    assert f.provenance["versions"]["reader_version"] == "1"


def test_components_declare_versions():
    # The producers expose a bumpable VERSION so findings can be traced to a build.
    from atlas.research.extract import ClaimExtractor
    from atlas.research.reader import Reader
    from atlas.verification.engine import VerificationEngine

    assert Reader.VERSION
    assert ClaimExtractor.VERSION
    assert VerificationEngine.VERSION
    assert EvidenceSynthesizer.VERSION
