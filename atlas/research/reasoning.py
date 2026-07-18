"""Cross-document reasoning v1 (Stage 3B.4).

Builds relationship edges, pattern cards, research opportunities from gaps, and
typed hypotheses. Hypotheses are **never** auto-promoted as Findings (A3B.10).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import uuid4

from atlas.evidence.models import CLAIM_TYPE_HYPOTHESIS, Claim, Finding
from atlas.knowledge.lifecycle import normalize_statement, normalize_unit
from atlas.research.gaps import Gap, GapStatus

REL_SUPPORT = "support"
REL_CONTRADICT = "contradict"
REL_REFINE = "refine"

_METHOD_HINTS = (
    "regression",
    "simulation",
    "measurement",
    "experiment",
    "field",
    "lab",
    "model",
    "survey",
    "meta-analysis",
    "cleaning",
    "coating",
)


@dataclass(frozen=True, slots=True)
class RelationshipEdge:
    source_id: str
    target_id: str
    relation: str  # support | contradict | refine
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PatternCard:
    id: str
    kind: str  # value_range | method
    label: str
    detail: str
    member_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "member_ids": list(self.member_ids),
        }


@dataclass(frozen=True, slots=True)
class ResearchOpportunity:
    id: str
    title: str
    why: str
    from_gap_kind: str = ""
    related_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "why": self.why,
            "from_gap_kind": self.from_gap_kind,
            "related_ids": list(self.related_ids),
            "type": "opportunity",
        }


@dataclass(frozen=True, slots=True)
class Hypothesis:
    id: str
    statement: str
    rationale: str
    related_ids: tuple[str, ...] = ()
    status: str = "open"  # open | rejected | adopted (never auto-adopted as finding)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "rationale": self.rationale,
            "related_ids": list(self.related_ids),
            "status": self.status,
            "type": CLAIM_TYPE_HYPOTHESIS,
            "claim_type": CLAIM_TYPE_HYPOTHESIS,
        }


@dataclass
class ReasoningResult:
    edges: list[RelationshipEdge] = field(default_factory=list)
    patterns: list[PatternCard] = field(default_factory=list)
    opportunities: list[ResearchOpportunity] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "edges": [e.as_dict() for e in self.edges],
            "patterns": [p.as_dict() for p in self.patterns],
            "opportunities": [o.as_dict() for o in self.opportunities],
            "hypotheses": [h.as_dict() for h in self.hypotheses],
        }


def _unit_items(items: Sequence[Finding | Claim | dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Finding):
            d = item.as_dict()
        elif isinstance(item, Claim):
            d = item.as_dict()
        else:
            d = dict(item)
        out.append(d)
    return out


def build_relationship_edges(items: Sequence[Finding | Claim | dict[str, Any]]) -> list[RelationshipEdge]:
    """Detect support / contradict / refine links across findings or claims."""
    rows = _unit_items(items)
    edges: list[RelationshipEdge] = []
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            aid, bid = str(a.get("id", "")), str(b.get("id", ""))
            if not aid or not bid:
                continue
            av, bv = a.get("value"), b.get("value")
            if (
                isinstance(av, dict)
                and isinstance(bv, dict)
                and (av.get("kind") or "").strip()
                and str(av.get("kind", "")).lower() == str(bv.get("kind", "")).lower()
                and normalize_unit(str(av.get("unit", ""))) == normalize_unit(str(bv.get("unit", "")))
            ):
                an = float(av.get("number", 0) or 0)
                bn = float(bv.get("number", 0) or 0)
                mag = max(abs(an), abs(bn), 1e-9)
                rel = abs(an - bn) / mag
                if rel <= 0.15:
                    edges.append(
                        RelationshipEdge(
                            aid, bid, REL_SUPPORT, "same quantity within tolerance"
                        )
                    )
                else:
                    edges.append(
                        RelationshipEdge(
                            aid, bid, REL_CONTRADICT, "same quantity diverges beyond tolerance"
                        )
                    )
                continue
            # Contested finding: internal contradict sources → self-edge style via status
            if a.get("contradicting_sources") and aid == bid:
                continue
            sa = normalize_statement(str(a.get("statement", "")))
            sb = normalize_statement(str(b.get("statement", "")))
            if not sa or not sb:
                continue
            ta, tb = set(sa.split()), set(sb.split())
            if not ta or not tb:
                continue
            jaccard = len(ta & tb) / len(ta | tb)
            if jaccard >= 0.7:
                edges.append(
                    RelationshipEdge(aid, bid, REL_SUPPORT, "highly similar statements")
                )
            elif 0.4 <= jaccard < 0.7 and (ta <= tb or tb <= ta):
                edges.append(
                    RelationshipEdge(aid, bid, REL_REFINE, "one statement refines the other")
                )
        # Contested → contradict edge from finding to itself marked via reason on members
        if a.get("contradicting_sources"):
            edges.append(
                RelationshipEdge(
                    str(a.get("id", "")),
                    str(a.get("id", "")),
                    REL_CONTRADICT,
                    "finding has contradicting sources",
                )
            )
    # de-dup
    seen: set[tuple[str, str, str]] = set()
    unique: list[RelationshipEdge] = []
    for e in edges:
        key = (e.source_id, e.target_id, e.relation)
        if key in seen or not e.source_id:
            continue
        seen.add(key)
        unique.append(e)
    return unique


def _qualitative_kind(row: dict[str, Any]) -> str:
    """Read the cue kind of a prose claim from its evidence locator (``prose:<kind>``)."""
    for src in row.get("supporting_sources", []) or []:
        loc = str(src.get("locator", ""))
        if loc.startswith("prose:"):
            return loc.split(":", 1)[1].strip()
    return ""


def build_pattern_cards(items: Sequence[Finding | Claim | dict[str, Any]]) -> list[PatternCard]:
    """Recurring value ranges and method mentions."""
    rows = _unit_items(items)
    cards: list[PatternCard] = []

    # Value-range patterns by (kind, unit)
    buckets: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for row in rows:
        value = row.get("value")
        if not isinstance(value, dict) or not (value.get("kind") or "").strip():
            continue
        key = (str(value["kind"]).lower(), normalize_unit(str(value.get("unit", ""))))
        buckets.setdefault(key, []).append(
            (str(row.get("id", "")), float(value.get("number", 0) or 0))
        )
    for (kind, unit), members in buckets.items():
        if len(members) < 2:
            continue
        nums = [n for _, n in members]
        lo, hi = min(nums), max(nums)
        cards.append(
            PatternCard(
                id=f"pat-{uuid4().hex[:8]}",
                kind="value_range",
                label=f"{kind} ({unit or 'unitless'})",
                detail=f"Recurring range {lo:g}–{hi:g} across {len(members)} finding(s).",
                member_ids=tuple(mid for mid, _ in members if mid),
            )
        )

    # Theme patterns from qualitative (prose) claims, grouped by their cue kind
    # (comparison / finding / method / limitation / recommendation). This is what
    # lets reasoning surface structure from prose, not just numbers.
    themes: dict[str, list[str]] = {}
    for row in rows:
        if isinstance(row.get("value"), dict) and (row["value"].get("kind") or "").strip():
            continue  # numeric claims are handled by value-range buckets above
        kind = _qualitative_kind(row)
        if not kind:
            continue
        themes.setdefault(kind, []).append(str(row.get("id", "")))
    for kind, ids in themes.items():
        uniq = tuple(dict.fromkeys(i for i in ids if i))
        if len(uniq) < 2:
            continue
        cards.append(
            PatternCard(
                id=f"pat-{uuid4().hex[:8]}",
                kind="theme",
                label=f"theme:{kind}",
                detail=f"{len(uniq)} claim(s) express a {kind}.",
                member_ids=uniq,
            )
        )

    # Method patterns from statement text
    method_hits: dict[str, list[str]] = {}
    for row in rows:
        text = str(row.get("statement", "")).lower()
        rid = str(row.get("id", ""))
        for hint in _METHOD_HINTS:
            if re.search(rf"\b{re.escape(hint)}\b", text):
                method_hits.setdefault(hint, []).append(rid)
    for method, ids in method_hits.items():
        uniq = tuple(dict.fromkeys(i for i in ids if i))
        if len(uniq) < 2:
            continue
        cards.append(
            PatternCard(
                id=f"pat-{uuid4().hex[:8]}",
                kind="method",
                label=f"method:{method}",
                detail=f"Method '{method}' recurs in {len(uniq)} finding(s).",
                member_ids=uniq,
            )
        )
    return cards


def opportunities_from_gaps(
    gaps: GapStatus | Sequence[Gap] | None,
    *,
    contested_ids: Sequence[str] = (),
    objective: str = "",
) -> list[ResearchOpportunity]:
    """Contradiction + missing variable / evidence gap → research opportunity."""
    gap_list: list[Gap]
    if gaps is None:
        gap_list = []
    elif isinstance(gaps, GapStatus):
        gap_list = list(gaps.gaps)
    else:
        gap_list = list(gaps)

    opps: list[ResearchOpportunity] = []
    for gap in gap_list:
        title = f"Close {gap.kind} gap"
        why = gap.reason
        if contested_ids and gap.kind in {"convergence", "sources", "peer_reviewed"}:
            why = (
                f"{gap.reason} Contested finding(s) {', '.join(contested_ids[:3])} "
                "suggest resolving contradictions may also help."
            )
        opps.append(
            ResearchOpportunity(
                id=f"opp-{uuid4().hex[:8]}",
                title=title,
                why=why,
                from_gap_kind=gap.kind,
                related_ids=tuple(contested_ids[:5]),
            )
        )

    # Explicit contradiction → opportunity even without budget gap
    if contested_ids and not any(o.from_gap_kind == "contradiction" for o in opps):
        opps.append(
            ResearchOpportunity(
                id=f"opp-{uuid4().hex[:8]}",
                title="Resolve contested findings",
                why=(
                    "Contradiction present without a settled majority; "
                    "gather decisive primary evidence"
                    + (f" for '{objective[:80]}'" if objective else "")
                    + "."
                ),
                from_gap_kind="contradiction",
                related_ids=tuple(contested_ids[:5]),
            )
        )
    return opps


def build_hypotheses(
    *,
    opportunities: Sequence[ResearchOpportunity] = (),
    contested: Sequence[dict[str, Any]] = (),
    objective: str = "",
) -> list[Hypothesis]:
    """Typed open hypotheses — never Findings (A3B.10)."""
    hyps: list[Hypothesis] = []
    for row in contested:
        stmt = str(row.get("statement", "")).strip()
        if not stmt:
            continue
        hyps.append(
            Hypothesis(
                id=f"hyp-{uuid4().hex[:8]}",
                statement=f"Unresolved: {stmt}",
                rationale="Contested evidence; treat as open question until stronger sources converge.",
                related_ids=(str(row.get("id", "")),) if row.get("id") else (),
                status="open",
            )
        )
    for opp in opportunities:
        if opp.from_gap_kind in {"claims", "convergence", "contradiction"}:
            hyps.append(
                Hypothesis(
                    id=f"hyp-{uuid4().hex[:8]}",
                    statement=(
                        f"Additional {opp.from_gap_kind} evidence would change "
                        f"confidence on: {(objective or opp.title)[:120]}"
                    ),
                    rationale=opp.why,
                    related_ids=opp.related_ids,
                    status="open",
                )
            )
    # Cap to keep reports readable
    return hyps[:8]


def reason_across_documents(
    items: Sequence[Finding | Claim | dict[str, Any]],
    *,
    gaps: GapStatus | Sequence[Gap] | None = None,
    objective: str = "",
) -> ReasoningResult:
    """Full v1 reasoning pass over findings/claims + gap status."""
    rows = _unit_items(items)
    edges = build_relationship_edges(rows)
    patterns = build_pattern_cards(rows)
    contested = [
        r
        for r in rows
        if r.get("status") == "contested" or r.get("contradicting_sources")
    ]
    contested_ids = [str(r.get("id", "")) for r in contested if r.get("id")]
    opportunities = opportunities_from_gaps(
        gaps, contested_ids=contested_ids, objective=objective
    )
    hypotheses = build_hypotheses(
        opportunities=opportunities, contested=contested, objective=objective
    )
    return ReasoningResult(
        edges=edges,
        patterns=patterns,
        opportunities=opportunities,
        hypotheses=hypotheses,
    )


class CrossDocumentReasoner:
    """Thin service wrapper for bootstrap / capability-style registration."""

    name = "cross_document_reasoning"

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("atlas.research.reasoning")

    def reason(
        self,
        items: Sequence[Finding | Claim | dict[str, Any]],
        *,
        gaps: GapStatus | Sequence[Gap] | None = None,
        objective: str = "",
    ) -> ReasoningResult:
        result = reason_across_documents(items, gaps=gaps, objective=objective)
        self._logger.debug(
            "reasoning: %d edges, %d patterns, %d opps, %d hypotheses",
            len(result.edges),
            len(result.patterns),
            len(result.opportunities),
            len(result.hypotheses),
        )
        return result


def filter_out_hypotheses(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guard: never promote hypothesis-typed items into knowledge.findings."""
    out = []
    for item in findings:
        ctype = str(item.get("claim_type", "") or item.get("type", ""))
        if ctype == CLAIM_TYPE_HYPOTHESIS or item.get("type") == CLAIM_TYPE_HYPOTHESIS:
            continue
        out.append(item)
    return out
