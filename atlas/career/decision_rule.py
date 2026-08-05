"""JobDecisionRule — ranked job matches for the Job Watcher (Phase D · §D.8, BB-D2).

Scores fixture postings against mission constraints + Personal skills into deterministic
``recommend_match`` / ``hold`` options. The Decision Engine then folds in **policy influence**
(e.g. ``prefer remote`` / ``avoid acme`` — DD5) and journals the P9 record.

Pure + deterministic (Q7): no LLM in the choice, no persistence. Recommend-only (P14/DD3):
every option is ``side_effecting = False`` — Atlas drafts/ranks, never applies.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from atlas.decision.contracts import DecisionRequest, ScoredOption
from atlas.decision.rules import CapabilityGap

if TYPE_CHECKING:
    from atlas.decision.context import IntelligenceContext

MISSION_TYPE_JOB_HUNTING = "job_hunting"

_HOLD_SCORE = 0.3
_BASE_MATCH_SCORE = 1.0
_SKILL_WEIGHT = 0.4
_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


class JobDecisionRule:
    """Deterministic ranking of job postings → recommend_match / hold."""

    mission_type = MISSION_TYPE_JOB_HUNTING
    VERSION = "1.0.0"

    def score(
        self, request: DecisionRequest, context: "IntelligenceContext"
    ) -> list[ScoredOption]:
        ctx = request.context or {}
        postings = list(ctx.get("postings") or [])

        hold = ScoredOption(
            key="hold",
            score=_HOLD_SCORE,
            text="hold — no job match this cycle",
            tags=("hold",),
            rationale="no posting worth recommending this cycle",
            payload={"kind": "hold"},
        )
        if not postings:
            return [hold]

        # Personal skills (P15: missing personal is an honest capability gap when the rule needs it).
        personal_skills = self._personal_skill_names(context, ctx)
        config_skills = {_norm(s) for s in (ctx.get("skills") or []) if s}
        wanted = personal_skills | config_skills

        locations = {_norm(s) for s in (ctx.get("locations") or []) if s}
        companies = {_norm(s) for s in (ctx.get("companies") or []) if s}
        min_salary = _as_float(ctx.get("min_salary"), default=0.0) or 0.0
        min_overlap = int(ctx.get("min_skill_overlap") or 0)

        options: list[ScoredOption] = [hold]
        research_by_company = ctx.get("research_by_company") or {}
        watchlist = [str(x) for x in (ctx.get("watchlist_companies") or []) if x]
        use_opp = bool(ctx.get("use_opportunity_score", True))
        for posting in postings:
            opt = self._score_posting(
                posting,
                wanted=wanted,
                locations=locations,
                companies=companies,
                min_salary=min_salary,
                min_overlap=min_overlap,
                use_opportunity_score=use_opp,
                research_by_company=research_by_company,
                watchlist_companies=watchlist,
                preferred_locations=list(ctx.get("locations") or []),
            )
            if opt is not None:
                options.append(opt)
        return options

    def _personal_skill_names(
        self, context: "IntelligenceContext", ctx: dict[str, Any]
    ) -> set[str]:
        # Worker may pre-inject skill names for hermetic tests / offline ticks.
        if "personal_skills" in ctx:
            return {_norm(s) for s in (ctx.get("personal_skills") or []) if s}
        if not context.has("personal"):
            # Matching still works from config skills alone — don't raise unless nothing else.
            return set()
        try:
            facts = context.skills(include_inferred=bool(ctx.get("include_inferred_skills", True)))
        except CapabilityGap:
            return set()
        from atlas.personal.skill_hygiene import clean_skill_name, is_noise_skill

        names: set[str] = set()
        for fact in facts or []:
            if not isinstance(fact, dict):
                continue
            if fact.get("state") == "rejected":
                continue
            value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
            raw = value.get("skill") or fact.get("key") or ""
            cleaned = clean_skill_name(str(raw))
            if cleaned:
                names.add(_norm(cleaned))
            statement = str(fact.get("statement") or "")
            # Only keep statement tokens that look like real skills (not noise hashes).
            for t in _WORD_RE.findall(statement):
                if len(t) >= 3 and not is_noise_skill(t):
                    names.add(_norm(t))
        return {n for n in names if n}

    def _score_posting(
        self,
        posting: dict[str, Any],
        *,
        wanted: set[str],
        locations: set[str],
        companies: set[str],
        min_salary: float,
        min_overlap: int,
        use_opportunity_score: bool = True,
        research_by_company: dict[str, Any] | None = None,
        watchlist_companies: list[str] | None = None,
        preferred_locations: list[str] | None = None,
    ) -> ScoredOption | None:
        pid = str(posting.get("id") or "").strip()
        title = str(posting.get("title") or "").strip()
        if not pid or not title:
            return None

        company = str(posting.get("company") or "")
        location = str(posting.get("location") or "")
        salary = _as_float(posting.get("salary"))
        posting_skills = {_norm(s) for s in (posting.get("skills") or []) if s}

        # Hard mission constraints (config) — withhold rather than recommend.
        if companies and _norm(company) not in companies:
            return None
        if locations and not self._location_matches(location, locations):
            return None
        if min_salary > 0 and (salary is None or salary < min_salary):
            return None

        overlap = posting_skills & wanted if wanted else set()
        # Also count title tokens that match wanted skills.
        title_hits = {_norm(t) for t in _WORD_RE.findall(title)} & wanted
        overlap |= title_hits
        if min_overlap > 0 and len(overlap) < min_overlap:
            return None

        opp: dict[str, Any] | None = None
        if use_opportunity_score:
            from atlas.career.ckg import opportunity_score, resolve_company

            research = None
            if research_by_company:
                research = research_by_company.get(company) or research_by_company.get(
                    _norm(company)
                )
                if research is None:
                    cid = resolve_company(company).get("company_id")
                    research = research_by_company.get(str(cid or ""))
            opp = opportunity_score(
                posting,
                personal_skills=wanted,
                preferred_locations=preferred_locations,
                watchlist_companies=watchlist_companies,
                research=research if isinstance(research, dict) else None,
            )
            # Map 0..1 opportunity into DecisionRule score space (~1.0–3.0).
            score = _BASE_MATCH_SCORE + float(opp.get("score") or 0) * 2.0
            rationale_parts = list(opp.get("why") or [])
        else:
            score = _BASE_MATCH_SCORE + _SKILL_WEIGHT * len(overlap)
            rationale_parts = []
            if overlap:
                rationale_parts.append(f"skill overlap: {', '.join(sorted(overlap)[:5])}")
            else:
                rationale_parts.append("matches mission constraints (no skill overlap required)")
        if company:
            rationale_parts.append(f"at {company}")
        if location:
            rationale_parts.append(f"in {location}")

        tags = ["match", "job"]
        for token in (
            _tokenize(company) | _tokenize(location) | posting_skills | _tokenize(title)
        ):
            if len(token) >= 3:
                tags.append(token)

        payload_posting = {
            "id": pid,
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "skills": list(posting.get("skills") or []),
            "url": posting.get("url"),
            "overlap": sorted(overlap),
        }
        if opp:
            payload_posting["opportunity"] = opp
            payload_posting["company_id"] = opp.get("company_id")

        return ScoredOption(
            key=f"recommend:{pid}",
            score=score,
            text=f"recommend: {title}" + (f" @ {company}" if company else ""),
            tags=tuple(dict.fromkeys(tags)),
            rationale="; ".join(rationale_parts),
            experience_refs=[],
            payload={
                "kind": "recommend_match",
                "posting": payload_posting,
            },
        )

    @staticmethod
    def _location_matches(location: str, allowed: set[str]) -> bool:
        loc = _norm(location)
        if not loc:
            return False
        if loc in allowed:
            return True
        # Substring match so "Berlin, DE" matches config "berlin".
        return any(a in loc or loc in a for a in allowed)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _as_float(value: Any, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
