"""Artifact version stamping (Phase 0 · ATLAS_OS_ROADMAP §3 P2, §2.6).

Model-independence rule (P2): the database *is* the knowledge; the LLM is just a
reasoning engine. To make swapping models a scoped, auditable re-derivation rather
than a rebuild, every durable artifact (Finding, Experience) records the **real**
component + model versions that produced it — never a hardcoded ``"v1"``.

This module holds the small, dependency-free value object; bootstrap resolves the
concrete versions (component ``VERSION`` constants + configured model names +
Capability Registry) and threads an :class:`ArtifactVersions` through the producers.
"""

from __future__ import annotations

from dataclasses import dataclass

# Knowledge schema version — bump when the knowledge/findings schema changes in a way
# that affects re-derivation. Tracks the migration series (latest knowledge-affecting
# migration at time of writing is 0016_finding_lifecycle).
KNOWLEDGE_SCHEMA_VERSION = "0016"


@dataclass(frozen=True, slots=True)
class ArtifactVersions:
    """The set of component/model versions that produced a durable artifact."""

    llm_id: str
    embedding_id: str
    reader_version: str
    extractor_version: str
    verifier_version: str
    synthesizer_version: str
    knowledge_schema_version: str = KNOWLEDGE_SCHEMA_VERSION

    def as_dict(self) -> dict[str, str]:
        return {
            "llm_id": self.llm_id,
            "embedding_id": self.embedding_id,
            "reader_version": self.reader_version,
            "extractor_version": self.extractor_version,
            "verifier_version": self.verifier_version,
            "synthesizer_version": self.synthesizer_version,
            "knowledge_schema_version": self.knowledge_schema_version,
        }


def build_artifact_versions(
    *,
    llm_id: str,
    embedding_id: str,
    reader_version: str,
    extractor_version: str,
    verifier_version: str,
    synthesizer_version: str,
    knowledge_schema_version: str = KNOWLEDGE_SCHEMA_VERSION,
) -> ArtifactVersions:
    """Assemble an :class:`ArtifactVersions` from resolved component/model versions.

    A thin constructor kept separate so callers (bootstrap) do the resolving — this
    module stays free of heavy imports and easy to unit-test.
    """
    return ArtifactVersions(
        llm_id=llm_id,
        embedding_id=embedding_id,
        reader_version=reader_version,
        extractor_version=extractor_version,
        verifier_version=verifier_version,
        synthesizer_version=synthesizer_version,
        knowledge_schema_version=knowledge_schema_version,
    )
