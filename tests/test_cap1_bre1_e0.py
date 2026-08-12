"""CAP.1 / E0 / BRE.1 hermetic tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.investment.bar_store import (
    last_completed_nse_session_date,
    persist_symbol_bars,
    readiness_from_rows,
    symbol_readiness,
)
from atlas.investment.symbol_aliases import (
    news_is_evidence,
    resolve_yahoo_symbol,
)
from atlas.investment.world_state import (
    evidence_delta_counts,
    format_evidence_delta_section,
    format_mind_change_section,
    sync_open_book_wsos,
)


def test_aliases_zomato_tatamotors_nifty():
    z = resolve_yahoo_symbol("ZOMATO.NS")
    assert z.yahoo == "ETERNAL.NS" and z.aliased
    t = resolve_yahoo_symbol("TATAMOTORS")
    assert t.yahoo == "TMPV.NS"
    n = resolve_yahoo_symbol("NIFTY")
    assert n.yahoo == "^NSEI"
    assert resolve_yahoo_symbol("^NSEI").yahoo == "^NSEI"


def test_seed_news_is_non_evidence():
    assert not news_is_evidence(
        {"source": "open_book_seed", "text": "Monitor material news"}
    )
    assert not news_is_evidence(
        {"source": "watchlist_seed", "evidence_class": "non_evidence"}
    )
    assert news_is_evidence({"source": "rss:pib", "text": "Real headline"})


def test_session_fresh_separate_from_calendar_fresh(tmp_path):
    # Friday last bar; Monday evening → calendar fresh (≤5d) but not session_fresh
    monday = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)  # ~19:30 IST
    bars = []
    for i in range(45):
        day = (datetime(2026, 8, 7, tzinfo=timezone.utc) - timedelta(days=44 - i)).date()
        bars.append({"date": day.isoformat(), "close": 100.0 + i})
    bars[-1]["date"] = "2026-08-07"
    persist_symbol_bars(tmp_path, "RELIANCE.NS", bars, provider="yahoo")
    from atlas.investment.bar_store import load_symbol_doc

    doc = load_symbol_doc(tmp_path, "RELIANCE.NS")
    ready = symbol_readiness(doc, now=monday)
    assert ready["fresh"] is True
    assert ready["session_fresh"] is False
    assert ready["last_nse_session"] == "2026-08-10" or ready[
        "last_nse_session"
    ] == last_completed_nse_session_date(monday).isoformat()


def test_session_fresh_when_bar_matches_session(tmp_path):
    monday = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)
    session = last_completed_nse_session_date(monday).isoformat()
    bars = [
        {"date": (datetime(2026, 8, 10) - timedelta(days=44 - i)).date().isoformat(), "close": 10.0 + i}
        for i in range(45)
    ]
    bars[-1]["date"] = session
    persist_symbol_bars(tmp_path, "TCS.NS", bars, provider="yahoo")
    from atlas.investment.bar_store import load_symbol_doc

    ready = symbol_readiness(load_symbol_doc(tmp_path, "TCS.NS"), now=monday)
    assert ready["session_fresh"] is True
    summary = readiness_from_rows([ready], membership=["TCS.NS"])
    assert summary["session_fresh_pct"] == 100.0


def test_wso_shell_and_evening_sections(tmp_path):
    wsos = sync_open_book_wsos(
        tmp_path,
        "india_equity_learner",
        ["EICHERMOT.NS"],
        missing_fundamentals={"EICHERMOT.NS": ["fcf", "debt_equity"]},
    )
    assert len(wsos) == 1
    w = wsos[0]
    assert "fcf" in (w.get("unknowns") or [])
    assert (w.get("uncertainty") or {}).get("data") == "high"
    assert w.get("revision_history")
    lines = format_mind_change_section(wsos)
    assert any("No beliefs changed today" in x or "unchanged" in x for x in lines)
    delta = evidence_delta_counts(seed_news_n=3, news_n=0)
    elines = format_evidence_delta_section(delta)
    assert any("seed_news_ignored=3" in x for x in elines)
    assert any("No material evidence delta" in x for x in elines)


def test_news_block_filters_seeds():
    from atlas.investment.open_book_packs import _news_block_from_observations

    block = _news_block_from_observations(
        [
            {"source": "open_book_seed", "text": "Monitor material news for CIPLA"},
            {
                "source": "rss:pib",
                "text": "Cabinet approves healthcare scheme",
                "topic_tags": ["policy"],
            },
        ]
    )
    assert block["seed_ignored"] == 1
    assert len(block["gov"]) == 1
    assert "company" in block["unknowns"]
