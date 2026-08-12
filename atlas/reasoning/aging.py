"""Belief aging — effective_confidence from stored confidence + evidence age."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Domain half-lives (days). Markets age faster than abstract engineering heuristics.
DEFAULT_HALF_LIVES_DAYS: dict[str, float] = {
    "market": 90.0,
    "engineering": 365.0,
    "personal": 180.0,
    "cross": 270.0,
}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def age_days(last_evidence_at: Any, *, now: datetime | None = None) -> float:
    dt = _parse_dt(last_evidence_at)
    if dt is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def effective_confidence(
    stored: float,
    *,
    domain: str = "cross",
    last_evidence_at: Any = None,
    half_lives: dict[str, float] | None = None,
    now: datetime | None = None,
) -> float:
    """Exponential decay toward 0 with domain half-life. Floor at 0.05 if stored > 0."""
    conf = max(0.0, min(1.0, float(stored)))
    if conf <= 0:
        return 0.0
    lives = half_lives or DEFAULT_HALF_LIVES_DAYS
    half = float(lives.get((domain or "cross").lower(), lives.get("cross", 270.0)))
    if half <= 0:
        return conf
    days = age_days(last_evidence_at, now=now)
    # 0.5 ** (days / half_life)
    decayed = conf * (0.5 ** (days / half))
    if conf > 0 and decayed < 0.05:
        return 0.05
    return round(decayed, 4)


def with_effective(belief: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    out = dict(belief)
    out["effective_confidence"] = effective_confidence(
        float(belief.get("confidence") or 0),
        domain=str(belief.get("domain") or "cross"),
        last_evidence_at=belief.get("last_evidence_at"),
        now=now,
    )
    out["evidence_age_days"] = round(
        age_days(belief.get("last_evidence_at"), now=now), 2
    )
    return out
