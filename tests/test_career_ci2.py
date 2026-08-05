"""CI.2–CI.5 Career Intelligence — CKG, research, boards, gated apply, one-step wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.career.boards import CareerQuery, discover_all, default_registry
from atlas.career.ckg import (
    career_timeline,
    company_id_for,
    dedupe_jobs,
    normalize_job,
    opportunity_score,
    skill_demand,
    skill_gaps,
)
from atlas.career.decision_rule import JobDecisionRule
from atlas.career.research import gated_apply, propose_learning_plans, research_pack_for_company
from atlas.career.wiring import ensure_career_observer_with_export
from atlas.configuration.schemas import default_registry as schema_registry
from atlas.decision.contracts import DecisionRequest
from atlas.decision.rules import CapabilityGap
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.missions.templates.resources import resources_for
from atlas.workers.base import TickContext
from atlas.workers.career_research import CareerResearchWorker


def test_company_id_shared_slug():
    assert company_id_for("Peak Energy") == "company:peak-energy"
    assert company_id_for("X", symbol="RELIANCE.NS") == "company:RELIANCE.NS"


def test_dedupe_and_normalize_jobs():
    posts = [
        {"id": "1", "title": "Engineer", "company": "Acme", "description": "short"},
        {
            "id": "1",
            "title": "Engineer",
            "company": "Acme",
            "description": "much longer description about systems",
            "skills": ["Python", "MATLAB"],
        },
        {"id": "2", "title": "Other", "company": "Beta"},
    ]
    jobs = dedupe_jobs(posts)
    assert len(jobs) == 2
    acme = next(j for j in jobs if j["id"] == "1")
    assert "longer" in acme["description"]
    assert acme["company_id"] == company_id_for("Acme")
    assert normalize_job(posts[0])["schema"] == "career.job.1"


def test_skill_demand_and_gaps():
    posts = [
        {"id": "a", "title": "Python Engineer", "skills": ["Python", "Docker"]},
        {"id": "b", "title": "Python Lead", "skills": ["Python", "K8s"]},
        {"id": "c", "title": "Controls", "skills": ["MATLAB"]},
    ]
    demand = skill_demand(posts)
    assert demand["posting_count"] == 3
    assert demand["skills"][0]["skill"] == "Python"
    gaps = skill_gaps(posts, ["Python"])
    assert any(g["skill"] == "Docker" for g in gaps["gaps"])


def test_opportunity_score_explainable():
    posting = {
        "id": "1",
        "title": "Senior Research Engineer",
        "company": "Siemens",
        "skills": ["Python", "Power Systems"],
        "location": "Remote",
        "salary": 150000,
    }
    out = opportunity_score(
        posting,
        personal_skills=["Python"],
        watchlist_companies=["Siemens"],
        research={"stability_score": 0.8, "network_score": 0.6},
    )
    assert out["schema"] == "career.opportunity_score.1"
    assert 0 < out["score"] <= 1.0
    assert "fit" in out["components"]
    assert out["why"]


def test_decision_rule_uses_opportunity_score():
    rule = JobDecisionRule()
    opts = rule.score(
        DecisionRequest(
            mission_id="t",
            mission_type="job_hunting",
            context={
                "postings": [
                    {
                        "id": "j1",
                        "title": "Python Engineer",
                        "company": "Acme",
                        "skills": ["Python"],
                    }
                ],
                "personal_skills": ["Python"],
                "use_opportunity_score": True,
            },
        ),
        context=type("C", (), {"has": lambda self, n: False})(),
    )
    match = next(o for o in opts if (o.payload or {}).get("kind") == "recommend_match")
    assert (match.payload or {})["posting"].get("opportunity")


def test_career_research_template_batch():
    names = {t["name"] for t in BUILTIN_TEMPLATES}
    assert "career_research" in names
    assert resources_for("career_research").service_class == "BATCH"
    schema_registry().validate("career_research", {})


def test_research_pack_and_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ATLAS_CAREER_DIR", str(tmp_path / "career"))
    pack = research_pack_for_company("Acme Corp", seed_facts=["Acme is a stable employer."])
    assert pack["company_id"] == company_id_for("Acme Corp")
    assert pack["research_sufficiency"] in {"thin", "partial", "adequate"}

    class _C:
        def __init__(self):
            self.emitted = []

        def emit(self, p):
            self.emitted.append(p)
            return p

        def consume_pending(self, limit=20):
            return len(self.emitted)

    c = _C()
    w = CareerResearchWorker(candidates=c)
    res = w.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"company_names": ["Acme Corp"], "from_watchlist": False},
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "research only" in (res.note or "")
    assert c.emitted
    assert all(p["domain"] == "career" for p in c.emitted)


def test_boards_fixture_and_blocked():
    out = discover_all({"sources": ["fixture"], "limit": 5})
    assert out["ok"] is True
    assert out["can_apply"] is False
    assert out["postings"] or out["gaps"] == []
    blocked = discover_all({"sources": ["indeed"], "limit": 5})
    assert blocked["gaps"]
    assert blocked["gaps"][0]["capability"].startswith("indeed")


def test_gated_apply_blocks_linkedin():
    with pytest.raises(CapabilityGap):
        gated_apply(
            {"id": "1", "url": "https://www.linkedin.com/jobs/view/1", "source": "linkedin"},
            enabled=True,
            approved=True,
        )
    need = gated_apply({"id": "2", "url": "https://jobs.example.com/2"}, enabled=True, approved=False)
    assert need["status"] == "needs_approval"


def test_learning_plans_from_gaps():
    plans = propose_learning_plans(
        {"gaps": [{"skill": "Kubernetes", "missing_in_jobs": 3, "share_pct": 50}]}
    )
    assert plans[0]["skill"] == "Kubernetes"
    assert plans[0]["can_write_linkedin"] is False


def test_timeline_shape():
    tl = career_timeline(
        positions=[{"company": "Peak", "title": "Specialist", "started_on": "2026"}],
        goals=[{"label": "Principal track"}],
    )
    assert tl["count"] >= 2


def test_one_step_wiring_without_services():
    out = ensure_career_observer_with_export(path="/tmp/export.zip")
    assert out["ok"] is False
    assert "unavailable" in (out.get("reason") or "")
