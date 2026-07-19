"""Hermetic tests for the StrategyDecisionRule (Phase D · §D.6, BB-D2).

Deterministic MA-crossover + RSI scoring over a single symbol's context: an uptrend offers a *buy*
above *hold*; a downtrend while holding offers a *sell*; constraints (operator block, allow-list, max
position / exposure) withhold trades; warming-up data holds. Policy influence itself is folded in by
the engine (tested in the worker/e2e), but the rule tags every option with its lowercased symbol so
``avoid SYM`` can bite.
"""

from __future__ import annotations

from atlas.decision.context import IntelligenceContext
from atlas.decision.contracts import DecisionRequest
from atlas.trading.strategy import StrategyDecisionRule

RULE = StrategyDecisionRule()
CTX = IntelligenceContext()


def _request(**context) -> DecisionRequest:
    return DecisionRequest(mission_id="m1", mission_type="paper_trading", context=context)


def _keys(options):
    return {o.key.split(":")[0] for o in options}


def test_uptrend_offers_buy_above_hold():
    opts = RULE.score(
        _request(
            symbol="ACME", price=100.0, equity=10000.0, cash=10000.0, position_qty=0.0,
            indicators={"sma_fast": 105.0, "sma_slow": 100.0, "rsi": 55.0, "bars": 40,
                        "params": {"sma_fast": 10, "sma_slow": 30}},
        ),
        CTX,
    )
    assert "buy" in _keys(opts)
    buy = next(o for o in opts if o.key.startswith("buy"))
    hold = next(o for o in opts if o.key.startswith("hold"))
    assert buy.score > hold.score
    assert "acme" in buy.tags  # lowercased symbol tag → policy can arbitrate
    assert buy.payload["kind"] == "buy" and buy.payload["quantity"] > 0
    assert buy.side_effecting is False  # simulation (P10/DD3)


def test_downtrend_while_holding_offers_sell():
    opts = RULE.score(
        _request(
            symbol="ACME", price=90.0, equity=10000.0, cash=5000.0, position_qty=10.0,
            indicators={"sma_fast": 95.0, "sma_slow": 100.0, "rsi": 45.0, "bars": 40, "params": {}},
        ),
        CTX,
    )
    assert "sell" in _keys(opts)
    sell = next(o for o in opts if o.key.startswith("sell"))
    assert sell.payload["quantity"] == 10.0  # default exits full position


def test_downtrend_without_position_only_holds():
    opts = RULE.score(
        _request(
            symbol="ACME", price=90.0, equity=10000.0, cash=10000.0, position_qty=0.0,
            indicators={"sma_fast": 95.0, "sma_slow": 100.0, "rsi": 45.0, "bars": 40, "params": {}},
        ),
        CTX,
    )
    assert _keys(opts) == {"hold"}


def test_operator_block_forces_hold_only():
    opts = RULE.score(
        _request(
            symbol="ACME", price=100.0, equity=10000.0, cash=10000.0, position_qty=0.0,
            blocked_symbols=["acme"],
            indicators={"sma_fast": 105.0, "sma_slow": 100.0, "rsi": 55.0, "bars": 40, "params": {}},
        ),
        CTX,
    )
    assert _keys(opts) == {"hold"}
    assert "blocked" in opts[0].rationale.lower()


def test_allow_list_excludes_symbol():
    opts = RULE.score(
        _request(
            symbol="ACME", price=100.0, equity=10000.0, cash=10000.0, position_qty=0.0,
            allowed_symbols=["other"],
            indicators={"sma_fast": 105.0, "sma_slow": 100.0, "rsi": 55.0, "bars": 40, "params": {}},
        ),
        CTX,
    )
    assert _keys(opts) == {"hold"}


def test_max_position_cap_withholds_buy():
    opts = RULE.score(
        _request(
            symbol="ACME", price=100.0, equity=100000.0, cash=100000.0, position_qty=50.0,
            max_position_qty=50.0,
            indicators={"sma_fast": 105.0, "sma_slow": 100.0, "rsi": 55.0, "bars": 40, "params": {}},
        ),
        CTX,
    )
    assert "buy" not in _keys(opts)


def test_overbought_rsi_suppresses_buy():
    opts = RULE.score(
        _request(
            symbol="ACME", price=100.0, equity=10000.0, cash=10000.0, position_qty=0.0,
            rsi_overbought=70.0,
            indicators={"sma_fast": 105.0, "sma_slow": 100.0, "rsi": 80.0, "bars": 40, "params": {}},
        ),
        CTX,
    )
    assert "buy" not in _keys(opts)


def test_warming_up_holds():
    opts = RULE.score(
        _request(
            symbol="ACME", price=100.0, equity=10000.0, cash=10000.0, position_qty=0.0,
            indicators={"sma_fast": None, "sma_slow": None, "rsi": None, "bars": 3, "params": {}},
        ),
        CTX,
    )
    assert _keys(opts) == {"hold"}
    assert "warming up" in opts[0].rationale


def test_no_symbol_returns_empty():
    assert RULE.score(_request(), CTX) == []
