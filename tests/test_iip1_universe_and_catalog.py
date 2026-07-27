"""IIP.1 universe manager + feed failure transparency."""

from __future__ import annotations

from atlas.investment.feed_failures import list_failures, record_failure
from atlas.investment.intelligence_catalog import catalog_skeleton
from atlas.investment.universe import (
    INDEX_NIFTY50,
    INDEX_NIFTY_MIDCAP150,
    INDEX_NIFTY_NEXT50,
    KNOWN_INDICES,
    membership,
)
from atlas.investment.universe_manager import (
    resolve_members,
    save_enabled,
    universes_view,
)


def test_known_indices_include_iip1_packs():
    assert INDEX_NIFTY_NEXT50 in KNOWN_INDICES
    assert INDEX_NIFTY_MIDCAP150 in KNOWN_INDICES
    assert len(membership(INDEX_NIFTY50)) == 50
    assert len(membership(INDEX_NIFTY_NEXT50)) >= 30
    assert len(membership(INDEX_NIFTY_MIDCAP150)) >= 40


def test_resolve_union_next50_midcap():
    r = resolve_members(universes=[INDEX_NIFTY50, INDEX_NIFTY_NEXT50, INDEX_NIFTY_MIDCAP150])
    assert r["count"] > 100
    assert INDEX_NIFTY50 in r["universes"]
    assert INDEX_NIFTY_MIDCAP150 in r["universes"]
    syms = {m["symbol"] for m in r["members"]}
    assert "RELIANCE.NS" in syms
    assert "TATAPOWER.NS" in syms  # midcap seed


def test_enabled_universes_durable(tmp_path):
    save_enabled(tmp_path, [INDEX_NIFTY50, INDEX_NIFTY_NEXT50])
    view = universes_view(tmp_path)
    assert INDEX_NIFTY50 in view["enabled"]
    assert INDEX_NIFTY_NEXT50 in view["enabled"]
    assert view["union_count"] >= 80
    nifty = next(u for u in view["universes"] if u["id"] == INDEX_NIFTY50)
    assert nifty["enabled"] is True


def test_feed_failures_record_and_list(tmp_path):
    record_failure(
        tmp_path,
        provider="yahoo",
        symbol="RELIANCE.NS",
        reason="empty_live_feed",
        source="test",
    )
    record_failure(
        tmp_path,
        provider="yahoo",
        symbol="TCS.NS",
        reason="HTTP 429 from Yahoo chart API",
        capability="market_data:yahoo",
        source="test",
    )
    out = list_failures(tmp_path, limit=10)
    assert out["count"] == 2
    assert out["items"][0]["symbol"] in {"RELIANCE.NS", "TCS.NS"}
    assert "empty_live_feed" in out["by_reason"] or any(
        "429" in k for k in out["by_reason"]
    )
    assert "help" in out


def test_intelligence_catalog_skeleton():
    cat = catalog_skeleton()
    assert cat["methodology"]["product"]
    assert any(s["id"] == "yahoo_finance" for s in cat["sources"])
    assert any(c["id"] == "universe_manager" for c in cat["capabilities"])
    assert cat["how_to_help"]
