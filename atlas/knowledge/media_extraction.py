"""Media transcript → typed knowledge **candidates** (KE.2 / KE.2.1).

Deterministic-first extractor for spoken/caption text. Emits candidates with
``claim_type`` in ``{concept, entity, relationship, fact, claim}`` for the
CandidateConsumer → Consolidator path (P11). Never writes findings directly.

**Q5 / KE5:** does **not** assign scored confidence. Candidates omit
``confidence`` / ``confidence_score``; the consumer defaults findings to
lifecycle ``UNVERIFIED`` / ``0`` until the Verification Engine runs.

**KE9:** concept matching uses a layered :class:`ConceptLexicon`
(builtin ∪ user ∪ domain ∪ planner).
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from atlas.knowledge.lifecycle import normalize_statement
from atlas.knowledge.prose_extraction import ProseKnowledgeExtractor

# Closed predicate vocabulary (KE.2). Open / free-form predicates = later.
_PRED_WRITTEN_BY = "written_by"
_PRED_PREFERRED_OVER = "preferred_over"
_PRED_REDUCES = "reduces"
_PRED_INCREASES = "increases"
_PRED_CAUSES = "causes"
_PRED_CREATES = "creates"
_PRED_PROTECTS = "protects_against"
_PRED_LEADS_TO = "leads_to"
_PRED_DEPENDS_ON = "depends_on"
_PRED_ENABLES = "enables"
_PRED_TEACHES = "teaches"

_RELATION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(.+?)\s+written\s+by\s+(.+)", re.I), _PRED_WRITTEN_BY),
    (re.compile(r"(.+?)\s+authored\s+by\s+(.+)", re.I), _PRED_WRITTEN_BY),
    (re.compile(r"(.+?)\s+(?:are|is)\s+preferred\s+over\s+(.+)", re.I), _PRED_PREFERRED_OVER),
    (re.compile(r"(.+?)\s+preferred\s+over\s+(.+)", re.I), _PRED_PREFERRED_OVER),
    (re.compile(r"(.+?)\s+better\s+than\s+(.+)", re.I), _PRED_PREFERRED_OVER),
    (re.compile(r"(.+?)\s+protects?\s+against\s+(.+)", re.I), _PRED_PROTECTS),
    (re.compile(r"(.+?)\s+hedge(?:s|d)?\s+against\s+(.+)", re.I), _PRED_PROTECTS),
    (re.compile(r"(.+?)\s+leads?\s+to\s+(.+)", re.I), _PRED_LEADS_TO),
    (re.compile(r"(.+?)\s+depends?\s+on\s+(.+)", re.I), _PRED_DEPENDS_ON),
    (re.compile(r"(.+?)\s+enables?\s+(.+)", re.I), _PRED_ENABLES),
    (re.compile(r"(.+?)\s+teaches?\s+(.+)", re.I), _PRED_TEACHES),
    (re.compile(r"(.+?)\s+reduces?\s+(.+)", re.I), _PRED_REDUCES),
    (re.compile(r"(.+?)\s+increases?\s+(.+)", re.I), _PRED_INCREASES),
    (re.compile(r"(.+?)\s+causes?\s+(.+)", re.I), _PRED_CAUSES),
    (re.compile(r"(.+?)\s+creates?\s+(.+)", re.I), _PRED_CREATES),
]

# Finance / learning seed lexicon (Q1 — small on purpose).
_DEFAULT_CONCEPTS: frozenset[str] = frozenset(
    {
        "inflation",
        "debt",
        "cash flow",
        "assets",
        "liabilities",
        "investing",
        "investment",
        "purchasing power",
        "middle class",
        "entrepreneurship",
        "entrepreneur",
        "currency",
        "monetary system",
        "wealth",
        "salary",
        "capital",
        "income",
        "expense",
        "expenses",
        "poverty",
        "rich dad",
        "poor dad",
        "financial education",
        "compound interest",
        "passive income",
        "real estate",
        "stock market",
        "stocks",
        "bonds",
        "savings",
        "budget",
        "taxes",
        "tax",
        "credit",
        "interest",
        "risk",
        "return",
        "portfolio",
        "equity",
        "leverage",
        "net worth",
    }
)

_KNOWN_WORKS: tuple[tuple[str, str], ...] = (
    ("rich dad poor dad", "Rich Dad Poor Dad"),
)

_KNOWN_PEOPLE: tuple[tuple[str, str], ...] = (
    ("robert kiyosaki", "Robert Kiyosaki"),
    ("robert kiosaki", "Robert Kiyosaki"),  # KV.0.5 alias
    ("ben bernanke", "Ben Bernanke"),
    ("ben bernaki", "Ben Bernanke"),  # KV.0.5 alias
)

_KNOWN_PLACES: tuple[tuple[str, str], ...] = (
    ("south africa", "South Africa"),
    ("united states", "United States"),
    ("united states of america", "United States"),
    ("america", "America"),
    ("india", "India"),
    ("china", "China"),
    ("russia", "Russia"),
    ("japan", "Japan"),
    ("europe", "Europe"),
    ("asia", "Asia"),
)

_KNOWN_ORGS: tuple[tuple[str, str], ...] = (
    ("federal reserve", "Federal Reserve"),
    ("world bank", "World Bank"),
    ("international monetary fund", "IMF"),
)

_ROLE_SUFFIXES = frozenset(
    {
        "chief",
        "chair",
        "chairman",
        "chairwoman",
        "president",
        "ceo",
        "cfo",
        "minister",
        "secretary",
        "governor",
        "director",
        "founder",
        "author",
    }
)

_PROPER_NAME = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")

# Predicates that are structured enough to count as facts (not mere claims).
_FACT_PREDICATES = frozenset({_PRED_WRITTEN_BY})

_CLAUSE_NOISE = re.compile(
    r"\b(going to|gonna|they're|they are|we're|we are|he's|she's|it's|"
    r"because|which|where|when|while|although|however|"
    r"baffles?|wonder|think that|is that|me is|that teaches|"
    r"what|who|whom|whose|how|why)\b",
    re.I,
)
# Pronouns / determiners that cannot head a graph edge alone.
_STOP_SUBJECTS = frozenset(
    {
        "it",
        "this",
        "that",
        "they",
        "he",
        "she",
        "we",
        "you",
        "i",
        "there",
        "here",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "how",
        "why",
        "the",
        "a",
        "an",
        "and",
        "but",
        "so",
        "or",
        "if",
        "as",
        "my",
        "your",
        "their",
        "our",
        "his",
        "her",
        "its",
    }
)
# Function words that signal a clause fragment rather than a noun phrase.
_FRAGMENT_MARKERS = re.compile(
    r"\b(is|are|was|were|be|been|being|do|does|did|have|has|had|"
    r"will|would|can|could|should|may|might|must|shall|"
    r"to|of|for|from|with|into|onto|about|over|under|"
    r"that|than|then|them|these|those|such)\b",
    re.I,
)

# Epistemic kinds (KE10). observation / question reserved for later extractors.
_EPISTEMIC_BY_CLAIM = {
    "concept": "concept",
    "entity": "entity",
    "relationship": "relationship",
    "fact": "fact",
    "claim": "claim",
    "observation": "observation",
    "question": "question",
}


def _norm_set(items: Iterable[str] | None) -> frozenset[str]:
    if not items:
        return frozenset()
    return frozenset(normalize_statement(c) for c in items if (c or "").strip())


class ConceptLexicon:
    """Layered concept lexicon (KE9).

    Matching uses the union of layers. The extractor never mutates itself —
    Learning Planner / operators add terms into ``user`` / ``domain`` / ``planner``.
    """

    def __init__(
        self,
        *,
        builtin: Iterable[str] | None = None,
        user: Iterable[str] | None = None,
        domain: Iterable[str] | None = None,
        planner: Iterable[str] | None = None,
    ) -> None:
        self.builtin = _norm_set(builtin if builtin is not None else _DEFAULT_CONCEPTS)
        self.user = _norm_set(user)
        self.domain = _norm_set(domain)
        self.planner = _norm_set(planner)

    def all_concepts(self) -> frozenset[str]:
        return self.builtin | self.user | self.domain | self.planner

    def with_user(self, terms: Iterable[str]) -> "ConceptLexicon":
        return ConceptLexicon(
            builtin=self.builtin,
            user=self.user | _norm_set(terms),
            domain=self.domain,
            planner=self.planner,
        )

    def with_domain(self, terms: Iterable[str]) -> "ConceptLexicon":
        return ConceptLexicon(
            builtin=self.builtin,
            user=self.user,
            domain=self.domain | _norm_set(terms),
            planner=self.planner,
        )

    def with_planner(self, terms: Iterable[str]) -> "ConceptLexicon":
        return ConceptLexicon(
            builtin=self.builtin,
            user=self.user,
            domain=self.domain,
            planner=self.planner | _norm_set(terms),
        )


def count_candidates_by_type(payloads: list[dict[str, Any]]) -> dict[str, int]:
    """Map emitted candidates to Learning Report category keys."""
    out = {
        "concepts": 0,
        "entities": 0,
        "relationships": 0,
        "facts": 0,
        "claims": 0,
    }
    for p in payloads:
        ct = str(p.get("claim_type") or "")
        if ct == "concept":
            out["concepts"] += 1
        elif ct == "entity":
            out["entities"] += 1
        elif ct == "relationship":
            out["relationships"] += 1
        elif ct == "fact":
            out["facts"] += 1
        elif ct in {"claim", "prose"}:
            out["claims"] += 1
    return out


def build_knowledge_preview(
    payloads: list[dict[str, Any]], *, limit: int = 5
) -> dict[str, list[str]]:
    """Operator-facing samples for the Learning Report (KE.2.2 / KE.2.6)."""
    buckets: dict[str, list[str]] = {
        "concepts": [],
        "entities": [],
        "relationships": [],
        "facts": [],
        "claims": [],
    }
    type_to_bucket = {
        "concept": "concepts",
        "entity": "entities",
        "relationship": "relationships",
        "fact": "facts",
        "claim": "claims",
        "prose": "claims",
    }
    for p in payloads:
        ct = str(p.get("claim_type") or "")
        bucket = type_to_bucket.get(ct)
        if not bucket or len(buckets[bucket]) >= limit:
            continue
        value = p.get("value") if isinstance(p.get("value"), dict) else {}
        if ct == "concept":
            label = str(value.get("name") or p.get("statement") or "").strip()
            if label.islower():
                label = label.title()
        elif ct == "entity":
            name = str(value.get("name") or "").strip()
            et = str(value.get("entity_type") or "").strip()
            label = f"{name} ({et})" if name and et else name or str(p.get("statement") or "")
        elif ct in {"relationship", "fact"}:
            label = format_spo_preview(value) or str(p.get("statement") or "").strip()
        else:
            label = str(p.get("statement") or "").strip()
        if label and label not in buckets[bucket]:
            buckets[bucket].append(label)
    return buckets


def format_spo_preview(value: dict[str, Any] | None) -> str:
    """KE.2.6 — Subject / Predicate / Object for Learning Report Top Relationships."""
    if not isinstance(value, dict):
        return ""
    subj = str(value.get("subject") or "").strip()
    pred = str(value.get("predicate") or "").strip()
    obj = str(value.get("object") or "").strip()
    if subj and pred and obj:
        return f"{subj} / {pred} / {obj}"
    return ""


def build_extraction_quality(
    text: str,
    payloads: list[dict[str, Any]],
    *,
    caps: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Extractor health stats — not truth confidence (Q5 / KE5)."""
    counts = count_candidates_by_type(payloads)
    limit_map = caps or {}
    caps_hit = [
        key
        for key, n in counts.items()
        if key in limit_map and int(limit_map[key]) > 0 and n >= int(limit_map[key])
    ]
    claims = [p for p in payloads if str(p.get("claim_type") or "") == "claim"]
    linked = 0
    for claim in claims:
        value = claim.get("value") if isinstance(claim.get("value"), dict) else {}
        if value.get("related_concepts") or value.get("related_entities"):
            linked += 1
    provenance = provenance_completeness(payloads)
    return {
        "candidates_emitted": len(payloads),
        "by_type": counts,
        "caps_hit": caps_hit,
        "claims_linked": linked,
        "claims_orphan": max(0, len(claims) - linked),
        "transcript_chars": len(text or ""),
        "provenance": provenance,
        "extractor_version": next(
            (
                str((p.get("value") or {}).get("extractor_version"))
                for p in payloads
                if isinstance(p.get("value"), dict) and p["value"].get("extractor_version")
            ),
            MediaKnowledgeExtractor.VERSION,
        ),
        # Intentionally omitted: extraction_confidence (would violate Q5).
    }


def link_claim_graph(
    payloads: list[dict[str, Any]],
    *,
    extra_concepts: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Attach related concepts/entities + mentions links (KE.2.4).

    Matches against emitted concepts/entities **and** the full lexicon
    (``extra_concepts``) so claims link even when a concept was capped out of
    the emitted set. Speaker on ``value`` is treated as a related entity.
    """
    concepts: list[tuple[str, str]] = []
    entities: list[tuple[str, str]] = []
    seen_c_seed: set[str] = set()
    seen_e_seed: set[str] = set()
    for p in payloads:
        value = p.get("value") if isinstance(p.get("value"), dict) else {}
        ct = str(p.get("claim_type") or "")
        name = str(value.get("name") or "").strip()
        if not name:
            continue
        norm = normalize_statement(name)
        if ct == "concept" and norm not in seen_c_seed:
            seen_c_seed.add(norm)
            concepts.append((norm, name))
        elif ct == "entity" and norm not in seen_e_seed:
            seen_e_seed.add(norm)
            entities.append((norm, name))

    for raw in extra_concepts or ():
        norm = normalize_statement(raw)
        if norm and norm not in seen_c_seed:
            seen_c_seed.add(norm)
            concepts.append((norm, raw if " " in raw else raw.title() if raw.islower() else raw))

    # Longer phrases first so "cash flow" wins over "cash".
    concepts.sort(key=lambda t: len(t[0]), reverse=True)
    entities.sort(key=lambda t: len(t[0]), reverse=True)

    for p in payloads:
        ct = str(p.get("claim_type") or "")
        if ct not in {"claim", "relationship", "fact"}:
            continue
        value = p.get("value") if isinstance(p.get("value"), dict) else {}
        if not isinstance(p.get("value"), dict):
            p["value"] = value = {}
        haystack = normalize_statement(str(p.get("statement") or ""))
        if ct in {"relationship", "fact"}:
            haystack = normalize_statement(
                f"{value.get('subject', '')} {value.get('object', '')} {p.get('statement', '')}"
            )
        related_c: list[str] = []
        related_e: list[str] = []
        seen_c: set[str] = set()
        seen_e: set[str] = set()
        for norm, display in concepts:
            if not norm or norm in seen_c:
                continue
            if re.search(rf"\b{re.escape(norm)}\b", haystack):
                seen_c.add(norm)
                related_c.append(_display_concept(display))
        for norm, display in entities:
            if not norm or norm in seen_e:
                continue
            if re.search(rf"\b{re.escape(norm)}\b", haystack):
                seen_e.add(norm)
                related_e.append(display)
        # Speaker is an entity link even if the name isn't repeated in the sentence.
        speaker = str(value.get("speaker") or "").strip()
        if speaker:
            sn = normalize_statement(speaker)
            if sn and sn not in seen_e:
                seen_e.add(sn)
                related_e.append(speaker)
        value["related_concepts"] = related_c[:8]
        value["related_entities"] = related_e[:8]
        links: list[dict[str, str]] = []
        for name in related_c[:5]:
            links.append({"rel": "mentions", "target_type": "concept", "target": name})
        for name in related_e[:5]:
            links.append({"rel": "mentions", "target_type": "entity", "target": name})
        value["links"] = links
    return payloads


def _display_concept(name: str) -> str:
    text = (name or "").strip()
    if text.islower():
        return text.title()
    return text


def attach_provenance(
    payloads: list[dict[str, Any]],
    text: str,
    *,
    evidence_ref: dict[str, Any] | None = None,
    default_speaker: str | None = None,
    duration_seconds: float | None = None,
    extractor_version: str | None = None,
) -> list[dict[str, Any]]:
    """Attach verification-ready provenance on every candidate (KE.2.3 / KE.2.7).

    Always stores ``asset_id``, ``source_url``, ``extractor_version``, and
    ``status``. Adds ``char_start`` / ``char_end`` / optional timestamp when the
    statement (or SPO subject) can be located in the transcript. UI may hide
    noisy fields; storage stays complete for verify/audit.
    """
    ev = evidence_ref or {}
    body = text or ""
    body_len = max(len(body), 1)
    version = extractor_version or MediaKnowledgeExtractor.VERSION
    for p in payloads:
        value = p.get("value") if isinstance(p.get("value"), dict) else {}
        if not isinstance(p.get("value"), dict):
            p["value"] = value = {}
        value.setdefault("asset_id", ev.get("asset_id"))
        value.setdefault("source_url", ev.get("source_url"))
        value.setdefault("chunk_id", ev.get("chunk_id") or ev.get("chunk_index"))
        value.setdefault("status", "UNVERIFIED")
        value["extractor_version"] = version
        ct = str(p.get("claim_type") or "")
        if value.get("speaker") is None and default_speaker and ct in {
            "claim",
            "relationship",
            "fact",
            "observation",
            "concept",
            "entity",
        }:
            value["speaker"] = default_speaker
        _attach_char_offsets(
            value,
            body,
            statement=str(p.get("statement") or ""),
            claim_type=ct,
            duration_seconds=duration_seconds,
            body_len=body_len,
        )
    return payloads


def _attach_char_offsets(
    value: dict[str, Any],
    body: str,
    *,
    statement: str,
    claim_type: str,
    duration_seconds: float | None,
    body_len: int,
) -> None:
    if "char_start" in value:
        return
    anchors: list[str] = []
    if statement:
        anchors.append(statement)
        if len(statement) > 80:
            anchors.append(statement[:80])
    if claim_type in {"relationship", "fact"}:
        subj = str(value.get("subject") or "").strip()
        obj = str(value.get("object") or "").strip()
        if subj:
            anchors.append(subj)
        if subj and obj:
            anchors.append(f"{subj} {obj}")
    if claim_type in {"concept", "entity"}:
        name = str(value.get("name") or "").strip()
        if name:
            anchors.append(name)
    idx = -1
    used = ""
    for anchor in anchors:
        if not anchor:
            continue
        idx = body.find(anchor)
        if idx < 0:
            idx = body.lower().find(anchor.lower())
        if idx >= 0:
            used = anchor
            break
    if idx < 0 or not used:
        return
    value["char_start"] = idx
    value["char_end"] = idx + len(used)
    value["transcript_offset_chars"] = idx
    if duration_seconds and duration_seconds > 0:
        approx = float(duration_seconds) * (idx / body_len)
        value["timestamp_seconds"] = round(approx, 1)
        if not value.get("timestamp"):
            value["timestamp"] = _format_hms(approx)


def provenance_completeness(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """KE.2.7 audit — how many candidates carry required provenance fields."""
    required = ("asset_id", "extractor_version", "status")
    optional_loc = ("char_start", "speaker", "timestamp", "timestamp_seconds")
    total = len(payloads)
    complete = 0
    with_offsets = 0
    missing: dict[str, int] = {k: 0 for k in required}
    for p in payloads:
        value = p.get("value") if isinstance(p.get("value"), dict) else {}
        ok = True
        for key in required:
            if value.get(key) in (None, ""):
                missing[key] += 1
                ok = False
        if ok:
            complete += 1
        if value.get("char_start") is not None:
            with_offsets += 1
    return {
        "candidates": total,
        "complete_required": complete,
        "with_char_offsets": with_offsets,
        "missing_required": missing,
        "optional_fields": list(optional_loc),
    }


def _format_hms(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _default_speaker_from_payloads(payloads: list[dict[str, Any]]) -> str | None:
    """Prefer a known person entity as default claim speaker when diarization is absent."""
    for p in payloads:
        if str(p.get("claim_type") or "") != "entity":
            continue
        value = p.get("value") if isinstance(p.get("value"), dict) else {}
        if str(value.get("entity_type") or "") == "person":
            name = str(value.get("name") or "").strip()
            if name:
                return name
    return None


class MediaExtractBundle:
    """Typed extract output for media.learn + Learning Report (KE.2.2+)."""

    __slots__ = ("candidates", "counts", "preview", "quality")

    def __init__(
        self,
        candidates: list[dict[str, Any]],
        counts: dict[str, int],
        preview: dict[str, list[str]],
        quality: dict[str, Any],
    ) -> None:
        self.candidates = candidates
        self.counts = counts
        self.preview = preview
        self.quality = quality


class MediaKnowledgeExtractor:
    """Extract typed knowledge candidates from media transcript text (KE.2.7)."""

    VERSION = "ke.2.7"

    def __init__(
        self,
        *,
        max_concepts: int = 24,
        max_entities: int = 24,
        max_relationships: int = 24,
        max_facts: int = 12,
        max_claims: int = 12,
        preview_limit: int = 5,
        lexicon: ConceptLexicon | None = None,
        concept_lexicon: frozenset[str] | set[str] | None = None,
        prose: ProseKnowledgeExtractor | None = None,
    ) -> None:
        self._max_concepts = max_concepts
        self._max_entities = max_entities
        self._max_relationships = max_relationships
        self._max_facts = max_facts
        self._max_claims = max_claims
        self._preview_limit = preview_limit
        if lexicon is not None:
            self._lexicon = lexicon
        elif concept_lexicon is not None:
            # Backward-compatible: treat flat set as builtin override.
            self._lexicon = ConceptLexicon(builtin=concept_lexicon)
        else:
            self._lexicon = ConceptLexicon()
        # Prose distiller for claim sentences — strip any default confidence (Q5).
        self._prose = prose or ProseKnowledgeExtractor(max_claims=max_claims)

    @property
    def lexicon(self) -> ConceptLexicon:
        return self._lexicon

    def extract(
        self,
        text: str,
        *,
        evidence_ref: dict[str, Any] | None = None,
        domain: str = "external",
        speaker: str | None = None,
        timestamp: str | None = None,
        duration_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        ev = dict(evidence_ref or {})
        body = text or ""
        ctx = {"speaker": speaker, "timestamp": timestamp}
        out: list[dict[str, Any]] = []
        out.extend(self._extract_concepts(body, evidence_ref=ev, domain=domain, **ctx))
        out.extend(self._extract_entities(body, evidence_ref=ev, domain=domain, **ctx))
        rels, facts = self._extract_triples(body, evidence_ref=ev, domain=domain, **ctx)
        out.extend(rels)
        out.extend(facts)
        out.extend(self._extract_claims(body, evidence_ref=ev, domain=domain, **ctx))
        default_speaker = speaker or _default_speaker_from_payloads(out)
        # Provenance first so speaker is available for entity linking.
        out = attach_provenance(
            out,
            body,
            evidence_ref=ev,
            default_speaker=default_speaker,
            duration_seconds=duration_seconds,
            extractor_version=self.VERSION,
        )
        out = link_claim_graph(out, extra_concepts=self._lexicon.all_concepts())
        return out

    def extract_bundle(
        self,
        text: str,
        *,
        evidence_ref: dict[str, Any] | None = None,
        domain: str = "external",
        speaker: str | None = None,
        timestamp: str | None = None,
        duration_seconds: float | None = None,
    ) -> MediaExtractBundle:
        """Extract + preview + quality stats for Learning Report operators."""
        candidates = self.extract(
            text,
            evidence_ref=evidence_ref,
            domain=domain,
            speaker=speaker,
            timestamp=timestamp,
            duration_seconds=duration_seconds,
        )
        caps = {
            "concepts": self._max_concepts,
            "entities": self._max_entities,
            "relationships": self._max_relationships,
            "facts": self._max_facts,
            "claims": self._max_claims,
        }
        return MediaExtractBundle(
            candidates=candidates,
            counts=count_candidates_by_type(candidates),
            preview=build_knowledge_preview(candidates, limit=self._preview_limit),
            quality=build_extraction_quality(text, candidates, caps=caps),
        )

    # --- concepts ----------------------------------------------------------
    def _extract_concepts(
        self,
        text: str,
        *,
        evidence_ref: dict[str, Any],
        domain: str,
        speaker: str | None,
        timestamp: str | None,
    ) -> list[dict[str, Any]]:
        lowered = text.lower()
        found: list[str] = []
        seen: set[str] = set()
        concepts = self._lexicon.all_concepts()
        # Longer phrases first so "cash flow" wins over "cash".
        for concept in sorted(concepts, key=len, reverse=True):
            if not concept or concept in seen:
                continue
            if re.search(rf"\b{re.escape(concept)}\b", lowered):
                seen.add(concept)
                found.append(concept)
                if len(found) >= self._max_concepts:
                    break
        return [
            self._candidate(
                statement=f"Concept: {name.title() if name.islower() else name}",
                claim_type="concept",
                domain=domain,
                evidence_ref=evidence_ref,
                value=self._value(
                    "concept",
                    name=name,
                    speaker=speaker,
                    timestamp=timestamp,
                ),
            )
            for name in found
        ]

    # --- entities ----------------------------------------------------------
    def _extract_entities(
        self,
        text: str,
        *,
        evidence_ref: dict[str, Any],
        domain: str,
        speaker: str | None,
        timestamp: str | None,
    ) -> list[dict[str, Any]]:
        found: list[tuple[str, str]] = []  # (display, entity_type)
        seen: set[str] = set()
        concepts = self._lexicon.all_concepts()

        def _add(display: str, entity_type: str) -> None:
            key = normalize_statement(display)
            if not key or key in seen:
                return
            if len(key.split()) > 6:
                return
            seen.add(key)
            found.append((display.strip(), entity_type))

        lowered = text.lower()
        for needle, display in _KNOWN_WORKS:
            if needle in lowered:
                _add(display, "work")
        for needle, display in _KNOWN_PEOPLE:
            if needle in lowered:
                _add(display, "person")
        for needle, display in sorted(_KNOWN_PLACES, key=lambda t: len(t[0]), reverse=True):
            if re.search(rf"\b{re.escape(needle)}\b", lowered):
                _add(display, "place")
        for needle, display in _KNOWN_ORGS:
            if needle in lowered:
                _add(display, "org")

        for match in _PROPER_NAME.finditer(text):
            name = match.group(1).strip()
            if len(name.split()) < 2:
                continue
            norm = normalize_statement(name)
            if norm in concepts or norm in seen:
                continue
            etype = _classify_proper_name(name)
            _add(name, etype)
            if len(found) >= self._max_entities:
                break

        return [
            self._candidate(
                statement=f"Entity: {display} ({etype})",
                claim_type="entity",
                domain=domain,
                evidence_ref=evidence_ref,
                value=self._value(
                    "entity",
                    name=display,
                    entity_type=etype,
                    speaker=speaker,
                    timestamp=timestamp,
                ),
            )
            for display, etype in found[: self._max_entities]
        ]

    # --- relationships / facts ---------------------------------------------
    def _extract_triples(
        self,
        text: str,
        *,
        evidence_ref: dict[str, Any],
        domain: str,
        speaker: str | None,
        timestamp: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        relationships: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        lexicon = self._lexicon.all_concepts()

        for raw in _SENT_SPLIT.split(text):
            sentence = " ".join(raw.split()).strip(" \t-*•").strip()
            if len(sentence) < 12 or len(sentence) > 280:
                continue
            for pattern, predicate in _RELATION_PATTERNS:
                m = pattern.search(sentence)
                if not m:
                    continue
                subj = _spo_phrase(m.group(1), lexicon=lexicon, require_anchor=True)
                obj = _spo_phrase(m.group(2), lexicon=lexicon, require_anchor=True)
                if not subj or not obj:
                    continue
                if normalize_statement(subj) in _STOP_SUBJECTS:
                    continue
                if not _is_structured_spo(subj, obj):
                    continue
                # KE.2.5: both sides must be graphable anchors (lexicon/entity/short NP).
                if not _is_spo_anchor(subj, lexicon=lexicon):
                    continue
                if not _is_spo_anchor(obj, lexicon=lexicon):
                    continue
                key = (normalize_statement(subj), predicate, normalize_statement(obj))
                if key in seen:
                    continue
                seen.add(key)
                statement = f"{subj} {predicate} {obj}"
                if predicate in _FACT_PREDICATES and len(facts) < self._max_facts:
                    facts.append(
                        self._candidate(
                            statement=statement,
                            claim_type="fact",
                            domain=domain,
                            evidence_ref=evidence_ref,
                            value=self._value(
                                "fact",
                                subject=subj,
                                predicate=predicate,
                                object=obj,
                                speaker=speaker,
                                timestamp=timestamp,
                            ),
                        )
                    )
                elif (
                    predicate not in _FACT_PREDICATES
                    and len(relationships) < self._max_relationships
                ):
                    relationships.append(
                        self._candidate(
                            statement=statement,
                            claim_type="relationship",
                            domain=domain,
                            evidence_ref=evidence_ref,
                            value=self._value(
                                "relationship",
                                subject=subj,
                                predicate=predicate,
                                object=obj,
                                speaker=speaker,
                                timestamp=timestamp,
                            ),
                        )
                    )
                break  # one triple per sentence
            if (
                len(relationships) >= self._max_relationships
                and len(facts) >= self._max_facts
            ):
                break
        return relationships, facts

    # --- claims (speaker assertions) ---------------------------------------
    def _extract_claims(
        self,
        text: str,
        *,
        evidence_ref: dict[str, Any],
        domain: str,
        speaker: str | None,
        timestamp: str | None,
    ) -> list[dict[str, Any]]:
        prose = self._prose.extract(
            text, evidence_ref=evidence_ref, domain=domain, max_claims=self._max_claims
        )
        out: list[dict[str, Any]] = []
        for row in prose:
            # Drop any confidence the prose distiller attached (Q5).
            payload = {
                "statement": row["statement"],
                "claim_type": "claim",
                "domain": domain,
                "evidence_ref": dict(evidence_ref),
                "value": self._value(
                    "claim",
                    speaker=speaker,
                    timestamp=timestamp,
                ),
            }
            out.append(payload)
        return out

    def _value(self, claim_type: str, **fields: Any) -> dict[str, Any]:
        """Structured value with epistemic + provenance hooks (KE10 / Q5)."""
        value: dict[str, Any] = {
            "kind": claim_type,
            "epistemic": _EPISTEMIC_BY_CLAIM.get(claim_type, claim_type),
            "speaker": fields.pop("speaker", None),
            "timestamp": fields.pop("timestamp", None),
        }
        for key, val in fields.items():
            if val is not None:
                value[key] = val
        return value

    def _candidate(
        self,
        *,
        statement: str,
        claim_type: str,
        domain: str,
        evidence_ref: dict[str, Any],
        value: dict[str, Any],
    ) -> dict[str, Any]:
        # Q5: intentionally omit confidence / confidence_score.
        return {
            "statement": statement,
            "claim_type": claim_type,
            "domain": domain,
            "evidence_ref": dict(evidence_ref),
            "value": value,
        }


def _clean_phrase(raw: str) -> str:
    text = " ".join((raw or "").split()).strip(" \t-*•\"'.,:;()")
    lowered = text.lower()
    for prefix in ("that ", "which ", "and ", "but ", "so ", "because "):
        if lowered.startswith(prefix):
            text = text[len(prefix) :].strip()
            lowered = text.lower()
    return text


def _classify_proper_name(name: str) -> str:
    """Coarse entity typing (KE.2.4) — place/org/role before defaulting to person."""
    norm = normalize_statement(name)
    for needle, _display in _KNOWN_PLACES:
        if norm == needle or norm.endswith(" " + needle) or needle in norm:
            return "place"
    for needle, _display in _KNOWN_ORGS:
        if needle in norm:
            return "org"
    tokens = norm.split()
    if tokens and tokens[-1] in _ROLE_SUFFIXES:
        return "role"
    # Multi-word all-capitalized geographic patterns often end with common place words.
    if tokens and tokens[-1] in {"africa", "america", "asia", "europe", "india", "china", "russia"}:
        return "place"
    return "person"


def _known_entity_names() -> frozenset[str]:
    names: set[str] = set()
    for group in (_KNOWN_WORKS, _KNOWN_PEOPLE, _KNOWN_PLACES, _KNOWN_ORGS):
        for needle, display in group:
            names.add(normalize_statement(needle))
            names.add(normalize_statement(display))
    return frozenset(names)


_KNOWN_ENTITY_NORMS = _known_entity_names()


def _spo_phrase(
    raw: str, *, lexicon: frozenset[str], require_anchor: bool = False
) -> str:
    """Shorten a capture group into an SPO-friendly phrase (KE15 / KE.2.5).

    When ``require_anchor`` is True (relationship emission), return only a
    lexicon concept, known entity, or short proper-name NP — never a clause
    fragment truncated to N words.
    """
    phrase = _clean_phrase(raw)
    if not phrase:
        return ""
    lowered = normalize_statement(phrase)
    # Prefer a lexicon concept contained in the phrase (longest first).
    for concept in sorted(lexicon, key=len, reverse=True):
        if concept and re.search(rf"\b{re.escape(concept)}\b", lowered):
            return _display_concept(concept)
    # Prefer a known entity contained in the phrase.
    for entity_norm in sorted(_KNOWN_ENTITY_NORMS, key=len, reverse=True):
        if entity_norm and re.search(rf"\b{re.escape(entity_norm)}\b", lowered):
            return _display_known_entity(entity_norm)
    if require_anchor:
        # Accept a short Title-Case proper name with no clause noise.
        words = phrase.split()
        if (
            1 <= len(words) <= 4
            and not _CLAUSE_NOISE.search(phrase)
            and not _looks_like_clause_fragment(phrase)
            and _looks_like_noun_phrase(phrase)
        ):
            return phrase.strip(" ,;:")
        return ""
    # Legacy soften path (unused for relationships): keep leading window.
    words = phrase.split()
    if len(words) > 4:
        phrase = " ".join(words[:4])
    return phrase.strip(" ,;:")


def _display_known_entity(norm: str) -> str:
    for group in (_KNOWN_WORKS, _KNOWN_PEOPLE, _KNOWN_PLACES, _KNOWN_ORGS):
        for needle, display in group:
            if normalize_statement(needle) == norm or normalize_statement(display) == norm:
                return display
    return _display_concept(norm)


def _looks_like_clause_fragment(side: str) -> bool:
    """True when the phrase still looks like prose, not a noun phrase."""
    words = side.split()
    if not words:
        return True
    first = normalize_statement(words[0])
    if first in _STOP_SUBJECTS:
        return True
    if _CLAUSE_NOISE.search(side):
        return True
    # Multiple finite/function markers → clause, not edge endpoint.
    markers = _FRAGMENT_MARKERS.findall(side)
    if len(markers) >= 2:
        return True
    if len(words) >= 3 and _FRAGMENT_MARKERS.search(words[1]):
        return True
    return False


def _looks_like_noun_phrase(side: str) -> bool:
    """Coarse NP check: no leading pronoun, limited length, little clause noise."""
    words = side.split()
    if not words or len(words) > 4:
        return False
    if normalize_statement(words[0]) in _STOP_SUBJECTS:
        return False
    if len(side) > 48:
        return False
    return not _looks_like_clause_fragment(side)


def _is_spo_anchor(side: str, *, lexicon: frozenset[str]) -> bool:
    """KE.2.5 — edge endpoints must resolve to concept/entity/short NP anchors."""
    norm = normalize_statement(side)
    if not norm or norm in _STOP_SUBJECTS:
        return False
    if norm in lexicon or any(
        re.search(rf"\b{re.escape(c)}\b", norm) for c in lexicon if len(c) >= 4
    ):
        return True
    if norm in _KNOWN_ENTITY_NORMS:
        return True
    if any(re.search(rf"\b{re.escape(e)}\b", norm) for e in _KNOWN_ENTITY_NORMS if len(e) >= 4):
        return True
    # Short proper-name / Title Case NP already cleaned.
    words = side.split()
    if 1 <= len(words) <= 4 and _looks_like_noun_phrase(side):
        # Prefer capitalized tokens for unknown NPs (Gold, Cash Flow Thinking).
        caps = sum(1 for w in words if w[:1].isupper())
        if caps >= max(1, len(words) - 1):
            return True
        # All-lowercase single/multi lexicon-like tokens of length >= 3.
        if all(len(w) >= 3 for w in words) and not _FRAGMENT_MARKERS.search(side):
            return True
    return False


def _is_structured_spo(subj: str, obj: str) -> bool:
    """Reject clause fragments that are not usable as graph edges (KE.2.5)."""
    for side in (subj, obj):
        words = side.split()
        if len(words) < 1 or len(words) > 4:
            return False
        if _looks_like_clause_fragment(side):
            return False
        if len(side) > 48:
            return False
    if normalize_statement(subj) == normalize_statement(obj):
        return False
    return True
