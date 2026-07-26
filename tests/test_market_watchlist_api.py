"""Market watchlist API for Learner dashboard."""

from __future__ import annotations

from atlas.investment import watchlists as wl
from atlas.api.routes import market_watchlist


def setup_function() -> None:
    wl.clear()


def teardown_function() -> None:
    wl.clear()


def test_market_watchlist_empty():
    out = market_watchlist()
    assert out["count"] == 0
    assert "No watchlist" in (out.get("note") or "")


def test_market_watchlist_ranked():
    wl.publish(
        index="NIFTY50",
        watchlist=[{"symbol": "TCS.NS", "name": "TCS"}],
        ranked=[
            {"symbol": "TCS.NS", "name": "TCS", "rank": 1, "reason": "quality+"},
            {"symbol": "INFY.NS", "name": "Infosys", "rank": 2},
        ],
    )
    out = market_watchlist(limit=1)
    assert out["count"] == 2
    assert out["index"] == "NIFTY50"
    assert len(out["ranked"]) == 1
    assert out["ranked"][0]["symbol"] == "TCS.NS"
