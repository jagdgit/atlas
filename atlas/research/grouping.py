"""Cross-source claim grouping (§5g / D3.7 / A2).

Step 4 produces **per-source** claims: each extracted claim carries a single
``EvidenceItem`` for the document it came from. To let the Verification Engine do what it
was built for — judge a finding by *multiple independent sources* — we must recognise
when two extracted claims are **the same claim** and merge their evidence.

Locked rule (A2):
- **Quantitative claims** (a numeric value with a `kind`): group deterministically by
  ``(kind, normalized-unit)`` and cluster the values by relative tolerance. The largest
  cluster is the agreed claim (supporting evidence); values in other clusters of the same
  ``(kind, unit)`` are **disagreements** → attached as `contradict` evidence, so
  confidence honestly erodes. Reuses the numeric-convergence machinery; no LLM.
- **Prose claims** (no value): group greedily by sentence similarity. v1 uses a
  deterministic token-Jaccard proxy (embedding cosine is the planned upgrade; no heavy
  pairwise-LLM matching). Similar sentences from different sources merge into one claim.

Everything here is pure and deterministic → hermetic and CPU-friendly.
"""

from __future__ import annotations

import re
from typing import Iterable

from atlas.evidence.models import (
    STANCE_CONTRADICT,
    STANCE_SUPPORT,
    Claim,
    ClaimValue,
    EvidenceItem,
)

_DEFAULT_TOLERANCE = 0.15
_DEFAULT_PROSE_SIMILARITY = 0.70
_STOPWORDS = frozenset(
    "the a an of to in on for and or is are was were be been being with by at as "
    "that this these those from into over under about it its their our we they".split()
)
_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_unit(unit: str) -> str:
    return re.sub(r"\s+", "", (unit or "").strip().lower())


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        w for w in _WORD_RE.findall((text or "").lower())
        if w not in _STOPWORDS and len(w) > 1
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def _agrees(value: float, anchor: float, tolerance: float) -> bool:
    window = tolerance * max(abs(anchor), 1e-9)
    return abs(value - anchor) <= window


_DIGIT_RE = re.compile(r"\d")


def _rep(members: list[Claim]) -> Claim:
    """Representative claim of a group: strongest evidence, then *most specific*.

    Specificity favours a statement that actually carries a number (e.g.
    "SVR beat Ridge by 0.4%") over a longer but vaguer paraphrase — so merging
    near-duplicate prose never discards the quantified version (§3B refinement).
    """
    def _peak(c: Claim) -> int:
        return max((e.evidence_level for e in c.evidence), default=0)

    def _has_digits(c: Claim) -> int:
        return 1 if (c.value is not None or _DIGIT_RE.search(c.statement)) else 0

    return max(members, key=lambda c: (_peak(c), _has_digits(c), len(c.statement)))


def _merge_evidence(
    members: Iterable[Claim], *, stance: str | None = None
) -> list[EvidenceItem]:
    """Flatten members' evidence, de-duped by source, optionally forcing a stance."""
    out: list[EvidenceItem] = []
    seen: set[str] = set()
    for claim in members:
        for ev in claim.evidence:
            if ev.source_id in seen:
                continue
            seen.add(ev.source_id)
            if stance is not None and ev.stance != stance:
                ev = EvidenceItem(
                    source_id=ev.source_id,
                    evidence_level=ev.evidence_level,
                    extracted_value=ev.extracted_value,
                    unit=ev.unit,
                    snippet=ev.snippet,
                    locator=ev.locator,
                    stance=stance,
                )
            out.append(ev)
    return out


def _cluster_quant(members: list[Claim], tolerance: float) -> Claim:
    """One merged claim per (kind, unit) bucket; minority values → contradictions."""
    # Greedy value clustering (single pass over value-sorted members).
    ordered = sorted(members, key=lambda c: c.value.number if c.value else 0.0)
    clusters: list[list[Claim]] = []
    for claim in ordered:
        v = claim.value.number
        placed = False
        for cluster in clusters:
            anchor = cluster[0].value.number
            if _agrees(v, anchor, tolerance):
                cluster.append(claim)
                placed = True
                break
        if not placed:
            clusters.append([claim])

    clusters.sort(key=len, reverse=True)
    support = clusters[0]
    rep = _rep(support)
    evidence = _merge_evidence(support, stance=STANCE_SUPPORT)
    # Minority clusters of the *same* quantity disagree → contradicting evidence.
    for minority in clusters[1:]:
        evidence.extend(_merge_evidence(minority, stance=STANCE_CONTRADICT))
    return Claim(
        id=rep.id,
        statement=rep.statement,
        value=rep.value,
        evidence=evidence,
        claim_type=rep.claim_type,
    )


def _cluster_prose(members: list[Claim], threshold: float) -> list[Claim]:
    groups: list[tuple[frozenset[str], list[Claim]]] = []
    for claim in members:
        toks = _tokens(claim.statement)
        best_idx, best_sim = -1, 0.0
        for i, (rep_toks, _) in enumerate(groups):
            sim = _jaccard(toks, rep_toks)
            if sim > best_sim:
                best_idx, best_sim = i, sim
        if best_idx >= 0 and best_sim >= threshold:
            groups[best_idx][1].append(claim)
        else:
            groups.append((toks, [claim]))
    out: list[Claim] = []
    for _, grp in groups:
        rep = _rep(grp)
        out.append(
            Claim(
                id=rep.id,
                statement=rep.statement,
                value=rep.value,
                evidence=_merge_evidence(grp, stance=STANCE_SUPPORT),
                claim_type=rep.claim_type,
            )
        )
    return out


def group_claims(
    claims: list[Claim],
    *,
    tolerance: float = _DEFAULT_TOLERANCE,
    prose_similarity: float = _DEFAULT_PROSE_SIMILARITY,
) -> list[Claim]:
    """Merge per-source claims into multi-source claims (A2). Order is stable-ish."""
    quant_groupable: dict[tuple[str, str], list[Claim]] = {}
    standalone: list[Claim] = []
    prose: list[Claim] = []

    for claim in claims:
        value: ClaimValue | None = claim.value
        if value is not None:
            kind = (value.kind or "").strip().lower()
            if kind:
                # Only quantities with a known *kind* group across sources; a bare number
                # without a kind stays standalone (grouping it would be a false match).
                quant_groupable.setdefault((kind, _norm_unit(value.unit)), []).append(claim)
            else:
                standalone.append(claim)
        else:
            prose.append(claim)

    grouped: list[Claim] = []
    for members in quant_groupable.values():
        grouped.append(_cluster_quant(members, tolerance))
    # Standalone (kind-less numeric, e.g. "q=0.9", "80/20 split") still dedup by
    # statement similarity so the same config isn't reported twice from two papers.
    grouped.extend(_cluster_prose(standalone, prose_similarity))
    grouped.extend(_cluster_prose(prose, prose_similarity))
    return grouped
