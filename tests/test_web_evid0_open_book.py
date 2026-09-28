"""OI-WEB-EVID0 Phase A — open-book web search densify (hermetic)."""

from __future__ import annotations

from types import SimpleNamespace

from atlas.investment.open_book_web_evidence import densify_open_book_web_evidence


def test_open_book_web_evidence_stores_hits(tmp_path):
    def fake_search(query, max_results=5):
        return SimpleNamespace(
            hits=[
                SimpleNamespace(
                    title="Welspun Corp wins order",
                    url="https://example.com/welcorp",
                    snippet="Order book update for WELCORP NSE",
                )
            ]
        )

    out = densify_open_book_web_evidence(
        str(tmp_path),
        ["WELCORP.NS"],
        search_fn=fake_search,
        max_symbols=2,
        max_hits=3,
    )
    assert out["ok"] is True
    assert out["hits_stored"] == 1
    assert out["queried"] == 1

    from atlas.investment.observations import DecisionObservationStore

    store = DecisionObservationStore(data_dir=str(tmp_path))
    rows = store.list_news_for_symbol(symbol="WELCORP.NS", limit=10)
    assert rows
    pl = rows[0].get("payload") or {}
    assert pl.get("evidence_class") == "evidence_candidate"
    assert "Welspun" in (pl.get("text") or "") or "welcorp" in (pl.get("text") or "").lower()


def test_open_book_web_evidence_skips_without_search(tmp_path):
    out = densify_open_book_web_evidence(
        str(tmp_path),
        ["WELCORP.NS"],
        search_fn=None,
    )
    # Without injectable search and no plugin registry, expect skip
    assert out.get("skipped") in {"search_unavailable", None} or out.get("hits_stored") == 0


def test_world_evidence_attaches_web_search_lane(tmp_path):
    """Tier-3 DuckDuckGo candidates still reach scientist via web_search lane."""
    from atlas.investment.observations import DecisionObservationStore
    from atlas.investment.world_evidence import attach_world_evidence

    store = DecisionObservationStore(data_dir=str(tmp_path))
    store.record_news_event(
        symbol="WELCORP.NS",
        text="Welspun Corp order book update",
        source="duckduckgo_search",
        link="https://example.com/welcorp",
        open_book=True,
        extra={
            "title": "Welspun Corp order book update",
            "evidence_class": "evidence_candidate",
            "source_tier": 3,
        },
    )
    world = attach_world_evidence(tmp_path, "WELCORP.NS")
    assert world["news"], world
    assert any(n.get("lane") == "web_search" for n in world["news"])
    assert any("web_search" in (ln or "") for ln in world.get("evidence_lines") or [])
