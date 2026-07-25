"""Policy Engine hard/soft evaluation (PA.2)."""

from __future__ import annotations

from atlas.policy.engine import PolicyEngine


class _FakePolicy:
    def __init__(self, rules):
        self._rules = rules

    def list_rules(self, *, enabled=True, limit=200, scope=None, rule=None):
        return list(self._rules)


def test_forbid_blocks_buy():
    engine = PolicyEngine(
        _FakePolicy(
            [
                {
                    "id": "r1",
                    "rule": "forbid",
                    "subject": "TSLA",
                    "scope": "global",
                    "strength": 1.0,
                    "enabled": True,
                }
            ]
        )
    )
    out = engine.evaluate(action={"kind": "buy", "symbol": "TSLA", "quantity": 1})
    assert out["allowed"] is False
    assert out["hard_violations"]


def test_soft_avoid_does_not_block():
    engine = PolicyEngine(
        _FakePolicy(
            [
                {
                    "id": "r2",
                    "rule": "avoid",
                    "subject": "TSLA",
                    "scope": "global",
                    "strength": 1.0,
                    "enabled": True,
                }
            ]
        )
    )
    out = engine.evaluate(action={"kind": "buy", "symbol": "TSLA", "quantity": 1})
    assert out["allowed"] is True
    assert out["soft_delta"] < 0


def test_limit_exposure():
    engine = PolicyEngine(
        _FakePolicy(
            [
                {
                    "id": "r3",
                    "rule": "limit",
                    "subject": "equity",
                    "scope": "global",
                    "strength": 1.0,
                    "enabled": True,
                    "provenance": {"max_exposure_pct": 10.0},
                }
            ]
        )
    )
    out = engine.evaluate(
        action={"kind": "buy", "symbol": "DEMO", "quantity": 1},
        context={"exposure_pct": 25.0, "text": "equity"},
    )
    assert out["allowed"] is False


def test_domain_scoped_forbid_only_when_domain_present():
    """OI-C9 — domain-scoped hard rules stay out of unrelated evaluate calls."""
    engine = PolicyEngine(
        _FakePolicy(
            [
                {
                    "id": "r4",
                    "rule": "forbid",
                    "subject": "TSLA",
                    "scope": "domain:markets",
                    "strength": 1.0,
                    "enabled": True,
                }
            ]
        )
    )
    open_out = engine.evaluate(action={"kind": "buy", "symbol": "TSLA", "quantity": 1})
    assert open_out["allowed"] is True
    scoped = engine.evaluate(
        action={"kind": "buy", "symbol": "TSLA", "quantity": 1},
        context={"domain": "markets"},
    )
    assert scoped["allowed"] is False
