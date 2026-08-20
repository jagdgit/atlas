"""OI-STAB0 P0.0 — Activity journal ownership."""

from __future__ import annotations

from atlas.activity import (
    ActivityJournal,
    InMemoryActivityRepository,
    bind_journal,
    record_activity,
)
from atlas.planner.planner import Intent, Planner
from atlas.reasoning.day_activity import build_day_activity_brief, detect_day_activity


def test_activity_journal_record_and_day_brief():
    repo = InMemoryActivityRepository()
    j = ActivityJournal(repo)
    bind_journal(j)
    try:
        j.record(
            domain="market",
            worker="investor_mailer",
            action="send_morning_plan",
            summary="Sent morning investor plan to configured recipients",
            result="completed",
        )
        j.record(
            domain="market",
            worker="yahoo_rate_gate",
            action="yahoo_cooldown",
            summary="Yahoo rate gate entered cooldown 900s",
            result="deferred",
        )
        out = j.format_day_brief()
        assert out["ok"]
        assert out["count"] == 2
        assert "morning investor plan" in out["answer"].lower()
        assert "yahoo rate gate" in out["answer"].lower()

        via_helper = record_activity(
            domain="market",
            worker="paper_trading",
            action="paper_tick",
            summary="Paper tick on india_equity_learner: +0 buy",
        )
        assert via_helper is not None
        assert j.format_day_brief()["count"] == 3

        brief = build_day_activity_brief(journal=j)
        assert brief.get("source") == "activity_events" or brief.get("mode") == "day_activity_journal"
        assert "work journal" in brief["answer"].lower() or "activity" in brief["answer"].lower()
    finally:
        bind_journal(None)


def test_day_activity_still_routes():
    assert detect_day_activity("what did you do today?")
    assert Planner().plan("what did you do today?").steps[0].intent == Intent.DAY_ACTIVITY


def test_market_data_service_cache(tmp_path):
    from atlas.investment.market_data_service import MarketDataService

    mds = MarketDataService(data_dir=tmp_path, mark_ttl_s=60)
    mds.put_cached_mark("TCS.NS", {"last": 100.0, "source": "test"})
    hit = mds.mark_for_symbol("TCS.NS", worker="test")
    assert hit["ok"]
    assert hit["source"] == "cache"
    assert mds.status()["cached_marks"] == 1
    audit = tmp_path / "investment" / "yahoo_request_audit.jsonl"
    assert audit.is_file()


def _daily_bars_ending(last_day: str, n: int = 41, close0: float = 100.0):
    from datetime import date, timedelta

    last = date.fromisoformat(last_day)
    return [
        {
            "date": (last - timedelta(days=n - 1 - i)).isoformat(),
            "open": close0 + i,
            "high": close0 + i + 1,
            "low": close0 + i - 1,
            "close": close0 + i,
            "volume": 1000,
        }
        for i in range(n)
    ]


def _yahoo_chart(days_closes: list[tuple[str, float]]) -> dict:
    from datetime import datetime, timezone

    timestamps = []
    closes = []
    for day, close in days_closes:
        d = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        timestamps.append(int(d.timestamp()))
        closes.append(close)
    return {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": closes,
                                "high": closes,
                                "low": closes,
                                "close": closes,
                                "volume": [1] * len(closes),
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_market_reader_session_fresh_skips_yahoo(tmp_path):
    """Session-fresh durable tips do not hit Yahoo."""
    from atlas.investment.bar_store import last_completed_nse_session_date, persist_symbol_bars
    from atlas.investment.market_data_service import MarketDataService
    from atlas.investment.yahoo_fundamentals import reset_yahoo_rate_gate_for_tests
    from atlas.trading.market_reader import MarketReaderService

    reset_yahoo_rate_gate_for_tests()
    sess = last_completed_nse_session_date().isoformat()
    persist_symbol_bars(tmp_path, "INFY.NS", _daily_bars_ending(sess), provider="yahoo")
    hits = {"n": 0}

    def opener(_url):
        hits["n"] += 1
        return {"chart": {"result": []}}

    reader = MarketReaderService(
        yahoo_enabled=True,
        yahoo_opener=opener,
        data_dir=str(tmp_path),
        prefer_durable_bars=True,
        market_data_service=MarketDataService(data_dir=tmp_path, mark_ttl_s=60),
    )
    out = reader.bars_for("INFY.NS", provider="yahoo", limit=20)
    assert out["provider"] == "yahoo_durable"
    assert out.get("note") == "session_fresh"
    assert hits["n"] == 0


def test_market_reader_stale_tip_refreshes_and_persists(tmp_path):
    """Not session-fresh → paced Yahoo + persist so paper marks can move."""
    from atlas.investment.bar_store import (
        last_completed_nse_session_date,
        load_symbol_doc,
        persist_symbol_bars,
    )
    from atlas.investment.market_data_service import MarketDataService
    from atlas.investment.yahoo_fundamentals import reset_yahoo_rate_gate_for_tests
    from atlas.trading.market_reader import MarketReaderService

    reset_yahoo_rate_gate_for_tests()
    persist_symbol_bars(
        tmp_path, "INFY.NS", _daily_bars_ending("2026-08-01"), provider="yahoo"
    )
    sess = last_completed_nse_session_date().isoformat()
    hits = {"n": 0}

    def opener(_url):
        hits["n"] += 1
        return _yahoo_chart([(sess, 555.0), ("2026-08-01", 140.0)])

    reader = MarketReaderService(
        yahoo_enabled=True,
        yahoo_opener=opener,
        data_dir=str(tmp_path),
        prefer_durable_bars=True,
        market_data_service=MarketDataService(data_dir=tmp_path, mark_ttl_s=60),
    )
    out = reader.bars_for("INFY.NS", provider="yahoo", limit=20)
    assert hits["n"] == 1
    assert out["source"] == "yahoo_network"
    assert out.get("note") == "session_tip_refresh"
    stored = load_symbol_doc(tmp_path, "INFY.NS") or {}
    last = (stored.get("bars") or [])[-1]
    assert str(last.get("date") or "")[:10] == sess
    assert float(last.get("close")) == 555.0


def test_market_reader_stale_uses_durable_during_yahoo_cooldown(tmp_path):
    """Cooldown still falls back to durable — no invent, no hammer."""
    from atlas.investment.bar_store import persist_symbol_bars
    from atlas.investment.market_data_service import MarketDataService
    from atlas.investment.yahoo_fundamentals import (
        get_yahoo_rate_gate,
        reset_yahoo_rate_gate_for_tests,
    )
    from atlas.trading.market_reader import MarketReaderService

    reset_yahoo_rate_gate_for_tests()
    persist_symbol_bars(
        tmp_path, "INFY.NS", _daily_bars_ending("2026-08-01"), provider="yahoo"
    )
    get_yahoo_rate_gate(str(tmp_path)).on_block(429)
    hits = {"n": 0}

    def opener(_url):
        hits["n"] += 1
        return {"chart": {"result": []}}

    reader = MarketReaderService(
        yahoo_enabled=True,
        yahoo_opener=opener,
        data_dir=str(tmp_path),
        prefer_durable_bars=True,
        market_data_service=MarketDataService(data_dir=tmp_path, mark_ttl_s=60),
    )
    out = reader.bars_for("INFY.NS", provider="yahoo", limit=20)
    assert out["provider"] == "yahoo_durable_stale"
    assert hits["n"] == 0
    assert "cooldown" in str(out.get("note") or "").lower()


def test_mem1_chat_messages_are_chatmessage_objects():
    """OI-STAB0 P0.4 — Ollama chat expects ChatMessage.as_dict(), not raw dicts."""
    from atlas.investment.memory_distill import _apply_llm_text
    from atlas.llm.provider import ChatMessage, LLMResponse

    seen = {}

    class _FakeLLM:
        def chat(self, messages, **_opts):
            seen["messages"] = messages
            return LLMResponse(
                text='{"concepts":[{"id":"c1","statement":"test concept"}],'
                '"procedures":[{"id":"p1","tip":"test tip"}]}',
                model="fake",
            )

    layers = {
        "episodic_n": 1,
        "concepts": [{"id": "c1", "label": "x", "count": 1}],
        "procedures": [{"id": "p1", "label": "y", "count": 1}],
        "status_counts": {},
        "symbol_counts": {},
    }
    out, err = _apply_llm_text(layers, llm=_FakeLLM())
    assert err is None
    assert seen["messages"]
    assert all(isinstance(m, ChatMessage) for m in seen["messages"])
    assert hasattr(seen["messages"][0], "as_dict")
    assert out["concepts"][0].get("statement") == "test concept"


def test_market_data_yahoo_soak_counts(tmp_path):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from atlas.investment.market_data_service import MarketDataService

    mds = MarketDataService(data_dir=tmp_path, mark_ttl_s=60)
    day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    path = tmp_path / "investment" / "yahoo_request_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts": f"{day}T04:00:00+00:00", "url_class": "durable_bar_store", "status": 200, "cache_hit": True},
        {"ts": datetime.now(timezone.utc).isoformat(), "url_class": "yahoo_network", "status": 429},
        {"ts": "2020-01-01T00:00:00+00:00", "url_class": "yahoo_network", "status": 429},
    ]
    path.write_text("\n".join(__import__("json").dumps(r) for r in rows) + "\n")
    soak = mds.yahoo_soak_today(day_ist=day)
    assert soak["rows"] >= 1
    assert soak["status_429"] >= 1
    assert mds.status()["yahoo_soak"]["day_ist"] == day
