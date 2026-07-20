"""Live-DB smoke for Technology / Security advisory decisions (Phase D · §D.9)."""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.decision.contracts import DecisionRequest
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.repositories.decision_repo import DecisionRepository
from atlas.watch.decision_rule import MISSION_TYPE_SECURITY, AdvisoryDecisionRule


@pytest.fixture(scope="module")
def engine():
    db = DatabaseManager()
    try:
        if not db.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    reg = DecisionRuleRegistry()
    reg.register(AdvisoryDecisionRule(MISSION_TYPE_SECURITY))
    eng = DecisionEngine(DecisionRepository(db), rules=reg)
    yield eng
    db.close()


def test_security_advisory_is_journaled(engine: DecisionEngine):
    decision = engine.decide(
        DecisionRequest(
            mission_id=str(uuid.uuid4()),
            mission_type="security_monitoring",
            config_version=1,
            context={
                "mode": "security",
                "focus": ["openssl"],
                "severity_floor": "high",
                "advisories": [
                    {
                        "id": "CVE-LIVE-1",
                        "title": "Critical OpenSSL vulnerability",
                        "severity": "critical",
                        "kind": "cve",
                        "package": "openssl",
                        "packages": ["openssl"],
                        "cve": "CVE-LIVE-1",
                        "url": "https://nvd.nist.gov/live",
                    }
                ],
            },
        )
    )
    assert decision.id is not None
    assert decision.action_kind == "recommend"
    assert decision.action["payload"]["kind"] == "recommend_advisory"
    assert decision.requires_approval is False
    row = engine.get_decision(decision.id)
    assert row["action"]["payload"]["advisory"]["id"] == "CVE-LIVE-1"
