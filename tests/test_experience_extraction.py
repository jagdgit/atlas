"""Hermetic tests: owner-experience extraction + consolidation (C.6c)."""

from __future__ import annotations

from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.learning.experience_extraction import (
    ExperienceWriter,
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
