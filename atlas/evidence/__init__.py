"""Evidence Graph (Stage 2, S15, D8/§5a) — the unit of truth is a **claim**.

Atlas never emits a raw conclusion; it emits **claims**, each carrying its supporting
and contradicting evidence (graded by quality level L1–L5), a *calculated* confidence,
and a reasoning trace. Stage 3B.2 adds durable **Findings** synthesized from claims.
"""

from __future__ import annotations

from atlas.evidence.models import (
    CLAIM_TYPE_HYPOTHESIS,
    CLAIM_TYPE_PROSE,
    CLAIM_TYPE_QUANT,
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNVERIFIED,
    FINDING_ACTIVE,
    FINDING_ARCHIVED,
    FINDING_CONTESTED,
    FINDING_DEPRECATED,
    FINDING_SUPERSEDED,
    FRESHNESS_AGING,
    FRESHNESS_CURRENT,
    FRESHNESS_STALE,
    Claim,
    ClaimValue,
    EvidenceGraph,
    EvidenceItem,
    Finding,
    Source,
    level_name,
)

__all__ = [
    "Claim",
    "ClaimValue",
    "EvidenceItem",
    "EvidenceGraph",
    "Finding",
    "Source",
    "level_name",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_INSUFFICIENT",
    "CONFIDENCE_UNVERIFIED",
    "FINDING_ACTIVE",
    "FINDING_CONTESTED",
    "FINDING_DEPRECATED",
    "FINDING_SUPERSEDED",
    "FINDING_ARCHIVED",
    "FRESHNESS_CURRENT",
    "FRESHNESS_AGING",
    "FRESHNESS_STALE",
    "CLAIM_TYPE_QUANT",
    "CLAIM_TYPE_PROSE",
    "CLAIM_TYPE_HYPOTHESIS",
]
