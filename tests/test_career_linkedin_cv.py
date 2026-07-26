"""CV extract + LinkedIn coach + best-jobs ranking (career slice)."""

from __future__ import annotations

from atlas.career.jobs_panel import best_jobs_for_profile
from atlas.personal.cv_extract import extract_cv_facts
from atlas.personal.linkedin_coach import linkedin_suggestions
from atlas.personal.service import PersonalService


SAMPLE_CV = """
Jagadeshwar M
jag@example.com
https://www.linkedin.com/in/jagadeshwar-m

Professional Summary
Backend engineer building reliable Python systems.

Experience
Senior Software Engineer at Acme Corp - 2020-2024
Software Engineer at Beta Labs - 2017-2020

Education
B.Tech Computer Science, Example University, 2017

Skills
Python, FastAPI, PostgreSQL, Kafka, Docker
"""


def test_extract_cv_facts_core_fields():
    facts = extract_cv_facts(SAMPLE_CV, source_path="/tmp/cv.txt")
    cats = {f["category"] for f in facts}
    assert "identity" in cats
    assert "professional" in cats
    assert "skill" in cats
    assert "timeline" in cats
    names = [f for f in facts if f["key"] == "full_name"]
    assert names and "Jagadeshwar" in names[0]["statement"]
    roles = [f for f in facts if f["category"] == "professional"]
    assert any("Acme" in f["statement"] for f in roles)
    skills = [f["value"]["skill"] for f in facts if f["category"] == "skill"]
    assert "Python" in skills
    assert "FastAPI" in skills


def test_linkedin_suggestions_never_write():
    profile = {
        "identity": [
            {"key": "full_name", "statement": "Name: Jag.", "value": {"name": "Jag"}, "state": "inferred"},
        ],
        "skills": [
            {"key": "python", "statement": "Skilled in Python", "value": {"skill": "Python"}, "state": "verified"},
            {"key": "fastapi", "statement": "Skilled in FastAPI", "value": {"skill": "FastAPI"}, "state": "inferred"},
        ],
        "professional": [],
        "timeline": [],
    }
    out = linkedin_suggestions(profile)
    assert out["can_write_linkedin"] is False
    assert out["policy"] == "suggestions_only"
    assert any(s["area"] == "experience" for s in out["suggestions"])
    assert out["draft_about"]


def test_personal_learn_from_cv_text_upserts():
    class _Repo:
        def __init__(self):
            self.rows = {}

        def get_by_natural(self, category, key, subject=""):
            return self.rows.get((category, key, subject))

        def upsert(self, category, key, **kwargs):
            row = {"id": f"{category}:{key}", "category": category, "key": key, **kwargs}
            prior = self.rows.get((category, key, kwargs.get("subject", "")))
            self.rows[(category, key, kwargs.get("subject", ""))] = row
            return row

        def record_event(self, *_a, **_k):
            return None

    svc = PersonalService(_Repo())
    out = svc.learn_from_cv_text(SAMPLE_CV, source_path="/tmp/cv.txt")
    assert out["ok"] is True
    assert out["facts"] >= 5
    assert out["by_category"].get("identity", 0) >= 1


def test_best_jobs_ranks_against_skills():
    class _Personal:
        def list_facts(self, category=None, limit=500):
            return [
                {"category": "skill", "key": "python", "state": "verified",
                 "value": {"skill": "Python"}},
                {"category": "skill", "key": "fastapi", "state": "inferred",
                 "value": {"skill": "FastAPI"}},
            ]

    postings = [
        {
            "id": "j1",
            "title": "Senior Python Engineer",
            "company": "GoodCo",
            "location": "Remote",
            "skills": ["Python", "FastAPI"],
            "url": "https://example.com/j1",
        },
        {
            "id": "j2",
            "title": "Cobol Maintainer",
            "company": "Legacy Inc",
            "location": "Onsite",
            "skills": ["Cobol"],
            "url": "https://example.com/j2",
        },
    ]
    out = best_jobs_for_profile(
        personal=_Personal(),
        extra_postings=postings,
        limit=5,
    )
    assert out["can_apply"] is False
    assert out["jobs"]
    assert out["jobs"][0]["id"] == "j1"
    assert out["jobs"][0]["score"] >= out["jobs"][-1]["score"]
