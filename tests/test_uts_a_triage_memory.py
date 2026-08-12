"""UTS.A — Full triage memory: score-all persist, watchlist truncate."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.ranking import score_universe, rank_universe, PHASE_LEARNING
from atlas.investment.triage_memory import (
    persist_triage_day,
    load_triage_day,
    symbol_history,
    list_triage_days,
)
from atlas.investment.watchlists import clear, latest
from atlas.workers.base import TickContext
from atlas.workers.investment_universe import InvestmentUniverseWorker


def _members(n: int = 5) -> list[dict]:
    out = []
    for i in range(n):
        out.append(
            {
                "symbol": f"S{i}.NS",
                "name": f"Name{i}",
                "sector": "Test",
                "nse_symbol": f"S{i}",
                "exchange": "NSE",
                "asset_class": "cash_equity",
            }
        )
    return out


def test_score_universe_returns_full_ladder_rank_universe_truncates():
    members = _members(5)
    scored = score_universe(members)
    assert len(scored) == 5
    assert [r["rank"] for r in scored] == [1, 2, 3, 4, 5]
    ranked = rank_universe(members, max_watchlist=2)
    assert len(ranked) == 2
    assert ranked[0]["symbol"] == scored[0]["symbol"]
    assert ranked[1]["symbol"] == scored[1]["symbol"]


def test_persist_triage_day_and_load(tmp_path: Path):
    members = _members(5)
    scored = score_universe(members)
    out = persist_triage_day(
        tmp_path,
        "market_intelligence",
        scored,
        as_of_ist="2026-08-09",
        membership=5,
    )
    assert out["ok"] is True
    assert out["count"] == 5
    cov = out["coverage"]
    assert cov["rank_ladder_persisted"] is True
    assert cov["scanned"] == 5
    assert cov["membership"] == 5
    assert cov["universe_scanned"] == "5/5"

    loaded = load_triage_day(tmp_path, "market_intelligence", "2026-08-09")
    assert loaded["ok"] is True
    assert len(loaded["rows"]) == 5
    assert loaded["rows"][0]["rank"] == 1
    assert "S0.NS" in {r["symbol"] for r in loaded["rows"]}


def test_symbol_history_across_days(tmp_path: Path):
    members = _members(3)
    for day in ("2026-08-07", "2026-08-08", "2026-08-09"):
        scored = score_universe(members)
        persist_triage_day(
            tmp_path,
            "market_intelligence",
            scored,
            as_of_ist=day,
            membership=3,
        )
    hist = symbol_history(tmp_path, "market_intelligence", "S1.NS", limit=10)
    assert len(hist) == 3
    assert all(r["symbol"] == "S1.NS" for r in hist)
    assert list_triage_days(tmp_path, "market_intelligence") == [
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
    ]


def test_m0_worker_persists_full_ladder_publishes_truncated_watchlist(tmp_path: Path, monkeypatch):
    clear()
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "market" / "watchlists"))

    # Stub resolve to fixed membership without live universe files.
    members = _members(5)

    def _fake_resolve(**kwargs):
        return {"members": members, "universes": ["TEST"], "skipped": []}

    monkeypatch.setattr(
        "atlas.workers.investment_universe.resolve_members",
        _fake_resolve,
    )

    worker = InvestmentUniverseWorker(data_dir=str(tmp_path))
    result = worker.do_tick(
        TickContext(
            worker_id="w-uts-a",
            mission_id="test-uts-a",
            config={
                "program_id": "market_intelligence",
                "max_watchlist": 2,
                "mode": "auto",
                "use_enabled_universes": False,
                "use_quality_seed": False,
                "use_screener_signals": False,
                "universe_triage_persist": True,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert "triage=5/5" in (result.note or "")
    assert result.state.get("triage_count") == 5
    assert result.state.get("triage", {}).get("persisted") is True
    assert len(result.state.get("watchlist_symbols") or []) == 2

    snap = latest("market_intelligence")
    assert snap is not None
    assert len(snap.get("watchlist") or []) == 2
    assert len(snap.get("ranked") or []) == 2
    assert (snap.get("extra") or {}).get("triage", {}).get("persisted") is True

    loaded = load_triage_day(tmp_path, "market_intelligence")
    assert loaded["ok"] is True
    assert len(loaded["rows"]) == 5
    assert all(r.get("phase") == PHASE_LEARNING for r in loaded["rows"])
