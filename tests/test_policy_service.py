"""Tests for PolicyService (Phase C · §C.5, CC8).

Hermetic tests cover the signed-influence math with a tiny fake repo; live-DB tests cover journaled
CRUD + the reversible edit flow end to end. DB tests skip when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.policy.service import POLICY_INFLUENCE_MAX, PolicyService


# --- hermetic: influence math -------------------------------------------
class _FakeRepo:
    def __init__(self, rules):
        self._rules = rules

    def list(self, *, scope=None, rule=None, enabled=None, limit=200):
        out = self._rules
        if enabled is not None:
            out = [r for r in out if r["enabled"] == enabled]
        return out


def _rule(subject, rule, *, strength=1.0, enabled=True, scope="global"):
    return {"id": uuid.uuid4(), "scope": scope, "subject": subject, "rule": rule,
            "strength": strength, "enabled": enabled}


def test_influence_sign_and_magnitude():
    svc = PolicyService(_FakeRepo([
        _rule("momentum strategies", "prefer", strength=1.0),
        _rule("crypto", "avoid", strength=0.5),
        _rule("finding-1928", "trust", strength=1.0),
        _rule("blog posts", "distrust", strength=1.0),
    ]))
    infl = {i["subject"]: i for i in svc.retrieval_influence()}
    assert infl["momentum strategies"]["weight"] == pytest.approx(POLICY_INFLUENCE_MAX)
    assert infl["crypto"]["weight"] == pytest.approx(-0.5 * POLICY_INFLUENCE_MAX)
    assert infl["finding-1928"]["weight"] == pytest.approx(POLICY_INFLUENCE_MAX)   # trust → positive
    assert infl["blog posts"]["weight"] == pytest.approx(-POLICY_INFLUENCE_MAX)    # distrust → negative
    assert infl["momentum strategies"]["terms"] == ["momentum", "strategies"]


def test_influence_excludes_disabled_and_scopes():
    svc = PolicyService(_FakeRepo([
        _rule("a", "prefer"),
        _rule("b", "prefer", enabled=False),
        _rule("c", "prefer", scope="mission:x"),
    ]))
    subjects = {i["subject"] for i in svc.retrieval_influence()}
    assert subjects == {"a"}  # disabled dropped; non-global scope excluded when no scope requested
    scoped = {i["subject"] for i in svc.retrieval_influence(scope="mission:x")}
    assert scoped == {"a", "c"}  # global always + the requested scope


# --- live DB: journaling + revert ---------------------------------------
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


def _svc(db):
    from atlas.repositories.policy_repo import PolicyRepository

    return PolicyService(PolicyRepository(db))


def test_create_journals_and_revert_removes(db):
    svc = _svc(db)
    subject = f"momentum-{uuid.uuid4().hex[:8]}"
    row = svc.create_rule(subject, "prefer", strength=0.7, created_by="op")

    events = svc.list_events(rule_id=row["id"])
    created = [e for e in events if e["action"] == "created"]
    assert created and created[0]["after"]["subject"] == subject

    # Reverting the creation removes the rule.
    svc.revert(created[0]["id"], actor="op")
    assert svc.get_rule(row["id"]) is None


def test_update_then_revert_restores_prior_value(db):
    svc = _svc(db)
    subject = f"redis-{uuid.uuid4().hex[:8]}"
    row = svc.create_rule(subject, "trust", strength=1.0)

    svc.update_rule(row["id"], strength=0.2, actor="op")
    assert svc.get_rule(row["id"])["strength"] == 0.2

    upd_event = [e for e in svc.list_events(rule_id=row["id"]) if e["action"] == "updated"][0]
    svc.revert(upd_event["id"], actor="op")
    assert svc.get_rule(row["id"])["strength"] == 1.0  # restored

    svc.delete_rule(row["id"])  # cleanup


def test_disable_then_revert_reenables(db):
    svc = _svc(db)
    subject = f"crypto-{uuid.uuid4().hex[:8]}"
    row = svc.create_rule(subject, "avoid")

    svc.set_enabled(row["id"], False, actor="op")
    assert svc.get_rule(row["id"])["enabled"] is False
    dis_event = [e for e in svc.list_events(rule_id=row["id"]) if e["action"] == "disabled"][0]
    svc.revert(dis_event["id"])
    assert svc.get_rule(row["id"])["enabled"] is True
    svc.delete_rule(row["id"])


def test_delete_then_revert_restores_rule(db):
    svc = _svc(db)
    subject = f"topic-{uuid.uuid4().hex[:8]}"
    row = svc.create_rule(subject, "prefer", strength=0.9)

    svc.delete_rule(row["id"], actor="op")
    assert svc.get_rule(row["id"]) is None
    del_event = [e for e in svc.list_events(rule_id=row["id"]) if e["action"] == "deleted"][0]
    restored = svc.revert(del_event["id"])
    assert restored is not None and str(restored["id"]) == str(row["id"])
    assert restored["strength"] == 0.9
    svc.delete_rule(row["id"])


def test_missing_rule_and_event_raise(db):
    svc = _svc(db)
    with pytest.raises(KeyError):
        svc.update_rule(str(uuid.uuid4()), strength=0.5)
    with pytest.raises(KeyError):
        svc.revert(str(uuid.uuid4()))
