"""Knowledge Access Layer — shared retrieve pipeline (Stage 3B.1).

Locked order (D3B.28):

    Retrieve (dense + lexical → equal RRF) → Re-rank → Context Build → LLM

One global ``retrieve(query, …, role=…)`` serves chat, research, and future domains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from atlas.knowledge.domains import RESEARCHER_DOMAINS

# Memory tiers (D3B.20). Archive excluded unless explicitly requested (D3B.21).
#
# Honesty (post-3B.5): only ``knowledge`` is backed by the Access Layer index today.
# ``experience`` is a *domain* tag on knowledge rows (not a separate store walk).
# ``working`` / ``session`` live in MemoryService and are not fused here yet.
# ``archive`` is an opt-in status filter on findings/chunks when present — not a
# separate corpus. Requesting deferred tiers is recorded in RankedContext.meta.
TIER_WORKING = "working"
TIER_SESSION = "session"
TIER_KNOWLEDGE = "knowledge"
TIER_EXPERIENCE = "experience"
TIER_ARCHIVE = "archive"

DEFAULT_TIERS = (TIER_KNOWLEDGE,)
ALL_TIERS = (
    TIER_WORKING,
    TIER_SESSION,
    TIER_KNOWLEDGE,
    TIER_EXPERIENCE,
    TIER_ARCHIVE,
)
# Tiers the Access Layer can actually retrieve from today.
LIVE_TIERS = frozenset({TIER_KNOWLEDGE})
# Accepted but not searched as independent corpora in this retrieve path.
DEFERRED_TIERS = frozenset({TIER_WORKING, TIER_SESSION, TIER_EXPERIENCE, TIER_ARCHIVE})


ROLE_CHAT = "chat"
ROLE_RESEARCH = "research"
ROLE_PLANNER = "planner"
ROLE_SCHEDULER = "scheduler"
ROLE_ENGINEERING = "engineering"
ROLE_PERSONAL = "personal"

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RankedHit:
    """One retrieval hit with fused diagnostics (D3B.30)."""

    chunk_id: str
    document_id: str
    ordinal: int
    content: str
    dense_score: float | None = None
    lexical_score: float | None = None
    rrf_score: float = 0.0
    score: float = 0.0  # post-rerank score used for final ordering
    distance: float | None = None
    similarity: float | None = None
    tier: str = TIER_KNOWLEDGE
    policy_boost: float = 0.0            # signed policy influence folded into `score` (C.5)
    policy_ids: tuple[str, ...] = ()     # which enabled policy rules affected this hit (P9)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "ordinal": self.ordinal,
            "content": self.content,
            "dense_score": self.dense_score,
            "lexical_score": self.lexical_score,
            "rrf_score": self.rrf_score,
            "score": self.score,
            "distance": self.distance,
            "similarity": self.similarity,
            "tier": self.tier,
            "policy_boost": self.policy_boost,
            "policy_ids": list(self.policy_ids),
        }


@dataclass(frozen=True, slots=True)
class RankedContext:
    """Output of Retrieve → Re-rank → Context Build (before LLM)."""

    query: str
    hits: tuple[RankedHit, ...]
    context: str
    citations: tuple[dict[str, Any], ...]
    role: str = ROLE_RESEARCH
    domains: tuple[str, ...] = ()
    tiers: tuple[str, ...] = DEFAULT_TIERS
    mode: str = "hybrid"
    diagnostics_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [h.as_dict() for h in self.hits],
            "context": self.context,
            "citations": list(self.citations),
            "role": self.role,
            "domains": list(self.domains),
            "tiers": list(self.tiers),
            "mode": self.mode,
            "diagnostics_id": self.diagnostics_id,
            "meta": dict(self.meta),
        }


def domains_for_role(role: str, domains: Sequence[str] | None = None) -> list[str] | None:
    """Resolve domain filter: explicit ``domains`` wins; else role defaults."""
    if domains is not None:
        return list(domains)
    role_key = (role or ROLE_RESEARCH).lower()
    if role_key in {ROLE_RESEARCH, ROLE_PLANNER, ROLE_SCHEDULER}:
        return list(RESEARCHER_DOMAINS)
    if role_key == ROLE_ENGINEERING:
        return ["code", "research", "external"]
    if role_key == ROLE_PERSONAL:
        return ["personal", "professional", "experience"]
    # chat / unknown → no domain filter (search all)
    return None


def normalize_tiers(tiers: Sequence[str] | None) -> list[str]:
    """Default to knowledge only; archive never implied."""
    if not tiers:
        return list(DEFAULT_TIERS)
    out = [t for t in tiers if t in ALL_TIERS]
    return out or list(DEFAULT_TIERS)


def partition_tiers(tiers: Sequence[str] | None) -> tuple[list[str], list[str]]:
    """Split requested tiers into live (searchable) vs deferred (acknowledged only)."""
    requested = normalize_tiers(tiers)
    live = [t for t in requested if t in LIVE_TIERS]
    deferred = [t for t in requested if t in DEFERRED_TIERS]
    if not live:
        live = list(DEFAULT_TIERS)
    return live, deferred


def archive_requested(tiers: Sequence[str]) -> bool:
    return TIER_ARCHIVE in tiers


def reciprocal_rank_fusion(
    ranked_id_lists: Sequence[Sequence[str]],
    *,
    k: int = 60,
) -> dict[str, float]:
    """Equal-weight RRF over ranked id lists (A3B.4)."""
    scores: dict[str, float] = {}
    for ranked in ranked_id_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores


def heuristic_rerank(
    hits: Sequence[RankedHit],
    query: str,
    *,
    soft_bias_terms: Sequence[str] | None = None,
    soft_bias_boost: float = 0.005,
    policy_rules: Sequence[dict[str, Any]] | None = None,
) -> list[RankedHit]:
    """Cheap token-overlap boost on top of RRF (swappable for cross-encoder later).

    Optional ``soft_bias_terms`` (from *applied + bias-enabled* experiences only)
    add a tiny extra boost — never filter or hide results (A3B.18 / A3B.25).

    Optional ``policy_rules`` (signed influence from enabled operator policies, C.5/CC8) add a small
    **signed** delta — prefer/trust push a matching hit up, avoid/distrust push it down — recording the
    rule ids that affected each hit for explainability. **Influence, not arbitration:** a hit is never
    removed or hard-filtered, only re-ordered.
    """
    q_tokens = set(_WORD_RE.findall((query or "").lower()))
    bias_tokens: set[str] = set()
    for term in soft_bias_terms or ():
        bias_tokens.update(_WORD_RE.findall(str(term).lower()))
    reranked: list[RankedHit] = []
    for hit in hits:
        boost = 0.0
        c_tokens = set(_WORD_RE.findall(hit.content.lower()))
        if q_tokens:
            boost = 0.01 * (len(q_tokens & c_tokens) / len(q_tokens))
        if bias_tokens and soft_bias_boost > 0:
            # Tiny additive boost only; never removes or hard-filters hits.
            boost += soft_bias_boost * (len(bias_tokens & c_tokens) / max(len(bias_tokens), 1))
        policy_delta = 0.0
        applied_ids: list[str] = []
        for pr in policy_rules or ():
            terms = pr.get("terms") or ()
            weight = float(pr.get("weight") or 0.0)
            if not terms or weight == 0.0:
                continue
            tset = set(terms)
            overlap = len(tset & c_tokens) / len(tset)
            if overlap > 0:
                policy_delta += weight * overlap
                applied_ids.append(str(pr.get("id")))
        score = hit.rrf_score + boost + policy_delta
        reranked.append(
            RankedHit(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                ordinal=hit.ordinal,
                content=hit.content,
                dense_score=hit.dense_score,
                lexical_score=hit.lexical_score,
                rrf_score=hit.rrf_score,
                score=score,
                distance=hit.distance,
                similarity=hit.similarity,
                tier=hit.tier,
                policy_boost=policy_delta,
                policy_ids=tuple(applied_ids),
            )
        )
    reranked.sort(key=lambda h: h.score, reverse=True)
    return reranked


def build_context(
    hits: Sequence[RankedHit],
    *,
    max_chars: int = 6000,
) -> tuple[str, list[dict[str, Any]]]:
    """Assemble numbered context + citation dicts (de-dup by chunk_id)."""
    blocks: list[str] = []
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    used = 0
    index = 0
    for hit in hits:
        if hit.chunk_id in seen:
            continue
        seen.add(hit.chunk_id)
        index += 1
        block = f"[{index}] {hit.content}"
        if index > 1 and used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
        citations.append(
            {
                "index": index,
                "document_id": hit.document_id,
                "chunk_id": hit.chunk_id,
                "similarity": hit.similarity,
                "dense_score": hit.dense_score,
                "lexical_score": hit.lexical_score,
                "rrf_score": hit.rrf_score,
                "score": hit.score,
                "snippet": _snippet(hit.content),
                "tier": hit.tier,
                "policy_boost": hit.policy_boost,
                "policy_ids": list(hit.policy_ids),
            }
        )
    return "\n\n".join(blocks), citations


def fuse_dense_lexical(
    dense_rows: Iterable[dict[str, Any]],
    lexical_rows: Iterable[dict[str, Any]],
    *,
    rrf_k: int = 60,
) -> list[RankedHit]:
    """Build RankedHit list from dense + lexical candidate rows via equal RRF."""
    dense_list = list(dense_rows)
    lexical_list = list(lexical_rows)
    dense_ids = [str(r["chunk_id"]) for r in dense_list]
    lexical_ids = [str(r["chunk_id"]) for r in lexical_list]
    rrf = reciprocal_rank_fusion([dense_ids, lexical_ids], k=rrf_k)

    by_id: dict[str, dict[str, Any]] = {}
    dense_rank: dict[str, float] = {}
    lexical_rank: dict[str, float] = {}

    for i, row in enumerate(dense_list, start=1):
        cid = str(row["chunk_id"])
        by_id[cid] = row
        # Higher is better for diagnostics: invert rank position + keep similarity.
        distance = float(row.get("distance", 1.0))
        dense_rank[cid] = 1.0 - distance  # similarity

    for i, row in enumerate(lexical_list, start=1):
        cid = str(row["chunk_id"])
        by_id.setdefault(cid, row)
        lexical_rank[cid] = float(row.get("rank", 1.0 / i))

    hits: list[RankedHit] = []
    for cid, rrf_score in rrf.items():
        row = by_id[cid]
        distance = row.get("distance")
        similarity = (1.0 - float(distance)) if distance is not None else dense_rank.get(cid)
        hits.append(
            RankedHit(
                chunk_id=cid,
                document_id=str(row["document_id"]),
                ordinal=int(row.get("ordinal", 0)),
                content=str(row.get("content", "")),
                dense_score=dense_rank.get(cid),
                lexical_score=lexical_rank.get(cid),
                rrf_score=rrf_score,
                score=rrf_score,
                distance=float(distance) if distance is not None else None,
                similarity=float(similarity) if similarity is not None else None,
                tier=TIER_KNOWLEDGE,
            )
        )
    hits.sort(key=lambda h: h.rrf_score, reverse=True)
    return hits


def _snippet(content: str, limit: int = 140) -> str:
    text = " ".join((content or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
