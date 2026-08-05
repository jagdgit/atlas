"""Career Knowledge Graph helpers (CI.2) — jobs, dedup, market, scores, gaps, companies."""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from typing import Any, Iterable

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def company_id_for(name: str, *, symbol: str | None = None) -> str:
    """Stable shared Company id (L-COMPANY) — slug; prefer exchange symbol when known."""
    sym = (symbol or "").strip().upper()
    if sym:
        return f"company:{sym}"
    slug = _NON_ALNUM.sub("-", (name or "").strip().lower()).strip("-")
    return f"company:{slug or 'unknown'}"


def resolve_company(
    name: str,
    *,
    company_data: Any | None = None,
    known: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve employer name → shared company_id (+ optional Market profile hint)."""
    raw = (name or "").strip()
    if not raw:
        return {"ok": False, "company_id": company_id_for(""), "name": "", "reason": "empty"}
    if known and raw in known:
        return {"ok": True, "company_id": known[raw], "name": raw, "source": "known"}
    if known:
        key = raw.lower()
        for k, cid in known.items():
            if k.lower() == key:
                return {"ok": True, "company_id": cid, "name": raw, "source": "known"}

    symbol = None
    profile = None
    if company_data is not None:
        try:
            # Prefer explicit profiles already loaded in CompanyDataService.
            profiles = getattr(company_data, "list_profiles", None)
            rows = profiles() if callable(profiles) else []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                pname = str(row.get("name") or "").strip().lower()
                psym = str(row.get("symbol") or "").strip()
                if pname and pname == raw.lower():
                    symbol = psym or None
                    profile = row
                    break
                if psym and psym.lower() == raw.lower():
                    symbol = psym
                    profile = row
                    break
        except Exception:  # noqa: BLE001
            pass

    cid = company_id_for(raw, symbol=symbol)
    return {
        "ok": True,
        "company_id": cid,
        "name": raw,
        "symbol": symbol,
        "profile": profile,
        "source": "resolved",
    }


def job_identity_key(posting: dict[str, Any]) -> str:
    """Stable job identity for dedup / supersession (CI.2.2)."""
    pid = str(posting.get("id") or "").strip()
    url = str(posting.get("url") or "").strip().lower()
    if pid:
        return f"id:{pid}"
    if url:
        return f"url:{url}"
    title = str(posting.get("title") or "").strip().lower()
    company = str(posting.get("company") or "").strip().lower()
    loc = str(posting.get("location") or "").strip().lower()
    digest = hashlib.sha256(f"{title}|{company}|{loc}".encode("utf-8")).hexdigest()[:16]
    return f"hash:{digest}"


def description_hash(posting: dict[str, Any]) -> str:
    text = str(posting.get("description") or posting.get("title") or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def normalize_job(posting: dict[str, Any], *, company_data: Any | None = None) -> dict[str, Any]:
    """Normalize a posting into ``career.job.1`` shape."""
    company = str(posting.get("company") or posting.get("employer") or "").strip()
    resolved = resolve_company(company, company_data=company_data)
    title = str(posting.get("title") or posting.get("role") or "").strip()
    skills = _as_skill_list(posting.get("skills"))
    now = time.time()
    status = str(posting.get("status") or "open").strip() or "open"
    return {
        "schema": "career.job.1",
        "identity_key": job_identity_key(posting),
        "id": str(posting.get("id") or job_identity_key(posting)),
        "company": company,
        "company_id": resolved.get("company_id"),
        "role": title,
        "title": title,
        "salary": posting.get("salary") or posting.get("salary_max"),
        "skills": skills,
        "location": str(posting.get("location") or "").strip(),
        "remote": bool(posting.get("remote")) if posting.get("remote") is not None else None,
        "url": str(posting.get("url") or "").strip(),
        "source": str(posting.get("source") or "unknown"),
        "description": str(posting.get("description") or "")[:4000],
        "description_hash": description_hash(posting),
        "status": status,
        "first_seen": posting.get("first_seen") or now,
        "last_seen": posting.get("last_seen") or now,
        "operator_status": posting.get("operator_status") or "none",
        "why": posting.get("why"),
    }


def dedupe_jobs(postings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep newest/richest posting per identity_key; mark superseded siblings."""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in postings:
        if not isinstance(raw, dict):
            continue
        job = normalize_job(raw) if raw.get("schema") != "career.job.1" else dict(raw)
        key = str(job.get("identity_key") or job_identity_key(job))
        job["identity_key"] = key
        prev = best.get(key)
        if prev is None:
            best[key] = job
            order.append(key)
            continue
        # Prefer richer description / later last_seen
        prev_score = len(str(prev.get("description") or "")) + float(prev.get("last_seen") or 0)
        cur_score = len(str(job.get("description") or "")) + float(job.get("last_seen") or 0)
        if cur_score >= prev_score:
            job["supersedes"] = prev.get("id")
            prev = dict(prev)
            prev["status"] = "superseded"
            prev["superseded_by"] = job.get("id")
            job["_superseded_prior"] = prev
            best[key] = job
        else:
            job = dict(job)
            job["status"] = "superseded"
            job["superseded_by"] = prev.get("id")
    return [best[k] for k in order if best[k].get("status") != "superseded" or k in best]


def skill_demand(
    postings: Iterable[dict[str, Any]],
    *,
    window_label: str = "observed",
) -> dict[str, Any]:
    """Career Market aggregate — skill demand % over observed postings (CI.2.3)."""
    counts: Counter[str] = Counter()
    total = 0
    for p in postings:
        if not isinstance(p, dict):
            continue
        total += 1
        skills = _as_skill_list(p.get("skills"))
        if not skills:
            # Fall back to tokens in title+description for thin feeds
            blob = f"{p.get('title') or ''} {p.get('description') or ''}"
            skills = sorted({t for t in _WORD_RE.findall(blob.lower()) if len(t) > 2})[:12]
        for s in skills:
            counts[s] += 1
    ranked = []
    for skill, n in counts.most_common(40):
        pct = round(100.0 * n / total, 1) if total else 0.0
        ranked.append({"skill": skill, "count": n, "demand_pct": pct})
    return {
        "schema": "career.market_signal",
        "kind": "skill_demand",
        "window": window_label,
        "posting_count": total,
        "skills": ranked,
        "as_of": time.time(),
    }


def mom_deltas(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """MoM demand deltas between two skill_demand snapshots."""
    if not previous:
        return []
    prev_map = {
        str(r.get("skill")): float(r.get("demand_pct") or 0)
        for r in (previous.get("skills") or [])
        if isinstance(r, dict) and r.get("skill")
    }
    out = []
    for row in current.get("skills") or []:
        if not isinstance(row, dict) or not row.get("skill"):
            continue
        skill = str(row["skill"])
        cur = float(row.get("demand_pct") or 0)
        prev = prev_map.get(skill)
        if prev is None:
            continue
        delta = round(cur - prev, 1)
        if abs(delta) < 0.1:
            continue
        out.append({"skill": skill, "demand_pct": cur, "delta_pct": delta, "previous_pct": prev})
    out.sort(key=lambda r: abs(float(r["delta_pct"])), reverse=True)
    return out


def opportunity_score(
    posting: dict[str, Any],
    *,
    personal_skills: Iterable[str] | None = None,
    preferred_locations: Iterable[str] | None = None,
    watchlist_companies: Iterable[str] | None = None,
    research: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Explainable Opportunity Score v1 (CI.2.4)."""
    w = {
        "fit": 0.28,
        "salary_growth": 0.10,
        "learning": 0.12,
        "career_impact": 0.10,
        "location": 0.10,
        "stability": 0.12,
        "interest": 0.10,
        "network": 0.08,
    }
    if weights:
        w.update({k: float(v) for k, v in weights.items() if k in w})

    wanted = {_norm(s) for s in (personal_skills or []) if s}
    job_skills = {_norm(s) for s in _as_skill_list(posting.get("skills"))}
    if not job_skills:
        blob = f"{posting.get('title') or ''} {posting.get('description') or ''}"
        job_skills = {_norm(t) for t in _WORD_RE.findall(blob) if len(t) > 2}
    overlap = wanted & job_skills
    fit = (len(overlap) / max(1, len(wanted))) if wanted else (0.4 if job_skills else 0.2)
    fit = min(1.0, fit)

    salary = _as_float(posting.get("salary"))
    salary_growth = 0.55 if salary and salary >= 100000 else (0.4 if salary else 0.35)

    gap = job_skills - wanted
    learning = min(1.0, 0.35 + 0.1 * min(5, len(gap)))

    title = str(posting.get("title") or posting.get("role") or "").lower()
    impact_hits = sum(1 for k in ("principal", "staff", "lead", "architect", "research", "r&d") if k in title)
    career_impact = min(1.0, 0.35 + 0.15 * impact_hits)

    locs = {_norm(x) for x in (preferred_locations or []) if x}
    ploc = _norm(str(posting.get("location") or ""))
    remote = posting.get("remote")
    if remote or "remote" in ploc:
        location = 0.85 if not locs or any("remote" in x for x in locs) else 0.55
    elif not locs:
        location = 0.5
    else:
        location = 0.9 if any(x in ploc for x in locs) else 0.25

    research = research or {}
    stability = float(research.get("stability_score") or 0.5)
    stability = max(0.0, min(1.0, stability))
    network = float(research.get("network_score") or 0.45)
    network = max(0.0, min(1.0, network))

    company = str(posting.get("company") or "").strip()
    watch = {_norm(c) for c in (watchlist_companies or []) if c}
    interest = 0.9 if _norm(company) in watch else float(
        {"interested": 0.85, "watching": 0.7, "applied": 0.95}.get(
            str(posting.get("operator_status") or ""), 0.35
        )
    )

    components = {
        "fit": round(fit, 3),
        "salary_growth": round(salary_growth, 3),
        "learning": round(learning, 3),
        "career_impact": round(career_impact, 3),
        "location": round(location, 3),
        "stability": round(stability, 3),
        "interest": round(interest, 3),
        "network": round(network, 3),
    }
    score = sum(components[k] * w[k] for k in components)
    why = [
        f"fit={components['fit']} (skills {sorted(overlap)[:5]})",
        f"learning_gaps={sorted(gap)[:5]}",
        f"stability={components['stability']}",
        f"interest={components['interest']}",
    ]
    return {
        "schema": "career.opportunity_score.1",
        "score": round(score, 4),
        "components": components,
        "weights": w,
        "why": why,
        "skill_overlap": sorted(overlap),
        "skill_gaps": sorted(gap),
        "company_id": posting.get("company_id") or resolve_company(company).get("company_id"),
    }


def skill_gaps(
    postings: Iterable[dict[str, Any]],
    personal_skills: Iterable[str],
    *,
    top_n: int = 15,
) -> dict[str, Any]:
    """Skills frequently required by observed jobs but missing from profile (CI.2.6)."""
    wanted = {_norm(s) for s in personal_skills if s}
    missing: Counter[str] = Counter()
    total = 0
    for p in postings:
        if not isinstance(p, dict):
            continue
        total += 1
        for s in _as_skill_list(p.get("skills")):
            if _norm(s) not in wanted:
                missing[s] += 1
    ranked = [
        {"skill": skill, "missing_in_jobs": n, "share_pct": round(100.0 * n / total, 1) if total else 0}
        for skill, n in missing.most_common(top_n)
    ]
    return {
        "schema": "career.skill_gaps.1",
        "posting_count": total,
        "personal_skill_count": len(wanted),
        "gaps": ranked,
        "as_of": time.time(),
    }


def career_timeline(
    *,
    positions: Iterable[dict[str, Any]] | None = None,
    personal_facts: Iterable[dict[str, Any]] | None = None,
    goals: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Career Timeline under Personal (CI.2.5 plan item CI.2.5 numbering = timeline CI.2.5 in plan table)."""
    events: list[dict[str, Any]] = []
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        events.append(
            {
                "kind": "role",
                "label": f"{pos.get('title') or ''} @ {pos.get('company') or ''}".strip(" @"),
                "company": pos.get("company"),
                "title": pos.get("title"),
                "started_on": pos.get("started_on") or pos.get("period_start"),
                "finished_on": pos.get("finished_on") or pos.get("period_end"),
            }
        )
    for fact in personal_facts or []:
        if not isinstance(fact, dict):
            continue
        value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
        key = str(fact.get("key") or "")
        if fact.get("kind") == "timeline" or key.startswith("timeline") or value.get("period_start"):
            events.append(
                {
                    "kind": "timeline_fact",
                    "label": str(value.get("label") or value.get("note") or key),
                    "started_on": value.get("period_start"),
                    "finished_on": value.get("period_end"),
                    "state": fact.get("state"),
                }
            )
    for g in goals or []:
        if not isinstance(g, dict):
            continue
        events.append(
            {
                "kind": "goal",
                "label": str(g.get("label") or g.get("title") or g.get("goal") or ""),
                "state": g.get("state") or "active",
            }
        )
    return {
        "schema": "career.timeline.1",
        "events": events,
        "count": len(events),
        "as_of": time.time(),
    }


def _as_skill_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,|;/]", raw)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(raw, (list, tuple, set)):
        out = []
        for x in raw:
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
        return out
    return []


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _as_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
