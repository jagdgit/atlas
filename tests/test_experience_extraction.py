"""Hermetic tests: owner-experience extraction + consolidation (C.6c)."""

from __future__ import annotations

from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.learning.experience_extraction import (
    ExperienceWriter,
    build_conversation_experiences,
    build_repo_experiences,
)


def _repo(name: str, *, languages=None, frameworks=None, patterns=None) -> dict:
    return {
        "name": name,
        "languages": languages or {"Python": 100},
        "frameworks": frameworks or [],
        "patterns": patterns or [],
    }


def test_build_repo_experiences_emits_language_framework_pattern():
    exps = build_repo_experiences(
        _repo(
            "shop",
            languages={"Python": 900, "HTML": 100},
            frameworks=["Django", "Celery"],
            patterns=[{"name": "Repository", "description": "data access", "confidence": 0.8}],
        ),
        repo_uid="repo-1",
        mission_id="m1", job_id="j1", source="repo",
    )
    statements = {e["statement"] for e in exps}
    assert "Works with Python" in statements
    assert "Uses Django" in statements
    assert "Uses Celery" in statements
    assert "Applies the Repository pattern" in statements
    # All carry experience domain + provenance (P12).
    for e in exps:
        assert e["domain"] == "experience"
        assert e["value"]["kind"] == "experience"
        assert e["provenance"]["mission_id"] == "m1"
        assert e["provenance"]["repo_uid"] == "repo-1"
    # Framework context is the primary language.
    django = next(e for e in exps if e["statement"] == "Uses Django")
    assert django["value"]["context"] == "python"


def test_experiences_consolidate_across_projects():
    life = KnowledgeLifecycleService(InMemoryFindingStore())
    writer = ExperienceWriter(life._store, lifecycle=life)  # type: ignore[attr-defined]

    a = writer.write(build_repo_experiences(
        _repo("projA", frameworks=["Celery"]), repo_uid="repoA",
    ))
    assert a["created"] == 2  # "Works with Python" + "Uses Celery"

    # A DIFFERENT project that also uses Celery corroborates the SAME experience.
    b = writer.write(build_repo_experiences(
        _repo("projB", frameworks=["Celery"]), repo_uid="repoB",
    ))
    assert b["merged"] == 2  # both python + celery strengthen in place
    assert b["created"] == 0

    # One row per (skill, context) — Celery corroborated by two projects.
    store = life._store  # type: ignore[attr-defined]
    celery = [
        r for r in store.rows.values()
        if r.get("value", {}).get("skill") == "Celery" and r["status"] == "active"
    ]
    assert len(celery) == 1
    assert len(celery[0]["supporting"]) == 2
    assert celery[0]["maturity"] == "verified"


def test_same_repo_relearn_is_noop():
    life = KnowledgeLifecycleService(InMemoryFindingStore())
    writer = ExperienceWriter(life._store, lifecycle=life)  # type: ignore[attr-defined]

    payload = _repo("proj", frameworks=["Redis"])
    first = writer.write(build_repo_experiences(payload, repo_uid="repoX"))
    assert first["created"] == 2
    again = writer.write(build_repo_experiences(payload, repo_uid="repoX"))
    assert again["noop"] == 2
    assert again["created"] == 0 and again["merged"] == 0


def test_build_conversation_experiences_from_user_turns():
    artifact = {
        "asset_id": "a1",
        "sections": [
            {
                "role": "user",
                "text": "I spent 5 years on PostgreSQL and I use Celery in production.",
            },
            {
                "role": "assistant",
                "text": "You should also learn Redis.",  # not owner evidence
            },
            {"role": "user", "text": "I built services with FastAPI."},
        ],
    }
    exps = build_conversation_experiences(artifact, asset_id="a1", source="conversation")
    skills = {e["value"]["skill"] for e in exps}
    assert "postgresql" in skills
    assert "celery" in skills
    assert "fastapi" in skills
    assert "redis" not in skills  # assistant-only mention ignored
    pg = next(e for e in exps if e["value"]["skill"] == "postgresql")
    assert pg["value"].get("years") == 5
    assert pg["value"]["context"] == "stated"
    assert pg["provenance"]["source"] == "conversation"


def test_conversation_experiences_ignore_bare_mentions_without_claim():
    artifact = {
        "sections": [
            {"role": "user", "text": "What is PostgreSQL used for?"},
        ],
    }
    assert build_conversation_experiences(artifact, asset_id="a2") == []


def test_build_repo_experiences_includes_dependency_packages():
    exps = build_repo_experiences(
        {
            "name": "svc",
            "languages": {"Python": 10},
            "dependencies": {"pip": ["celery>=5.3", "pytest", "redis"]},
        },
        repo_uid="repo-deps",
    )
    stmts = {e["statement"] for e in exps}
    assert any("celery" in s and "dependencies" in s for s in stmts)
    assert any("redis" in s and "dependencies" in s for s in stmts)
    assert not any("pytest" in s.lower() and "dependencies" in s for s in stmts)
    celery = next(e for e in exps if e["value"]["skill"] == "celery")
    assert celery["value"]["context"] == "dependency"
