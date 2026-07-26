"""IL.4 — M1/M2/M3 follow ranked Investment Universe watchlist."""

from __future__ import annotations

from atlas.investment.watchlists import (
    clear,
    publish,
    resolve_company_targets,
    resolve_instruments,
    resolve_news_items,
    resolve_symbols,
)
from atlas.trading.company import CompanyDataService
from atlas.trading.market_reader import MarketReaderService
from atlas.workers.base import TickContext
from atlas.workers.company_intelligence import CompanyIntelligenceWorker
from atlas.workers.market_observer import MarketObserverWorker
from atlas.workers.news_intelligence import NewsIntelligenceWorker


def _publish_demo() -> None:
    clear()
    publish(
        program_id="market_intelligence",
        index="NIFTY50",
        watchlist=[
            {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "sector": "Oil Gas & Fuels"},
            {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "sector": "Information Technology"},
        ],
        ranked=[
            {
                "symbol": "RELIANCE.NS",
                "name": "Reliance Industries",
                "sector": "Oil Gas & Fuels",
                "rank": 1,
                "score": 0.9,
                "reason": "+ Strong momentum",
            },
            {
                "symbol": "TCS.NS",
                "name": "Tata Consultancy Services",
                "sector": "Information Technology",
                "rank": 2,
                "score": 0.8,
                "reason": "+ High liquidity",
            },
        ],
    )


def test_resolve_symbols_operator_pin_wins():
    clear()
    _publish_demo()
    syms, auto = resolve_symbols({"symbols": ["INFY.NS"]})
    assert syms == ["INFY.NS"]
    assert auto is False


def test_resolve_symbols_falls_back_to_watchlist():
    _publish_demo()
    syms, auto = resolve_symbols({"program_id": "market_intelligence"}, max_n=1)
    assert syms == ["RELIANCE.NS"]
    assert auto is True


def test_resolve_instruments_and_company_and_news():
    _publish_demo()
    inst, auto_i = resolve_instruments({})
    assert auto_i and inst[0]["symbol"] == "RELIANCE.NS"

    tickers, seeds, auto_c = resolve_company_targets({})
    assert auto_c and tickers[0] == "RELIANCE.NS"
    assert seeds[0]["name"] == "Reliance Industries"
    assert "NIFTY50" in seeds[0]["facts"][0]

    items, auto_n = resolve_news_items({})
    assert auto_n and items[0]["symbol"] == "RELIANCE.NS"
    assert items[0]["source"] == "watchlist_seed"


def test_market_observer_auto_loads_watchlist():
    _publish_demo()

    class _Reader:
        def bars_for(self, symbol, **kwargs):
            return {
                "provider": "fake",
                "symbol": symbol,
                "bars": [{"close": 100}, {"close": 101}],
                "count": 2,
                "pct_move": 1.0,
            }

    worker = MarketObserverWorker(market_reader=_Reader())
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"symbols": [], "instruments": []},
            config_version=1,
            state={},
        )
    )
    assert result.state.get("auto_watchlist") is True
    assert "RELIANCE.NS" in (result.state.get("auto_symbols") or [])
    assert "auto watchlist" in result.note
    assert "idle" not in result.note


def test_market_observer_still_idle_without_watchlist():
    clear()
    worker = MarketObserverWorker(market_reader=MarketReaderService())
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={},
            config_version=1,
            state={},
        )
    )
    assert "idle" in result.note


def test_company_intelligence_auto_emits_from_watchlist():
    _publish_demo()
    emitted: list[dict] = []

    class _Candidates:
        def emit(self, payload):
            emitted.append(payload)
            return {"id": str(len(emitted))}

        def consume_pending(self, *, limit=100):
            return []

    worker = CompanyIntelligenceWorker(
        company_data=CompanyDataService(),
        candidates=_Candidates(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"tickers": [], "companies": []},
            config_version=1,
            state={},
        )
    )
    assert result.state.get("auto_watchlist") is True
    assert result.state.get("last_ok", 0) >= 1
    assert result.state.get("last_emitted", 0) >= 1
    assert any("RELIANCE" in str(p.get("statement") or "") or
               (p.get("value") or {}).get("symbol") == "RELIANCE.NS"
               for p in emitted)
    assert "auto watchlist" in result.note


def test_news_intelligence_auto_seeds_from_watchlist():
    _publish_demo()
    emitted: list[dict] = []

    class _Candidates:
        def emit(self, payload):
            emitted.append(payload)
            return {"id": str(len(emitted))}

        def consume_pending(self, *, limit=100):
            return []

    worker = NewsIntelligenceWorker(candidates=_Candidates())
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"headlines": [], "items": []},
            config_version=1,
            state={},
        )
    )
    assert result.state.get("auto_watchlist") is True
    assert "RELIANCE.NS" in (result.state.get("auto_symbols") or [])
    assert "auto watchlist" in result.note
    assert emitted  # extractor + watchlist seed text


def test_news_pin_headlines_skips_auto():
    _publish_demo()
    items, auto = resolve_news_items({"headlines": ["Reliance reports strong refining margins this quarter."]})
    assert auto is False
    assert items[0]["source"] == "headline"
