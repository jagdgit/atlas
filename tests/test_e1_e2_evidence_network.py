"""E1 / E2 — Evidence Network densify (PIB RSS + open-books FCF cadence)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from atlas.investment import rss_feeds as rss
from atlas.investment import watchlists as wl
from atlas.investment.fundamentals import enrich_watchlist_gaps
from atlas.investment.symbol_aliases import news_is_evidence
from atlas.missions.programs import india_equity_learner_overrides
from atlas.workers.base import TickContext
from atlas.workers.fundamentals_enrich import (
    FundamentalsEnrichWorker,
    _in_universe_weekly_window,
)
from atlas.workers.government_intelligence import GovernmentIntelligenceWorker
from tests.test_laboratory_li2_providers import _fake_quote_summary


SAMPLE_PIB = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Press Information Bureau</title>
  <item>
    <title>Cabinet approves PLI for electronics</title>
    <description>Production Linked Incentive scheme extended.</description>
    <link>https://pib.gov.in/example</link>
  </item>
</channel></rss>
"""


def test_e1_learner_overrides_enable_pib_only():
    ov = india_equity_learner_overrides()
    news = ov["news_intelligence"]
    gov = ov["government_intelligence"]
    assert news.get("use_rss_allowlist") is True
    assert news.get("rss_enable") == ["pib_press"]
    assert gov.get("fetch_policy_rss") is True
    assert gov.get("rss_enable") == ["pib_press"]
    # SEBI/RBI must stay off unless explicitly listed
    assert "sebi_press" not in (news.get("rss_enable") or [])
    assert "rbi_press" not in (gov.get("rss_enable") or [])


def test_e1_news_worker_fetches_enabled_pib(tmp_path):
    def opener(url: str):
        assert "pib.gov.in" in url
        return SAMPLE_PIB

    feeds = rss.merge_allowlist(None, include_defaults=True)
    for row in feeds:
        row["enabled"] = row.get("id") == "pib_press"
    result = rss.fetch_allowlist(feeds, opener=opener)
    assert result["ok_feeds"] == 1
    items = rss.items_as_news(result)
    assert items
    assert news_is_evidence(items[0])
    assert str(items[0].get("source") or "").startswith("rss:")
    disabled = [f for f in (result.get("feeds") or []) if f.get("status") == "disabled"]
    assert any(f.get("id") == "sebi_press" for f in disabled)


def test_e1_gov_worker_ingests_pib_policy(tmp_path):
    worker = GovernmentIntelligenceWorker(data_dir=str(tmp_path))

    # Inject via policy_rss list with hermetic URL + opener not available on worker;
    # exercise fetch_allowlist path the worker uses.
    feeds = [
        {
            "id": "pib_press",
            "url": "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1",
            "kind": "policy",
            "enabled": True,
            "max_items": 5,
        }
    ]
    result = rss.fetch_allowlist(feeds, opener=lambda _u: SAMPLE_PIB, kinds=["policy"])
    policy = rss.items_as_policy(result)
    assert policy
    snap = worker.do_tick(
        TickContext(
            worker_id="gov-e1",
            mission_id="m-gov",
            config={
                "include_defaults": False,
                "items": policy,
            },
            config_version=1,
            state={},
        )
    )
    assert snap.state.get("item_count", 0) >= 1


def test_e2_open_books_only_skips_watchlist_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[
            {"symbol": "OPENFCF.NS"},
            {"symbol": "OTHERGAP.NS"},
        ],
        ranked=[
            {"symbol": "OPENFCF.NS", "rank": 1},
            {"symbol": "OTHERGAP.NS", "rank": 2},
        ],
    )
    seen: list[str] = []

    def opener(url: str):
        u = url.upper()
        for sym in ("OPENFCF", "OTHERGAP"):
            if sym in u:
                seen.append(f"{sym}.NS")
                break
        return _fake_quote_summary(pe=12.0, fcf=1e8)

    out = enrich_watchlist_gaps(
        tmp_path,
        program_id="market_intelligence",
        enabled=True,
        opener=opener,
        batch_size=5,
        priority_symbols=["OPENFCF.NS"],
        open_books_only=True,
    )
    assert out["ok"] is True
    assert out.get("open_books_only") is True
    assert out.get("mode") == "lq.7_open_books_only"
    assert "OPENFCF.NS" in (out.get("gap_symbols") or [])
    assert "OTHERGAP.NS" not in (out.get("gap_symbols") or [])
    assert seen == ["OPENFCF.NS"]


def test_e2_open_books_only_idle_without_holdings(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[{"symbol": "OTHERGAP.NS"}],
        ranked=[{"symbol": "OTHERGAP.NS", "rank": 1}],
    )
    out = enrich_watchlist_gaps(
        tmp_path,
        program_id="market_intelligence",
        enabled=True,
        opener=lambda _u: _fake_quote_summary(),
        priority_symbols=[],
        open_books_only=True,
    )
    assert out["reason"] == "no_open_books"
    assert out["fetched"] == 0


def test_e2_weekly_window_sunday_ist():
    sunday_morning = datetime(2026, 8, 9, 4, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    monday = datetime(2026, 8, 10, 4, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    cfg = {"universe_weekly": {"enabled": True, "ist_weekday": 6, "hour_start": 3, "hour_end": 5}}
    assert _in_universe_weekly_window(cfg, now=sunday_morning) is True
    assert _in_universe_weekly_window(cfg, now=monday) is False


def test_e2_worker_notes_open_books_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[{"symbol": "X.NS"}],
        ranked=[{"symbol": "X.NS", "rank": 1}],
    )
    # Avoid live Yahoo by disabling enrich path via empty priority + open_books_only
    worker = FundamentalsEnrichWorker(data_dir=str(tmp_path), yahoo_enabled=True)
    result = worker.do_tick(
        TickContext(
            worker_id="fe-e2",
            mission_id="m-fe",
            config={
                "program_id": "market_intelligence",
                "open_books_only": True,
                "prefer_open_books": True,
                "universe_weekly": {"enabled": False},
                "yahoo_enabled": True,
            },
            config_version=1,
            state={},
        )
    )
    assert "open_books_only" in (result.note or "")
