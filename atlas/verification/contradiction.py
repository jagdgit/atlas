"""Cross-source contradiction detection for knowledge verification (KV.8 / KV9).

Conservative rules (noise was why this was postponed):

1. **Quantitative** — same ``value.kind`` + unit, relative gap > 15% (mirrors
   ``build_relationship_edges`` / grouping).
2. **SPO relationships** — shared subject+object (normalized), antonym predicates.
3. **Prose claims** — shared related concepts/entities (or solid token overlap) **and**
   opposite polarity cues in the statements.

Hits become ``STANCE_CONTRADICT`` evidence on the claim so VerificationEngine
erodes confidence; findings are marked ``contested`` on write-back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from atlas.evidence.models import EvidenceItem, LEVEL_TECHNICAL, STANCE_CONTRADICT
from atlas.knowledge.lifecycle import normalize_statement, normalize_unit
from atlas.knowledge.normalize import normalize_claim_statement

# Closed antonym pairs for relationship predicates (KE.2 vocabulary).
_PRED_ANTONYMS: dict[str, str] = {
    "increases": "reduces",
    "reduces": "increases",
    "creates": "destroys",
    "destroys": "creates",
    "causes": "prevents",
    "prevents": "causes",
    "enables": "blocks",
    "blocks": "enables",
    "leads_to": "prevents",
    "preferred_over": "preferred_under",  # rare; still catches explicit flip
}

# Statement polarity cues (word-level). Paired so A contains left and B contains right.
_POLARITY_PAIRS: tuple[tuple[str, str], ...] = (
    ("increases", "reduces"),
    ("increase", "reduce"),
    ("rising", "falling"),
    ("higher", "lower"),
    ("buy", "sell"),
    ("buys", "sells"),
    ("assets", "liabilities"),
    ("rich", "poor"),
    ("true", "false"),
    ("always", "never"),
    ("causes", "prevents"),
    ("creates", "destroys"),
    ("good", "bad"),
    ("profit", "loss"),
)

_NUMERIC_TOLERANCE = 0.15
_MIN_JACCARD = 0.35
_MAX_HITS = 5


@dataclass(frozen=True, slots=True)
class ContradictionHit:
    peer_id: str
    reason: str
    peer_statement: str = ""
    evidence_level: int = LEVEL_TECHNICAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "reason": self.reason,
            "peer_statement": self.peer_statement,
            "evidence_level": self.evidence_level,
        }


def _concepts(row: dict[str, Any]) -> set[str]:
    value = row.get("value") if isinstance(row.get("value"), dict) else {}
    out = {
        normalize_statement(str(c))
        for c in (value.get("related_concepts") or [])
        if c
    }
    name = value.get("name")
    if name:
        out.add(normalize_statement(str(name)))
    return {c for c in out if c}


def _entities(row: dict[str, Any]) -> set[str]:
    value = row.get("value") if isinstance(row.get("value"), dict) else {}
    return {
        normalize_statement(str(e))
        for e in (value.get("related_entities") or [])
        if e
    }


def _spo(row: dict[str, Any]) -> tuple[str, str, str] | None:
    value = row.get("value") if isinstance(row.get("value"), dict) else {}
    if not isinstance(value, dict):
        return None
    subj = normalize_statement(str(value.get("subject") or ""))
    pred = normalize_statement(str(value.get("predicate") or ""))
    obj = normalize_statement(str(value.get("object") or ""))
    if subj and pred and obj:
        return subj, pred, obj
    return None


def _quant(row: dict[str, Any]) -> tuple[str, str, float] | None:
    value = row.get("value") if isinstance(row.get("value"), dict) else {}
    if not isinstance(value, dict) or "number" not in value:
        return None
    kind = str(value.get("kind") or "").strip().lower()
    if not kind or kind in {"claim", "concept", "entity", "relationship", "fact"}:
        # Media structured values often use kind=claim — not quantitative.
        return None
    try:
        number = float(value["number"])
    except (TypeError, ValueError, KeyError):
        return None
    unit = normalize_unit(str(value.get("unit") or ""))
    return kind, unit, number


def _tokens(statement: str) -> set[str]:
    return {t for t in normalize_statement(statement).split() if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _shared_anchor(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Require a shared concept/entity (or strong statement overlap) before prose conflict."""
    if _concepts(a) & _concepts(b):
        return True
    if _entities(a) & _entities(b):
        return True
    return _jaccard(_tokens(str(a.get("statement") or "")), _tokens(str(b.get("statement") or ""))) >= _MIN_JACCARD


def _polarity_conflict(sa: str, sb: str) -> str | None:
    na, nb = normalize_statement(sa), normalize_statement(sb)
    ta, tb = set(na.split()), set(nb.split())
    for left, right in _POLARITY_PAIRS:
        if left in ta and right in tb and left not in tb and right not in ta:
            return f"polarity conflict ({left} vs {right})"
        if right in ta and left in tb and right not in tb and left not in ta:
            return f"polarity conflict ({right} vs {left})"
    return None


def _numeric_conflict(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    qa, qb = _quant(a), _quant(b)
    if not qa or not qb:
        return None
    kind_a, unit_a, num_a = qa
    kind_b, unit_b, num_b = qb
    if kind_a != kind_b or unit_a != unit_b:
        return None
    mag = max(abs(num_a), abs(num_b), 1e-9)
    if abs(num_a - num_b) / mag > _NUMERIC_TOLERANCE:
        return f"same quantity {kind_a} diverges ({num_a} vs {num_b} {unit_a})"
    return None


def _spo_conflict(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    sa, sb = _spo(a), _spo(b)
    if not sa or not sb:
        return None
    subj_a, pred_a, obj_a = sa
    subj_b, pred_b, obj_b = sb
    if subj_a != subj_b or obj_a != obj_b:
        return None
    antonym = _PRED_ANTONYMS.get(pred_a)
    if antonym and antonym == pred_b:
        return f"SPO antonym ({pred_a} vs {pred_b}) on {subj_a}→{obj_a}"
    return None


def contradiction_reason(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    """Return a short reason if ``a`` and ``b`` contradict; else None."""
    numeric = _numeric_conflict(a, b)
    if numeric:
        return numeric
    spo = _spo_conflict(a, b)
    if spo:
        return spo
    # Prose / claim polarity — only with a shared anchor to limit noise.
    if not _shared_anchor(a, b):
        return None
    return _polarity_conflict(str(a.get("statement") or ""), str(b.get("statement") or ""))


def find_contradictions(
    row: dict[str, Any],
    peers: Sequence[dict[str, Any]],
    *,
    limit: int = _MAX_HITS,
) -> list[ContradictionHit]:
    """Scan peers for contradictions against ``row`` (excludes self)."""
    rid = str(row.get("id") or "")
    hits: list[ContradictionHit] = []
    for peer in peers:
        pid = str(peer.get("id") or "")
        if not pid or pid == rid:
            continue
        # Skip archived / superseded noise.
        status = str(peer.get("status") or "active").lower()
        if status in {"archived", "superseded"}:
            continue
        reason = contradiction_reason(row, peer)
        if not reason:
            continue
        level = LEVEL_TECHNICAL
        supporting = peer.get("supporting") or peer.get("supporting_sources") or []
        if supporting and isinstance(supporting[0], dict):
            try:
                level = int(supporting[0].get("evidence_level") or LEVEL_TECHNICAL)
            except (TypeError, ValueError):
                level = LEVEL_TECHNICAL
        hits.append(
            ContradictionHit(
                peer_id=pid,
                reason=reason,
                peer_statement=normalize_claim_statement(str(peer.get("statement") or "")),
                evidence_level=level,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def attach_contradictions(claim: Any, hits: Sequence[ContradictionHit]) -> Any:
    """Append contradicting EvidenceItems for each hit (deduped by source_id)."""
    existing = {e.source_id for e in claim.evidence if getattr(e, "source_id", "")}
    for hit in hits:
        source_id = f"kb-contra:{hit.peer_id}"
        if source_id in existing:
            continue
        claim.evidence.append(
            EvidenceItem(
                source_id=source_id,
                evidence_level=hit.evidence_level,
                snippet=(hit.peer_statement or hit.reason)[:200],
                stance=STANCE_CONTRADICT,
            )
        )
        existing.add(source_id)
    return claim
