"""DAV densify — named news headlines + bar-derived regime tags."""

from __future__ import annotations

from atlas.investment.causal_attribution import evaluate_causal_factors
from atlas.investment.decision_timeline import what_changed
from atlas.investment.open_book_packs import (
    build_open_book_daily_pack,
    regime_tags_from_bars,
)


def test_named_news_in_open_book_pack():
    pack = build_open_book_daily_pack(
        symbol="CIPLA.NS",
        portfolio_key="india_equity_learner",
        session_day="2026-08-09",
        bars=[{"close": 100}, {"close": 101}],
        recent_news_rows=[
            {
                "id": "n1",
                "kind": "news_event",
                "payload": {
                    "text": "Cipla wins US FDA nod for inhaler",
                    "sentiment": "positive",
                    "topic_tags": ["pharma"],
                },
            }
        ],
    )
    assert pack["news"]["company"]
    assert "FDA" in pack["news"]["company"][0]["title"]
    assert "company" not in pack["news"]["unknowns"]
    assert pack["cited_observation_ids"] == ["n1"]


def test_regime_from_bars_bull_and_high_vol():
    # Strong up move → bull; large daily swings → high_vol
    bars = [
        {"close": 100},
        {"close": 103},
        {"close": 101},
        {"close": 106},
        {"close": 110},
        {"close": 108},
    ]
    tags = regime_tags_from_bars(bars, lookback=5)
    assert "bull" in tags
    pack = build_open_book_daily_pack(
        symbol="X.NS",
        portfolio_key="india_equity_learner",
        bars=[{"close": 50}, {"close": 51}],
        benchmark_bars=bars,
    )
    assert pack["market"]["regime_tags"]
    assert "regime_tags" not in pack["market"]["unknowns"]


def test_what_changed_named_news_and_regime_from_pack():
    packet = {"action": "buy", "prices": {"fill_price": 100.0}, "observation_ids": []}
    obs = [
        {
            "id": "pack-1",
            "kind": "market_event",
            "payload": {
                "kind": "open_book_daily_pack",
                "market": {
                    "rs_vs_nifty": 1.5,
                    "regime_tags": ["bull", "high_vol"],
                },
                "news": {
                    "company": [
                        {
                            "id": "n1",
                            "title": "Board approves buyback",
                            "sentiment": "positive",
                        }
                    ],
                    "observation_ids": ["n1"],
                },
            },
        }
    ]
    diff = what_changed(packet, current_mark=105.0, recent_observations=obs)
    assert diff["news_delta"]["titles"][0].startswith("Board")
    assert diff["news_delta"]["source"] == "open_book_pack_headlines"
    assert "bull" in (diff.get("regime_tags") or [])


def test_causal_includes_headline_and_regime():
    out = evaluate_causal_factors(
        {"feature_contributions": {"valuation": 5}, "fundamentals": {"pe": 20}},
        price_change_pct=4.0,
        news_titles=["Board approves buyback"],
        news_sentiment="positive",
        regime_tags=["bull"],
        thesis_correct="yes",
    )
    assert "news" in out["helped"]
    assert "Board" in (out.get("news_titles") or [""])[0]
    assert "bull" in (out.get("regime_tags") or [])
    news_f = next(f for f in out["factors"] if f["factor"] == "news")
    assert "Board" in news_f["evidence"]
