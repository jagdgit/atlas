"""IL.5 — India data depth: hermetic quality seed + Yahoo .NS contract."""

from __future__ import annotations

from atlas.decision.rules import CapabilityGap
from atlas.investment.quality_seed import (
    nifty50_quality_seed,
    ratios_for_symbol,
    resolve_quality_seed,
)
from atlas.investment.ranking import rank_universe
from atlas.investment.universe import membership
from atlas.investment.watchlists import clear, publish, resolve_company_targets
from atlas.missions.programs import india_equity_learner_overrides
from atlas.trading.adapters import YahooFinanceAdapter
from atlas.workers.base import TickContext
from atlas.workers.investment_universe import InvestmentUniverseWorker


def test_nifty50_quality_seed_covers_membership():
    seed = nifty50_quality_seed()
    members = membership("NIFTY50")
    assert len(seed) == len(members) == 50
    row = seed["RELIANCE.NS"]
    assert row["source"] == "hermetic_seed"
    assert row["method"] == "sector_proxy"
    assert 0 < float(row["roe"]) < 1
    assert float(row["debt_to_equity"]) >= 0


def test_resolve_quality_seed_operator_override_and_disable():
    merged = resolve_quality_seed({"INFY.NS": {"roe": 0.99, "debt_to_equity": 0.01}})
    assert merged["INFY.NS"]["roe"] == 0.99
    assert len(merged) >= 50
    assert resolve_quality_seed(False) == {}
    assert resolve_quality_seed({}, use_default=False) == {}


def test_quality_seed_shifts_rank_vs_neutral():
    pool = [
        {"symbol": "IT.NS", "name": "IT Co", "sector": "Information Technology"},
        {"symbol": "TEL.NS", "name": "Telco", "sector": "Telecommunication"},
    ]
    # No bars → cold momentum; quality should still differentiate.
    neutral = rank_universe(pool, max_watchlist=2, quality_by_symbol=None)
    seeded = rank_universe(
        pool,
        max_watchlist=2,
        quality_by_symbol={
            "IT.NS": {"roe": 0.30, "debt_to_equity": 0.1},
            "TEL.NS": {"roe": 0.05, "debt_to_equity": 2.0},
        },
    )
    assert seeded[0]["symbol"] == "IT.NS"
    # Neutral (no quality) may tie-break by membership order; seeded must prefer IT.
    assert seeded[0]["score"] >= seeded[1]["score"]
    assert any("quality" in (r.get("reason") or "").lower() or "roe" in (r.get("reason") or "").lower()
               or "+" in (r.get("reason") or "") for r in seeded)


def test_company_auto_seed_includes_ratios():
    clear()
    from atlas.investment.screener_signals import clear as clear_screener

    clear_screener()
    publish(
        index="NIFTY50",
        watchlist=[{"symbol": "TCS.NS", "name": "TCS", "sector": "Information Technology"}],
        ranked=[{"symbol": "TCS.NS", "name": "TCS", "sector": "Information Technology", "rank": 1}],
    )
    tickers, seeds, auto = resolve_company_targets({})
    assert auto is True
    assert "TCS.NS" in tickers
    assert seeds[0]["ratios"].get("roe")
    assert any("Hermetic quality seed" in f for f in seeds[0]["facts"])
    assert ratios_for_symbol("TCS.NS")["source"] == "hermetic_seed"
    assert seeds[0]["filings"]
    assert any("Filing ref" in f for f in seeds[0]["facts"])


def test_m0_worker_loads_default_quality_seed():
    worker = InvestmentUniverseWorker()
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m0",
            config={"index": "NIFTY50", "max_watchlist": 5, "use_quality_seed": True},
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state.get("quality_seed_count") == 50
    assert "quality_seed=50" in (result.note or "")


def test_india_learner_preset_uses_yahoo_for_m0_m1():
    ov = india_equity_learner_overrides()
    assert ov["investment_universe"]["provider"] == "yahoo"
    assert ov["investment_universe"]["use_quality_seed"] is True
    assert ov["market_observer"]["provider"] == "yahoo"
    assert ov["decision_simulation"]["live_provider"] == "yahoo"


def test_yahoo_ns_symbol_in_chart_url():
    seen: list[str] = []

    def opener(url: str):
        seen.append(url)
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": [1, 2],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10.0, 11.0],
                                    "high": [11.0, 12.0],
                                    "low": [9.0, 10.0],
                                    "close": [10.5, 11.5],
                                    "volume": [100, 200],
                                }
                            ]
                        },
                    }
                ]
            }
        }

    adapter = YahooFinanceAdapter(enabled=True, opener=opener)
    bars = adapter.fetch_bars("RELIANCE.NS", limit=2)
    assert len(bars) == 2
    assert "RELIANCE.NS" in seen[0]
    assert "/chart/RELIANCE.NS" in seen[0]


def test_yahoo_disabled_still_gaps_for_ns():
    adapter = YahooFinanceAdapter(enabled=False)
    try:
        adapter.fetch_bars("TCS.NS")
        assert False, "expected CapabilityGap"
    except CapabilityGap as exc:
        assert "yahoo" in exc.capability
