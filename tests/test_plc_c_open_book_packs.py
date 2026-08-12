"""PLC.C — daily open-book observation packs (hermetic)."""

from __future__ import annotations

from atlas.investment.open_book_packs import (
    build_open_book_daily_pack,
    ist_session_day,
    record_open_book_daily_packs,
)


class _FakeObs:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def list_symbol(self, *, symbol: str, limit: int = 40, **_kw):
        return [r for r in self.rows if r.get("symbol") == symbol][:limit]

    def record(self, **kwargs):
        row = {"id": f"obs-{len(self.rows)+1}", **kwargs}
        self.rows.append(row)
        return row


class _FakePortfolio:
    def __init__(self, positions):
        self._positions = positions
        self._repo = self

    def list_positions(self, _pid):
        return self._positions


def test_build_pack_keeps_unknowns():
    pack = build_open_book_daily_pack(
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        session_day="2026-08-08",
        bars=[{"close": 100.0, "volume": 10}, {"close": 110.0, "volume": 20}],
        fundamentals={"pe": 22.0},
    )
    assert pack["kind"] == "open_book_daily_pack"
    assert pack["market"]["close"] == 110.0
    assert pack["market"]["return_pct"] is not None
    assert "rs_vs_nifty" in pack["market"]["unknowns"]
    assert pack["fundamentals"]["pe"] == 22.0
    assert "roe" in pack["fundamentals"]["unknowns"]
    assert pack["thesis"]["status"] == "unknown"


def test_build_pack_fills_rs_vs_nifty_when_benchmark_bars():
    pack = build_open_book_daily_pack(
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        session_day="2026-08-08",
        bars=[{"close": 100.0}, {"close": 110.0}],  # +10%
        benchmark_bars=[{"close": 1000.0}, {"close": 1020.0}],  # +2%
        fundamentals={"pe": 22.0, "fcf": 1e9},
    )
    assert pack["market"]["rs_vs_nifty"] == 8.0
    assert "rs_vs_nifty" not in pack["market"]["unknowns"]
    assert pack["fundamentals"]["fcf"] == 1e9
    assert "fcf" not in pack["fundamentals"]["unknowns"]


def test_record_dedupes_same_day(monkeypatch, tmp_path):
    from atlas.investment import portfolios as vp

    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    with vp._LOCK:  # noqa: SLF001
        vp._STORE.clear()  # noqa: SLF001
        vp._LOADED = False  # noqa: SLF001
    vp.register(
        label="India Equity Learner",
        persona={"capital": 50000, "allowed_assets": ["cash_equity"]},
        portfolio_key="india_equity_learner",
        asset_class="cash_equity",
    )
    # stamp sim id for resolve
    row = vp.get("india_equity_learner")
    assert row
    row["sim_portfolio_id"] = "p1"
    with vp._LOCK:  # noqa: SLF001
        vp._STORE["india_equity_learner"] = row

    obs = _FakeObs()
    port = _FakePortfolio(
        [{"symbol": "EICHERMOT.NS", "qty": 2}, {"symbol": "CIPLA.NS", "qty": 1}]
    )
    day = ist_session_day()
    out1 = record_open_book_daily_packs(
        observations=obs,
        portfolio=port,
        market_reader=None,
        data_dir=None,
        portfolio_key="india_equity_learner",
        budget=5,
    )
    assert out1["recorded"] == 2
    out2 = record_open_book_daily_packs(
        observations=obs,
        portfolio=port,
        market_reader=None,
        data_dir=None,
        portfolio_key="india_equity_learner",
        budget=5,
    )
    assert out2["recorded"] == 0
    assert out2["skipped"] == 2
    assert out2["session_day"] == day
