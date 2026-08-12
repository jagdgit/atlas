"""DAV densify close-out — sector indices, event regimes, sizing journal."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_timeline import what_changed
from atlas.investment.open_book_packs import build_open_book_daily_pack
from atlas.investment.sector_benchmarks import (
    infer_event_regime_tags,
    resolve_sector_benchmark,
    yahoo_index_for_sector,
)
from atlas.investment.sizing_learning import (
    format_sizing_learning_evening_lines,
    load_sizing_journal,
    record_sizing_outcome,
)


def test_yahoo_index_for_sector_packs():
    assert yahoo_index_for_sector(pack_id="banks") == "^NSEBANK"
    assert yahoo_index_for_sector(pack_id="saas_it") == "^CNXIT"
    assert yahoo_index_for_sector(sector="Pharmaceuticals") == "^CNXPHARMA"
    assert yahoo_index_for_sector(sector="Consumer Durables") == "^CNXFMCG"
    assert yahoo_index_for_sector(sector="Telecommunication") == "^NSEI"
    assert yahoo_index_for_sector(sector="unknown widgets") == "^NSEI"


def test_resolve_sector_benchmark_from_symbol_hint():
    # EICHERMOT is auto-adjacent in hermetic hints when present; else NIFTY ok
    out = resolve_sector_benchmark(symbol="INFY.NS", sector="Information Technology")
    assert out["yahoo_symbol"] == "^CNXIT"
    assert out["is_broad_market"] is False


def test_pack_uses_sector_benchmark_and_event_regime():
    pack = build_open_book_daily_pack(
        symbol="INFY.NS",
        portfolio_key="india_equity_learner",
        bars=[{"close": 100}, {"close": 103}],
        benchmark_bars=[{"close": 1000}, {"close": 1005}],
        benchmark_symbol="^CNXIT",
        macro_rows=[
            {
                "kind": "macro_event",
                "payload": {
                    "title": "Union Budget speech",
                    "regime_tags": ["budget"],
                },
            }
        ],
    )
    assert pack["market"]["benchmark_symbol"] == "^CNXIT"
    assert pack["market"]["rs_vs_nifty"] is not None
    assert "budget" in pack["market"]["regime_tags"]


def test_infer_event_regime_tags():
    assert "election" in infer_event_regime_tags(title="Lok Sabha election results")
    assert "rate_cut" in infer_event_regime_tags(detail="RBI repo cut expected")
    assert infer_event_regime_tags(title="quiet day") == []


def test_what_changed_merges_macro_event_regime():
    diff = what_changed(
        {"action": "buy", "prices": {"fill_price": 10}, "observation_ids": []},
        current_mark=11,
        recent_observations=[
            {
                "id": "m1",
                "kind": "macro_event",
                "payload": {"title": "Geopolitical flare-up", "regime_tags": ["geopolitical"]},
            }
        ],
    )
    assert "geopolitical" in (diff.get("regime_tags") or [])


def test_sizing_journal_roundtrip(tmp_path: Path):
    out = record_sizing_outcome(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        decision_id="d1",
        confidence=0.62,
        size_fraction=0.4,
        pnl=120.0,
        price_change_pct=3.5,
        thesis_correct="yes",
    )
    assert out["ok"] is True
    doc = load_sizing_journal(tmp_path, laboratory_id="india_equity_learner")
    assert doc["count"] == 1
    assert doc["rows"][0]["symbol"] == "CIPLA.NS"
    lines = format_sizing_learning_evening_lines(doc)
    assert any("Sample=1" in ln for ln in lines)
