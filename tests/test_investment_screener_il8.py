"""IL.8 — screener-class signals (hermetic; no scrape)."""

from __future__ import annotations

from atlas.investment.ranking import rank_universe
from atlas.investment.screener_signals import (
    clear,
    compute_from_bars_quality,
    merge_into_quality,
    publish_snapshot,
    signals_view,
)
from atlas.investment.watchlists import clear as clear_wl
from atlas.investment.watchlists import publish, resolve_company_targets
from atlas.workers.base import TickContext
from atlas.workers.investment_universe import InvestmentUniverseWorker


def test_publish_and_view_snapshot():
    clear()
    snap = publish_snapshot(
        {"INFY.NS": {"pe": 22, "roe": 0.28, "promoter_holding": 0.74, "score": 0.9}},
        program_id="market_intelligence",
        as_of="2026-07-26",
    )
    assert snap["count"] == 1
    view = signals_view()
    assert "INFY.NS" in view["symbols"]
    assert view["symbols"]["INFY.NS"]["pe"] == 22


def test_operator_snapshot_shifts_rank():
    clear()
    pool = [
        {"symbol": "A.NS", "name": "A", "sector": "IT"},
        {"symbol": "B.NS", "name": "B", "sector": "IT"},
    ]
    quality = {
        "A.NS": {"roe": 0.15, "debt_to_equity": 0.5},
        "B.NS": {"roe": 0.15, "debt_to_equity": 0.5},
    }
    publish_snapshot(
        {
            "A.NS": {"screener_score": 0.95, "pe": 12},
            "B.NS": {"screener_score": 0.1, "pe": 45},
        }
    )
    merged, meta = merge_into_quality(quality, use_computed=False)
    assert meta["operator_count"] == 2
    ranked = rank_universe(pool, quality_by_symbol=merged, max_watchlist=2)
    assert ranked[0]["symbol"] == "A.NS"
    assert any("screener" in (e.get("text") or "").lower() or "quality" in (e.get("text") or "").lower()
               for e in (ranked[0].get("explanations") or []))


def test_computed_from_bars_is_deterministic():
    bars = {
        "X.NS": [
            {"close": 100 + i, "volume": 100}
            for i in range(10)
        ]
        + [{"close": 120, "volume": 500} for _ in range(5)],
    }
    rows = compute_from_bars_quality(bars_by_symbol=bars)
    assert "X.NS" in rows
    assert rows["X.NS"]["signals"]["rel_volume"] > 1.0
    assert 0 <= rows["X.NS"]["score"] <= 1


def test_disable_screener_keeps_il5_path():
    clear()
    publish_snapshot({"Z.NS": {"screener_score": 0.99}})
    worker = InvestmentUniverseWorker()
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m0",
            config={
                "index": "NIFTY50",
                "max_watchlist": 5,
                "use_screener_signals": False,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state.get("screener_merged") == 0


def test_m0_merges_operator_screener():
    clear()
    publish_snapshot(
        {
            "RELIANCE.NS": {"pe": 20, "screener_score": 0.88},
            "TCS.NS": {"pe": 30, "screener_score": 0.4},
        }
    )
    worker = InvestmentUniverseWorker()
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m0",
            config={"index": "NIFTY50", "max_watchlist": 10, "use_screener_signals": True},
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state.get("screener_merged", 0) >= 2
    assert "screener=" in (result.note or "")


def test_company_seed_includes_screener_fact():
    clear()
    clear_wl()
    publish_snapshot({"TCS.NS": {"pe": 28, "promoter_holding": 0.72, "score": 0.7}})
    publish(
        index="NIFTY50",
        watchlist=[{"symbol": "TCS.NS", "name": "TCS", "sector": "Information Technology"}],
        ranked=[{"symbol": "TCS.NS", "name": "TCS", "sector": "Information Technology", "rank": 1}],
    )
    _, seeds, auto = resolve_company_targets({})
    assert auto
    assert seeds[0]["ratios"].get("pe") == 28
    assert any("Screener" in f for f in seeds[0]["facts"])
