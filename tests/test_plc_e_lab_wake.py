"""PLC.E lab wake — F&O/intraday durable feed + config enrich hermetic tests."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.bar_store import load_symbol_doc, persist_symbol_bars
from atlas.investment.portfolios import (
    default_decision_config,
    enrich_decision_config_from_book,
)
from atlas.investment.symbol_aliases import resolve_yahoo_symbol
from atlas.trading.market_reader import MarketReaderService


def test_banknifty_alias():
    r = resolve_yahoo_symbol("BANKNIFTY")
    assert r.yahoo == "^NSEBANK"
    assert r.aliased is True


def test_fno_skips_cash_equity_alts():
    from atlas.workers.paper_trading import skip_cash_alts_for_lab

    assert skip_cash_alts_for_lab({"asset_class": "futures", "instrument_pack": "nse_fno"})
    assert skip_cash_alts_for_lab({}, pack_id="futures")
    assert skip_cash_alts_for_lab({}, portfolio_key="fno_paper")
    assert skip_cash_alts_for_lab({}, portfolio_key="equity_intraday_learner")
    assert not skip_cash_alts_for_lab(
        {"asset_class": "cash_equity"}, pack_id="nse_cash", portfolio_key="india_equity_learner"
    )


def test_load_nifty_from_caret_legacy_filename(tmp_path):
    """Observer wrote ``^NSEI.json``; safe path is ``_NSEI.json`` — both must load."""
    root = tmp_path / "market" / "bars"
    root.mkdir(parents=True)
    doc = {
        "version": "mkt.bars.v1",
        "symbol": "^NSEI",
        "provider": "yahoo",
        "bar_count": 2,
        "bars": [
            {"date": "2026-08-06", "close": 100.0},
            {"date": "2026-08-07", "close": 101.0},
        ],
    }
    (root / "^NSEI.json").write_text(json.dumps(doc), encoding="utf-8")
    loaded = load_symbol_doc(tmp_path, "NIFTY")
    assert loaded is not None
    assert loaded["symbol"] == "^NSEI"
    assert len(loaded["bars"]) == 2


def test_market_reader_nifty_uses_durable_caret(tmp_path):
    bars = [{"date": f"2026-07-{i:02d}", "close": 100.0 + i} for i in range(1, 28)]
    bars += [{"date": f"2026-08-{i:02d}", "close": 130.0 + i} for i in range(1, 20)]
    root = tmp_path / "market" / "bars"
    root.mkdir(parents=True)
    (root / "^NSEI.json").write_text(
        json.dumps(
            {
                "version": "mkt.bars.v1",
                "symbol": "^NSEI",
                "bars": bars,
                "bar_count": len(bars),
            }
        ),
        encoding="utf-8",
    )

    mr = MarketReaderService(
        default_provider="yahoo",
        yahoo_enabled=False,  # force durable path; no network
        data_dir=str(tmp_path),
        prefer_durable_bars=True,
    )
    out = mr.bars_for("NIFTY", provider="yahoo", limit=20)
    assert out["count"] > 0
    assert out.get("source") == "durable_bar_store"
    assert "durable" in str(out.get("provider") or "")


def test_enrich_seeds_fno_instruments():
    book = {
        "portfolio_key": "india_fno_learner",
        "asset_class": "futures",
        "instrument_pack": "futures",
        "persona": {"capital": 100000, "allowed_assets": ["futures"]},
    }
    cfg = enrich_decision_config_from_book(
        {
            "instruments": [],
            "auto_max_instruments": 0,
            "portfolio_key": "india_fno_learner",
        },
        book,
    )
    assert cfg["market_session"] == "nse_fno"
    assert cfg["instruments"]
    assert cfg["instruments"][0]["symbol"] == "NIFTY"
    assert cfg["instruments"][0]["asset_class"] == "futures"
    assert cfg.get("_lab_seeded_instruments") is True


def test_enrich_intraday_session_defaults():
    book = {
        "portfolio_key": "equity_intraday_learner",
        "asset_class": "cash_equity",
        "instrument_pack": "cash_equity",
        "persona": {"capital": 50000, "allowed_assets": ["cash_equity"]},
    }
    cfg = enrich_decision_config_from_book({}, book)
    assert cfg["market_session"] == "nse_equity"
    assert cfg["respect_market_hours"] is True
    assert int(cfg.get("auto_max_instruments") or 0) >= 1


def test_default_fno_includes_banknifty():
    cfg = default_decision_config(
        {
            "portfolio_key": "india_fno_learner",
            "asset_class": "futures",
            "instrument_pack": "futures",
            "persona": {"capital": 1, "allowed_assets": ["futures"]},
        }
    )
    syms = {i["symbol"] for i in cfg["instruments"]}
    assert "NIFTY" in syms
    assert "BANKNIFTY" in syms


def test_persist_writes_safe_path_and_loads(tmp_path):
    bars = [{"date": "2026-08-07", "close": 1.0}] * 40
    # pad unique dates
    bars = [{"date": f"2026-06-{(i % 28) + 1:02d}", "close": float(i)} for i in range(45)]
    persist_symbol_bars(tmp_path, "NIFTY", bars, provider="yahoo")
    safe = tmp_path / "market" / "bars" / "_NSEI.json"
    assert safe.is_file()
    assert load_symbol_doc(tmp_path, "^NSEI") is not None
