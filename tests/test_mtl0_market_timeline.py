"""OI-MTL0 — open-book market timeline hermetic tests."""

from __future__ import annotations

from atlas.investment.bar_store import persist_symbol_bars
from atlas.investment.market_timeline import (
    build_open_book_timelines,
    build_symbol_timeline,
    format_market_timeline_evening_lines,
    load_timeline_day,
)
from atlas.investment.reports import format_learned_today_section


def test_build_symbol_timeline_lanes_and_unknowns():
    bars = [{"date": f"2026-07-{d:02d}", "close": 100.0 + d} for d in range(1, 28)]
    bars += [{"date": f"2026-08-{d:02d}", "close": 130.0 + d} for d in range(1, 10)]
    doc = build_symbol_timeline(
        symbol="CIPLA.NS",
        as_of_ist="2026-08-09",
        bars=bars,
        fundamentals={"pe": 36.1, "roe": 10.4},  # fcf missing
        decisions=[
            {
                "action": "hold",
                "strategy_tag": "switch_blocked_cold_start",
                "decision_id": "d1",
            }
        ],
    )
    assert doc["symbol"] == "CIPLA.NS"
    assert doc["lanes"]["price"]["status"] == "ok"
    assert doc["lanes"]["technical"]["rsi14"] is not None
    assert doc["lanes"]["fundamentals"]["pe"] == 36.1
    assert "fcf" in (doc["lanes"]["fundamentals"].get("missing") or [])
    assert "news" in doc["unknowns"]
    assert doc["revisit_questions"]


def test_persist_and_evening_lines(tmp_path):
    # Durable bars for two names
    bars = [{"date": f"2026-08-{(i % 28) + 1:02d}", "close": 50.0 + i} for i in range(45)]
    # Fix dates to be contiguous ending Aug 9
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    bars = [
        {
            "date": (now - timedelta(days=44 - i)).date().isoformat(),
            "close": 50.0 + i,
        }
        for i in range(45)
    ]
    persist_symbol_bars(tmp_path, "CIPLA.NS", bars, provider="yahoo")
    persist_symbol_bars(tmp_path, "EICHERMOT.NS", bars, provider="yahoo")
    # NIFTY + pharma/auto sector benches for densify
    nifty = [
        {
            "date": (now - timedelta(days=44 - i)).date().isoformat(),
            "close": 24000.0 + i,
        }
        for i in range(45)
    ]
    pharma = [
        {
            "date": (now - timedelta(days=44 - i)).date().isoformat(),
            "close": 18000.0 + 0.5 * i,
        }
        for i in range(45)
    ]
    auto = [
        {
            "date": (now - timedelta(days=44 - i)).date().isoformat(),
            "close": 20000.0 + 0.8 * i,
        }
        for i in range(45)
    ]
    persist_symbol_bars(tmp_path, "^NSEI", nifty, provider="yahoo")
    persist_symbol_bars(tmp_path, "^CNXPHARMA", pharma, provider="yahoo")
    persist_symbol_bars(tmp_path, "^CNXAUTO", auto, provider="yahoo")

    # Fundamentals via real store path (investment/fundamentals/…)
    from atlas.investment.fundamentals import save_store

    save_store(
        tmp_path,
        {
            "symbols": {
                "CIPLA.NS": {"pe": 36.1, "roe": 10.4, "sector": "Healthcare"},
                "EICHERMOT.NS": {
                    "pe": 41.7,
                    "roe": 25.2,
                    "sector": "Automobile",
                },
            },
        },
        program_id="market_intelligence",
    )

    # Fake observation store with a named headline for CIPLA
    class _Obs:
        def list_symbol(self, *, symbol, limit=25):
            if "CIPLA" in str(symbol).upper():
                return [
                    {
                        "id": "n1",
                        "kind": "news",
                        "payload": {
                            "title": "Cipla gets USFDA nod for inhaler",
                            "topic_tags": ["company"],
                        },
                    }
                ]
            return []

        def list_since(self, *, since_hours=72.0, limit=30):
            return [
                {
                    "id": "g1",
                    "kind": "policy_event",
                    "payload": {
                        "title": "RBI keeps rates unchanged",
                        "topic_tags": ["policy", "rbi"],
                    },
                }
            ]

    doc = build_open_book_timelines(
        tmp_path,
        ["CIPLA.NS", "EICHERMOT.NS"],
        laboratory_id="india_equity_learner",
        persist=True,
        observations=_Obs(),
    )
    assert doc["ok"] is True
    assert doc["count"] == 2
    assert doc.get("nifty_last") is not None
    by_sym = {r["symbol"]: r for r in doc["rows"]}
    assert by_sym["CIPLA.NS"]["lanes"]["sector"]["benchmark"] == "^CNXPHARMA"
    assert by_sym["CIPLA.NS"]["lanes"]["sector"]["rs_vs_benchmark_pct"] is not None
    assert by_sym["EICHERMOT.NS"]["lanes"]["sector"]["benchmark"] == "^CNXAUTO"
    assert by_sym["CIPLA.NS"]["lanes"]["news"]["status"] == "ok"
    assert by_sym["CIPLA.NS"]["lanes"]["market"]["status"] == "ok"
    loaded = load_timeline_day(tmp_path, laboratory_id="india_equity_learner")
    assert loaded["ok"] is True
    assert len(loaded["rows"]) == 2

    blob = "\n".join(format_market_timeline_evening_lines(doc))
    assert "Market Timeline" in blob
    assert "NIFTY:" in blob
    assert "CIPLA.NS" in blob
    assert "rs=" in blob
    assert "Revisit questions" in blob
    assert "fcf=missing" in blob


def test_evening_includes_timeline_section(tmp_path, monkeypatch):
    from atlas.config import get_config

    # Point config data at tmp if possible — else pass portfolio.market_timeline
    lines = format_learned_today_section(
        portfolio={
            "portfolio_key": "india_equity_learner",
            "positions": [{"symbol": "CIPLA.NS", "qty": 1}],
            "market_timeline": {
                "ok": True,
                "as_of_ist": "2026-08-09",
                "count": 1,
                "rows": [
                    {
                        "symbol": "CIPLA.NS",
                        "unknowns": ["news", "policy"],
                        "lanes": {
                            "price": {"last_price": 1500.0, "return_1d_pct": 0.5},
                            "technical": {"rsi14": 55.0},
                            "fundamentals": {"pe": 36.1},
                            "atlas": {"last_action": "hold"},
                        },
                        "revisit_questions": ["What changed?"],
                    }
                ],
                "honesty": "test",
            },
            "evolution": {"done_revisits": 0, "pending_revisits": 0},
        }
    )
    blob = "\n".join(lines)
    assert "Market Timeline" in blob
    assert "CIPLA.NS" in blob
