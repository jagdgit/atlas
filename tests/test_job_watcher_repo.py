"""Live-DB smoke for the Job Watcher decision path (Phase D · §D.8).

Real DecisionEngine + DecisionRepository with JobDecisionRule (skipped if DB unreachable).
"""

from __future__ import annotations

import uuid

import pytest

from atlas.career.decision_rule import JobDecisionRule
from atlas.database.connection import DatabaseManager
from atlas.decision.contracts import DecisionRequest
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.repositories.decision_repo import DecisionRepository


@pytest.fixture(scope="module")
def engine():
    db = DatabaseManager()
    try:
        if not db.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    reg = DecisionRuleRegistry()
    reg.register(JobDecisionRule())
    eng = DecisionEngine(DecisionRepository(db), rules=reg)
    yield eng
    db.close()


def test_job_match_is_journaled(engine: DecisionEngine):
    mission_id = uuid.uuid4()
    decision = engine.decide(
        DecisionRequest(
            mission_id=str(mission_id),
            mission_type="job_hunting",
            config_version=1,
            context={
                "postings": [
                    {
                        "id": "live-1",
                        "title": "Python Platform Engineer",
                        "company": "AtlasLabs",
                        "location": "Remote",
                        "skills": ["python", "kubernetes"],
                        "salary": 140000,
                        "url": "https://example.com/live-1",
                    }
                ],
                "personal_skills": ["python", "kubernetes"],
                "locations": ["remote"],
                "min_salary": 100000,
            },
        )
    )
    assert decision.id is not None
    assert decision.action_kind == "recommend"
    assert decision.action["payload"]["kind"] == "recommend_match"
    assert decision.decision_rule == "job_hunting"
    assert decision.requires_approval is False  # recommend-only (P14/DD3)

    row = engine.get_decision(decision.id)
    assert row is not None
    assert row["action"]["payload"]["posting"]["id"] == "live-1"
