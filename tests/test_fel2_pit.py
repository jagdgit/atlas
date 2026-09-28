"""FEL.2 — PIT dataset, no look-ahead in features, lab hermeticity."""

from __future__ import annotations

import pytest

from atlas.investment.bar_store import persist_symbol_bars
from atlas.investment.fel import default_fel
from atlas.investment.fel.datasets.builder import (
    bars_as_of,
    build_pit_dataset,
    compute_features_as_of,
    persist_pit_dataset,
    pit_to_matrix,
)
from atlas.investment.fel.features.store import is_decision_eligible
from atlas.investment.laboratory import LaboratoryContaminationError


def _bars(*, n: int = 40, vol_spike_day: str | None = None) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        day = f"2026-07-{i:02d}" if i <= 31 else f"2026-08-{i - 31:02d}"
        vol = 1000.0
        if vol_spike_day and day == vol_spike_day:
            vol = 1_000_000.0
        rows.append(
            {
                "date": day,
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.0 + i,
                "volume": vol,
            }
        )
    return rows


def test_bars_as_of_drops_future_sessions():
    bars = _bars(n=10)
    kept = bars_as_of(bars, "2026-07-05")
    assert [b["date"] for b in kept] == [f"2026-07-{d:02d}" for d in range(1, 6)]


def test_future_volume_does_not_leak_into_as_of_feature(tmp_path):
    fel = default_fel()
    persist_symbol_bars(tmp_path, "AAA.NS", _bars(n=40), provider="test")
    as_of = "2026-07-20"
    a = compute_features_as_of(
        fel,
        _bars(n=40),
        as_of,
        feature_ids=["volume_acceleration_20d"],
    )
    spiked = _bars(n=40, vol_spike_day="2026-07-31")
    persist_symbol_bars(tmp_path, "AAA.NS", spiked, provider="test")
    b = compute_features_as_of(
        fel,
        spiked,
        as_of,
        feature_ids=["volume_acceleration_20d"],
    )
    assert a["volume_acceleration_20d"] == b["volume_acceleration_20d"]
    # Target *may* use the future; features must not.
    from atlas.investment.fel.datasets.builder import forward_return

    t_plain = forward_return(_bars(n=40), as_of, horizon=5)
    t_spike = forward_return(spiked, as_of, horizon=5)
    assert t_plain == t_spike  # spike is volume-only; close path unchanged


def test_pit_dataset_stamps_lab_and_keeps_candidates_as_observations(tmp_path):
    persist_symbol_bars(tmp_path, "AAA.NS", _bars(n=40), provider="test")
    persist_symbol_bars(
        tmp_path,
        "^NSEI",
        [
            {
                "date": f"2026-07-{d:02d}",
                "close": 22000.0 + d,
                "open": 22000,
                "high": 22100,
                "low": 21900,
                "volume": 1,
            }
            for d in range(1, 32)
        ],
        provider="test",
    )
    doc = build_pit_dataset(
        tmp_path,
        symbols=["AAA.NS"],
        as_of_dates=["2026-07-20"],
        laboratory_id="india_equity_learner",
        benchmark_symbol="^NSEI",
    )
    assert doc["laboratory_id"] == "india_equity_learner"
    assert doc["n_rows"] == 1
    feats = doc["rows"][0]["features"]
    assert "volume_acceleration_20d" in feats
    assert "momentum" in feats
    fel = default_fel()
    vol = fel.features.get("volume_acceleration_20d")
    assert vol is not None and not is_decision_eligible(vol)
    path = persist_pit_dataset(tmp_path, doc)
    assert path is not None and path.exists()
    matrix = pit_to_matrix(doc)
    assert matrix.meta["laboratory_id"] == "india_equity_learner"
    assert matrix.rows[0]["laboratory_id"] == "india_equity_learner"


def test_pit_rejects_mixed_laboratories(tmp_path):
    persist_symbol_bars(tmp_path, "AAA.NS", _bars(n=40), provider="test")
    doc = build_pit_dataset(
        tmp_path,
        symbols=["AAA.NS"],
        as_of_dates=["2026-07-20"],
        laboratory_id="india_equity_learner",
    )
    doc["rows"][0]["laboratory_id"] = "india_fno_learner"
    with pytest.raises(LaboratoryContaminationError):
        persist_pit_dataset(tmp_path, doc)
