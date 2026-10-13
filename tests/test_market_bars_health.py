"""Durable daily OHLCV health checks (P2)."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.market_bars_health import (
    assess_symbols,
    validate_daily_bars_file,
)


def _write_bars(tmp: Path, symbol: str, days: list[tuple[str, float]]) -> Path:
    p = tmp / "market" / "bars" / f"{symbol}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    bars = [
        {"date": d, "open": px, "high": px + 1, "low": px - 1, "close": px, "volume": 1}
        for d, px in days
    ]
    p.write_text(json.dumps({"symbol": symbol, "bars": bars}), encoding="utf-8")
    return p


def test_validate_continuous_daily_ok(tmp_path: Path):
    p = _write_bars(
        tmp_path,
        "AAA.NS",
        [("2026-10-01", 10.0), ("2026-10-02", 11.0), ("2026-10-05", 12.0)],  # weekend gap
    )
    out = validate_daily_bars_file(p)
    assert out["replayable"] is True
    assert out["null_ohlc"] == 0
    assert out["gaps_gt_5d"] == 0


def test_null_close_not_replayable(tmp_path: Path):
    p = tmp_path / "market" / "bars" / "BBB.NS.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "bars": [
                    {
                        "date": "2026-10-01",
                        "open": 1,
                        "high": 1,
                        "low": 1,
                        "close": None,
                        "volume": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    out = validate_daily_bars_file(p)
    assert out["replayable"] is False
    assert "null_ohlc" in out["issues"]


def test_assess_symbols_provisional_when_missing(tmp_path: Path):
    _write_bars(tmp_path, "TCS.NS", [("2026-10-01", 100.0), ("2026-10-02", 101.0)])
    doc = assess_symbols(tmp_path, ["TCS", "MISSINGCO"], as_of_ist="2026-10-05")
    assert doc["n_symbols"] == 2
    assert doc["n_replayable"] == 1
    assert doc["all_replayable"] is False
    assert "provisional_ranking" in doc["ranking_honest"]


def test_index_names_resolve_to_the_writer_file(tmp_path):
    import json

    from atlas.investment.market_bars_health import assess_symbols, bar_path

    root = tmp_path / "market" / "bars"
    root.mkdir(parents=True)
    bars = [{"date": f"2026-09-{d:02d}", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for d in range(1, 29)]
    (root / "_NSEI.json").write_text(json.dumps({"bars": bars}), encoding="utf-8")
    assert bar_path(tmp_path, "NIFTY").name == "_NSEI.json"
    assert assess_symbols(tmp_path, ["NIFTY"])["all_replayable"] is True
