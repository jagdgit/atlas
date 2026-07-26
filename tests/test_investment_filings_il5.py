"""IL.5+ — hermetic / operator filing refs (no scrape)."""

from __future__ import annotations

from atlas.investment import watchlists as wl
from atlas.investment.filings import (
    clear,
    filings_for_symbol,
    hermetic_filings_for,
    nifty50_filings_seed,
    publish_snapshot,
)
from atlas.investment.screener_signals import clear as clear_screener
from atlas.trading.company import CompanyDataService


def setup_function() -> None:
    clear()
    wl.clear()
    clear_screener()


def teardown_function() -> None:
    clear()
    wl.clear()
    clear_screener()


def test_hermetic_filings_for_reliance():
    refs = hermetic_filings_for("RELIANCE.NS")
    assert len(refs) == 2
    kinds = {r["kind"] for r in refs}
    assert kinds == {"annual", "quarterly"}
    assert all(r["source"] == "hermetic_seed" for r in refs)


def test_nifty50_filings_seed_size():
    pack = nifty50_filings_seed()
    assert len(pack) == 50
    assert "TCS.NS" in pack


def test_operator_snapshot_wins_over_hermetic():
    publish_snapshot(
        {
            "INFY.NS": [
                {
                    "title": "Operator AR FY25",
                    "kind": "annual",
                    "as_of": "2025-03-31",
                    "url": "https://example.invalid/infy-ar.pdf",
                }
            ]
        },
        program_id="market_intelligence",
    )
    refs = filings_for_symbol("INFY.NS")
    assert len(refs) == 1
    assert refs[0]["title"] == "Operator AR FY25"
    assert refs[0]["source"] == "operator_snapshot"
    assert "example.invalid" in refs[0]["url"]


def test_m2_auto_seed_includes_filings():
    wl.publish(
        index="NIFTY50",
        watchlist=[
            {
                "symbol": "TCS.NS",
                "name": "TCS",
                "sector": "Information Technology",
            }
        ],
        ranked=[
            {
                "symbol": "TCS.NS",
                "name": "TCS",
                "sector": "Information Technology",
                "rank": 1,
            }
        ],
    )
    tickers, seeds, auto = wl.resolve_company_targets({})
    assert auto is True
    assert "TCS.NS" in tickers
    assert seeds[0]["filings"]
    assert any(f["kind"] == "annual" for f in seeds[0]["filings"])
    assert any("Filing ref" in f for f in seeds[0]["facts"])


def test_filings_seed_provider():
    svc = CompanyDataService()
    out = svc.fetch("RELIANCE.NS", provider="filings_seed")
    assert out["provider"] == "filings_seed"
    assert out["profile"]["filings"]
    text = out["knowledge_text"].lower()
    assert "annual" in text or "filing" in text
