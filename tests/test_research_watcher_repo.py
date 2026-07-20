"""Live-DB smoke for the Research Watcher decision path (Phase D · §D.7).

Exercises a real ``DecisionEngine`` + ``DecisionRepository`` with ``ResearchDecisionRule``
against PostgreSQL (skipped if unreachable): one decide journals a P9 ``read_next`` record
with evidence refs. No migration beyond 0039.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.decision.contracts import DecisionRequest
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.repositories.decision_repo import DecisionRepository
from atlas.research.decision_rule import ResearchDecisionRule


@pytest.fixture(scope="module")
def engine():
    db = DatabaseManager()
    try:
        if not db.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    reg = DecisionRuleRegistry()
    reg.register(ResearchDecisionRule())
    eng = DecisionEngine(DecisionRepository(db), rules=reg)
    yield eng
    db.close()


def test_research_read_next_is_journaled(engine: DecisionEngine):
    mission_id = uuid.uuid4()
    decision = engine.decide(
        DecisionRequest(
            mission_id=str(mission_id),
            mission_type="research",
            config_version=1,
            context={
                "objective": "soiling loss rates",
                "candidates": [
                    {
                        "id": "src-1",
                        "title": "IEEE Measurement of Soiling",
                        "url": "https://ieeexplore.ieee.org/document/1",
                        "evidence_level": 3,
                        "kind": "scholar",
                        "why": "Could fill the peer-reviewed gap.",
                    }
                ],
            },
        )
    )
    assert decision.id is not None
    assert decision.action_kind == "recommend"
    assert decision.action["payload"]["kind"] == "read_next"
    assert decision.decision_rule == "research"
    assert decision.why

    row = engine.get_decision(decision.id)
    assert row is not None
    assert row["mission_type"] == "research"
    assert row["action"]["payload"]["source"]["id"] == "src-1"
