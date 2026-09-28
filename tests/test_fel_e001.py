"""E001 volume-acceleration experiment — hermetic + plugin registration."""

from __future__ import annotations

from atlas.investment.bar_store import persist_symbol_bars
from atlas.investment.fel import default_fel
from atlas.investment.fel.experiments.e001_vol_accel import (
    E001_ID,
    HYPOTHESIS_ID,
    month_end_as_ofs,
    run_e001,
)
from atlas.investment.fel.models.linear_features import (
    BASELINE_MOM_RS_ID,
    CANDIDATE_MOM_RS_VOL_ID,
)


def _series(sym: str, *, months: int = 12, vol_boost_late: bool = False) -> list[dict]:
    rows = []
    i = 0
    for m in range(1, months + 1):
        for d in range(1, 21):
            i += 1
            date = f"2024-{m:02d}-{d:02d}"
            vol = 1000.0 + 10 * i
            if vol_boost_late and m >= months - 1:
                vol *= 3.0
            rows.append(
                {
                    "date": date,
                    "open": 100 + i,
                    "high": 101 + i,
                    "low": 99 + i,
                    "close": 100.0 + i + (5 if "A" in sym else 0),
                    "volume": vol,
                }
            )
    return rows


def test_linear_plugins_registered():
    fel = default_fel()
    assert fel.models.require(BASELINE_MOM_RS_ID).available()
    assert fel.models.require(CANDIDATE_MOM_RS_VOL_ID).available()


def test_month_end_as_ofs_leaves_tail():
    bars = [{"date": f"2024-{m:02d}-28", "close": 1} for m in range(1, 13)]
    bars += [{"date": f"2024-12-{d:02d}", "close": 1} for d in range(1, 31)]
    dates = month_end_as_ofs(bars, start="2024-01-01", leave_tail_days=5)
    assert dates
    assert dates[-1] < bars[-1]["date"]


def test_e001_runs_end_to_end_on_synthetic_bars(tmp_path):
    for sym, boost in (("AAA.NS", True), ("BBB.NS", False)):
        persist_symbol_bars(
            tmp_path, sym, _series(sym, months=10, vol_boost_late=boost), provider="test"
        )
    persist_symbol_bars(
        tmp_path,
        "^NSEI",
        _series("N", months=10, vol_boost_late=False),
        provider="test",
    )

    import atlas.investment.fel.experiments.e001_vol_accel as e001

    real_select = e001.select_symbols

    def _select(data_dir, **kw):
        return ["AAA.NS", "BBB.NS"]

    e001.select_symbols = _select  # type: ignore[method-assign]
    try:
        out = run_e001(
            tmp_path,
            laboratory_id="india_equity_learner",
            min_train_months=2,
            costs={"round_trip": 0.001, "slippage": 0.0005},
        )
    finally:
        e001.select_symbols = real_select  # type: ignore[method-assign]

    assert out["experiment_id"] == E001_ID
    assert out["result"] in {
        "improve",
        "no_significant",
        "worse",
        "conditional",
        "invalid",
    }
    assert out["promotion"] != "live_control"
    exp_dir = tmp_path / "investment" / "fel" / "experiments" / "india_equity_learner"
    assert list(exp_dir.glob("*.json"))