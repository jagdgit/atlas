"""Hermetic tests for the deterministic trading indicators (Phase D · §D.6).

Pure math over close-price series: correct values on known inputs, ``None`` when the series is too
short, and reproducibility (same input → same output, Q7).
"""

from __future__ import annotations

from atlas.trading.indicators import compute_indicators, ema, macd, rsi, sma


def test_sma_basic_and_too_short():
    assert sma([1, 2, 3, 4], 2) == 3.5  # last 2: (3+4)/2
    assert sma([1, 2, 3, 4], 4) == 2.5
    assert sma([1, 2], 5) is None
    assert sma([], 3) is None


def test_ema_seeds_with_sma_and_tracks():
    # EMA of a flat series equals the level.
    assert ema([5, 5, 5, 5, 5], 3) == 5.0
    up = ema([1, 2, 3, 4, 5, 6], 3)
    assert up is not None and up > 3.0  # rising series → EMA above the mid


def test_rsi_all_gains_is_100_and_range_bounded():
    rising = list(range(1, 40))
    r = rsi(rising, 14)
    assert r == 100.0
    mixed = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
    rm = rsi(mixed, 14)
    assert rm is not None and 0.0 <= rm <= 100.0


def test_rsi_too_short():
    assert rsi([1, 2, 3], 14) is None


def test_macd_shape_when_enough_data():
    series = [float(x) for x in range(1, 60)]
    out = macd(series)
    assert out is not None
    assert set(out) == {"macd", "signal", "histogram"}
    assert abs(out["histogram"] - (out["macd"] - out["signal"])) < 1e-9


def test_macd_too_short():
    assert macd([1, 2, 3, 4, 5]) is None


def test_compute_indicators_bundle_and_determinism():
    closes = [float(x) for x in range(1, 50)]
    params = {"sma_fast": 5, "sma_slow": 10, "rsi_period": 14}
    a = compute_indicators(closes, params)
    b = compute_indicators(closes, params)
    assert a == b  # deterministic
    assert a["price"] == 49.0
    assert a["bars"] == 49
    assert a["sma_fast"] is not None and a["sma_slow"] is not None
    # On a monotonically rising series the fast MA is above the slow MA.
    assert a["sma_fast"] > a["sma_slow"]
    assert a["params"] == {"sma_fast": 5, "sma_slow": 10, "rsi_period": 14}


def test_compute_indicators_short_series_returns_none_signals():
    out = compute_indicators([1.0, 2.0], {"sma_fast": 5, "sma_slow": 10})
    assert out["price"] == 2.0
    assert out["sma_fast"] is None
    assert out["sma_slow"] is None
