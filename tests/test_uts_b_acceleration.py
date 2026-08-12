"""UTS.B — Rank acceleration, opportunity queue, evening near-miss honesty."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.ranking import score_universe
from atlas.investment.reports import format_learned_today_section
from atlas.investment.triage_memory import (
    persist_triage_day,
    load_triage_day,
    build_opportunity_queue,
    enrich_rows_with_acceleration,
    format_triage_evening_lines,
    load_latest_triage_bundle,
)


def _members(n: int = 5) -> list[dict]:
    return [
        {
            "symbol": f"S{i}.NS",
            "name": f"Name{i}",
            "sector": "Test",
            "nse_symbol": f"S{i}",
            "exchange": "NSE",
            "asset_class": "cash_equity",
        }
        for i in range(n)
    ]


def _ranked(members: list[dict], order: list[str]) -> list[dict]:
    """Build fake scored rows with explicit ranks (bypass cold-start equality)."""
    by = {m["symbol"]: m for m in members}
    out = []
    for i, sym in enumerate(order, start=1):
        m = by[sym]
        out.append(
            {
                **m,
                "rank": i,
                "score": round(1.0 - i * 0.01, 4),
                "components": {},
                "confidence": "low",
                "phase": "active",
                "reason": "test",
                "last_price": 100.0 + i,
            }
        )
    return out


def test_acceleration_and_deltas_after_three_days(tmp_path: Path):
    members = _members(5)
    # Need 3 prior days so acceleration_3d = rank(t-3)-rank(t) is defined.
    # S4: #5 → #4 → #3 → #1  ⇒ accel=5-1=4, Δ1d=3-1=2
    d0 = _ranked(members, ["S0.NS", "S1.NS", "S2.NS", "S3.NS", "S4.NS"])
    d1 = _ranked(members, ["S0.NS", "S1.NS", "S2.NS", "S4.NS", "S3.NS"])
    d2 = _ranked(members, ["S0.NS", "S1.NS", "S4.NS", "S2.NS", "S3.NS"])
    d3 = _ranked(members, ["S4.NS", "S0.NS", "S1.NS", "S2.NS", "S3.NS"])
    for day, rows in (
        ("2026-08-06", d0),
        ("2026-08-07", d1),
        ("2026-08-08", d2),
    ):
        persist_triage_day(
            tmp_path,
            "market_intelligence",
            rows,
            as_of_ist=day,
            membership=5,
            enrich_acceleration=False,
        )
    out = persist_triage_day(
        tmp_path,
        "market_intelligence",
        d3,
        as_of_ist="2026-08-09",
        membership=5,
        max_watchlist=2,
        enrich_acceleration=True,
    )
    assert out["ok"] is True
    assert out["coverage"]["acceleration_computed"] is True
    loaded = load_triage_day(tmp_path, "market_intelligence", "2026-08-09")
    by = {r["symbol"]: r for r in loaded["rows"]}
    s4 = by["S4.NS"]
    assert s4["rank"] == 1
    assert s4["acceleration_3d"] == 4
    assert s4["rank_delta_1d"] == 2
    assert s4["accel_score"] is not None


def test_opportunity_queue_near_miss_and_accelerator(tmp_path: Path):
    members = _members(6)
    # ranks 1..6; S5 accelerating from outside watchlist(max=2)
    rows = _ranked(members, ["S0.NS", "S1.NS", "S2.NS", "S3.NS", "S4.NS", "S5.NS"])
    # seed history so S5 has accel
    older = _ranked(members, ["S0.NS", "S1.NS", "S2.NS", "S3.NS", "S5.NS", "S4.NS"])
    mid = _ranked(members, ["S0.NS", "S1.NS", "S2.NS", "S5.NS", "S3.NS", "S4.NS"])
    persist_triage_day(
        tmp_path, "market_intelligence", older, as_of_ist="2026-08-07",
        enrich_acceleration=False, membership=6,
    )
    persist_triage_day(
        tmp_path, "market_intelligence", mid, as_of_ist="2026-08-08",
        enrich_acceleration=False, membership=6,
    )
    # Move S5 to rank 3 (near miss) with history from rank 5
    today = _ranked(members, ["S0.NS", "S1.NS", "S5.NS", "S2.NS", "S3.NS", "S4.NS"])
    enrich_rows_with_acceleration(
        today, data_dir=tmp_path, program_id="market_intelligence", as_of_ist="2026-08-09"
    )
    q = build_opportunity_queue(today, max_watchlist=2, near_miss_end=4)
    syms = [x["symbol"] for x in q]
    assert "S5.NS" in syms
    reasons = {x["symbol"]: x["reason"] for x in q}
    assert reasons["S5.NS"] in {
        "near_miss",
        "near_miss_accelerating",
        "acceleration_outside_watchlist",
    }


def test_evening_lines_include_triage_block():
    triage = {
        "ok": True,
        "coverage": {
            "universe_scanned": "6/6",
            "rank_ladder_persisted": True,
            "acceleration_status": "ready",
            "acceleration_symbols": 2,
            "price_coverage_pct": 100.0,
        },
        "evening": {
            "accelerating": [{"symbol": "S5.NS", "rank": 3, "acceleration_3d": 2}],
            "near_misses": [{"symbol": "S2.NS", "rank": 3, "rank_delta_1d": 1}],
            "near_miss_band": [3, 4],
        },
        "opportunity_queue": [
            {"symbol": "S5.NS", "reason": "near_miss_accelerating"},
        ],
    }
    lines = format_triage_evening_lines(triage)
    blob = "\n".join(lines)
    assert "Universe triage" in blob
    assert "Accelerating" in blob
    assert "Near misses" in blob
    assert "Opportunity queue" in blob

    section = format_learned_today_section(portfolio={"triage": triage})
    joined = "\n".join(section)
    assert "Universe triage" in joined


def test_load_latest_bundle_reads_queue_sidecar(tmp_path: Path):
    members = _members(4)
    rows = _ranked(members, ["S0.NS", "S1.NS", "S2.NS", "S3.NS"])
    persist_triage_day(
        tmp_path,
        "market_intelligence",
        rows,
        as_of_ist="2026-08-09",
        max_watchlist=2,
        enrich_acceleration=False,
        membership=4,
    )
    bundle = load_latest_triage_bundle(tmp_path, "market_intelligence")
    assert bundle["ok"] is True
    assert "opportunity_queue" in bundle
    assert "evening" in bundle
    assert Path(bundle["path"]).with_suffix(".queue.json").is_file()
