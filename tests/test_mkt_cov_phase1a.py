"""OI-MKT-COV Phase 1A — M0 provider resolution + report honesty D3."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from atlas.investment.causal_attribution import format_causal_learning_lines
from atlas.investment.reports import (
    _format_fundamentals_clarity_section,
    ranking_trust_status,
)
from atlas.workers.investment_universe import InvestmentUniverseWorker


def test_resolve_bars_provider_explicit_wins():
    w = InvestmentUniverseWorker()
    assert w._resolve_bars_provider({"provider": "polygon"}) == "polygon"
    assert w._resolve_bars_provider({"provider": "asset_replay"}) == "asset_replay"


def test_resolve_bars_provider_empty_uses_yahoo_when_enabled():
    w = InvestmentUniverseWorker()
    market = MagicMock()
    market.yahoo_enabled = True
    cfg = MagicMock()
    cfg.market = market
    with patch("atlas.config.get_config", return_value=cfg):
        assert w._resolve_bars_provider({"provider": ""}) == "yahoo"
        assert w._resolve_bars_provider({}) == "yahoo"


def test_resolve_bars_provider_empty_stays_none_when_yahoo_off():
    w = InvestmentUniverseWorker()
    market = MagicMock()
    market.yahoo_enabled = False
    cfg = MagicMock()
    cfg.market = market
    with patch("atlas.config.get_config", return_value=cfg):
        assert w._resolve_bars_provider({}) is None


def test_ranking_trust_requires_durable_bars():
    trust = ranking_trust_status(
        triage={
            "ok": True,
            "coverage": {
                "price_coverage_pct": 98.0,
                "acceleration_status": "ok",
                "durable_bars_ok": False,
            },
        },
        plan={"phase": "active", "confidence": "medium"},
        fundamentals_coverage={"with_pe": 18, "symbols": 18},
    )
    assert trust["trustworthy"] is False
    assert trust["durable_bars_ok"] is False
    assert any("Durable OHLCV" in r for r in trust["reasons"])

    trust_ok = ranking_trust_status(
        triage={
            "ok": True,
            "coverage": {
                "price_coverage_pct": 98.0,
                "acceleration_status": "pending_history",
                "durable_bars_ok": True,
                "durable_history_ok_pct": 97.0,
                "readiness_grade": "B",
            },
        },
        plan={"phase": "active", "confidence": "low"},
        fundamentals_coverage={"with_pe": 18, "symbols": 18},
    )
    assert trust_ok["trustworthy"] is True
    assert trust_ok["status"] == "TRUSTWORTHY"


def test_fundamentals_clarity_store_vs_watchlist():
    lines = _format_fundamentals_clarity_section(
        {
            "symbols": 18,
            "with_pe": 18,
            "with_fcf": 2,
            "with_roe": 1,
            "learner_gaps": {
                "symbols_checked": 5,
                "symbols_with_gaps": 5,
                "missing_pe": 0,
                "missing_fcf": 5,
                "missing_roe": 5,
            },
        }
    )
    blob = "\n".join(lines)
    assert "ACTIVE STORE" in blob
    assert "PE        18/18" in blob
    assert "FCF       2/18" in blob
    assert "ACTIVE WATCHLIST" in blob
    assert "PE        5/5" in blob
    assert "FCF       0/5" in blob


def test_causal_unknown_is_not_learned():
    lines = format_causal_learning_lines(
        [
            {
                "symbol": "CIPLA.NS",
                "trigger": "revisit",
                "payload": {
                    "causal_factors": {
                        "helped": [],
                        "hurt": [],
                        "unknown": ["sector", "news", "policy", "thesis"],
                        "narrative": "unknown: sector, news, policy, thesis",
                    }
                },
            }
        ]
    )
    blob = "\n".join(lines)
    assert "WHAT ATLAS LEARNED" in blob
    assert "none yet" in blob.lower()
    assert "WHAT ATLAS COULD NOT DETERMINE" in blob
    assert "CIPLA" in blob
    assert "DATA REQUIRED" in blob
    assert "news" in blob.lower()
