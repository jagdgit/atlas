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
    value = data.get("value")
    if isinstance(value, dict) and (value.get("kind") or "").strip():
        return (
            "quant",
            domain,
            str(value.get("kind", "")).strip().lower(),
            normalize_unit(str(value.get("unit", ""))),
        )
    return ("prose", domain, normalize_statement(str(data.get("statement", ""))))


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


def apply_freshness(data: dict[str, Any], *, now: datetime | None = None) -> str:
    """Compute freshness for a finding dict using type-aware policy."""
    contradicted = bool(data.get("contradicting_sources") or data.get("contradicting"))
    ref = data.get("last_verified") or data.get("created_at") or data.get("updated_at")
    return freshness_label(
        knowledge_type=knowledge_type_from_finding(data),
        age_days=age_days_since(ref, now=now),
        contradicted=contradicted,
    )
