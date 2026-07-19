"""Tests for PersonalService — inference + operator governance (C.7b)."""

from __future__ import annotations

import uuid

import pytest

from atlas.personal.service import PersonalService
from atlas.repositories.personal_repo import PersonalRepository


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


class _FakeExperiences:
    def __init__(self, rows):
        self._rows = rows

    def list_active(self, *, limit=1000):
        return self._rows


class _FakeIntelligence:
    def profile(self):
        return {
            "repositories": 3,
            "languages": {"python": 20, "html": 3},
            "frameworks": {"FastAPI": 2},
            "summary": "You work mainly in python.",
        }

    def list_repositories(self, *, limit=500):
        return [
            {"id": "r1", "repo_uid": "u1", "name": f"proj-{uuid.uuid4().hex[:6]}",
             "languages": {"python": 10}, "frameworks": ["FastAPI"], "created_at": "2024-01-01"},
        ]


def _exp(skill, context, *, maturity="verified", corr=2, sources=None):
    return {
        "id": str(uuid.uuid4()),
        "canonical_id": f"XP-{uuid.uuid4().hex[:8]}",
        "value": {"kind": "experience", "skill": skill, "context": context},
        "maturity": maturity,
        "corroboration_count": corr,
        "supporting": [{"source_id": s} for s in (sources or ["repoA", "repoB"])],
    }


def _svc(db, *, experiences=None, intelligence=None):
    return PersonalService(
        PersonalRepository(db), experiences=experiences, intelligence=intelligence
    )


def test_infer_skills_creates_inferred_facts_with_provenance(db):
    skill = f"celery-{uuid.uuid4().hex[:8]}"
    svc = _svc(db, experiences=_FakeExperiences([_exp(skill, "python", maturity="established", corr=3)]))
    result = svc.infer()
    assert result["skills"] >= 1

    fact = svc._repo.get_by_natural("skill", skill, "python")  # type: ignore[attr-defined]
    assert fact is not None
    assert fact["state"] == "inferred"
    assert fact["confidence"] == "HIGH"  # established → HIGH
    assert fact["source"] == "experience"
    assert fact["provenance"]["sources"] == ["repoA", "repoB"]
    # An inference event was journaled.
    assert any(e["action"] == "inferred" for e in svc.list_events(fact_id=fact["id"]))


def test_confirm_promotes_to_verified_and_journals(db):
    skill = f"redis-{uuid.uuid4().hex[:8]}"
    svc = _svc(db, experiences=_FakeExperiences([_exp(skill, "python")]))
    svc.infer()
    fact = svc._repo.get_by_natural("skill", skill, "python")  # type: ignore[attr-defined]

    confirmed = svc.confirm(fact["id"], actor="jagd")
    assert confirmed["state"] == "verified"
    events = svc.list_events(fact_id=fact["id"])
    assert events[0]["action"] == "confirmed"
    assert events[0]["actor"] == "jagd"


def test_reinference_never_downgrades_operator_decisions(db):
    skill = f"docker-{uuid.uuid4().hex[:8]}"
    exp = _exp(skill, "python", maturity="candidate", corr=1)
    fake = _FakeExperiences([exp])
    svc = _svc(db, experiences=fake)
    svc.infer()
    fact = svc._repo.get_by_natural("skill", skill, "python")  # type: ignore[attr-defined]
    svc.confirm(fact["id"])

    # A later inference pass (now with more corroboration) refreshes confidence but keeps verified.
    exp["maturity"] = "established"
    exp["corroboration_count"] = 5
    svc.infer()
    again = svc._repo.get(fact["id"])  # type: ignore[attr-defined]
    assert again["state"] == "verified"


def test_correct_edits_and_verifies(db):
    skill = f"kafka-{uuid.uuid4().hex[:8]}"
    svc = _svc(db, experiences=_FakeExperiences([_exp(skill, "python")]))
    svc.infer()
    fact = svc._repo.get_by_natural("skill", skill, "python")  # type: ignore[attr-defined]

    corrected = svc.correct(fact["id"], statement="Expert in Kafka", value={"level": "expert"})
    assert corrected["state"] == "verified"
    assert corrected["statement"] == "Expert in Kafka"
    assert corrected["value"] == {"level": "expert"}


def test_reject_hides_from_profile(db):
    skill = f"php-{uuid.uuid4().hex[:8]}"
    svc = _svc(db, experiences=_FakeExperiences([_exp(skill, "web")]))
    svc.infer()
    fact = svc._repo.get_by_natural("skill", skill, "web")  # type: ignore[attr-defined]
    svc.reject(fact["id"])

    keys = {f["key"] for f in svc.skills()}
    assert skill not in keys  # rejected facts are never presented
    verified_only = {f["key"] for f in svc.skills(include_inferred=False)}
    assert skill not in verified_only


def test_profile_assembles_categories(db):
    skill = f"rust-{uuid.uuid4().hex[:8]}"
    svc = _svc(
        db,
        experiences=_FakeExperiences([_exp(skill, "systems")]),
        intelligence=_FakeIntelligence(),
    )
    svc.infer()
    profile = svc.profile()
    assert any(f["value"].get("skill") == skill for f in profile["skills"])
    assert profile["identity"]  # engineering_profile identity fact
    assert profile["timeline"]  # at least one project


def test_e2e_experience_to_profile_to_draft(db):
    """Acceptance: real consolidated experiences → inferred skill → confirm → resume draft."""
    from atlas.knowledge.consolidation import KnowledgeLifecycleService
    from atlas.repositories.experience_store import ExperienceStore

    store = ExperienceStore(db)
    life = KnowledgeLifecycleService(store)
    skill = f"Airflow-{uuid.uuid4().hex[:8]}"

    def obs(source):
        return {
            "statement": f"Uses {skill}",
            "domain": "experience", "claim_type": "experience",
            "value": {"kind": "experience", "skill": skill, "context": "python"},
            "confidence": "LOW", "confidence_score": 0.4, "status": "active",
            "supporting": [{"source_id": source, "evidence_level": 2}],
            "provenance": {"source": "repo", "repo_uid": source},
        }

    # Two projects corroborate the same skill → one consolidated experience.
    life.consolidate(obs(f"repoA-{uuid.uuid4().hex[:6]}"))
    life.consolidate(obs(f"repoB-{uuid.uuid4().hex[:6]}"))

    svc = PersonalService(PersonalRepository(db), experiences=store)
    svc.infer()

    fact = svc._repo.get_by_natural("skill", skill.lower(), "python")  # type: ignore[attr-defined]
    assert fact is not None
    assert fact["state"] == "inferred"
    assert fact["provenance"]["maturity"] == "verified"  # 2 sources → verified maturity

    # Inferred facts do NOT appear on a resume until confirmed (retrieval, not action).
    resume_before = svc.draft("resume")
    assert skill not in resume_before["markdown"]

    svc.confirm(fact["id"])
    resume_after = svc.draft("resume")
    assert skill in resume_after["markdown"]


def test_revert_confirm_restores_inferred(db):
    skill = f"scala-{uuid.uuid4().hex[:8]}"
    svc = _svc(db, experiences=_FakeExperiences([_exp(skill, "jvm")]))
    svc.infer()
    fact = svc._repo.get_by_natural("skill", skill, "jvm")  # type: ignore[attr-defined]
    confirmed = svc.confirm(fact["id"])
    ev = svc.list_events(fact_id=fact["id"])[0]
    assert ev["action"] == "confirmed"

    reverted = svc.revert(ev["id"])
    assert reverted["state"] == "inferred"
