"""Evidence Synthesizer — Claims → Findings (Stage 3B.2).

Evolves ``group_claims`` into durable Finding objects with quality dimensions,
provenance, and identity hooks for ``knowledge.findings`` promotion.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence
from uuid import uuid4

from atlas.evidence.models import (
    CLAIM_TYPE_PROSE,
    CLAIM_TYPE_QUANT,
    FINDING_ACTIVE,
    FINDING_CONTESTED,
    FRESHNESS_CURRENT,
    Claim,
    Finding,
)
from atlas.knowledge.provenance import build_finding_provenance
from atlas.research.grouping import group_claims

_COMPONENT = "synthesizer:v1"


def _claim_type(claim: Claim) -> str:
    # Prefer the fine-grained taxonomy (result/parameter/method/…) when the
    # extractor assigned one; fall back to the coarse quant/prose split.
    if (claim.claim_type or "").strip():
        return claim.claim_type
    if claim.value is not None and (claim.value.kind or "").strip():
        return CLAIM_TYPE_QUANT
    return CLAIM_TYPE_PROSE


def _quality_profile(claim: Claim) -> dict[str, Any]:
    """Dimension profile first (D3B.18 / A3B.11) — no opaque overall score."""
    levels = [e.evidence_level for e in claim.evidence] or [0]
    peak = max(levels)
    avg = sum(levels) / len(levels)
    evidence_q = round(peak / 5.0, 3)
    extraction_q = 1.0 if claim.value is not None else 0.7
    completeness = round(min(1.0, len(claim.supporting) / 3.0), 3)
    research_q = round(avg / 5.0, 3)
    return {
        "research": research_q,
        "extraction": extraction_q,
        "evidence": evidence_q,
        "freshness": None,  # filled by lifecycle (3B.3)
        "completeness": completeness,
    }


def claim_to_finding(
    claim: Claim,
    *,
    job_id: str | None = None,
    objective: str = "",
    domain: str = "research",
    documents: dict[str, Any] | None = None,
) -> Finding:
    """Wrap a (grouped + verified) Claim as a Finding."""
    contested = bool(claim.contradicting)
    finding_id = str(uuid4())
    provenance = build_finding_provenance(
        claim,
        finding_id=finding_id,
        job_id=job_id,
        objective=objective,
        component=_COMPONENT,
        documents=documents,
    )
    return Finding(
        id=finding_id,
        statement=claim.statement,
        canonical_id="",  # allocated on durable promote
        revision=1,
        value=claim.value,
        evidence=list(claim.evidence),
        confidence=claim.confidence,
        confidence_score=float(claim.confidence_score or 0.0),
        claim_type=_claim_type(claim),
        status=FINDING_CONTESTED if contested else FINDING_ACTIVE,
        freshness=FRESHNESS_CURRENT,
        quality=_quality_profile(claim),
        provenance=provenance,
        domain=domain,
        last_verified=claim.last_verified,
        source_claim_ids=[claim.id] if claim.id else [],
    )


class EvidenceSynthesizer:
    """``SynthesisCapability`` provider — synthesize(claims) → Findings."""

    name = "synthesis"

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("atlas.research.synthesis")

    def synthesize(
        self,
        claims: Sequence[Claim] | Sequence[dict[str, Any]],
        *args: Any,
        already_grouped: bool = False,
        job_id: str | None = None,
        objective: str = "",
        domain: str = "research",
        documents: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Finding]:
        """Synthesize Findings from claims (groups first unless already_grouped)."""
        del args, kwargs
        parsed = [_as_claim(c) for c in claims]
        grouped = parsed if already_grouped else group_claims(parsed)
        findings = [
            claim_to_finding(
                c,
                job_id=job_id,
                objective=objective,
                domain=domain,
                documents=documents,
            )
            for c in grouped
        ]
        self._logger.debug(
            "synthesized %d finding(s) from %d claim(s) (grouped=%s)",
            len(findings),
            len(parsed),
            already_grouped,
        )
        return findings


def _as_claim(item: Claim | dict[str, Any]) -> Claim:
    if isinstance(item, Claim):
        return item
    return Claim.from_dict(item)
