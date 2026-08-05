"""Skill label hygiene for Personal drafts, LinkedIn coach, and job ranking (CI.0.1).

Filters test-fixture / hash-suffixed noise (``docker-fb7c6151``, ``skill-cc0d78847e``,
``Original``) so Career Intelligence does not recommend on garbage skills.
"""

from __future__ import annotations

import re
from typing import Any

# Fixture / synthetic labels that should never appear on a resume or job match.
_NOISE_EXACT = frozenset({
    "original",
    "skill",
    "skills",
    "unknown",
    "n/a",
    "none",
})

# ``celery-d0be09db``, ``Airflow-884315d5``, ``skill-cc0d78847e``, ``pg-acec78c1``
_HASH_SUFFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+./-]*-[a-f0-9]{6,}$", re.I)
# Bare synthetic keys like ``skill-cc0d78847e`` without a real package name prefix length check
_SKILL_HASH_RE = re.compile(r"^skill-[a-f0-9]{6,}$", re.I)
_ROLE_HASH_RE = re.compile(r"^role-[a-f0-9]{6,}$", re.I)


def is_noise_skill(name: str | None) -> bool:
    """True if this skill label should be excluded from drafts and ranking."""
    s = str(name or "").strip()
    if len(s) < 2:
        return True
    low = s.lower()
    if low in _NOISE_EXACT:
        return True
    if _SKILL_HASH_RE.match(s) or _ROLE_HASH_RE.match(s):
        return True
    if _HASH_SUFFIX_RE.match(s):
        return True
    return False


def clean_skill_name(name: str | None) -> str | None:
    """Return stripped skill name, or None if empty/noise."""
    s = str(name or "").strip()
    if not s or is_noise_skill(s):
        return None
    return s


def skill_names_from_facts(
    facts: list[dict[str, Any]] | None,
    *,
    include_inferred: bool = True,
    reject_rejected: bool = True,
) -> list[str]:
    """Ordered unique display names from personal skill facts (noise filtered)."""
    out: list[str] = []
    seen: set[str] = set()
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        state = str(f.get("state") or "")
        if reject_rejected and state == "rejected":
            continue
        if state == "inferred" and not include_inferred:
            continue
        val = f.get("value") if isinstance(f.get("value"), dict) else {}
        raw = val.get("skill") or f.get("key") or ""
        name = clean_skill_name(str(raw))
        if name is None:
            continue
        low = name.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(name)
    return out
