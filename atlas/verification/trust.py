"""Multi-dimensional trust for knowledge findings (KV10).

Dimensions stay **separate** — never collapse into one unlabeled score:

| Key | Meaning |
|-----|---------|
| ``extraction_confidence`` | Heuristic that the span was extracted correctly (not truth) |
| ``verification_confidence`` | VerificationEngine corroboration score |
| ``source_reliability`` | Prior from evidence levels / source class |
| ``overall_trust`` | Documented weighted blend for mission consumption |

``findings.confidence`` / ``confidence_score`` remain the VerificationEngine
label/score for backward compatibility. Missions that want governance trust
should read ``quality.trust.overall_trust``.
"""

from __future__ import annotations

from typing import Any, Sequence

# Documented blend for overall_trust (mission consumption).
DEFAULT_TRUST_WEIGHTS: dict[str, float] = {
    "verification_confidence": 0.50,
    "source_reliability": 0.30,
    "extraction_confidence": 0.20,
}

_TRUST_VERSION = "kv10.1"


def extraction_confidence(row: dict[str, Any] | None) -> float:
    """Heuristic extraction quality — not epistemic truth (Q5 / KE5)."""
    row = row or {}
    value = row.get("value") if isinstance(row.get("value"), dict) else {}
    claim_type = str(row.get("claim_type") or value.get("kind") or "").lower()

    # Lexicon / structure-backed types are usually extraction-stable.
    if claim_type in {"concept", "entity"}:
        score = 0.82
        if value.get("entity_type") in {"place", "org", "work", "person", "role"}:
            score = 0.88
        return _clamp(score)

    if claim_type in {"relationship", "fact"}:
        score = 0.55
        if value.get("subject") and value.get("predicate") and value.get("object"):
            score += 0.25
        if len(str(value.get("subject") or "").split()) <= 5 and len(
            str(value.get("object") or "").split()
        ) <= 5:
            score += 0.05
        return _clamp(score)

    # Claims / prose: provenance hooks raise confidence the span is real.
    score = 0.45
    if value.get("char_start") is not None or value.get("transcript_offset_chars") is not None:
        score += 0.20
    if value.get("speaker"):
        score += 0.08
    if value.get("timestamp") or value.get("timestamp_seconds") is not None:
        score += 0.05
    concepts = value.get("related_concepts") or []
    entities = value.get("related_entities") or []
    if concepts:
        score += min(0.12, 0.04 * len(concepts))
    if entities:
        score += min(0.10, 0.04 * len(entities))
    stmt = str(row.get("statement") or "")
    words = len(stmt.split())
    if 4 <= words <= 40:
        score += 0.05
    elif words > 60:
        score -= 0.08
    return _clamp(score)


def source_reliability(claim: Any) -> float:
    """Prior from supporting evidence levels (L1–L5 → 0.2–1.0), minus contradictions."""
    supporting = list(getattr(claim, "supporting", None) or [])
    contradicting = list(getattr(claim, "contradicting", None) or [])
    if not supporting:
        return 0.0
    levels: list[float] = []
    for item in supporting:
        try:
            levels.append(float(getattr(item, "evidence_level", 2) or 2))
        except (TypeError, ValueError):
            levels.append(2.0)
    avg = sum(levels) / len(levels)
    # Map L1..L5 → ~0.2..1.0
    score = avg / 5.0
    # Independent-source diversity bonus (capped).
    source_ids = {
        str(getattr(item, "source_id", "") or "")
        for item in supporting
        if getattr(item, "source_id", "")
    }
    if len(source_ids) >= 3:
        score += 0.08
    elif len(source_ids) >= 2:
        score += 0.04
    n_contra = len(
        {
            str(getattr(item, "source_id", "") or "")
            for item in contradicting
            if getattr(item, "source_id", "")
        }
        or contradicting
    )
    if n_contra:
        score *= max(0.4, 1.0 - 0.15 * n_contra)
    return _clamp(score)


def blend_overall(
    dimensions: dict[str, float | None],
    *,
    weights: dict[str, float] | None = None,
    contradiction_count: int = 0,
) -> float:
    """Weighted blend of present dimensions; missing dims redistribute weight."""
    w = dict(weights or DEFAULT_TRUST_WEIGHTS)
    present = {
        k: float(v)
        for k, v in dimensions.items()
        if v is not None and k in w
    }
    if not present:
        return 0.0
    total_w = sum(w[k] for k in present)
    if total_w <= 0:
        return 0.0
    score = sum(present[k] * (w[k] / total_w) for k in present)
    if contradiction_count:
        score *= max(0.4, 1.0 - 0.12 * contradiction_count)
    return _clamp(score)


def build_trust_profile(
    claim: Any,
    *,
    row: dict[str, Any] | None = None,
    contradictions: Sequence[Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Full labeled trust object for ``quality.trust`` write-back."""
    verification = float(getattr(claim, "confidence_score", 0.0) or 0.0)
    label = str(getattr(claim, "confidence", "") or "UNVERIFIED")
    extraction = extraction_confidence(row)
    reliability = source_reliability(claim)
    n_contra = len(list(contradictions or []))
    if not n_contra:
        n_contra = len(list(getattr(claim, "contradicting", None) or []))

    overall = blend_overall(
        {
            "verification_confidence": verification,
            "source_reliability": reliability,
            "extraction_confidence": extraction,
        },
        weights=weights,
        contradiction_count=n_contra,
    )

    profile: dict[str, Any] = {
        "version": _TRUST_VERSION,
        "extraction_confidence": round(extraction, 3),
        "verification_confidence": round(verification, 3),
        "verification_label": label,
        "source_reliability": round(reliability, 3),
        "overall_trust": round(overall, 3),
        "weights": dict(weights or DEFAULT_TRUST_WEIGHTS),
        "dimensions": {
            "extraction_confidence": {
                "score": round(extraction, 3),
                "meaning": "span extraction quality (not truth)",
            },
            "verification_confidence": {
                "score": round(verification, 3),
                "label": label,
                "meaning": "VerificationEngine corroboration",
            },
            "source_reliability": {
                "score": round(reliability, 3),
                "meaning": "evidence-level prior on sources",
            },
            "overall_trust": {
                "score": round(overall, 3),
                "meaning": "blend for mission consumption",
            },
        },
    }
    if contradictions:
        profile["contradictions"] = [
            h.as_dict() if hasattr(h, "as_dict") else dict(h)
            for h in contradictions
        ]
    return profile


def overall_trust_from_finding(row: dict[str, Any] | None) -> float | None:
    """Mission helper: prefer ``quality.trust.overall_trust``, else confidence_score."""
    if not isinstance(row, dict):
        return None
    quality = row.get("quality") if isinstance(row.get("quality"), dict) else {}
    trust = quality.get("trust") if isinstance(quality.get("trust"), dict) else {}
    if trust.get("overall_trust") is not None:
        try:
            return float(trust["overall_trust"])
        except (TypeError, ValueError):
            pass
    if row.get("confidence_score") is not None:
        try:
            return float(row["confidence_score"])
        except (TypeError, ValueError):
            return None
    return None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
