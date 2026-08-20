"""OI-LINT0 Phase 3A — living events, source tiers, honest analogues."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from atlas.investment.market_events import (
    TIER_DISCOVERY,
    TIER_PRIMARY,
    analogue_distribution,
    classify_attribution,
    classify_relative_move,
    classify_source_tier,
    events_for_packet,
    living_lane,
    may_become_evidence,
    rsi_regime_analogues,
    stamp_market_event,
    usable_as_of,
)
from atlas.investment.market_timeline import build_symbol_timeline
from atlas.investment.rss_feeds import items_as_news, items_as_policy
from atlas.investment.symbol_aliases import news_is_evidence
from atlas.reasoning.research_scientist import build_research_packet


def test_pib_is_tier_one_and_stamped():
    ev = stamp_market_event(
        {
            "title": "Cabinet approves PLI",
            "source": "rss:pib_press",
            "feed_id": "pib_press",
            "link": "https://pib.gov.in/example",
            "published": "2026-08-18T06:00:00+00:00",
            "kind": "policy",
        }
    )
    assert ev["source_tier"] == TIER_PRIMARY
    assert ev["published_at"]
    assert ev["valid_from"]
    assert ev["observed_at"]
    assert ev["retrieved_at"]
    assert may_become_evidence(ev) is True


def test_aggregator_is_research_question_not_evidence():
    ev = stamp_market_event(
        {
            "title": "Forum rumor CIPLA",
            "source": "rss:random_blog",
            "link": "https://example.blog/post",
        }
    )
    assert ev["source_tier"] == TIER_DISCOVERY
    assert ev["evidence_class"] == "research_question"
    assert may_become_evidence(ev) is False
    assert news_is_evidence(ev) is False


def test_empty_and_catalog_stay_unknown():
    lane = living_lane([], lane="company_news")
    assert lane["status"] == "unknown"
    assert lane["items"] == []
    cat = stamp_market_event(
        {"title": "policy catalog items=12", "source": "government_intelligence"}
    )
    assert may_become_evidence(cat) is False
    stale_lane = living_lane([cat], lane="policy_events")
    assert stale_lane["status"] == "unknown"


def test_no_future_leakage_into_decision():
    ev = stamp_market_event(
        {
            "title": "After-hours filing",
            "source": "rss:pib_press",
            "feed_id": "pib_press",
            "published_at": "2026-08-19T10:00:00+00:00",
        }
    )
    as_of = datetime(2026, 8, 19, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
    assert usable_as_of(ev, as_of=as_of) is False


def test_attribution_does_not_assume_causality():
    assert classify_attribution(event_present=False) == "unknown"
    assert (
        classify_attribution(
            event_present=True,
            expected_sign=1,
            actual_sign=1,
            event_before_move=False,
        )
        == "unsupported"
    )
    assert (
        classify_attribution(
            event_present=True,
            expected_sign=1,
            actual_sign=1,
            relative="outperform",
            evidence_tier=TIER_PRIMARY,
            event_before_move=True,
        )
        == "likely"
    )


def test_relative_move_vs_nifty_not_slogan():
    assert classify_relative_move(name_ret_pct=1.2, nifty_ret_pct=1.1) == "inline"
    assert classify_relative_move(name_ret_pct=2.0, nifty_ret_pct=0.2) == "outperform"
    assert classify_relative_move(name_ret_pct=None, nifty_ret_pct=0.2) == "unknown"


def test_analogue_distribution_honest_when_thin():
    thin = analogue_distribution([1.0, 2.0])
    assert thin["status"] == "unknown"
    fat = analogue_distribution([1, 2, 3, 4, 5, 20, -3, 0.5])
    assert fat["status"] == "ok"
    assert fat["n"] == 8
    assert "median_pct" in fat


def test_rsi_analogues_unknown_on_short_series():
    out = rsi_regime_analogues([100.0, 101.0, 99.0])
    assert out["status"] == "unknown"


def test_rss_items_carry_tier_and_packet_unknowns():
    result = {
        "items": [
            {
                "text": "Cabinet approves PLI for electronics scheme",
                "title": "Cabinet approves PLI",
                "source": "rss:pib_press",
                "feed_id": "pib_press",
                "link": "https://pib.gov.in/x",
                "kind": "policy",
                "published": "Tue, 18 Aug 2026 06:00:00 GMT",
            }
        ]
    }
    news = items_as_news(result)
    policy = items_as_policy(result)
    assert news[0]["source_tier"] == TIER_PRIMARY
    assert policy[0]["source_tier"] == TIER_PRIMARY
    pkt = events_for_packet(news=news, policy=policy)
    assert pkt["news"] != "unknown"
    assert pkt["policy"] != "unknown"
    empty = events_for_packet(news=[], policy=[])
    assert empty["news"] == "unknown"
    rp = build_research_packet(
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action="buy",
        events={"news": [], "policy": []},
    )
    assert rp["events"]["news"] == "unknown"
    assert rp["events"]["news_freshness"] == "unknown"


def test_timeline_news_unknown_without_evidence():
    row = build_symbol_timeline(
        symbol="CIPLA.NS",
        as_of_ist="2026-08-19",
        bars=[{"close": 1400.0, "date": "2026-08-19"}],
        news={"company": [], "gov": [], "unknowns": ["company"]},
    )
    assert "news" in row["unknowns"]
    assert row["lanes"]["news"]["status"] == "unknown"


def test_stale_headline_is_stale_not_invented():
    old = datetime.now(timezone.utc) - timedelta(days=40)
    lane = living_lane(
        [
            {
                "title": "Old PIB note",
                "source": "rss:pib_press",
                "feed_id": "pib_press",
                "published_at": old.isoformat(),
            }
        ],
        as_of=datetime.now(timezone.utc),
        max_age_days=14,
        lane="policy_events",
    )
    assert lane["status"] == "stale"
    assert lane["freshness"] == "stale"
    assert lane["count"] == 1
