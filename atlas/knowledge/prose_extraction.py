"""Prose → knowledge **candidates** (Phase C · §C.3, CC5 / P11/P13).

Turns document text into a *bounded* set of distilled prose claims worth remembering — NOT per-sentence
facts. Each claim is a **candidate** (a transient observation), never a finding: readers/extractors
emit candidates and only the Consolidator turns them into findings (P11). Extraction depth is
config-driven (``max_claims``); a pluggable ``distiller`` callable lets production swap the default
heuristic for an LLM without changing the seam.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from atlas.knowledge.lifecycle import normalize_statement

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")

# A distiller takes (text, max_claims) and returns candidate statements.
Distiller = Callable[[str, int], list[str]]


def _heuristic_distill(text: str, max_claims: int) -> list[str]:
    """Deterministic fallback distiller: substantive, de-duplicated sentences, bounded.

    Keeps sentences that read like claims (enough words, not headers/boilerplate) and drops
    near-duplicates. Crude but stable and model-free — production wires an LLM distiller instead.
    """
    claims: list[str] = []
    seen: set[str] = set()
    for raw in _SENT_SPLIT.split(text or ""):
        sentence = " ".join(raw.split()).strip(" \t-*•").strip()
        if len(sentence) < 40 or len(sentence) > 400:
            continue
        if len(sentence.split()) < 6:
            continue
        norm = normalize_statement(sentence)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        claims.append(sentence)
        if len(claims) >= max_claims:
            break
    return claims


class ProseKnowledgeExtractor:
    """Extract a bounded set of prose knowledge **candidates** from document text (CC5)."""

    def __init__(
        self,
        *,
        distiller: Distiller | None = None,
        max_claims: int = 12,
        default_confidence: str = "UNVERIFIED",
    ) -> None:
        self._distiller = distiller or _heuristic_distill
        self._max_claims = max_claims
        self._confidence = default_confidence

    def extract(
        self,
        text: str,
        *,
        evidence_ref: dict[str, Any] | None = None,
        domain: str = "external",
        max_claims: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return candidate payloads ``{statement, claim_type, domain, confidence, evidence_ref}``.

        The result is a list of *candidate* dicts (never findings) suitable for
        :meth:`atlas.knowledge.candidate_consumer.CandidateConsumer.emit`.
        """
        cap = max_claims if max_claims is not None else self._max_claims
        ev = dict(evidence_ref or {})
        statements = self._distiller(text or "", cap)
        return [
            {
                "statement": s,
                "claim_type": "prose",
                "domain": domain,
                "confidence": self._confidence,
                "evidence_ref": ev,
            }
            for s in statements
        ]
