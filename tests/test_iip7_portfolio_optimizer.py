"""IIP.7 portfolio optimizer — gates + sizing."""

from __future__ import annotations

from atlas.investment.portfolio_optimizer import (
    optimize_candidate,
    pre_trade_check,
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
