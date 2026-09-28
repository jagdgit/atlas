"""OI-LAB-LOOP0 Step 3 — nearest NIFTY FUT resolver (no options chain)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from atlas.investment.fno_contract import (
    choose_atm_overlay,
    is_nifty50_fut_row,
    is_nifty50_option_row,
    is_phase2_underlying,
    kite_instrument,
    load_phase2_experiment,
    load_resolved,
    persist_phase2_bundle,
    persist_resolved,
    resolve_nearest_fut,
    resolve_phase2_bundle,
    stamp_phase1_contracts,
    stamp_phase2_experiment,
)
from atlas.investment.zerodha_feed import ZerodhaMarketFeed
from tests.test_zerodha_feed import _FakeKite


def _rows(as_of: date) -> list[dict]:
    return [
        {
            "tradingsymbol": "NIFTYEXPIREDFUT",
            "name": "NIFTY",
            "instrument_type": "FUT",
            "instrument_token": 1,
            "expiry": as_of - timedelta(days=2),
            "lot_size": 25,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "NIFTYNEARFUT",
            "name": "NIFTY",
            "instrument_type": "FUT",
            "instrument_token": 222,
            "expiry": as_of + timedelta(days=6),
            "lot_size": 25,
            "exchange": "NFO",
            "segment": "NFO-FUT",
        },
        {
            "tradingsymbol": "NIFTYFARFUT",
            "name": "NIFTY",
            "instrument_type": "FUT",
            "instrument_token": 333,
            "expiry": as_of + timedelta(days=34),
            "lot_size": 25,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "BANKNIFTYNEARFUT",
            "name": "NIFTY BANK",
            "instrument_type": "FUT",
            "instrument_token": 444,
            "expiry": as_of + timedelta(days=6),
            "lot_size": 15,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "NIFTYNEAR25000CE",
            "name": "NIFTY",
            "instrument_type": "CE",
            "instrument_token": 555,
            "expiry": as_of + timedelta(days=6),
            "strike": 25000,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "NIFTYNEAR25000PE",
            "name": "NIFTY",
            "instrument_type": "PE",
            "instrument_token": 556,
            "expiry": as_of + timedelta(days=6),
            "strike": 25000,
            "exchange": "NFO",
        },
        {
            "tradingsymbol": "FINNIFTYNEARFUT",
            "name": "NIFTY FIN SERVICE",
            "instrument_type": "FUT",
            "instrument_token": 666,
            "expiry": as_of + timedelta(days=5),
            "exchange": "NFO",
        },
    ]


def test_nearest_unexpired_nifty_fut_skips_options_and_other_indices():
    as_of = date(2026, 9, 17)
    out = resolve_nearest_fut(_rows(as_of), symbol="NIFTY", as_of=as_of)
    assert out["ok"] is True
    assert out["tradingsymbol"] == "NIFTYNEARFUT"
    assert out["instrument_token"] == 222
    assert out["expiry"] == "2026-09-23"
    assert out["exchange"] == "NFO"
    assert out["instrument_type"] == "FUT"
    assert kite_instrument(out) == "NFO:NIFTYNEARFUT"
    assert not is_nifty50_fut_row({"tradingsymbol": "NIFTYNEAR25000CE", "instrument_type": "CE", "name": "NIFTY"})


def test_banknifty_resolves_nearest_fut():
    as_of = date(2026, 9, 17)
    out = resolve_nearest_fut(_rows(as_of), symbol="BANKNIFTY", as_of=as_of)
    assert out["ok"] is True
    assert out["tradingsymbol"] == "BANKNIFTYNEARFUT"
    assert out["underlying"] == "BANKNIFTY"
    assert out["lot_size"] == 15


def test_cash_equity_is_not_index_underlier():
    as_of = date(2026, 9, 17)
    out = resolve_nearest_fut(_rows(as_of), symbol="BOSCHLTD", as_of=as_of)
    assert out["ok"] is False
    assert out["reason"] == "not_index_underlier"


def test_finnifty_resolves_nearest_fut():
    as_of = date(2026, 9, 17)
    out = resolve_nearest_fut(_rows(as_of), symbol="FINNIFTY", as_of=as_of)
    assert out["ok"] is True
    assert out["tradingsymbol"] == "FINNIFTYNEARFUT"
    assert out["underlying"] == "FINNIFTY"
    as_of = date(2026, 9, 17)
    expired = [
        {
            "tradingsymbol": "NIFTYOLDFUT",
            "name": "NIFTY",
            "instrument_type": "FUT",
            "instrument_token": 1,
            "expiry": as_of - timedelta(days=1),
            "exchange": "NFO",
        }
    ]
    out = resolve_nearest_fut(expired, symbol="NIFTY", as_of=as_of)
    assert out["ok"] is False
    assert out["reason"] == "no_unexpired_fut"


def test_stamp_and_persist_reconstructable(tmp_path: Path):
    as_of = date(2026, 9, 17)
    instruments = [
        {"symbol": "NIFTY", "asset_class": "futures", "lot_size": 25},
        {"symbol": "BANKNIFTY", "asset_class": "futures", "lot_size": 15},
    ]
    stamped, cmap = stamp_phase1_contracts(
        instruments, rows=_rows(as_of), data_dir=tmp_path, now=as_of
    )
    nifty = next(r for r in stamped if r["symbol"] == "NIFTY")
    assert nifty["fno_contract"]["tradingsymbol"] == "NIFTYNEARFUT"
    assert nifty["nfo_tradingsymbol"] == "NIFTYNEARFUT"
    assert nifty["expiry"] == "2026-09-23"
    bank = next(r for r in stamped if r["symbol"] == "BANKNIFTY")
    assert bank["fno_contract"]["ok"] is True
    assert bank["fno_contract"]["tradingsymbol"] == "BANKNIFTYNEARFUT"
    loaded_bank = load_resolved(tmp_path, underlying="BANKNIFTY")
    assert loaded_bank["instrument_token"] == 444
    loaded = load_resolved(tmp_path, underlying="NIFTY")
    assert loaded["instrument_token"] == 222
    dated = load_resolved(tmp_path, underlying="NIFTY", ist_date="2026-09-17")
    assert dated["tradingsymbol"] == "NIFTYNEARFUT"
    assert persist_resolved(tmp_path, nifty["fno_contract"])["ok"] is True


def test_zerodha_nifty_resolves_nfo_fut_not_index(tmp_path: Path):
    kite = _FakeKite()
    feed = ZerodhaMarketFeed(
        api_key="key",
        api_secret="secret",
        data_dir=tmp_path,
        client=kite,
    )
    assert feed.complete_login("req123")["ok"]
    tok = feed.resolve_instrument_token("NIFTY")
    fut = feed.resolve_phase1_fut("NIFTY")
    assert fut["ok"] is True
    assert tok == fut["instrument_token"]
    assert str(fut["tradingsymbol"]).endswith("FUT")
    assert "CE" not in fut["tradingsymbol"]
    inst = feed.kite_quote_instrument("NIFTY")
    assert inst.startswith("NFO:")
    assert inst.endswith("FUT")

    bars = feed.get_historical_bars("NIFTY", interval="1d", limit=10)
    assert bars["ok"] is True
    assert bars["count"] >= 1

    rel = feed.resolve_instrument_token("RELIANCE.NS")
    assert rel == 1000  # first EQ row in FakeKite NSE dump


def test_atm_ce_pe_match_nearest_fut_expiry_skip_banknifty(tmp_path: Path):
    as_of = date(2026, 9, 17)
    rows = _rows(as_of) + [
        {
            "tradingsymbol": "BANKNIFTYNEAR55000CE",
            "name": "NIFTY BANK",
            "instrument_type": "CE",
            "instrument_token": 777,
            "expiry": as_of + timedelta(days=6),
            "strike": 55000,
            "lot_size": 15,
            "exchange": "NFO",
        }
    ]
    bundle = resolve_phase2_bundle(rows, symbol="NIFTY", spot=25010, as_of=as_of)
    assert bundle["ok"] is True
    assert bundle["writing"] is False
    assert bundle["fut"]["tradingsymbol"] == "NIFTYNEARFUT"
    assert bundle["ce"]["tradingsymbol"] == "NIFTYNEAR25000CE"
    assert bundle["pe"]["tradingsymbol"] == "NIFTYNEAR25000PE"
    assert bundle["ce"]["strike"] == 25000
    assert bundle["ce"]["expiry"] == "2026-09-23"
    assert not is_nifty50_option_row(rows[-1])
    persisted = persist_phase2_bundle(tmp_path, bundle)
    assert persisted["ok"] is True
    atm_path = tmp_path / "investment" / "fno" / "contracts" / "NIFTY_ATM.json"
    assert atm_path.is_file()
    # Full chain is not written — only the ATM snapshot.
    assert "BANKNIFTYNEAR55000CE" not in atm_path.read_text(encoding="utf-8")


def test_overlay_flat_bearish_buys_pe_not_index_proxy():
    as_of = date(2026, 9, 17)
    bundle = resolve_phase2_bundle(_rows(as_of), symbol="NIFTY", spot=25000, as_of=as_of)
    out = choose_atm_overlay(
        sma_margin=-0.01,
        underlier_held=0.0,
        positions=[],
        bundle=bundle,
        cash=50_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        control_action="buy",
        underlying_price=25000.0,
        future_price=25020.0,
    )
    assert out["used"] is True
    assert out["fallback_l4"] is False
    assert out["kind"] == "buy"
    assert out["right"] == "PE"
    assert out["symbol"] == "NIFTYNEAR25000PE"
    assert out["qty"] == 25.0
    assert out["price"] == 110.0
    assert out["writing"] is False
    assert out["strategy_tag"] == "sma_cross_rsi"
    assert out["adapter_id"] == "fno_atm_ce_pe.v1"
    marks = out["marks"]
    assert marks["option_ltp"] == 110.0
    assert marks["underlying_price"] == 25000.0
    assert marks["future_price"] == 25020.0
    assert marks["cash_debit"] == 25.0 * 110.0
    assert marks["option_type"] == "PE"


def test_overlay_flat_bullish_buys_ce():
    as_of = date(2026, 9, 17)
    bundle = resolve_phase2_bundle(_rows(as_of), symbol="NIFTY", spot=25000, as_of=as_of)
    out = choose_atm_overlay(
        sma_margin=0.01,
        underlier_held=0.0,
        positions=[],
        bundle=bundle,
        cash=50_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        control_action="buy",
    )
    assert out["used"] is True
    assert out["kind"] == "buy"
    assert out["right"] == "CE"
    assert out["symbol"] == "NIFTYNEAR25000CE"


def test_overlay_holding_ce_bearish_exits_ce():
    as_of = date(2026, 9, 17)
    bundle = resolve_phase2_bundle(_rows(as_of), symbol="NIFTY", spot=25000, as_of=as_of)
    out = choose_atm_overlay(
        sma_margin=-0.02,
        underlier_held=0.0,
        positions=[{"symbol": "NIFTYNEAR25000CE", "quantity": 25.0}],
        bundle=bundle,
        cash=50_000.0,
        ce_ltp=80.0,
        pe_ltp=140.0,
        control_action="sell",
    )
    assert out["used"] is True
    assert out["kind"] == "sell"
    assert out["symbol"] == "NIFTYNEAR25000CE"
    assert out["qty"] == 25.0
    assert out["writing"] is False


def test_overlay_resolved_neutral_does_not_force_l4():
    as_of = date(2026, 9, 17)
    bundle = resolve_phase2_bundle(_rows(as_of), symbol="NIFTY", spot=25000, as_of=as_of)
    out = choose_atm_overlay(
        sma_margin=0.0,
        underlier_held=0.0,
        positions=[],
        bundle=bundle,
        cash=50_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        control_action="buy",
    )
    assert out["used"] is False
    assert out["fallback_l4"] is False
    assert out["reason"] == "underlier_neutral"


def test_overlay_unresolved_falls_back_to_l4():
    out = choose_atm_overlay(
        sma_margin=-0.01,
        underlier_held=0.0,
        positions=[],
        bundle={"ok": False, "reason": "no_unexpired_nifty_fut"},
        cash=50_000.0,
        ce_ltp=None,
        pe_ltp=None,
    )
    assert out["used"] is False
    assert out["fallback_l4"] is True


def test_zerodha_atm_options_quote_not_remapped_to_fut(tmp_path: Path):
    kite = _FakeKite()
    feed = ZerodhaMarketFeed(
        api_key="key",
        api_secret="secret",
        data_dir=tmp_path,
        client=kite,
    )
    assert feed.complete_login("req123")["ok"]
    opts = feed.list_nfo_options()
    rights = {(r["tradingsymbol"], r["instrument_type"]) for r in opts}
    assert ("NIFTY23SEP2625000CE", "CE") in rights
    assert ("NIFTY23SEP2625000PE", "PE") in rights
    assert all(not str(r["tradingsymbol"]).endswith(".NS") for r in opts)
    ce = "NIFTY23SEP2625000CE"
    assert feed.kite_quote_instrument(ce) == f"NFO:{ce}"
    assert feed.kite_quote_instrument("NIFTY").endswith("FUT")
    ltp = feed.get_ltp(ce)
    assert ltp["ok"] is True
    assert ltp["prices"][ce]["last"] == 100.5
    assert "CE" in ltp["prices"][ce]["instrument"]


def test_overlay_hold_does_not_open_atm():
    as_of = date(2026, 9, 17)
    bundle = resolve_phase2_bundle(_rows(as_of), symbol="NIFTY", spot=25000, as_of=as_of)
    out = choose_atm_overlay(
        sma_margin=-0.01,
        underlier_held=0.0,
        positions=[],
        bundle=bundle,
        cash=50_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        control_action="hold",
    )
    assert out["used"] is False
    assert out["reason"] == "control_hold"
    assert out["fallback_l4"] is False


def test_overlay_ignores_legacy_non_atm_pe():
    as_of = date(2026, 9, 17)
    bundle = resolve_phase2_bundle(_rows(as_of), symbol="NIFTY", spot=25000, as_of=as_of)
    out = choose_atm_overlay(
        sma_margin=-0.01,
        underlier_held=0.0,
        positions=[{"symbol": "NIFTY26SEP23350PE", "quantity": 65.0, "avg_price": 175.0}],
        bundle=bundle,
        cash=85_000.0,
        ce_ltp=120.0,
        pe_ltp=110.0,
        control_action="buy",
    )
    assert out["used"] is False
    assert out["reason"] == "legacy_non_atm_option"
    assert "NIFTY26SEP23350PE" in (out.get("legacy_positions") or [])


def test_phase2_underlying_is_nifty_only():
    assert is_phase2_underlying("NIFTY") is True
    assert is_phase2_underlying("BANKNIFTY") is False
    assert is_phase2_underlying("FINNIFTY") is False
    assert is_phase2_underlying("RELIANCE.NS") is False


def test_fno_p2_001_stamp_records_leftover_not_new_evidence(tmp_path):
    snap = {
        "cash": 85086.68,
        "equity": 96461.68,
        "positions": [
            {
                "symbol": "NIFTY26SEP23350PE",
                "quantity": 65.0,
                "avg_price": 175.0,
            }
        ],
    }
    first = stamp_phase2_experiment(tmp_path, snapshot=snap)
    assert first["ok"] is True
    assert first["already_stamped"] is False
    assert first["experiment_id"] == "FNO-P2-001"
    assert first["writing"] is False
    assert first["live_orders"] is False
    assert first["strategy_version"] == "sma_cross_rsi.v1"
    assert first["initial_position"][0]["symbol"] == "NIFTY26SEP23350PE"
    second = stamp_phase2_experiment(tmp_path, snapshot={"cash": 1, "positions": []})
    assert second["already_stamped"] is True
    assert second["initial_cash"] == 85086.68
    loaded = load_phase2_experiment(tmp_path)
    assert loaded["initial_position"][0]["qty"] == 65.0

