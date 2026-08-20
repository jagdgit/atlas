"""IIP.7 portfolio optimizer — gates + sizing."""

from __future__ import annotations

from atlas.investment.portfolio_optimizer import (
    max_allowed_quantity,
    name_cap_override_fraction,
    optimize_candidate,
    pre_trade_check,
    resolve_limits,
    suggest_notional,
)
from atlas.investment.portfolios import india_equity_learner_persona


def test_suggest_notional_respects_cash_and_risk():
    persona = india_equity_learner_persona(capital=10000)
    size = suggest_notional(
        equity=10000,
        cash=2000,
        persona=persona,
        mos_pct=20,
        horizon="long_term",
        investment_confidence_score=0.7,
        price=100,
    )
    assert size["notional"] <= 2000
    assert size["quantity"] >= 0
    # Min cash buffer for medium risk = 15% → spendable ~500 if equity 10k cash 2k
    assert size["spendable_cash"] <= 2000


def test_pre_trade_blocks_concentration_and_confidence():
    persona = india_equity_learner_persona(capital=10000)
    snap = {
        "cash": 8000,
        "equity": 10000,
        "positions": [
            {"symbol": "INFY.NS", "quantity": 20, "mark": 150},  # 3000
            {"symbol": "TCS.NS", "quantity": 10, "mark": 200},  # 2000
        ],
    }
    # Huge buy → name concentration fail
    check = pre_trade_check(
        side="buy",
        symbol="RELIANCE.NS",
        quantity=50,
        price=100,  # 5000 notional on 10k equity = 50% > 18%
        snapshot=snap,
        persona=persona,
        investment_score={
            "path": "buy_eligible",
            "investment_confidence": "medium",
            "investment_confidence_score": 0.6,
            "horizon": "long_term",
        },
        research_gate={"allowed": True, "action": "buy_ok"},
        require_research=True,
        require_score=True,
    )
    assert check["allowed"] is False
    assert any("concentration_name" in r for r in check["reasons"])

    # Low investment confidence floor
    check2 = pre_trade_check(
        side="buy",
        symbol="BEL.NS",
        quantity=1,
        price=100,
        snapshot={"cash": 9000, "equity": 10000, "positions": []},
        persona=persona,
        investment_score={
            "path": "watch",
            "path_reason": "high_research_low_investment",
            "investment_confidence": "very_low",
            "investment_confidence_score": 0.2,
        },
        research_gate={"allowed": True},
        min_investment_confidence="low",
    )
    assert check2["allowed"] is False
    assert any("score_watch" in r or "investment_confidence" in r for r in check2["reasons"])


def test_buys_require_research_and_score_and_portfolio():
    """Done-when: score + research + portfolio gates all logged."""
    persona = india_equity_learner_persona(capital=10000)
    # Research blocked
    blocked = pre_trade_check(
        side="buy",
        symbol="INFY.NS",
        quantity=5,
        price=100,
        snapshot={"cash": 9000, "equity": 10000, "positions": []},
        persona=persona,
        investment_score={"path": "buy_eligible", "investment_confidence": "medium"},
        research_gate={"allowed": False, "reasons": ["mvr_incomplete"]},
    )
    assert blocked["allowed"] is False
    assert any("research_gate" in r for r in blocked["reasons"])

    # All pass
    ok = pre_trade_check(
        side="buy",
        symbol="INFY.NS",
        quantity=5,
        price=100,
        snapshot={"cash": 9000, "equity": 10000, "positions": []},
        persona=persona,
        investment_score={
            "path": "buy_eligible",
            "investment_confidence": "medium",
            "investment_confidence_score": 0.6,
            "horizon": "long_term",
        },
        research_gate={"allowed": True, "action": "buy_ok"},
    )
    assert ok["allowed"] is True
    assert ok["action"] == "buy_ok"
    ids = {c["id"] for c in ok["checks"]}
    assert "research_gate" in ids
    assert "score_path" in ids
    assert "cash" in ids


def test_sector_cap_never_below_single_name_cap():
    """max_exposure_pct=40 must not leave a 35% sector cap that blocks every buy."""
    persona = india_equity_learner_persona(capital=50000)
    limits = resolve_limits(persona, {"max_name_pct": 0.40})
    assert limits["sector_cap_pct"] >= limits["max_name_pct"]
    # An explicit operator sector cap still wins.
    tight = resolve_limits(persona, {"max_name_pct": 0.40, "sector_cap_pct": 0.20})
    assert tight["sector_cap_pct"] == 0.20


def test_template_max_exposure_zero_is_persona_default_not_zero_cap():
    """LOOP0 L0 — paper template ships max_exposure_pct=0 meaning unset."""
    persona = india_equity_learner_persona(capital=50000)
    assert name_cap_override_fraction({"max_exposure_pct": 0}) is None
    assert name_cap_override_fraction({"max_exposure_pct": 0.0}) is None
    assert name_cap_override_fraction({}) is None
    unset = resolve_limits(persona, {"max_exposure_pct": 0})
    assert unset["max_name_pct"] == resolve_limits(persona, {})["max_name_pct"]
    assert unset["max_name_pct"] > 0
    explicit = resolve_limits(persona, {"max_exposure_pct": 40})
    assert abs(explicit["max_name_pct"] - 0.40) < 1e-9
    # max_name_pct=0 is an explicit hard cap, not template-unset.
    assert name_cap_override_fraction({"max_name_pct": 0}) == 0.0
    hard_zero = resolve_limits(persona, {"max_name_pct": 0})
    assert hard_zero["max_name_pct"] == 0.0


def test_blocked_buy_reports_trimmable_room():
    persona = india_equity_learner_persona(capital=10000)
    snap = {"cash": 9000, "equity": 10000, "positions": []}
    check = pre_trade_check(
        side="buy",
        symbol="INFY.NS",
        quantity=50,
        price=100,  # 5000 = 50% of equity vs 18% name cap
        snapshot=snap,
        persona=persona,
        investment_score={
            "path": "buy_eligible",
            "investment_confidence": "medium",
            "investment_confidence_score": 0.6,
            "horizon": "long_term",
        },
        research_gate={"allowed": True, "action": "buy_ok"},
    )
    assert check["allowed"] is False
    assert check["trimmable"] is True
    assert 0 < check["max_quantity"] < 50

    retry = pre_trade_check(
        side="buy",
        symbol="INFY.NS",
        quantity=check["max_quantity"],
        price=100,
        snapshot=snap,
        persona=persona,
        investment_score={
            "path": "buy_eligible",
            "investment_confidence": "medium",
            "investment_confidence_score": 0.6,
            "horizon": "long_term",
        },
        research_gate={"allowed": True, "action": "buy_ok"},
    )
    assert retry["allowed"] is True


def test_research_block_is_not_trimmable():
    persona = india_equity_learner_persona(capital=10000)
    check = pre_trade_check(
        side="buy",
        symbol="INFY.NS",
        quantity=5,
        price=100,
        snapshot={"cash": 9000, "equity": 10000, "positions": []},
        persona=persona,
        investment_score={"path": "buy_eligible", "investment_confidence": "medium"},
        research_gate={"allowed": False, "reasons": ["mvr_incomplete"]},
    )
    assert check["trimmable"] is False


def test_max_allowed_quantity_respects_cash_buffer():
    persona = india_equity_learner_persona(capital=10000)
    room = max_allowed_quantity(
        symbol="INFY.NS",
        price=100,
        snapshot={"cash": 2000, "equity": 10000, "positions": []},
        persona=persona,
    )
    # Medium risk keeps a 15% cash buffer → only 500 of the 2000 cash is spendable.
    assert room["quantity"] == 5
    assert room["binding"] == "cash_buffer"


def test_empty_score_is_not_invented_very_low():
    """Missing research score must not invent investment_confidence=very_low."""
    persona = india_equity_learner_persona(capital=10000)
    check = pre_trade_check(
        side="buy",
        symbol="INFY.NS",
        quantity=5,
        price=100,
        snapshot={"cash": 9000, "equity": 10000, "positions": []},
        persona=persona,
        investment_score={},
        research_gate={"allowed": True, "action": "buy_ok"},
        require_score=True,
        min_investment_confidence="low",
    )
    assert check["allowed"] is True
    assert not any("investment_confidence_floor" in r for r in check["reasons"])


def test_optimize_candidate_sizes():
    persona = india_equity_learner_persona(capital=10000)
    out = optimize_candidate(
        symbol="INFY.NS",
        price=1500,
        snapshot={"cash": 8000, "equity": 10000, "positions": []},
        persona=persona,
        investment_score={
            "path": "buy_eligible",
            "investment_confidence": "medium",
            "investment_confidence_score": 0.55,
            "horizon": "structural",
        },
        research_gate={"allowed": True},
        mos_pct=25,
    )
    assert "sizing" in out and "pre_trade" in out
    assert out["sizing"]["quantity"] >= 0
