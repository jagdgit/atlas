"""IIP.2 themes + discovery engine tests."""

from __future__ import annotations

from atlas.investment.discovery import run_discovery, save_discovery, load_latest_discovery, screen_symbol
from atlas.investment.themes import expand_theme_candidates, get_theme, list_themes, themes_view
from atlas.investment.universe_manager import resolve_members


def test_themes_seeded():
    themes = list_themes()
    assert len(themes) >= 6
    dc = get_theme("data_centers")
    assert dc and "POWERGRID.NS" in dc["symbols"]
    cands = expand_theme_candidates(theme_id="defence")
    assert any(c["symbol"] == "BEL.NS" for c in cands)
    assert all(c.get("horizon") for c in cands)
    assert themes_view()["count"] >= 6


def test_screen_and_discovery_mix():
    # Synthetic breakout + volume
    bars = []
    for i in range(30):
        bars.append({"close": 100 + i * 0.1, "volume": 1_000_000})
    bars[-1] = {"close": 110.0, "volume": 5_000_000}
    hits = screen_symbol("DEMO.NS", bars, quality={"roce": 25.0, "debt_to_equity": 0.1})
    assert hits
    assert any(h["filter"] == "volume_spike" for h in hits)

    members = [{"symbol": "BEL.NS"}, {"symbol": "TATAPOWER.NS"}, {"symbol": "DEMO.NS"}]
    doc = run_discovery(
        members=members,
        bars_by_symbol={"DEMO.NS": bars},
        quality_by_symbol={"DEMO.NS": {"roce": 22}},
        max_interesting=20,
        max_enqueue_research=5,
        include_themes=True,
        themes=["defence", "green_energy"],
    )
    assert doc["interesting_count"] >= 1
    assert any(r.get("mode") in {"hypothesis", "screen", "screen+hypothesis"} for r in doc["interesting"])
    assert all(r.get("horizon") for r in doc["interesting"])
    assert len(doc["research_queue"]) <= 5


def test_discovery_persist(tmp_path):
    doc = run_discovery(
        members=[{"symbol": "BEL.NS"}],
        include_themes=True,
        themes=["defence"],
        max_interesting=10,
    )
    path = save_discovery(tmp_path, doc)
    assert path and path.is_file()
    latest = load_latest_discovery(tmp_path)
    assert latest.get("interesting_count", 0) >= 1


def test_theme_universe_resolve():
    r = resolve_members(universes=["NIFTY50", "THEME_DEFENCE"])
    assert "THEME_DEFENCE" in r["universes"]
    assert r["count"] >= 50
    syms = {m["symbol"] for m in r["members"]}
    assert "BEL.NS" in syms
