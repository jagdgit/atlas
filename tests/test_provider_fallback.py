"""OI-MDPH-FALLBACK — labeled live-provider plan (never silent Zerodha)."""

from __future__ import annotations

import pytest

from atlas.investment import provider_fallback as pf


def _health(status: str, *, allowed: bool | None = None) -> dict:
    return {
        "status": status,
        "live_trading_allowed": allowed if allowed is not None else status == "READY",
    }


def test_zerodha_ready_uses_zerodha(monkeypatch):
    monkeypatch.delenv("ATLAS_MDPH_LIVE_FALLBACK", raising=False)
    plan = pf.resolve_live_provider_plan(
        portfolio_key="equity_intraday_learner",
        cfg={"live_provider": "zerodha"},
        zerodha_health=_health("READY"),
        live_required=True,
    )
    assert plan["paused"] is False
    assert plan["provider"] == "zerodha"
    assert plan["fallback"] is None
    assert plan["reason"] == "zerodha_ready"


def test_intraday_auto_yahoo_labeled_when_login_required(monkeypatch):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "auto")
    monkeypatch.setattr(pf, "groww_available", lambda: False)
    plan = pf.resolve_live_provider_plan(
        portfolio_key="equity_intraday_learner",
        cfg={},
        zerodha_health=_health("LOGIN_REQUIRED", allowed=False),
        live_required=True,
    )
    assert plan["paused"] is False
    assert plan["provider"] == "yahoo"
    assert plan["fallback"] == "yahoo"
    assert plan["reason"] == "live_zerodha_down_yahoo_labeled"
    assert "Not Zerodha" in (plan.get("honesty") or "")


def test_fno_pauses_without_broker_ltp(monkeypatch):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "auto")
    monkeypatch.setattr(pf, "groww_available", lambda: False)
    plan = pf.resolve_live_provider_plan(
        portfolio_key="india_fno_learner",
        cfg={"asset_class": "options"},
        zerodha_health=_health("LOGIN_REQUIRED", allowed=False),
        live_required=True,
    )
    assert plan["paused"] is True
    assert plan["provider"] is None
    assert plan["reason"] == "fno_paused_no_broker_ltp"
    assert "Yahoo cannot" in (plan.get("honesty") or "")


def test_fallback_off_pauses_intraday(monkeypatch):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "off")
    plan = pf.resolve_live_provider_plan(
        portfolio_key="equity_intraday_learner",
        cfg={},
        zerodha_health=_health("EXPIRED", allowed=False),
        live_required=True,
    )
    assert plan["paused"] is True
    assert plan["reason"] == "live_paused_fallback_off"


def test_non_live_continues_on_yahoo(monkeypatch):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "off")
    plan = pf.resolve_live_provider_plan(
        portfolio_key="india_equity_learner",
        cfg={"live_provider": "yahoo"},
        zerodha_health=_health("LOGIN_REQUIRED", allowed=False),
        live_required=False,
    )
    assert plan["paused"] is False
    assert plan["provider"] == "yahoo"
    assert plan["reason"] == "non_live"


def test_groww_without_bars_falls_to_labeled_yahoo(monkeypatch):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "groww")
    monkeypatch.setattr(pf, "groww_available", lambda: True)
    monkeypatch.setattr(pf, "groww_bars_usable", lambda: False)
    plan = pf.resolve_live_provider_plan(
        portfolio_key="equity_intraday_learner",
        cfg={},
        zerodha_health=_health("LOGIN_REQUIRED", allowed=False),
        live_required=True,
    )
    assert plan["paused"] is False
    assert plan["provider"] == "yahoo"
    assert plan["fallback"] == "yahoo"
    assert "bars adapter not wired" in (plan.get("honesty") or "")


def test_fno_groww_without_bars_still_pauses(monkeypatch):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "groww")
    monkeypatch.setattr(pf, "groww_available", lambda: True)
    monkeypatch.setattr(pf, "groww_bars_usable", lambda: False)
    plan = pf.resolve_live_provider_plan(
        portfolio_key="india_fno_learner",
        cfg={"asset_class": "fno"},
        zerodha_health=_health("LOGIN_REQUIRED", allowed=False),
        live_required=True,
    )
    assert plan["paused"] is True
    assert plan["reason"] == "fno_paused_no_broker_ltp"


def test_live_fallback_mode_aliases(monkeypatch):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "false")
    assert pf.live_fallback_mode() == pf.FALLBACK_OFF
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "yfinance")
    assert pf.live_fallback_mode() == pf.FALLBACK_YAHOO
    monkeypatch.delenv("ATLAS_MDPH_LIVE_FALLBACK", raising=False)
    assert pf.live_fallback_mode() == pf.FALLBACK_AUTO


@pytest.mark.parametrize(
    "status",
    ["LOGIN_REQUIRED", "EXPIRED", "DEGRADED"],
)
def test_yahoo_force_mode_labels_intraday(monkeypatch, status: str):
    monkeypatch.setenv("ATLAS_MDPH_LIVE_FALLBACK", "yahoo")
    monkeypatch.setattr(pf, "groww_available", lambda: False)
    plan = pf.resolve_live_provider_plan(
        portfolio_key="equity_intraday_learner",
        cfg={},
        zerodha_health=_health(status, allowed=False),
        live_required=True,
    )
    assert plan["fallback"] == "yahoo"
    assert plan["paused"] is False
