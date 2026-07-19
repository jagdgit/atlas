"""Hermetic tests: resume/LinkedIn drafting from the personal profile (C.7c)."""

from __future__ import annotations

from atlas.personal.draft import build_linkedin, build_resume


def _profile():
    return {
        "identity": [
            {"key": "engineering_profile", "state": "verified",
             "statement": "You work mainly in python, favouring FastAPI.",
             "value": {"repositories": 3}},
        ],
        "skills": [
            {"key": "fastapi", "state": "verified", "value": {"skill": "FastAPI", "context": "python"}},
            {"key": "celery", "state": "verified", "value": {"skill": "Celery", "context": "python"}},
        ],
        "timeline": [
            {"key": "shop", "state": "verified",
             "value": {"project": "shop", "languages": {"python": 900, "html": 100}}},
        ],
        "professional": [
            {"key": "paper-1", "state": "verified", "statement": "Published a paper on X."},
        ],
    }


def test_build_resume_renders_sections_from_profile():
    out = build_resume(_profile(), name="Jane Dev")
    md = out["markdown"]
    assert md.startswith("# Jane Dev")
    assert "## Summary" in md
    assert "## Skills" in md
    assert "FastAPI" in md and "Celery" in md
    assert "## Projects" in md and "shop" in md
    assert "## Professional" in md and "Published a paper" in md
    assert out["counts"]["skills"] == 2


def test_build_linkedin_is_short_and_skill_listed():
    out = build_linkedin(_profile())
    assert "FastAPI" in out["markdown"]
    assert out["summary"]
    assert out["counts"]["skills"] == 2


def test_empty_profile_still_drafts():
    out = build_resume({"identity": [], "skills": [], "timeline": [], "professional": []})
    assert "## Summary" in out["markdown"]
    assert out["counts"]["skills"] == 0


class _FakeResp:
    text = "Polished, factual, grounded summary."


class _FakeClient:
    def chat(self, messages):
        return _FakeResp()


class _FakeLLM:
    def for_role(self, role):
        return _FakeClient()


def test_llm_polish_is_used_when_available():
    out = build_resume(_profile(), llm=_FakeLLM())
    assert out["summary"] == "Polished, factual, grounded summary."


def test_llm_polish_failure_falls_back():
    class _Boom:
        def for_role(self, role):
            raise RuntimeError("no llm")

    out = build_resume(_profile(), llm=_Boom())
    assert "python" in out["summary"]  # deterministic fallback
