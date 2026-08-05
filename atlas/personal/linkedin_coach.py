"""LinkedIn profile coaching — suggestions only (never write to LinkedIn).

P10 / P14: Atlas may *read* an export or public page text the operator supplies and propose
improvements. It never clicks, posts, edits, or applies on LinkedIn. The human copies advice
into LinkedIn themselves.
"""

from __future__ import annotations

import re
from typing import Any

_LINKEDIN_IN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?", re.I
)

# Soft targets for a strong professional LinkedIn presence.
_TARGET_ABOUT_CHARS = 200
_TARGET_SKILLS = 8
_TARGET_ROLES = 2


def linkedin_suggestions(
    profile: dict[str, Any],
    *,
    linkedin_text: str | None = None,
    linkedin_url: str | None = None,
) -> dict[str, Any]:
    """Compare owner profile (+ optional LinkedIn export text) → actionable suggestions.

    Returns structured advice Atlas shows in the UI; ``can_write_linkedin`` is always False.
    """
    skills = _clean_skills(profile.get("skills") or [])
    professional = [
        f
        for f in (profile.get("professional") or [])
        if (f.get("value") or {}).get("kind") in {None, "role"}
        or "Role:" in str(f.get("statement") or "")
    ]
    education = [
        f
        for f in (profile.get("timeline") or [])
        if (f.get("value") or {}).get("kind") == "education"
        or str(f.get("statement") or "").lower().startswith("education:")
    ]
    identity = profile.get("identity") or []
    name = _fact_value(identity, "full_name", "name") or _name_from_statements(identity)
    headline = _fact_value(identity, "headline", "text") or _headline_from_identity(identity)
    email = _fact_value(identity, "email", "email")
    known_url = linkedin_url or _fact_value(identity, "linkedin_url", "url")

    li_text = (linkedin_text or "").strip()
    li_has_about = bool(li_text) and len(li_text) >= 80
    li_skills_mentioned = _skills_mentioned_in_text(skills, li_text) if li_text else set()

    suggestions: list[dict[str, Any]] = []

    def tip(priority: str, area: str, action: str, why: str) -> None:
        suggestions.append(
            {
                "priority": priority,  # high | medium | low
                "area": area,
                "action": action,
                "why": why,
                "atlas_writes": False,
            }
        )

    if not name:
        tip(
            "high",
            "identity",
            "Confirm your full name on Personal (from resume) so LinkedIn Headline/About stay consistent.",
            "Name anchors search and recruiter trust.",
        )
    if not headline or len(str(headline)) < 40:
        tip(
            "high",
            "about",
            "Write a 2–4 sentence About section: who you help, top stack, and one proof point.",
            "Profiles with a clear About convert better than skill lists alone.",
        )
    elif li_text and len(li_text) < _TARGET_ABOUT_CHARS:
        tip(
            "high",
            "about",
            f"Expand your LinkedIn About (now ~{len(li_text)} chars) toward {_TARGET_ABOUT_CHARS}+ characters with outcomes, not duties.",
            "Short About sections under-sell senior/IC impact.",
        )

    if len(skills) < _TARGET_SKILLS:
        tip(
            "high",
            "skills",
            f"Confirm at least {_TARGET_SKILLS} real skills on Personal, then mirror the top ones on LinkedIn Skills.",
            "Job matching and LinkedIn search both need a clean skill set.",
        )
    else:
        top = skills[:12]
        tip(
            "medium",
            "skills",
            "On LinkedIn, pin these Atlas-confirmed skills (you edit LinkedIn yourself): "
            + ", ".join(top[:8])
            + ("…" if len(top) > 8 else ""),
            "Keep LinkedIn Skills aligned with verified Personal facts — reject noise first.",
        )
        if li_text and top:
            missing = [s for s in top[:10] if s.lower() not in li_skills_mentioned]
            if missing:
                tip(
                    "medium",
                    "skills",
                    "Add missing high-signal skills to LinkedIn: " + ", ".join(missing[:8]),
                    "These appear on your Atlas profile but not in the LinkedIn text you shared.",
                )

    if len(professional) < _TARGET_ROLES:
        tip(
            "high",
            "experience",
            "Share your resume again or Confirm role facts so Experience entries are complete.",
            "Recruiters scan titles + orgs first; thin Experience hurts matches.",
        )
    else:
        tip(
            "medium",
            "experience",
            "For each role on LinkedIn, add 3 bullets with metrics (latency, users, $ impact, team size).",
            "Outcome bullets beat responsibility lists for career advancement.",
        )

    if not education:
        tip(
            "medium",
            "education",
            "Add education from your CV (Confirm the Education facts on Personal), then mirror on LinkedIn.",
            "Education still filters many India-market roles.",
        )

    if not known_url and not li_text:
        tip(
            "high",
            "access",
            "Share your LinkedIn profile URL or a profile export path in Programs chat "
            "(e.g. `share /path/to/linkedin_export.html`) so Atlas can coach against the live wording.",
            "Without profile text, suggestions stay generic.",
        )
    elif known_url:
        tip(
            "low",
            "access",
            f"Keep Atlas updated when you edit LinkedIn ({known_url}) — re-share the export; Atlas will not edit LinkedIn for you.",
            "Suggestions-only policy (P10): you make every change yourself.",
        )

    if email and li_text and email.lower() not in li_text.lower():
        tip(
            "low",
            "contact",
            "Ensure Contact info on LinkedIn includes a reachable email (you set this in LinkedIn settings).",
            "Missing contact slows inbound recruiter loops.",
        )

    # Career advancement framing
    tip(
        "medium",
        "advancement",
        "Weekly: Confirm new Personal facts → apply top LinkedIn tip → journal what changed.",
        "Compounding small profile upgrades beats one big rewrite.",
    )

    # Sort high → low
    order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: order.get(str(s.get("priority")), 9))

    draft_about = _draft_about(name, headline, skills, professional)

    return {
        "policy": "suggestions_only",
        "can_write_linkedin": False,
        "note": (
            "Atlas never edits LinkedIn. Copy suggestions you agree with into LinkedIn yourself. "
            "This also feeds future job-search matching."
        ),
        "profile_url": known_url,
        "linkedin_text_chars": len(li_text),
        "counts": {
            "skills": len(skills),
            "roles": len(professional),
            "education": len(education),
            "suggestions": len(suggestions),
        },
        "suggestions": suggestions,
        "draft_about": draft_about,
    }


def _clean_skills(facts: list[dict[str, Any]]) -> list[str]:
    from atlas.personal.skill_hygiene import skill_names_from_facts

    return skill_names_from_facts(facts, include_inferred=True)


def _fact_value(facts: list[dict[str, Any]], key: str, field: str) -> str | None:
    for f in facts:
        if f.get("key") == key:
            val = f.get("value") or {}
            if val.get(field):
                return str(val[field])
            stmt = str(f.get("statement") or "")
            if stmt:
                return stmt
    return None


def _name_from_statements(identity: list[dict[str, Any]]) -> str | None:
    for f in identity:
        stmt = str(f.get("statement") or "")
        if stmt.lower().startswith("name:"):
            return stmt.split(":", 1)[-1].strip(" .")
    return None


def _headline_from_identity(identity: list[dict[str, Any]]) -> str | None:
    for f in identity:
        if f.get("key") == "headline":
            return str(f.get("statement") or "")
        val = f.get("value") or {}
        if val.get("kind") == "headline":
            return str(val.get("text") or f.get("statement") or "")
    return None


def _skills_mentioned_in_text(skills: list[str], text: str) -> set[str]:
    low = text.lower()
    return {s.lower() for s in skills if s.lower() in low}


def _draft_about(
    name: str | None,
    headline: str | None,
    skills: list[str],
    professional: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    if headline:
        parts.append(str(headline).strip())
    elif name:
        parts.append(f"I'm {name}, a software professional focused on shipping reliable systems.")
    else:
        parts.append("Software professional focused on shipping reliable systems.")
    if professional:
        roles = []
        for f in professional[:3]:
            val = f.get("value") or {}
            title = val.get("title") or ""
            org = val.get("org") or ""
            if title:
                roles.append(f"{title}" + (f" at {org}" if org else ""))
        if roles:
            parts.append("Recently: " + "; ".join(roles) + ".")
    if skills:
        parts.append("Core strengths: " + ", ".join(skills[:8]) + ".")
    parts.append(
        "(Draft for you to paste into LinkedIn About — Atlas will not post this.)"
    )
    return " ".join(parts)
