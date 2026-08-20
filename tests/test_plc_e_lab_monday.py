"""PLC.E — F&O / intraday lab pack alignment."""

from __future__ import annotations

from atlas.investment import portfolios as vp


def test_default_decision_config_fno_seeds_instruments(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    with vp._LOCK:  # noqa: SLF001
        vp._STORE.clear()  # noqa: SLF001
        vp._LOADED = False  # noqa: SLF001
    row = {
        "portfolio_key": "india_fno_learner",
        "label": "F&O",
        "asset_class": "futures",
        "instrument_pack": "futures",
        "persona": {
            "capital": 100000,
            "allowed_assets": ["futures"],
            "objective": "Learning",
            "risk": "very_high",
            "time_horizon": "intraday",
            "strategy": {},
            "currency": "INR",
        },
    }
    cfg = vp.default_decision_config(row)
    assert cfg["market_session"] == "nse_fno"
    assert cfg["auto_max_instruments"] == 0
    assert cfg["instruments"]
    assert cfg["instruments"][0]["symbol"] == "NIFTY"
    assert cfg["instrument_pack"] == "futures"
    assert any(i.get("symbol") == "BANKNIFTY" for i in cfg["instruments"])


def test_create_book_aligns_fno_allowed_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    # reset in-memory store
    with vp._LOCK:  # noqa: SLF001
        vp._STORE.clear()  # noqa: SLF001
        vp._LOADED = False  # noqa: SLF001
    row = vp.create_book(
        label="India F&O Lab",
        portfolio_key="india_fno_learner",
        capital=100000,
        asset_class="futures",
        instantiate=False,
    )
    assert row["asset_class"] == "futures"
    assert row["persona"]["allowed_assets"] == ["futures"]
    assert row["persona"].get("mentor") == "margin_lot_expiry"
    assert row.get("personality_kind") == "futures"


def test_create_book_intraday_personality(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    with vp._LOCK:  # noqa: SLF001
        vp._STORE.clear()  # noqa: SLF001
        vp._LOADED = False  # noqa: SLF001
    row = vp.create_book(
        label="India Intraday Lab",
        portfolio_key="equity_intraday_learner",
        capital=50000,
        asset_class="cash_equity",
        instantiate=False,
    )
    assert row["persona"].get("mentor") == "session_risk"
    assert row["persona"].get("holding_philosophy") == "flat_eod"


def test_paper_trading_schema_accepts_fno_plc_e_fields():
    from atlas.configuration.schemas import default_registry

    registry = default_registry()
    doc = {
        "instruments": [
            {
                "symbol": "NIFTY",
                "asset_class": "futures",
                "lot_size": 25,
                "note": "seed",
            }
        ],
        "auto_max_instruments": 0,
        "market_session": "nse_fno",
        "asset_class": "futures",
        "instrument_pack": "futures",
        "persona": {
            "capital": 100000,
            "allowed_assets": ["futures"],
            "mentor": "margin_lot_expiry",
            "holding_philosophy": "contract_lifecycle",
        },
    }
    normalized, _sv = registry.validate("paper_trading", doc)
    assert normalized["auto_max_instruments"] == 0
    assert normalized["instruments"][0]["lot_size"] == 25
    assert normalized["persona"]["mentor"] == "margin_lot_expiry"


def test_fno_auto_max_zero_seeds_via_enrich(tmp_path, monkeypatch):
    """Empty F&O instruments + auto_max=0 → enrich seeds demo contracts (no idle forever)."""
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    with vp._LOCK:  # noqa: SLF001
        vp._STORE.clear()  # noqa: SLF001
        vp._LOADED = False  # noqa: SLF001

    book = vp.create_book(
        label="India F&O Lab",
        portfolio_key="india_fno_learner",
        capital=100000,
        asset_class="futures",
        instantiate=False,
    )
    cfg = vp.enrich_decision_config_from_book(
        {
            "instruments": [],
            "auto_max_instruments": 0,
            "asset_class": "futures",
            "instrument_pack": "futures",
            "portfolio_key": "india_fno_learner",
            "persona": {"allowed_assets": ["futures"], "capital": 100000},
        },
        book,
    )
    assert cfg["instruments"], "must seed demo F&O contracts instead of idling"
    assert cfg["auto_max_instruments"] == 0
    assert all(i.get("asset_class") == "futures" for i in cfg["instruments"])
    # Still must not fall back to cash auto-universe
    assert not any(str(i.get("symbol") or "").endswith(".NS") for i in cfg["instruments"])


def test_repair_intraday_persona_character(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    with vp._LOCK:  # noqa: SLF001
        vp._STORE.clear()  # noqa: SLF001
        vp._LOADED = False  # noqa: SLF001
    vp.register(
        label="India Intraday Lab",
        portfolio_key="equity_intraday_learner",
        persona={
            "capital": 50000,
            "allowed_assets": ["cash_equity"],
            "risk": "medium",
            "time_horizon": "medium",
            "mentor": "session_risk",
            "holding_philosophy": "flat_eod",
        },
        asset_class="cash_equity",
    )
    out = vp.repair_laboratory_pack_alignment("equity_intraday_learner")
    assert out is not None
    person = (out.get("portfolio") or {}).get("persona") or {}
    assert person.get("risk") == "high"
    assert person.get("time_horizon") == "intraday"
    assert person.get("mentor") == "session_risk"
