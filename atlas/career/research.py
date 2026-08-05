"""Career Research helpers + gated actions (CI.2.5 / CI.4 / CI.5)."""

from __future__ import annotations

import time
from typing import Any, Iterable

from atlas.career.ckg import company_id_for, resolve_company, skill_gaps
from atlas.decision.rules import CapabilityGap


def research_pack_for_company(
    name: str,
    *,
    company_data: Any | None = None,
    jobs: Iterable[dict[str, Any]] | None = None,
    seed_facts: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a Career Research pack on the shared Company entity (never applies)."""
    resolved = resolve_company(name, company_data=company_data)
    company_id = str(resolved.get("company_id") or company_id_for(name))
    related_jobs = [
        j
        for j in (jobs or [])
        if isinstance(j, dict)
        and (
            str(j.get("company") or "").strip().lower() == name.strip().lower()
            or str(j.get("company_id") or "") == company_id
        )
    ]
    facts = [str(f).strip() for f in (seed_facts or []) if str(f).strip()]
    profile = resolved.get("profile") if isinstance(resolved.get("profile"), dict) else {}
    if profile:
        if profile.get("sector"):
            facts.append(f"Sector: {profile['sector']}")
        for f in profile.get("facts") or []:
            if str(f).strip():
                facts.append(str(f).strip())

    # Heuristic sufficiency — real verify is later; Advisor can still soft-rank.
    stability = 0.55
    if any("stable" in f.lower() or "profit" in f.lower() for f in facts):
        stability = 0.75
    if any("layoff" in f.lower() or "distress" in f.lower() for f in facts):
        stability = 0.25
    learning = 0.6 if related_jobs else 0.4
    if any("research" in str(j.get("title") or "").lower() for j in related_jobs):
        learning = 0.75

    sufficiency = "partial" if facts or related_jobs else "thin"
    if profile and facts:
        sufficiency = "adequate"

    return {
        "schema": "career.research_pack.1",
        "company_id": company_id,
        "name": name,
        "symbol": resolved.get("symbol"),
        "jobs_observed": len(related_jobs),
        "facts": facts[:40],
        "stability_score": stability,
        "network_score": 0.5,
        "learning_opportunity": learning,
        "research_sufficiency": sufficiency,
        "as_of": time.time(),
        "policy": "research_only",
        "can_apply": False,
    }


def research_candidates(pack: dict[str, Any], *, mission_id: str | None = None) -> list[dict[str, Any]]:
    """Emit domain=career candidates from a research pack (P11 path)."""
    company_id = pack.get("company_id")
    name = pack.get("name")
    payloads = [
        {
            "statement": (
                f"Career research sufficiency for {name} ({company_id}): "
                f"{pack.get('research_sufficiency')}"
            ),
            "claim_type": "fact",
            "domain": "career",
            "value": {
                "company_id": company_id,
                "name": name,
                "research_sufficiency": pack.get("research_sufficiency"),
                "stability_score": pack.get("stability_score"),
            },
            "evidence_ref": {"source": "career_research", "company_id": company_id, "mission_id": mission_id},
            "provenance": {"pipeline": "career_research", "ci": "CI.2.5"},
            "reader": "career_research",
            "reader_version": 1,
            "mission_id": mission_id,
        }
    ]
    for fact in pack.get("facts") or []:
        payloads.append(
            {
                "statement": f"{name}: {fact}",
                "claim_type": "claim",
                "domain": "career",
                "value": {"company_id": company_id, "fact": fact},
                "evidence_ref": {"source": "career_research", "company_id": company_id},
                "provenance": {"pipeline": "career_research", "ci": "CI.2.5"},
                "reader": "career_research",
                "reader_version": 1,
                "mission_id": mission_id,
            }
        )
    return payloads


def propose_learning_plans(gaps: dict[str, Any], *, max_plans: int = 5) -> list[dict[str, Any]]:
    """CI.4.4 — Learning Plans from repeated skill gaps (proposals only)."""
    plans = []
    for row in (gaps.get("gaps") or [])[:max_plans]:
        skill = str(row.get("skill") or "").strip()
        if not skill:
            continue
        plans.append(
            {
                "schema": "career.learning_plan.1",
                "skill": skill,
                "why": (
                    f"Missing in {row.get('missing_in_jobs')} observed job(s) "
                    f"({row.get('share_pct')}% of sample)"
                ),
                "steps": [
                    f"Study fundamentals of {skill}",
                    f"Build a small project demonstrating {skill}",
                    "Update resume/LinkedIn draft (suggestions only — you paste)",
                ],
                "status": "proposed",
                "can_write_linkedin": False,
            }
        )
    return plans


def interview_intelligence(outcomes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """CI.4.2 — aggregate interview / application outcomes."""
    by_status: dict[str, int] = {}
    lessons: list[str] = []
    n = 0
    for row in outcomes:
        if not isinstance(row, dict):
            continue
        n += 1
        st = str(row.get("operator_status") or row.get("outcome") or "unknown")
        by_status[st] = by_status.get(st, 0) + 1
        if row.get("why") or row.get("lesson"):
            lessons.append(str(row.get("why") or row.get("lesson")))
    return {
        "schema": "career.interview_intelligence.1",
        "count": n,
        "by_status": by_status,
        "lessons": lessons[:20],
        "as_of": time.time(),
    }


def gated_apply(
    posting: dict[str, Any],
    *,
    enabled: bool = False,
    approved: bool = False,
    channel: str = "non_linkedin_form",
) -> dict[str, Any]:
    """CI.5 — apply only when explicitly enabled + approved; never LinkedIn Easy Apply."""
    source = str(posting.get("source") or "").lower()
    url = str(posting.get("url") or "").lower()
    if "linkedin" in source or "linkedin.com" in url:
        raise CapabilityGap(
            "linkedin_apply_forbidden",
            detail="LinkedIn Easy Apply is out of scope (OI-D4 / L-P14) — apply yourself in the browser",
        )
    if not enabled:
        raise CapabilityGap(
            "career_apply_disabled",
            detail="Gated apply is off — enable only under OI-D4 + per-action approval",
        )
    if not approved:
        return {
            "ok": False,
            "status": "needs_approval",
            "posting_id": posting.get("id"),
            "channel": channel,
            "can_apply": False,
            "note": "Human approval required before any non-LinkedIn form submit",
        }
    # Still do not actually submit forms in this build — return an intent receipt.
    return {
        "ok": True,
        "status": "intent_recorded",
        "posting_id": posting.get("id"),
        "channel": channel,
        "submitted": False,
        "can_apply": False,
        "note": "Approval recorded; live form submit remains disabled until a dedicated adapter ships",
    }


def learning_plans_from_postings(
    postings: list[dict[str, Any]],
    personal_skills: Iterable[str],
) -> dict[str, Any]:
    gaps = skill_gaps(postings, personal_skills)
    return {"gaps": gaps, "plans": propose_learning_plans(gaps)}
