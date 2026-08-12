"""UTS.F — Missed Opportunity Ledger (hermetic)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.missed_opportunity import (
    WHY_NEVER_TOP15,
    WHY_WATCHLIST_NOT_BOUGHT,
    classify_why_missed,
    compute_missed_opportunities,
    format_missed_opportunity_evening_lines,
    persist_missed_ledger,
    load_missed_ledger,
)


def test_classify_why_missed_codes():
    assert (
        classify_why_missed("ZZ.NS", rank_on_t=40, max_watchlist=15)
        == WHY_NEVER_TOP15
    )
    assert (
        classify_why_missed("AA.NS", rank_on_t=3, in_watchlist=True)
        == WHY_WATCHLIST_NOT_BOUGHT
    )
    assert (
        classify_why_missed(
            "BB.NS",
            rank_on_t=20,
            switch_rows_for_symbol=[
                {
                    "challenger_symbol": "BB.NS",
                    "reason_code": "switch_blocked_plc_a",
                }
            ],
        )
        == "plc_a"
    )


def test_compute_top5_excess_fail_closed(tmp_path: Path):
    prices = {
        ("A.NS", "2026-07-01"): 100.0,
        ("A.NS", "2026-07-21"): 120.0,  # +20%
        ("B.NS", "2026-07-01"): 100.0,
        ("B.NS", "2026-07-21"): 110.0,  # +10%
        ("C.NS", "2026-07-01"): 100.0,
        ("C.NS", "2026-07-21"): 105.0,  # +5%
        ("HELD.NS", "2026-07-01"): 100.0,
        ("HELD.NS", "2026-07-21"): 130.0,
        # D missing as_of mark → skipped
        ("D.NS", "2026-07-01"): 100.0,
    }

    def price_fn(sym: str, day: str) -> float | None:
        return prices.get((sym, day[:10]))

    triage = [
        {"symbol": "A.NS", "rank": 40, "acceleration_3d": 5, "score": 0.4},
        {"symbol": "B.NS", "rank": 8, "acceleration_3d": 2, "score": 0.6},
        {"symbol": "C.NS", "rank": 50, "score": 0.3},
        {"symbol": "HELD.NS", "rank": 1, "score": 0.9},
        {"symbol": "D.NS", "rank": 60, "score": 0.2},
    ]
    # Fail closed without book return
    miss = compute_missed_opportunities(
        triage,
        held_on_t={"HELD.NS"},
        decision_ist="2026-07-01",
        as_of_ist="2026-07-21",
        price_fn=price_fn,
        book_return_20d=None,
    )
    assert miss["ok"] is False

    out = compute_missed_opportunities(
        triage,
        held_on_t={"HELD.NS"},
        decision_ist="2026-07-01",
        as_of_ist="2026-07-21",
        price_fn=price_fn,
        book_return_20d=0.04,
        top_n=5,
        max_watchlist=15,
        queue_symbols={"C.NS"},
    )
    assert out["ok"] is True
    assert out["skipped_missing_marks"] >= 1
    syms = [r["symbol"] for r in out["rows"]]
    assert "HELD.NS" not in syms
    assert "D.NS" not in syms
    assert syms[0] == "A.NS"  # highest excess
    assert out["rows"][0]["why_missed"] == WHY_NEVER_TOP15
    b = next(r for r in out["rows"] if r["symbol"] == "B.NS")
    assert b["why_missed"] == WHY_WATCHLIST_NOT_BOUGHT
    assert b["in_watchlist_on_t"] is True

    persisted = persist_missed_ledger(
        tmp_path, out, laboratory_id="india_equity_learner"
    )
    assert persisted["ok"] is True
    loaded = load_missed_ledger(
        tmp_path,
        laboratory_id="india_equity_learner",
        decision_ist="2026-07-01",
    )
    assert loaded.get("ok") is True
    lines = format_missed_opportunity_evening_lines(loaded)
    assert any("Missed opportunities" in ln for ln in lines)
    assert any("A.NS" in ln for ln in lines)
