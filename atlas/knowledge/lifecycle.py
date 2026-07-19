"""Finding freshness + lifecycle policy helpers (Stage 3B.3).

Knowledge-type aware freshness (D3B.16): newest does not automatically win.
Production policies must stay aligned with eval fixtures in ``atlas.eval.lifecycle``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

FRESHNESS_CURRENT = "current"
FRESHNESS_AGING = "aging"
FRESHNESS_STALE = "stale"

STATUS_ACTIVE = "active"
STATUS_CONTESTED = "contested"
STATUS_DEPRECATED = "deprecated"
STATUS_SUPERSEDED = "superseded"
STATUS_ARCHIVED = "archived"

ACTIVE_STATUSES = frozenset({STATUS_ACTIVE, STATUS_CONTESTED})

# Maturity axis (CC13) — orthogonal to the validity `status` machine. How well-corroborated the
# understanding is, derived from the number of independent supporting sources + confidence.
MATURITY_CANDIDATE = "candidate"
MATURITY_VERIFIED = "verified"
MATURITY_ESTABLISHED = "established"

# Default corroboration thresholds (configurable by the Consolidator).
ESTABLISHED_MIN_SOURCES = 3
VERIFIED_MIN_SOURCES = 2

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def freshness_label(
    *,
    knowledge_type: str,
    age_days: int,
    contradicted: bool = False,
) -> str:
    """Type-aware freshness label (locked eval oracle / production policy)."""
    if contradicted:
        return FRESHNESS_STALE
    kind = (knowledge_type or "").lower()
    if kind in {"software", "api", "sdk"}:
        if age_days <= 90:
            return FRESHNESS_CURRENT
        if age_days <= 365:
            return FRESHNESS_AGING
        return FRESHNESS_STALE
    if kind in {"standard", "regulation"}:
        return FRESHNESS_CURRENT if age_days <= 3650 else FRESHNESS_AGING
    if age_days <= 730:
        return FRESHNESS_CURRENT
    if age_days <= 1825:
        return FRESHNESS_AGING
    return FRESHNESS_STALE


def age_days_since(ts: datetime | str | None, *, now: datetime | None = None) -> int:
    """Whole days since ``ts`` (UTC); unknown → 0."""
    if ts is None:
        return 0
    if isinstance(ts, str):
        raw = ts.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return 0
        ts = parsed
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - ts).total_seconds() // 86400))


def knowledge_type_from_finding(data: dict[str, Any]) -> str:
    """Infer knowledge_type for freshness from provenance / claim_type / domain."""
    prov = data.get("provenance") or {}
    if isinstance(prov, dict) and prov.get("knowledge_type"):
        return str(prov["knowledge_type"])
    claim_type = str(data.get("claim_type", "") or "")
    if claim_type in {"software", "api", "sdk", "standard", "regulation"}:
        return claim_type
    domain = str(data.get("domain", "") or "")
    if domain == "code":
        return "software"
    return "science"


def normalize_statement(statement: str) -> str:
    text = (statement or "").strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_unit(unit: str) -> str:
    return re.sub(r"\s+", "", (unit or "").strip().lower())


def finding_identity_key(data: dict[str, Any]) -> tuple[Any, ...]:
    """Conservative identity key (A3B.1): value+unit+kind, else normalized statement.

    Engineering findings (``domain == "code"``) key on their structural coordinates instead
    (Q-B5): ``repo_uid + path + symbol + claim_type + reader`` — two readers can produce
    different findings for the same symbol, so the reader is part of identity.
    """
    domain = str(data.get("domain", "research") or "research")
    if domain == "code":
        prov = data.get("provenance") or {}
        if isinstance(prov, dict):
            return (
                "code",
                str(prov.get("repo_uid", "")),
                str(prov.get("path", "")),
                str(prov.get("symbol", "")),
                str(data.get("claim_type", "") or ""),
                str(prov.get("reader", "")),
            )
    if domain == "experience":
        # Owner experiences (C.6/CC6) key on skill/technology + context so the *same* skill seen across
        # many projects is ONE cumulative experience (evidence-merged), not N rows. Falls back to the
        # normalized statement when no structured skill is supplied.
        value = data.get("value") if isinstance(data.get("value"), dict) else {}
        skill = str(value.get("skill") or value.get("kind") or "").strip().lower()
        context = str(value.get("context") or "").strip().lower()
        if not skill:
            skill = normalize_statement(str(data.get("statement", "")))
        return ("experience", skill, context)
    value = data.get("value")
    if isinstance(value, dict) and (value.get("kind") or "").strip():
        return (
            "quant",
            domain,
            str(value.get("kind", "")).strip().lower(),
            normalize_unit(str(value.get("unit", ""))),
        )
    return ("prose", domain, normalize_statement(str(data.get("statement", ""))))


def body_fingerprint(data: dict[str, Any]) -> tuple[Any, ...]:
    """Fingerprint of the durable claim **body only** — statement + value.

    Unlike :func:`content_fingerprint`, this EXCLUDES supporting/contradicting sources, confidence
    and status. A change here is a genuine statement/value change (→ revision); a change only in the
    evidence set is *not* a body change (→ evidence-merge in place, C.3d).
    """
    value = data.get("value")
    if isinstance(value, dict):
        value_key: Any = (
            value.get("number"),
            normalize_unit(str(value.get("unit", ""))),
            str(value.get("kind", "")).strip().lower(),
        )
    else:
        value_key = None
    return (normalize_statement(str(data.get("statement", ""))), value_key)


_CONF_ORDER = {"": 0, "UNVERIFIED": 1, "INSUFFICIENT": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4}
_CONF_LABELS = {0: "UNVERIFIED", 1: "UNVERIFIED", 2: "LOW", 3: "MEDIUM", 4: "HIGH"}


def merge_confidence(
    *, existing: str | None, incoming: str | None, source_count: int
) -> str:
    """Confidence after corroboration — monotonic, never downgrades on new support (C.3d).

    Takes the stronger of the existing/incoming label, then bumps for independent corroboration:
    ≥2 sources ⇒ at least MEDIUM, ≥3 ⇒ at least HIGH. Explainable and bounded.
    """
    base = max(
        _CONF_ORDER.get((existing or "").upper(), 0),
        _CONF_ORDER.get((incoming or "").upper(), 0),
    )
    if source_count >= 3:
        base = max(base, 4)
    elif source_count >= 2:
        base = max(base, 3)
    return _CONF_LABELS[base]


def merge_confidence_score(
    *, existing: float, incoming: float, source_count: int
) -> float:
    """Bounded, monotonic score that grows with corroboration (C.3d)."""
    corroboration = 0.3 + 0.2 * max(0, source_count - 1)
    return round(min(0.99, max(existing, incoming, corroboration)), 4)


def content_fingerprint(data: dict[str, Any]) -> tuple[Any, ...]:
    """Fingerprint of durable content — change ⇒ new revision."""
    value = data.get("value")
    value_key: Any
    if isinstance(value, dict):
        value_key = (
            value.get("number"),
            normalize_unit(str(value.get("unit", ""))),
            str(value.get("kind", "")).strip().lower(),
        )
    else:
        value_key = None
    support = tuple(
        sorted(
            str(e.get("source_id", ""))
            for e in (data.get("supporting_sources") or data.get("supporting") or [])
            if isinstance(e, dict)
        )
    )
    contradict = tuple(
        sorted(
            str(e.get("source_id", ""))
            for e in (data.get("contradicting_sources") or data.get("contradicting") or [])
            if isinstance(e, dict)
        )
    )
    return (
        normalize_statement(str(data.get("statement", ""))),
        value_key,
        support,
        contradict,
        str(data.get("confidence", "")),
        str(data.get("status", "")),
    )


def decide_lifecycle_transition(
    *,
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
    content_changed: bool,
) -> str:
    """Lifecycle transition label for consolidation (aligned with eval fixtures)."""
    if existing is None:
        return "create"
    explicit = incoming.get("transition") or incoming.get("gold_transition")
    if explicit in {"archive", "supersede", "split_contested", "revise", "create"}:
        return str(explicit)
    if incoming.get("replaces_canonical"):
        return "supersede"
    if content_changed:
        return "revise"
    return "noop"


def independent_source_count(supporting: Any) -> int:
    """Count *distinct* supporting sources (by source_id, else the raw entry).

    Corroboration is about independent sources, so two evidence entries from the same source_id
    count once. Non-dict entries are counted by their string form.
    """
    seen: set[str] = set()
    for entry in supporting or []:
        if isinstance(entry, dict):
            key = str(entry.get("source_id") or entry.get("source") or entry)
        else:
            key = str(entry)
        if key:
            seen.add(key)
    return len(seen)


def derive_maturity(
    *,
    supporting_count: int,
    confidence: str | None,
    established_min_sources: int = ESTABLISHED_MIN_SOURCES,
    verified_min_sources: int = VERIFIED_MIN_SOURCES,
) -> str:
    """Two-axis maturity from corroboration count + confidence (CC13).

    - ``established``: ≥ ``established_min_sources`` independent sources **and** decent confidence.
    - ``verified``: ≥ ``verified_min_sources`` independent sources **or** HIGH/MEDIUM confidence.
    - ``candidate``: otherwise (a single, uncorroborated observation).
    """
    conf = (confidence or "").upper()
    decent = conf in {"HIGH", "MEDIUM"}
    if supporting_count >= established_min_sources and decent:
        return MATURITY_ESTABLISHED
    if supporting_count >= verified_min_sources or decent:
        return MATURITY_VERIFIED
    return MATURITY_CANDIDATE


def apply_freshness(data: dict[str, Any], *, now: datetime | None = None) -> str:
    """Compute freshness for a finding dict using type-aware policy."""
    contradicted = bool(data.get("contradicting_sources") or data.get("contradicting"))
    ref = data.get("last_verified") or data.get("created_at") or data.get("updated_at")
    return freshness_label(
        knowledge_type=knowledge_type_from_finding(data),
        age_days=age_days_since(ref, now=now),
        contradicted=contradicted,
    )
