"""Evidence Graph (Stage 2, S15, D8/§5a) — the unit of truth is a **claim**.

Atlas never emits a raw conclusion; it emits **claims**, each carrying its supporting
and contradicting evidence (graded by quality level L1–L5), a *calculated* confidence,
and a reasoning trace. Because a claim is a persistent, serialisable object, Atlas can
**re-verify** it later when new evidence appears.

This package is the data model + graph container; the scoring/convergence/budget logic
lives in ``atlas.verification`` (the Verification Engine).
"""

from __future__ import annotations

from atlas.evidence.models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNVERIFIED,
    Claim,
    ClaimValue,
    EvidenceGraph,
    EvidenceItem,
    Source,
    level_name,
)

__all__ = [
    "Claim",
    "ClaimValue",
    "EvidenceItem",
    "EvidenceGraph",
    "Source",
    "level_name",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_INSUFFICIENT",
    "CONFIDENCE_UNVERIFIED",
]
