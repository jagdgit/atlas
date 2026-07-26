"""Market watchlist store + dashboard recovery (disk persistence)."""

from __future__ import annotations

from atlas.investment import watchlists as wl


def setup_function() -> None:
    wl.clear(disk=False)


def teardown_function() -> None:
    wl.clear(disk=False)


def test_latest_empty():
    wl.clear(disk=True)
    assert wl.latest() is None


def test_publish_and_latest():
    wl.publish(
        index="NIFTY50",
        watchlist=[{"symbol": "TCS.NS", "name": "TCS"}],
        ranked=[
            {"symbol": "TCS.NS", "name": "TCS", "rank": 1, "reason": "quality+"},
            {"symbol": "INFY.NS", "name": "Infosys", "rank": 2},
        ],
    )
    snap = wl.latest()
    assert snap is not None
    assert snap["index"] == "NIFTY50"
    assert snap["ranked"][0]["symbol"] == "TCS.NS"
    assert len(snap["ranked"]) == 2


def test_watchlist_survives_memory_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path))
    wl.clear(disk=True)
    wl.publish(
        index="NIFTY50",
        watchlist=[{"symbol": "RELIANCE.NS"}],
        ranked=[{"symbol": "RELIANCE.NS", "rank": 1}],
    )
    wl.clear(disk=False)  # wipe memory only
    snap = wl.latest("market_intelligence")
    assert snap is not None
    assert snap["ranked"][0]["symbol"] == "RELIANCE.NS"
