"""Live-DB tests: the shared Knowledge Consolidator over ``learning.experiences`` (C.6b)."""

from __future__ import annotations

import uuid

import pytest

from atlas.knowledge.consolidation import KnowledgeLifecycleService
from atlas.repositories.experience_store import ExperienceStore


@pytest.fixture(scope="module")
def db():
    from atlas.database.connection import DatabaseManager

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def _exp(skill: str, context: str, *, source: str, statement: str | None = None) -> dict:
    return {
        "statement": statement or f"Uses {skill}",
        "domain": "experience",
        "claim_type": "experience",
        "value": {"kind": "experience", "skill": skill, "context": context},
        "confidence": "LOW",
        "confidence_score": 0.4,
        "status": "active",
        "supporting": [{"source_id": source, "evidence_level": 2, "snippet": f"repo {source}"}],
        "provenance": {"source": "repo", "repo_uid": source},
    }


def test_experience_consolidates_across_projects(db):
    store = ExperienceStore(db)
    life = KnowledgeLifecycleService(store)
    skill = f"celery-{uuid.uuid4().hex[:8]}"

    first = life.consolidate(_exp(skill, "python", source=f"repoA-{uuid.uuid4().hex[:6]}"))
    assert first["_transition"] == "create"
    cid = first["canonical_id"]
    fid = first["id"]

    # Same skill+context, DIFFERENT project → evidence merges in place (one row, growing evidence).
    second = life.consolidate(_exp(skill, "python", source=f"repoB-{uuid.uuid4().hex[:6]}"))
    assert second["_transition"] == "merge_evidence"
    assert second["id"] == fid  # NOT a new row
    assert len(second["supporting"]) == 2

    # A third independent project → reaches "established" maturity + HIGH confidence.
    third = life.consolidate(_exp(skill, "python", source=f"repoC-{uuid.uuid4().hex[:6]}"))
    assert third["_transition"] == "merge_evidence"
    assert third["id"] == fid
    assert len(third["supporting"]) == 3
    assert third["maturity"] == "established"

    head = store.get(fid)
    assert head["corroboration_count"] == 3
    assert head["revision"] == 1  # evidence-merge never spawns a revision


def test_experience_same_project_repeated_is_noop(db):
    store = ExperienceStore(db)
    life = KnowledgeLifecycleService(store)
    skill = f"redis-{uuid.uuid4().hex[:8]}"
    src = f"repo-{uuid.uuid4().hex[:6]}"

    first = life.consolidate(_exp(skill, "python", source=src))
    assert first["_transition"] == "create"
    # Re-learning the SAME project must not inflate corroboration.
    again = life.consolidate(_exp(skill, "python", source=src))
    assert again["_transition"] == "noop"
    assert store.get(first["id"])["corroboration_count"] == 1


def test_experience_distinct_context_is_separate_row(db):
    store = ExperienceStore(db)
    life = KnowledgeLifecycleService(store)
    skill = f"docker-{uuid.uuid4().hex[:8]}"

    a = life.consolidate(_exp(skill, "python", source=f"r-{uuid.uuid4().hex[:6]}"))
    b = life.consolidate(_exp(skill, "rust", source=f"r-{uuid.uuid4().hex[:6]}"))
    assert a["_transition"] == "create"
    assert b["_transition"] == "create"
    assert a["id"] != b["id"]
    assert a["canonical_id"] != b["canonical_id"]
