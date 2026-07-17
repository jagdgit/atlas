"""Claim Extraction — read Document → structured Claims (§5f, C2 / D3.1, the heart).

Stage 3, Step 4. This is the cognition Atlas was missing: turning a document it has
actually read into **structured claims** (statement + optional value/unit + source +
locator + stance), not chunks or embeddings. These populate the existing
``evidence.models.Claim``/``EvidenceItem`` directly, so the Verification Engine finally
sees claims with real, per-source support instead of URLs.

Hybrid, per the locked decisions (D3.1 / A2 / A5):
- **Deterministic first** — regex over section-scoped sentences pulls quantitative
  claims (a number + unit/percent, e.g. "RMSE from 3.1% to 1.2%", "0.35 %/day").
  Reliable, free, and CPU-friendly; always available.
- **Bounded LLM prose pass (optional)** — when an LLM is wired, the ``researcher`` role
  extracts a few *prose* claims from the abstract + conclusions as strict JSON. It is
  **section-scoped and capped** (A5/D3.9) so it never becomes one giant call, and it can
  only *add* to the deterministic claims — a bad/absent LLM degrades to deterministic.

Each extracted claim carries a **single** ``EvidenceItem`` for its source; grouping the
same finding across sources into one multi-supported claim is Step 5 (§5g).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from atlas.evidence.models import (
    STANCE_SUPPORT,
    Claim,
    ClaimValue,
    EvidenceItem,
    LEVEL_TECHNICAL,
)
from atlas.research.reader import (
    SECTION_ABSTRACT,
    SECTION_BODY,
    SECTION_CONCLUSION,
    SECTION_METHODS,
    SECTION_RESULTS,
    Document,
)

if TYPE_CHECKING:
    from atlas.jobs.activity import ActivityRecorder
    from atlas.llm.service import LLMService

# Prefer results-bearing sections first (A5). Methods is included because many
# papers (and HTML converters like ar5iv) bury quantitative findings under a
# Methods/Experimental heading when Results isn't detected cleanly.
_DEFAULT_SECTIONS = (
    SECTION_ABSTRACT,
    SECTION_RESULTS,
    SECTION_CONCLUSION,
    SECTION_METHODS,
)

# A number followed by a unit/percent. Captures value + unit. Years are filtered later.
# Also accepts European decimals (0,4%), LaTeX ``80\%``, and spaced ``80 %``.
_NUM_UNIT_RE = re.compile(
    r"([-+]?\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d+)?|\d+[.,]\d+|\d+)\s*"
    r"(\\?%|%|percent|pct|"
    r"kwh(?:/m(?:\^?2|²))?|wh|w/m(?:\^?2|²)|kw|mw|gw|"
    r"°?\s?[ck]\b|kelvin|"
    r"kg|g/m(?:\^?2|²)|mg|µg|ug|"
    r"km|cm|mm|nm|µm|um|m\b|"
    r"years?|yrs?|months?|days?|hours?|hrs?|min(?:ute)?s?|"
    r"x\b|×)",
    re.IGNORECASE,
)
# Soft cap on how much body text we scan when falling back (CPU / noise).
_FALLBACK_BODY_CHARS = 40_000
# Don't burn minutes on the LLM prose pass when deterministic already got signal,
# or when the scoped text is tiny (abstract-only chrome).
_LLM_MIN_CHARS = 80
_LLM_TIMEOUT = 45.0
# Keywords that hint at the *kind* of a quantity, for ClaimValue.kind.
_KIND_HINTS = (
    ("rmse", "rmse"), ("mae", "mae"), ("mape", "mape"), ("r2", "r2"),
    ("accuracy", "accuracy"), ("precision", "precision"), ("recall", "recall"),
    ("f1", "f1"), ("efficiency", "efficiency"), ("soiling", "soiling_loss"),
    ("loss", "loss"), ("degradation", "degradation"), ("error", "error"),
    ("yield", "yield"), ("reduction", "reduction"), ("increase", "increase"),
    ("temperature", "temperature"), ("cost", "cost"),
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

_LLM_SYSTEM = (
    "You extract factual claims from a scientific/technical document. Respond with "
    "ONLY a JSON array (no prose). Each element: {\"statement\": str, \"value\": "
    "{\"number\": float, \"unit\": str, \"kind\": str} or null, \"locator\": str}. "
    "Extract concrete, checkable findings (results, measured effects, conclusions). "
    "Do NOT invent numbers or facts not present in the text. At most {max} claims."
)


@dataclass
class ExtractionResult:
    claims: list[Claim] = field(default_factory=list)
    numeric: int = 0
    prose: int = 0

    @property
    def count(self) -> int:
        return len(self.claims)

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "numeric": self.numeric,
            "prose": self.prose,
            "claims": [c.as_dict() for c in self.claims],
        }


def _clean_number(token: str) -> float | None:
    cleaned = token.strip().replace(" ", "").replace("\\", "")
    # European decimal: "0,4" → "0.4"; thousands: "1,234" → "1234".
    if "," in cleaned and "." not in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            cleaned = f"{parts[0]}.{parts[1]}"
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "")
    if _YEAR_RE.match(cleaned):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_unit(unit: str) -> str:
    u = unit.strip().lower().lstrip("\\")
    if u in ("percent", "pct", "%"):
        return "%"
    return unit.strip().lstrip("\\")


def _normalize_text(text: str) -> str:
    """Flatten ar5iv / MathJax noise so numeric regex can fire."""
    if not text:
        return ""
    # "80 % percent 80 80\%" → "80%"
    text = re.sub(
        r"(\d+)\s*%\s*percent\s*\d+\s*\d+\s*\\?%",
        r"\1%",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\\%", "%", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _infer_kind(sentence: str) -> str:
    low = sentence.lower()
    for needle, kind in _KIND_HINTS:
        if needle in low:
            return kind
    return ""


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    # Normalize whitespace, then split on sentence boundaries.
    flat = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in _SENT_SPLIT_RE.split(flat) if s.strip()]


class ClaimExtractor:
    """Extracts structured claims from a read :class:`Document` (hybrid, D3.1)."""

    def __init__(
        self,
        llm: "LLMService | None" = None,
        *,
        max_claims_per_doc: int = 15,
        sections: tuple[str, ...] = _DEFAULT_SECTIONS,
        max_sentence_chars: int = 400,
        logger: logging.Logger | None = None,
    ) -> None:
        self._llm = llm
        self._max = max_claims_per_doc
        self._sections = sections
        self._max_sentence_chars = max_sentence_chars
        self._logger = logger or logging.getLogger("atlas.research.extract")

    def extract(
        self,
        document: Document,
        *,
        evidence_level: int | None = None,
        activity: "ActivityRecorder | None" = None,
    ) -> ExtractionResult:
        level = evidence_level if evidence_level is not None else LEVEL_TECHNICAL
        scoped = self._scoped_sections(document)
        result = ExtractionResult()
        seen: set[str] = set()

        # 1) Deterministic numeric claims (always).
        for label, text in scoped:
            for claim in self._numeric_claims(document, label, text, level):
                key = self._dedup_key(claim)
                if key in seen:
                    continue
                seen.add(key)
                result.claims.append(claim)
                result.numeric += 1
                if len(result.claims) >= self._max:
                    break
            if len(result.claims) >= self._max:
                break

        # If preferred sections yielded nothing, fall back to the full body (capped).
        # Live soiling run (2026-07-14): ar5iv results lived under "methods"/body while
        # abstract+conclusion were prose-only → 0 claims despite a full paper being read.
        if not result.claims and document.text.strip():
            body = _normalize_text(document.text)[:_FALLBACK_BODY_CHARS]
            for claim in self._numeric_claims(document, SECTION_BODY, body, level):
                key = self._dedup_key(claim)
                if key in seen:
                    continue
                seen.add(key)
                result.claims.append(claim)
                result.numeric += 1
                if len(result.claims) >= self._max:
                    break

        # 2) Bounded LLM prose claims (optional; short timeout; skip if no useful text).
        if self._llm is not None and len(result.claims) < self._max:
            budget = self._max - len(result.claims)
            for claim in self._llm_claims(document, scoped, level, budget):
                key = self._dedup_key(claim)
                if key in seen:
                    continue
                seen.add(key)
                result.claims.append(claim)
                result.prose += 1
                if len(result.claims) >= self._max:
                    break

        if activity is not None:
            activity.record(
                "extract",
                f"Extracted {result.count} claim(s) "
                f"({result.numeric} numeric, {result.prose} prose) from: "
                f"{(document.title or document.source_id)[:70]}",
                source_id=document.source_id,
                count=result.count,
            )
        return result

    # --- internals ------------------------------------------------------
    def _scoped_sections(self, document: Document) -> list[tuple[str, str]]:
        """(label, text) for the target sections; fall back to the body/full text."""
        scoped = [
            (s.label, _normalize_text(s.text))
            for s in document.sections
            if s.label in self._sections and s.text.strip()
        ]
        if scoped:
            return scoped
        # No recognized target sections → use whatever text we have (capped upstream).
        if document.text.strip():
            return [(SECTION_BODY, _normalize_text(document.text)[:_FALLBACK_BODY_CHARS])]
        return []

    def _numeric_claims(
        self, document: Document, label: str, text: str, level: int
    ) -> list[Claim]:
        claims: list[Claim] = []
        text = _normalize_text(text)
        for i, sentence in enumerate(_split_sentences(text)):
            match = _NUM_UNIT_RE.search(sentence)
            if match is None:
                continue
            number = _clean_number(match.group(1))
            if number is None:
                continue
            unit = _normalize_unit(match.group(2))
            statement = sentence[: self._max_sentence_chars].strip()
            value = ClaimValue(number=number, unit=unit, kind=_infer_kind(sentence))
            claims.append(
                self._make_claim(document, statement, value, label, level, tag=f"n{i}")
            )
        return claims

    def _llm_claims(
        self,
        document: Document,
        scoped: list[tuple[str, str]],
        level: int,
        budget: int,
    ) -> list[Claim]:
        from atlas.llm.provider import ChatMessage

        # Prose extraction is scoped to abstract + conclusions (short, cheap; A5/D3.9).
        prose_labels = {SECTION_ABSTRACT, SECTION_CONCLUSION}
        parts = [t for lbl, t in scoped if lbl in prose_labels]
        if not parts:
            parts = [t for _, t in scoped[:1]]
        context = "\n\n".join(parts)[:6000].strip()
        if len(context) < _LLM_MIN_CHARS:
            return []
        try:
            resp = self._llm.for_role("researcher").chat(
                [
                    ChatMessage("system", _LLM_SYSTEM.replace("{max}", str(budget))),
                    ChatMessage("user", context),
                ],
                timeout=_LLM_TIMEOUT,
            )
            raw = (resp.text or "").strip()
        except Exception:  # noqa: BLE001 - LLM failure degrades to deterministic-only
            self._logger.debug("LLM prose extraction failed for %s", document.source_id)
            return []
        return self._parse_llm(raw, document, level, budget)

    def _parse_llm(
        self, raw: str, document: Document, level: int, budget: int
    ) -> list[Claim]:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except (ValueError, TypeError):
            return []
        if not isinstance(items, list):
            return []
        claims: list[Claim] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            statement = str(item.get("statement", "")).strip()
            if not statement:
                continue
            statement = statement[: self._max_sentence_chars]
            value = self._parse_value(item.get("value"))
            locator = str(item.get("locator", "")).strip() or "abstract/conclusion"
            claims.append(
                self._make_claim(document, statement, value, locator, level, tag=f"l{i}")
            )
            if len(claims) >= budget:
                break
        return claims

    @staticmethod
    def _parse_value(value: Any) -> ClaimValue | None:
        if not isinstance(value, dict):
            return None
        number = value.get("number")
        try:
            number = float(number)
        except (TypeError, ValueError):
            return None
        return ClaimValue(
            number=number,
            unit=str(value.get("unit", "")).strip(),
            kind=str(value.get("kind", "")).strip(),
        )

    def _make_claim(
        self,
        document: Document,
        statement: str,
        value: ClaimValue | None,
        locator: str,
        level: int,
        *,
        tag: str,
    ) -> Claim:
        claim_id = f"{document.source_id}#{tag}"
        evidence = EvidenceItem(
            source_id=document.source_id,
            evidence_level=level,
            extracted_value=value.number if value else None,
            unit=value.unit if value else "",
            snippet=statement[:300],
            locator=locator,
            stance=STANCE_SUPPORT,
        )
        return Claim(id=claim_id, statement=statement, value=value, evidence=[evidence])

    @staticmethod
    def _dedup_key(claim: Claim) -> str:
        return re.sub(r"\s+", " ", claim.statement.lower()).strip()
