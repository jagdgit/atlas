"""Career morning brief (CI.1.5 / CI.4.5) — operator-facing summary, recommend-only / no apply."""

from __future__ import annotations

from typing import Any

from atlas.career import watchlist as wl
from atlas.career.ckg import skill_demand
from atlas.career.feeds import load_postings_json, sample_fixture_path
from atlas.career.research import interview_intelligence, learning_plans_from_postings


def build_morning_brief(
    *,
    personal: Any | None = None,
    assets: Any | None = None,
    postings_reader: Any | None = None,
    decision_engine: Any | None = None,
    include_jobs: bool = True,
    job_limit: int = 5,
) -> dict[str, Any]:
    """Assemble watchlist + market demand + optional ranked jobs + learning plans."""
    watching = wl.list_items()
    items = watching.get("items") or []
    by_status: dict[str, int] = {}
    for row in items:
        st = str(row.get("operator_status") or "watching")
        by_status[st] = by_status.get(st, 0) + 1

    companies = [
        str(x.get("label") or "")
        for x in items
        if str(x.get("kind") or "") == "company" and x.get("label")
    ][:12]

    jobs_block: dict[str, Any] | None = None
    if include_jobs and personal is not None:
        try:
            jobs_block = personal.best_jobs(
                assets=assets,
                postings_reader=postings_reader,
                decision_engine=decision_engine,
                limit=job_limit,
            )
        except Exception as exc:  # noqa: BLE001
            jobs_block = {"ok": False, "error": str(exc)[:200], "can_apply": False}

    market = None
    plans = None
    try:
        posts = load_postings_json(sample_fixture_path())
        market = skill_demand(posts, window_label="fixture")
        if personal is not None:
            from atlas.personal.skill_hygiene import skill_names_from_facts

            try:
                facts = personal.skills(include_inferred=True) or []
            except Exception:  # noqa: BLE001
                facts = []
            skills = skill_names_from_facts(facts, include_inferred=True)
            plans = learning_plans_from_postings(posts, skills)
    except Exception:  # noqa: BLE001
        pass

    interviews = interview_intelligence(
        [x for x in items if str(x.get("kind") or "") == "job"]
    )

    highlights: list[str] = []
    if by_status.get("interested"):
        highlights.append(f"{by_status['interested']} interested watchlist item(s)")
    if by_status.get("applied"):
        highlights.append(f"{by_status['applied']} marked applied")
    if by_status.get("watching"):
        highlights.append(f"{by_status['watching']} watching")
    if market and (market.get("skills") or []):
        top = market["skills"][0]
        highlights.append(
            f"Market demand leader: {top.get('skill')} ({top.get('demand_pct')}%)"
        )
    ranked = (jobs_block or {}).get("matches") or (jobs_block or {}).get("jobs") or []
    if isinstance(ranked, list) and ranked:
        top = ranked[0] if isinstance(ranked[0], dict) else {}
        title = top.get("title") or top.get("job_title") or "a match"
        company = top.get("company") or ""
        highlights.append(
            f"Top Advisor suggestion: {title}"
            + (f" at {company}" if company else "")
            + " (recommend-only)"
        )
    if plans and (plans.get("plans") or []):
        highlights.append(
            f"{len(plans['plans'])} learning plan(s) proposed from skill gaps"
        )
    if not highlights:
        highlights.append(
            "No career watchlist yet — ingest a LinkedIn export (one step wires Observer) "
            "or add companies via POST /v1/personal/career/watchlist"
        )

    return {
        "ok": True,
        "title": "Career morning brief",
        "highlights": highlights,
        "watchlist": {
            "count": len(items),
            "by_status": by_status,
            "companies_sample": companies,
            "updated_at": watching.get("updated_at"),
        },
        "market": market,
        "learning_plans": (plans or {}).get("plans") if plans else None,
        "skill_gaps": (plans or {}).get("gaps") if plans else None,
        "interview_intelligence": interviews,
        "jobs": jobs_block,
        "policy": {
            "can_write_linkedin": False,
            "can_apply": False,
            "observer_recommends": False,
            "advisor_recommends": True,
        },
        "note": (
            "Career Observer discovers; Career Research deepens; Career Advisor ranks. "
            "Atlas never applies or edits LinkedIn. One ingest wires Observer."
        ),
    }
