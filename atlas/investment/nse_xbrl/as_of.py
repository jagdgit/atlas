"""available_at / evidence_as_of leak protection (L31)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _d(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def fact_usable_as_of(
    fact: dict[str, Any] | None,
    *,
    evidence_as_of: str | date | None,
) -> dict[str, Any]:
    """A May filing must not enter an April (or earlier replay) decision."""
    f = fact if isinstance(fact, dict) else {}
    as_of = _d(evidence_as_of)
    avail = _d(f.get("available_at") or f.get("filed_at"))
    if as_of is None:
        return {"ok": True, "reason": "no_evidence_as_of_bound"}
    if avail is None:
        return {
            "ok": False,
            "reason": "available_at_unknown",
            "honesty": "Do not invent available_at; do not use this fact for a dated decision.",
        }
    if avail > as_of:
        return {"ok": False, "reason": "look_ahead", "available_at": avail.isoformat()}
    return {"ok": True, "available_at": avail.isoformat()}
