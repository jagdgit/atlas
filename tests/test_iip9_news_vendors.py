"""IIP.9 — RSS allow-list, Stooq adapter, TradingView chart links."""

from __future__ import annotations

import pytest

from atlas.decision.rules import CapabilityGap
from atlas.investment.chart_links import chart_links_for, tradingview_chart_url
from atlas.investment.government_policy import load_snapshot, refresh_catalog
from atlas.investment import rss_feeds as rss
from atlas.trading.adapters import StooqAdapter
from atlas.trading.market_reader import MarketReaderService


SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test Policy</title>
  <item>
    <title>Defence budget raised for indigenisation</title>
    <description>Higher capital outlay for domestic defence manufacturing.</description>
    <link>https://example.test/1</link>
    <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Renewable energy PLI extended</title>
    <description>Policy support for green hydrogen and solar manufacturing.</description>
    <link>https://example.test/2</link>
  </item>
</channel></rss>
"""


def test_parse_rss_and_refuse_html():
    items = rss.parse_feed_xml(SAMPLE_RSS, feed_id="demo", kind="policy")
    assert len(items) == 2
    assert "Defence" in items[0]["title"]
    assert items[0]["source"] == "rss:demo"

    with pytest.raises(ValueError, match="HTML"):
        rss.parse_feed_xml("<!DOCTYPE html><html><body>news</body></html>", feed_id="bad")


def test_fetch_allowlist_with_opener(tmp_path):
    feeds = [
        {
            "id": "demo_policy",
            "url": "https://example.test/feed.xml",
            "kind": "policy",
            "enabled": True,
            "max_items": 5,
        }
    ]
    result = rss.fetch_allowlist(feeds, opener=lambda _u: SAMPLE_RSS)
    assert result["ok_feeds"] == 1
    assert result["item_count"] == 2
    path = rss.save_last_fetch(tmp_path, result)
    assert path and path.is_file()
    loaded = rss.load_last_fetch(tmp_path)
    assert loaded["item_count"] == 2

    policy_items = rss.items_as_policy(result)
    snap = refresh_catalog(tmp_path, operator_items=policy_items, include_defaults=True)
    assert snap["item_count"] >= 2
    assert any("rss:" in str(i.get("source") or "") for i in snap["items"])
    assert load_snapshot(tmp_path).get("sector_deltas")


def test_stooq_symbol_and_csv_parse():
    assert StooqAdapter.to_stooq_symbol("INFY.NS") == "infy.in"
    assert StooqAdapter.to_stooq_symbol("AAPL") == "aapl.us"
    csv = (
        "Date,Open,High,Low,Close,Volume\n"
        "2024-01-02,100,105,99,102,1000\n"
        "2024-01-03,102,106,101,104,1100\n"
    )
    adapter = StooqAdapter(opener=lambda _u: csv)
    bars = adapter.fetch_bars("INFY.NS", limit=10)
    assert len(bars) == 2
    assert bars[-1]["close"] == 104.0

    empty = StooqAdapter(opener=lambda _u: "Date,Open,High,Low,Close,Volume\n")
    with pytest.raises(CapabilityGap):
        empty.fetch_bars("MISSING.NS")


def test_market_reader_lists_stooq():
    svc = MarketReaderService(yahoo_enabled=False)
    names = {p["name"] for p in svc.list_providers()}
    assert "stooq" in names
    assert "yahoo" in names


def test_tradingview_chart_links():
    url = tradingview_chart_url("INFY.NS")
    assert "NSE" in url and "INFY" in url
    links = chart_links_for("RELIANCE")
    assert "tradingview.com" in links["tradingview"]
    assert "finance.yahoo.com" in links["yahoo"]
    assert links["note"]
