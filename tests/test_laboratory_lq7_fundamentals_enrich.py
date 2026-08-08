"""LQ.7 — scheduled Tier C enrich on watchlist gaps (hermetic)."""

from __future__ import annotations

from atlas.investment import watchlists as wl
from atlas.investment.fundamentals import (
    enrich_watchlist_gaps,
    get_symbol,
    import_csv_text,
)
from atlas.workers.base import TickContext
from atlas.workers.fundamentals_enrich import FundamentalsEnrichWorker
from tests.test_laboratory_li2_providers import _fake_quote_summary


def test_enrich_watchlist_gaps_fetches_holes(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[
            {"symbol": "GAPCO.NS"},
            {"symbol": "FULLCO.NS"},
        ],
        ranked=[
            {"symbol": "GAPCO.NS", "rank": 1},
            {"symbol": "FULLCO.NS", "rank": 2},
        ],
    )
    import_csv_text(
        tmp_path,
        "symbol,pe,fcf,roe,debt_to_equity\nFULLCO,20,1e9,0.2,30\n",
        source="screener_export",
        note="covered",
    )

    def opener(url: str):
        assert "GAPCO" in url.upper() or "gapco" in url.lower()
        return _fake_quote_summary(pe=18.0, fcf=2e8)

    out = enrich_watchlist_gaps(
        tmp_path,
        program_id="market_intelligence",
        enabled=True,
        opener=opener,
        limit=40,
    )
    assert out["ok"] is True
    assert out.get("mode") == "lq.7_watchlist_gaps"
    assert "GAPCO.NS" in (out.get("gap_symbols") or [])
    assert out["fetched"] >= 1
    row = get_symbol(tmp_path, "GAPCO.NS")
    assert row is not None
    assert row.get("pe") == 18.0
    assert row["evidence"]["pe"][0]["confidence"] == "medium"


def test_enrich_watchlist_gaps_disabled_no_write(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[{"symbol": "NEEDY.NS"}],
        ranked=[{"symbol": "NEEDY.NS", "rank": 1}],
    )
    out = enrich_watchlist_gaps(
        tmp_path,
        program_id="market_intelligence",
        enabled=False,
    )
    assert out["ok"] is False
    assert out["reason"] == "yahoo_disabled"
    assert out["fetched"] == 0
    assert get_symbol(tmp_path, "NEEDY.NS") is None


def test_enrich_watchlist_gaps_no_gaps(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[{"symbol": "FULLCO.NS"}],
        ranked=[{"symbol": "FULLCO.NS", "rank": 1}],
    )
    import_csv_text(
        tmp_path,
        "symbol,pe,fcf,roe,debt_to_equity\nFULLCO,20,1e9,0.2,30\n",
        source="screener_export",
    )
    out = enrich_watchlist_gaps(
        tmp_path,
        program_id="market_intelligence",
        enabled=True,
        opener=lambda _u: _fake_quote_summary(),
    )
    assert out["reason"] == "no_gaps"
    assert out["fetched"] == 0


def test_fundamentals_enrich_worker_tick(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[{"symbol": "W1.NS"}],
        ranked=[{"symbol": "W1.NS", "rank": 1}],
    )
    worker = FundamentalsEnrichWorker(data_dir=str(tmp_path), yahoo_enabled=False)
    result = worker.do_tick(
        TickContext(
            worker_id="fe-1",
            mission_id="m-fe",
            config={"program_id": "market_intelligence", "max_symbols": 10},
            config_version=1,
            state={},
        )
    )
    assert "yahoo_disabled" in result.note or "LQ.7" in result.note
    assert result.state.get("last_enrich", {}).get("reason") == "yahoo_disabled"
