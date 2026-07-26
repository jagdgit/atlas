"""Best open jobs for the current Personal profile (recommend-only).

Ranks job_postings assets (and optional operator-supplied feed JSON) against Personal skills
using the same JobDecisionRule as Career Advisor. Never applies (P14).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atlas.career.decision_rule import JobDecisionRule, MISSION_TYPE_JOB_HUNTING
from atlas.decision.contracts import DecisionRequest

_LOG = logging.getLogger("atlas.career.jobs_panel")


def best_jobs_for_profile(
    *,
    personal: Any,
    assets: Any | None = None,
    postings_reader: Any | None = None,
    decision_engine: Any | None = None,
    extra_postings: list[dict[str, Any]] | None = None,
    feed_path: str | None = None,
    source_ids: list[str] | None = None,
    limit: int = 10,
    include_inferred_skills: bool = True,
) -> dict[str, Any]:
    """Return ranked open jobs for the owner profile (suggestions only)."""
    postings: list[dict[str, Any]] = list(extra_postings or [])
    load_notes: list[str] = []

    if feed_path:
        loaded, note = _load_feed_path(feed_path)
        postings.extend(loaded)
        if note:
            load_notes.append(note)

    if assets is not None and postings_reader is not None:
        ids = list(source_ids or [])
        if not ids:
            try:
                rows = assets.list_assets(kind="job_postings") or []
                ids = [str(r.get("id") or r.get("name") or "") for r in rows]
                ids = [i for i in ids if i]
            except Exception as exc:  # noqa: BLE001
                load_notes.append(f"list job_postings failed: {exc}")
        for sid in ids[:20]:
            try:
                art = postings_reader.read(sid)
                chunk = (art or {}).get("postings") or (art or {}).get("items") or []
                if isinstance(chunk, list):
                    postings.extend(chunk)
            except Exception as exc:  # noqa: BLE001
                load_notes.append(f"read {sid}: {exc}")

    personal_skills = _skill_names(personal, include_inferred=include_inferred_skills)
    if not postings:
        return {
            "policy": "recommend_only",
            "can_apply": False,
            "jobs": [],
            "personal_skills": sorted(personal_skills)[:40],
            "note": (
                "No job postings loaded yet. Add a `job_postings` asset, or share a LinkedIn "
                "jobs export JSON (`share /path/to/jobs.json`). Atlas never applies for you."
            ),
            "load_notes": load_notes,
            "version": "career.jobs.1",
        }

    # Dedup by id/url/title
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in postings:
        if not isinstance(p, dict):
            continue
        key = str(p.get("id") or p.get("url") or p.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    rule = JobDecisionRule()
    request = DecisionRequest(
        mission_id="career-panel",
        mission_type=MISSION_TYPE_JOB_HUNTING,
        context={
            "postings": deduped,
            "personal_skills": sorted(personal_skills),
            "include_inferred_skills": include_inferred_skills,
            "min_skill_overlap": 0,
        },
    )

    if decision_engine is not None:
        try:
            decision = decision_engine.decide(request)
            jobs = _jobs_from_decision(decision, limit=limit)
            return {
                "policy": "recommend_only",
                "can_apply": False,
                "jobs": jobs,
                "personal_skills": sorted(personal_skills)[:40],
                "decision_id": str(getattr(decision, "id", None) or ""),
                "note": (
                    "Ranked against your Personal skills. Atlas recommends only — "
                    "you apply on LinkedIn/company site yourself."
                ),
                "load_notes": load_notes,
                "postings_considered": len(deduped),
                "version": "career.jobs.1",
            }
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("decision engine path failed, falling back to rule: %s", exc)

    options = rule.score(request, context=_EmptyContext())
    ranked = [
        o
        for o in options
        if (o.payload or {}).get("kind") == "recommend_match"
    ]
    ranked.sort(key=lambda o: float(o.score or 0), reverse=True)
    jobs = []
    for o in ranked[: max(1, limit)]:
        posting = (o.payload or {}).get("posting") or {}
        jobs.append(
            {
                "title": posting.get("title"),
                "company": posting.get("company") or posting.get("organization"),
                "location": posting.get("location"),
                "url": posting.get("url"),
                "score": round(float(o.score or 0), 3),
                "why": o.rationale or o.text,
                "skills": posting.get("skills") or posting.get("required_skills") or [],
                "source": posting.get("source") or "feed",
                "id": posting.get("id"),
            }
        )
    return {
        "policy": "recommend_only",
        "can_apply": False,
        "jobs": jobs,
        "personal_skills": sorted(personal_skills)[:40],
        "note": (
            "Ranked against your Personal skills. Atlas recommends only — "
            "you apply on LinkedIn/company site yourself."
            if jobs
            else "No posting passed the match bar for your current skills — confirm CV skills or add feeds."
        ),
        "load_notes": load_notes,
        "postings_considered": len(deduped),
        "version": "career.jobs.1",
    }


class _EmptyContext:
    """Minimal stand-in when DecisionEngine context is unused by JobDecisionRule."""

    personal_skills: set[str] = set()


def _skill_names(personal: Any, *, include_inferred: bool) -> set[str]:
    names: set[str] = set()
    try:
        facts = personal.list_facts(category="skill", limit=500) or []
    except Exception:  # noqa: BLE001
        return names
    for f in facts:
        state = str(f.get("state") or "")
        if state == "rejected":
            continue
        if state == "inferred" and not include_inferred:
            continue
        val = f.get("value") or {}
        skill = str(val.get("skill") or f.get("key") or "").strip()
        if not skill or re_noise(skill):
            continue
        names.add(skill.lower())
    return names


def re_noise(skill: str) -> bool:
    import re

    s = skill.strip()
    if s.lower() in {"original", "skill"}:
        return True
    return bool(re.search(r"-[a-f0-9]{6,}$", s, re.I))


def _load_feed_path(path: str) -> tuple[list[dict[str, Any]], str | None]:
    p = Path(path).expanduser()
    if not p.is_file():
        return [], f"feed path not found: {p}"
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return [], f"invalid JSON feed: {exc}"
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], None
    if isinstance(data, dict):
        for key in ("postings", "jobs", "items", "results"):
            chunk = data.get(key)
            if isinstance(chunk, list):
                return [x for x in chunk if isinstance(x, dict)], None
        if data.get("title"):
            return [data], None
    return [], "JSON feed had no postings list"


def _jobs_from_decision(decision: Any, *, limit: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    # Prefer action payload top match + alternatives if present.
    action = getattr(decision, "action", None) or {}
    if isinstance(action, dict):
        payload = action.get("payload") or {}
        if payload.get("kind") == "recommend_match":
            posting = payload.get("posting") or {}
            jobs.append(
                {
                    "title": posting.get("title"),
                    "company": posting.get("company") or posting.get("organization"),
                    "location": posting.get("location"),
                    "url": posting.get("url"),
                    "score": float(getattr(decision, "confidence", 0) or 0) or None,
                    "why": getattr(decision, "why", None),
                    "skills": posting.get("skills") or [],
                    "source": posting.get("source") or "decision",
                    "id": posting.get("id"),
                }
            )
    alts = getattr(decision, "alternatives", None) or []
    for alt in alts:
        payload = (getattr(alt, "payload", None) or {}) if not isinstance(alt, dict) else (alt.get("payload") or {})
        if isinstance(alt, dict):
            payload = alt.get("payload") or {}
            score = alt.get("score")
            rationale = alt.get("rationale") or alt.get("text")
        else:
            score = getattr(alt, "score", None)
            rationale = getattr(alt, "rationale", None) or getattr(alt, "text", None)
        if (payload or {}).get("kind") != "recommend_match":
            continue
        posting = (payload or {}).get("posting") or {}
        jobs.append(
            {
                "title": posting.get("title"),
                "company": posting.get("company") or posting.get("organization"),
                "location": posting.get("location"),
                "url": posting.get("url"),
                "score": score,
                "why": rationale,
                "skills": posting.get("skills") or [],
                "source": posting.get("source") or "decision",
                "id": posting.get("id"),
            }
        )
    # Dedup
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for j in jobs:
        key = str(j.get("id") or j.get("url") or j.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
        if len(out) >= limit:
            break
    return out
