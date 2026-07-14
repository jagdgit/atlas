"""Evidence-gap targeting (§5h / C5 / D3.2) — named gaps, not synonym cycling.

After each verify pass the research loop asks *"what specifically is still missing?"*
and issues a **targeted** next search (government/lab domains, peer-reviewed venues,
numeric confirmation, …) instead of appending another synonym to the objective.

When the document cap is hit with unmet gaps, Atlas surfaces a ranked
*"recommended further reading"* list (title + why) rather than silently stopping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from atlas.evidence.models import (
    LEVEL_GOVERNMENT,
    LEVEL_PEER_REVIEWED,
    Claim,
    EvidenceGraph,
    Source,
)
from atlas.verification.engine import EvidenceBudget

# Named gap kinds the loop can target.
GAP_SOURCES = "sources"
GAP_PEER_REVIEWED = "peer_reviewed"
GAP_GOVERNMENT = "government"
GAP_CONVERGENCE = "convergence"

# Deterministic query refinements per named gap (mode, suffix/site hint).
_GAP_QUERIES: dict[str, list[tuple[str, str]]] = {
    GAP_PEER_REVIEWED: [
        ("scholar", "peer reviewed"),
        ("scholar", "IEEE OR Elsevier OR Springer"),
        ("web", "site:ieeexplore.ieee.org OR site:sciencedirect.com"),
    ],
    GAP_GOVERNMENT: [
        ("web", "site:nrel.gov OR site:energy.gov"),
        ("web", "site:gov laboratory report"),
        ("scholar", "NREL OR Sandia OR national laboratory"),
    ],
    GAP_SOURCES: [
        ("scholar", "review"),
        ("web", "measurement study"),
    ],
    GAP_CONVERGENCE: [
        ("scholar", "measured value OR empirical result"),
        ("web", "dataset OR field measurement"),
    ],
}


@dataclass(frozen=True, slots=True)
class Gap:
    kind: str
    needed: int
    have: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "needed": self.needed,
            "have": self.have,
            "reason": self.reason,
        }


@dataclass
class GapStatus:
    gaps: list[Gap] = field(default_factory=list)
    met: dict[str, bool] = field(default_factory=dict)
    convergence: float = 0.0
    n_sources: int = 0
    n_peer: int = 0
    n_gov: int = 0

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gaps": [g.as_dict() for g in self.gaps],
            "met": dict(self.met),
            "convergence": round(self.convergence, 3),
            "n_sources": self.n_sources,
            "n_peer_reviewed": self.n_peer,
            "n_government": self.n_gov,
        }


def analyze_gaps(
    graph: EvidenceGraph,
    budget: EvidenceBudget,
    *,
    claims: list[Claim] | None = None,
) -> GapStatus:
    """Named evidence gaps across the whole graph (unique supporting sources)."""
    claims = claims if claims is not None else list(graph.claims.values())
    # Unique supporting source ids across all claims (quality by graph.sources level).
    supporting_ids: set[str] = set()
    for claim in claims:
        for ev in claim.supporting:
            supporting_ids.add(ev.source_id)

    levels = []
    for sid in supporting_ids:
        src = graph.sources.get(sid)
        if src is not None:
            levels.append(src.evidence_level)
        else:
            # Fall back to the level attached to an evidence item.
            for claim in claims:
                for ev in claim.supporting:
                    if ev.source_id == sid:
                        levels.append(ev.evidence_level)
                        break

    n = len(supporting_ids)
    n_peer = sum(1 for lvl in levels if lvl >= LEVEL_PEER_REVIEWED)
    n_gov = sum(1 for lvl in levels if lvl == LEVEL_GOVERNMENT)
    # Best numeric convergence among claims (0 if none have ≥2 values).
    conv = 0.0
    for claim in claims:
        values = claim.supporting_values()
        if len(values) >= 2:
            # Local agreement: largest cluster / n within 15% window.
            conv = max(conv, _local_convergence(values))

    met = {
        GAP_SOURCES: n >= budget.min_sources,
        GAP_PEER_REVIEWED: n_peer >= budget.min_peer_reviewed,
        GAP_GOVERNMENT: n_gov >= budget.min_government,
        GAP_CONVERGENCE: conv >= budget.convergence,
    }
    gaps: list[Gap] = []
    if not met[GAP_SOURCES]:
        gaps.append(Gap(
            GAP_SOURCES, budget.min_sources, n,
            f"need ≥{budget.min_sources} supporting sources (have {n})",
        ))
    if not met[GAP_PEER_REVIEWED]:
        gaps.append(Gap(
            GAP_PEER_REVIEWED, budget.min_peer_reviewed, n_peer,
            f"need ≥{budget.min_peer_reviewed} peer-reviewed (have {n_peer})",
        ))
    if not met[GAP_GOVERNMENT]:
        gaps.append(Gap(
            GAP_GOVERNMENT, budget.min_government, n_gov,
            f"need ≥{budget.min_government} government/lab (have {n_gov})",
        ))
    if not met[GAP_CONVERGENCE]:
        gaps.append(Gap(
            GAP_CONVERGENCE, 1, 0 if conv < budget.convergence else 1,
            f"convergence {conv:.0%} < {budget.convergence:.0%} threshold",
        ))
    return GapStatus(
        gaps=gaps, met=met, convergence=conv,
        n_sources=n, n_peer=n_peer, n_gov=n_gov,
    )


def _local_convergence(values: list[float], tolerance: float = 0.15) -> float:
    if len(values) < 2:
        return 0.0
    magnitude = max(abs(sum(values) / len(values)), 1e-9)
    window = tolerance * magnitude
    best = 0
    for anchor in values:
        cluster = sum(1 for v in values if abs(v - anchor) <= window)
        best = max(best, cluster)
    return best / len(values)


def gap_queries(objective: str, gaps: Iterable[Gap], *, base: str) -> list[tuple[str, str]]:
    """Build a (mode, query) plan that targets the *named* unmet gaps."""
    plan: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for gap in gaps:
        for mode, hint in _GAP_QUERIES.get(gap.kind, []):
            query = f"{base} {hint}".strip()
            key = (mode, query)
            if key in seen:
                continue
            seen.add(key)
            plan.append(key)
    return plan


def recommend_reading(
    unread: list[Source],
    gaps: list[Gap],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank unread candidates as 'recommended further reading' (title + why).

    Scoring: prefer sources that would fill the named gaps (peer-reviewed for a
    peer gap, government for a gov gap), then higher evidence level.
    """
    wanted = {g.kind for g in gaps}
    why_peer = "Could fill the peer-reviewed gap."
    why_gov = "Could fill the government/lab gap."
    why_more = "Additional independent source."

    scored: list[tuple[int, dict[str, Any]]] = []
    for src in unread:
        score = src.evidence_level
        reasons: list[str] = []
        if GAP_PEER_REVIEWED in wanted and src.evidence_level >= LEVEL_PEER_REVIEWED:
            score += 10
            reasons.append(why_peer)
        if GAP_GOVERNMENT in wanted and src.evidence_level == LEVEL_GOVERNMENT:
            score += 10
            reasons.append(why_gov)
        if not reasons:
            reasons.append(why_more)
        scored.append((
            score,
            {
                "id": src.id,
                "title": src.title or src.id,
                "url": src.url,
                "evidence_level": src.evidence_level,
                "kind": src.kind,
                "why": " ".join(reasons),
            },
        ))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["title"]))
    return [row for _, row in scored[:limit]]
