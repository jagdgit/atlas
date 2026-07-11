"""Evidence Graph data model (§5a.1–5a.2).

Frozen/serialisable dataclasses so a graph can be persisted (e.g. in a job's result)
and reloaded for re-verification. Confidence is a *label set by the Verification
Engine* — never set here — so the model stays a pure record of evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- evidence levels (§5a.2): quality, not count. Higher = stronger. -----
LEVEL_FIELD_DATA = 5     # L5 measured field data / primary datasets
LEVEL_PEER_REVIEWED = 4  # L4 peer-reviewed papers
LEVEL_GOVERNMENT = 3     # L3 government / national-lab reports (NREL, Sandia, …)
LEVEL_TECHNICAL = 2      # L2 technical blogs, manufacturer white papers
LEVEL_FORUM = 1          # L1 forums, Reddit, LinkedIn

_LEVEL_NAMES = {
    5: "L5 field data",
    4: "L4 peer-reviewed",
    3: "L3 government/lab",
    2: "L2 technical blog",
    1: "L1 forum",
}


def level_name(level: int) -> str:
    return _LEVEL_NAMES.get(int(level), f"L{level}")


# --- calculated confidence labels (§5a.3) --------------------------------
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_INSUFFICIENT = "INSUFFICIENT"  # too little evidence to judge
CONFIDENCE_UNVERIFIED = "UNVERIFIED"      # not yet run through the engine

# evidence stance toward a claim
STANCE_SUPPORT = "support"
STANCE_CONTRADICT = "contradict"


@dataclass(frozen=True, slots=True)
class Source:
    """A place evidence came from (a paper, report, dataset, page)."""

    id: str
    title: str = ""
    url: str = ""
    evidence_level: int = LEVEL_TECHNICAL
    kind: str = ""  # e.g. "peer_reviewed", "government", "field_data", "blog"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "evidence_level": self.evidence_level,
            "level_name": level_name(self.evidence_level),
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Source":
        return cls(
            id=str(data["id"]),
            title=data.get("title", ""),
            url=data.get("url", ""),
            evidence_level=int(data.get("evidence_level", LEVEL_TECHNICAL)),
            kind=data.get("kind", ""),
        )


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One source's contribution to a claim (§5a.1)."""

    source_id: str
    evidence_level: int
    extracted_value: float | None = None
    unit: str = ""
    snippet: str = ""
    locator: str = ""  # page/section/anchor
    stance: str = STANCE_SUPPORT

    @property
    def supports(self) -> bool:
        return self.stance != STANCE_CONTRADICT

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "evidence_level": self.evidence_level,
            "level_name": level_name(self.evidence_level),
            "extracted_value": self.extracted_value,
            "unit": self.unit,
            "snippet": self.snippet,
            "locator": self.locator,
            "stance": self.stance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceItem":
        return cls(
            source_id=str(data.get("source_id", "")),
            evidence_level=int(data.get("evidence_level", LEVEL_TECHNICAL)),
            extracted_value=(
                float(data["extracted_value"])
                if data.get("extracted_value") is not None
                else None
            ),
            unit=data.get("unit", ""),
            snippet=data.get("snippet", ""),
            locator=data.get("locator", ""),
            stance=data.get("stance", STANCE_SUPPORT),
        )


@dataclass(frozen=True, slots=True)
class ClaimValue:
    number: float
    unit: str = ""
    kind: str = ""  # e.g. "annual_mean"

    def as_dict(self) -> dict[str, Any]:
        return {"number": self.number, "unit": self.unit, "kind": self.kind}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaimValue":
        return cls(
            number=float(data["number"]),
            unit=data.get("unit", ""),
            kind=data.get("kind", ""),
        )


@dataclass
class Claim:
    """A statement Atlas may assert, with graded evidence and a *calculated* confidence."""

    id: str
    statement: str
    value: ClaimValue | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)
    confidence: str = CONFIDENCE_UNVERIFIED
    confidence_score: float = 0.0
    convergence: float | None = None
    last_verified: str | None = None
    verification_method: str = ""
    reasoning_trace: list[str] = field(default_factory=list)

    @property
    def supporting(self) -> list[EvidenceItem]:
        return [e for e in self.evidence if e.supports]

    @property
    def contradicting(self) -> list[EvidenceItem]:
        return [e for e in self.evidence if not e.supports]

    def supporting_values(self) -> list[float]:
        return [e.extracted_value for e in self.supporting if e.extracted_value is not None]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "value": self.value.as_dict() if self.value else None,
            "confidence": self.confidence,
            "confidence_score": round(self.confidence_score, 3),
            "convergence": (
                round(self.convergence, 3) if self.convergence is not None else None
            ),
            "last_verified": self.last_verified,
            "verification_method": self.verification_method,
            "reasoning_trace": list(self.reasoning_trace),
            "supporting_sources": [e.as_dict() for e in self.supporting],
            "contradicting_sources": [e.as_dict() for e in self.contradicting],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        value = data.get("value")
        # Accept both the flat `evidence` list and split supporting/contradicting.
        items: list[EvidenceItem] = []
        if "evidence" in data:
            items = [EvidenceItem.from_dict(e) for e in data["evidence"]]
        else:
            for e in data.get("supporting_sources", []):
                items.append(EvidenceItem.from_dict({**e, "stance": STANCE_SUPPORT}))
            for e in data.get("contradicting_sources", []):
                items.append(EvidenceItem.from_dict({**e, "stance": STANCE_CONTRADICT}))
        return cls(
            id=str(data.get("id", "")),
            statement=data.get("statement", ""),
            value=ClaimValue.from_dict(value) if value else None,
            evidence=items,
        )


class EvidenceGraph:
    """A container of sources + claims (§5a). Serialisable for persistence/re-verify."""

    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.claims: dict[str, Claim] = {}

    def add_source(self, source: Source) -> Source:
        self.sources[source.id] = source
        return source

    def add_claim(self, claim: Claim) -> Claim:
        self.claims[claim.id] = claim
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        return self.claims.get(claim_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sources": [s.as_dict() for s in self.sources.values()],
            "claims": [c.as_dict() for c in self.claims.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceGraph":
        graph = cls()
        for s in data.get("sources", []):
            graph.add_source(Source.from_dict(s))
        for c in data.get("claims", []):
            graph.add_claim(Claim.from_dict(c))
        return graph
