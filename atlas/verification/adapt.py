"""Finding → Evidence Claim adapter (KV.1).

Inverse of ``claim_to_finding`` (research synthesis). Media findings carry a
structured ``value`` dict that is *not* a ClaimValue — never pass it through
``ClaimValue.from_dict`` (KeyError on ``number``).
"""

from __future__ import annotations

from typing import Any

from atlas.evidence.models import (
    CONFIDENCE_UNVERIFIED,
    Claim,
    ClaimValue,
    EvidenceItem,
    STANCE_CONTRADICT,
    STANCE_SUPPORT,
)
from atlas.knowledge.normalize import normalize_claim_statement
from atlas.verification.trust import build_trust_profile


def _claim_value(raw: Any) -> ClaimValue | None:
    """Only promote quantitative value shapes into ClaimValue."""
    if not isinstance(raw, dict):
        return None
    if "number" not in raw:
        return None
    try:
        return ClaimValue.from_dict(raw)
    except (KeyError, TypeError, ValueError):
        return None


def _evidence_items(row: dict[str, Any]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for e in row.get("supporting") or row.get("supporting_sources") or []:
        if not isinstance(e, dict):
            continue
        items.append(EvidenceItem.from_dict({**e, "stance": e.get("stance") or STANCE_SUPPORT}))
    for e in row.get("contradicting") or row.get("contradicting_sources") or []:
        if not isinstance(e, dict):
            continue
        items.append(
            EvidenceItem.from_dict({**e, "stance": e.get("stance") or STANCE_CONTRADICT})
        )
    return items


def finding_row_to_claim(row: dict[str, Any], *, claim_id: str | None = None) -> Claim:
    """Build a VerificationEngine ``Claim`` from a durable finding row.

    - Applies entity-alias normalize on the statement (KV.0.5).
    - Leaves confidence UNVERIFIED until the engine runs (KV2).
    - Ignores non-numeric media ``value`` payloads.
    """
    if not isinstance(row, dict):
        raise TypeError("finding row must be a dict")

    fid = str(row.get("id") or "")
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    claim_ids = provenance.get("claim_ids") or row.get("source_claim_ids") or []
    if claim_id is None:
        if isinstance(claim_ids, list) and claim_ids:
            claim_id = str(claim_ids[0])
        elif fid:
            claim_id = f"finding:{fid}"
        else:
            claim_id = "finding:unknown"

    statement = normalize_claim_statement(str(row.get("statement") or ""))
    claim = Claim(
        id=claim_id,
        statement=statement,
        value=_claim_value(row.get("value")),
        evidence=_evidence_items(row),
        confidence=CONFIDENCE_UNVERIFIED,
        confidence_score=0.0,
        claim_type=str(row.get("claim_type") or ""),
    )
    return claim


def claim_verification_writeback(
    claim: Claim,
    *,
    row: dict[str, Any] | None = None,
    contradictions: list[Any] | None = None,
) -> dict[str, Any]:
    """Fields to persist via ``FindingRepository.update_verification`` (+ KV10 trust)."""
    label = str(claim.confidence or CONFIDENCE_UNVERIFIED)
    score = float(claim.confidence_score or 0.0)
    freshness = "stale" if label in {"INSUFFICIENT", "UNVERIFIED"} else "current"
    trust = build_trust_profile(
        claim, row=row, contradictions=contradictions or None
    )
    return {
        "confidence": label,
        "confidence_score": score,  # VerificationEngine score (compat)
        "last_verified": claim.last_verified,
        "freshness": freshness,
        "convergence": claim.convergence,
        "verification_method": claim.verification_method,
        "reasoning_trace": list(claim.reasoning_trace or []),
        "trust": trust,
    }
