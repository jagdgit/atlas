"""Data-plane provider contract + observable symbol evidence view."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.bar_store import persist_symbol_bars
from atlas.investment.data_plane_contract import (
    build_symbol_evidence_view,
    data_provider_contract,
    format_symbol_evidence_view,
)
from atlas.investment.fundamentals import upsert_rows


def test_provider_contract_zerodha_never_supplies_pe():
    c = data_provider_contract()
    assert c["kind"] == "DATA_PROVIDER_CONTRACT"
    by = {r["field"]: r for r in c["rows"]}
    assert by["ltp"]["zerodha_role"] == "primary_live"
    assert by["pe"]["zerodha_role"] == "never"
    assert by["fcf"]["zerodha_role"] == "never"
    assert by["mos"]["zerodha_role"] == "never"
    assert "screener_export" in by["pe"]["providers"]
    assert by["mos"]["providers"] == ("ira_valuation",)


def test_welcorp_evidence_view_stops_at_pe(tmp_path: Path):
    upsert_rows(
        tmp_path,
        [
            {
                "symbol": "WELCORP.NS",
                "roe": 11.0,
                "debt_to_equity": 0.7,
                "sector": "Steel pipes",
                "source": "universe_seed",
            }
        ],
        program_id="market_intelligence",
        merge_screener=False,
    )
    persist_symbol_bars(
        tmp_path,
        "WELCORP.NS",
        [
            {
                "date": "2026-09-02",
                "open": 2500,
                "high": 2550,
                "low": 2480,
                "close": 2523.5,
                "volume": 1,
            }
        ],
        provider="test",
    )
    view = build_symbol_evidence_view(
        tmp_path,
        "WELCORP.NS",
        laboratory_id="india_equity_learner",
        technical="BUY",
    )
    assert view["market"]["price"]["status"] == "available"
    assert view["fundamentals"]["roe"]["status"] == "available"
    assert view["fundamentals"]["pe"]["status"] == "missing"
    assert view["fundamentals"]["fcf"]["status"] == "missing"
    assert view["valuation"]["mos"]["status"] == "missing"
    assert view["chain_stops_at"] == "pe"
    assert view["authorization_candidate"] is False
    text = format_symbol_evidence_view(view)
    assert "chain_stops_at: pe" in text


def test_evidence_view_stops_at_mos_when_pe_fcf_present(tmp_path: Path):
    upsert_rows(
        tmp_path,
        [
            {
                "symbol": "WELCORP.NS",
                "pe": 18.4,
                "fcf": 1.2e9,
                "roe": 11.0,
                "debt_to_equity": 0.7,
                "source": "yahoo_fundamentals",
            }
        ],
        program_id="market_intelligence",
        merge_screener=False,
    )
    persist_symbol_bars(
        tmp_path,
        "WELCORP.NS",
        [{"date": "2026-09-02", "open": 1, "high": 1, "low": 1, "close": 2523.5, "volume": 1}],
        provider="test",
    )
    view = build_symbol_evidence_view(
        tmp_path,
        "WELCORP.NS",
        laboratory_id="india_equity_learner",
        technical="BUY",
    )
    assert view["fundamentals"]["pe"]["status"] == "available"
    assert view["fundamentals"]["fcf"]["status"] == "available"
    assert view["chain_stops_at"] == "mos"
