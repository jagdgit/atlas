"""E002 high-momentum volume-acceleration experiment."""

from __future__ import annotations

from atlas.investment.bar_store import persist_symbol_bars
from atlas.investment.fel.experiments.e002_vol_accel_high_mom import E002_ID, HYPOTHESIS_ID, run_e002
from atlas.investment.fel.experiments.store import persist_experiment
from atlas.investment.fel.queue import enqueue, get_item
from atlas.investment.fel.experiments.dispatch import process_one
from tests.test_fel_e001 import _series


def test_e002_runs_on_synthetic_parent_tape(tmp_path):
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

    import atlas.investment.fel.experiments.e002_vol_accel_high_mom as e002

    real = e002.select_symbols

    def _select(data_dir, **kw):
        return ["AAA.NS", "BBB.NS"]

    e002.select_symbols = _select  # type: ignore[method-assign]
    try:
        out = run_e002(
            tmp_path,
            laboratory_id="india_equity_learner",
            min_train_months=2,
            costs={"round_trip": 0.001, "slippage": 0.0005},
        )
    finally:
        e002.select_symbols = real  # type: ignore[method-assign]

    assert out["experiment_id"] == E002_ID
    assert out["parent_experiment"] == "E001-buy_name-vol-accel"
    assert out["result"] in {
        "improve",
        "no_significant",
        "worse",
        "conditional",
        "invalid",
    }
    assert out["promotion"] != "live_control"
    assert (out.get("regime") or {}).get("name") == "high_momentum"
    hyp = tmp_path / "investment" / "hypotheses" / "india_equity_learner" / "by_id" / f"{HYPOTHESIS_ID}.json"
    exp = tmp_path / "investment" / "fel" / "experiments" / "india_equity_learner" / f"{E002_ID}.json"
    assert exp.is_file()
    assert hyp.is_file() or out.get("hypothesis")


def test_e002_skip_if_complete(tmp_path):
    persist_experiment(
        tmp_path,
        {
            "experiment_id": E002_ID,
            "laboratory_id": "india_equity_learner",
            "result": "no_significant",
            "promotion": "never",
            "hypothesis_id": HYPOTHESIS_ID,
        },
    )
    enqueue(tmp_path, kind="e002", experiment_id=E002_ID, skip_if_complete=True)
    out = process_one(str(tmp_path))
    assert out["status"] == "COMPLETED"
    assert out["summary"]["skipped"] is True
    assert get_item(tmp_path, E002_ID)["status"] == "COMPLETED"
