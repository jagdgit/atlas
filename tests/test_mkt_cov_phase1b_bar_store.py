"""OI-MKT-COV Phase 1B — durable bar store hermetic tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.investment.bar_store import (
    load_bars,
    merge_bars,
    persist_bars_batch,
    persist_symbol_bars,
    readiness_for_symbols,
    readiness_from_rows,
    symbol_readiness,
)


def test_merge_bars_dedupes_by_date():
    a = [{"date": "2026-08-01", "close": 10.0, "volume": 1}]
    b = [
        {"date": "2026-08-01", "close": 11.0, "volume": 2},
        {"date": "2026-08-02", "close": 12.0},
    ]
    m = merge_bars(a, b)
    assert len(m) == 2
    assert m[0]["close"] == 11.0
    assert m[1]["date"] == "2026-08-02"


def test_persist_and_readiness_grade_b(tmp_path):
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    bars = []
    for i in range(45):
        day = (now - timedelta(days=44 - i)).date().isoformat()
        bars.append({"date": day, "close": 100.0 + i, "volume": 1000})
    r = persist_symbol_bars(tmp_path, "TCS.NS", bars, provider="yahoo")
    assert r["priced"] is True
    assert r["history_ok"] is True
    assert r["fresh"] is True
    assert r["bar_count"] == 45
    loaded = load_bars(tmp_path, "TCS.NS")
    assert len(loaded) == 45

    # Second symbol thin → universe not B yet
    persist_symbol_bars(
        tmp_path,
        "INFY.NS",
        [{"date": now.date().isoformat(), "close": 1.0}],
        provider="yahoo",
    )
    summary = readiness_for_symbols(tmp_path, ["TCS.NS", "INFY.NS"])
    assert summary["priced_pct"] == 100.0
    assert summary["readiness_grade"] in {"C", "D"}  # INFY lacks history
    assert summary["durable_bars_ok"] is False

    # Both ready
    bars2 = [
        {
            "date": (now - timedelta(days=44 - i)).date().isoformat(),
            "close": 50.0 + i,
        }
        for i in range(45)
    ]
    persist_symbol_bars(tmp_path, "INFY.NS", bars2, provider="yahoo")
    summary2 = readiness_for_symbols(tmp_path, ["TCS.NS", "INFY.NS"])
    assert summary2["readiness_grade"] in {"A", "B"}
    assert summary2["durable_bars_ok"] is True


def test_symbol_readiness_stale_not_ok():
    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    bars = [
        {
            "date": (now - timedelta(days=80 - i)).date().isoformat(),
            "close": 10.0 + i,
        }
        for i in range(45)
    ]
    # Make last bar old
    bars[-1]["date"] = "2026-07-01"
    doc = {"symbol": "X.NS", "provider": "yahoo", "bars": bars}
    r = symbol_readiness(doc, now=now, fresh_days=5)
    assert r["history_ok"] is True
    assert r["fresh"] is False
    assert r["ok"] is False


def test_readiness_from_rows_grades():
    rows = [{"priced": True, "history_ok": True, "fresh": True, "ok": True}] * 95
    rows += [{"priced": False, "history_ok": False, "fresh": False, "ok": False}] * 5
    s = readiness_from_rows(rows, membership=[f"S{i}" for i in range(100)])
    assert s["readiness_grade"] == "B"
    assert s["durable_bars_ok"] is True
