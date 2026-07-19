"""Deterministic technical indicators over OHLCV bars (Phase D · §D.6).

Pure functions — no I/O, no LLM, no randomness — so the same bars always produce the same signals
(Q7). They turn a price series into the ephemeral **signal context** a
:class:`~atlas.trading.strategy.StrategyDecisionRule` scores; signals are decision inputs, never
knowledge candidates. Implementations are stdlib-only (no numpy/pandas dependency) and defensive:
too-short a series returns ``None`` for that indicator rather than raising.
"""

from __future__ import annotations

from typing import Any, Sequence


def sma(values: Sequence[float], period: int) -> float | None:
    """Simple moving average of the last ``period`` values (None if not enough data)."""
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ema(values: Sequence[float], period: int) -> float | None:
    """Exponential moving average (None if not enough data). Seeded with the first SMA."""
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    e = seed
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    """Wilder's Relative Strength Index over ``period`` (None if not enough data). Range 0–100."""
    if period <= 0 or len(values) <= period:
        return None
    gains = 0.0
    losses = 0.0
    # Seed with the first `period` deltas.
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing over the remaining deltas.
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, float] | None:
    """MACD line + signal line + histogram (None if not enough data)."""
    if len(values) < slow + signal:
        return None
    macd_series: list[float] = []
    # Build the MACD line series so its own EMA (the signal line) can be computed.
    for i in range(slow, len(values) + 1):
        window = values[:i]
        fast_ema = ema(window, fast)
        slow_ema = ema(window, slow)
        if fast_ema is None or slow_ema is None:
            continue
        macd_series.append(fast_ema - slow_ema)
    if len(macd_series) < signal:
        return None
    macd_line = macd_series[-1]
    signal_line = ema(macd_series, signal)
    if signal_line is None:
        return None
    return {"macd": macd_line, "signal": signal_line, "histogram": macd_line - signal_line}


def compute_indicators(
    closes: Sequence[float], params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compute the strategy's indicator bundle over a close-price series.

    Returns a flat, JSON-serialisable dict of signals (values may be ``None`` when the series is too
    short). ``params`` overrides the default periods (sma_fast/sma_slow/rsi/macd_*).
    """
    p = params or {}
    fast_p = int(p.get("sma_fast", 10))
    slow_p = int(p.get("sma_slow", 30))
    rsi_p = int(p.get("rsi_period", 14))
    closes = list(closes)
    macd_out = macd(
        closes,
        fast=int(p.get("macd_fast", 12)),
        slow=int(p.get("macd_slow", 26)),
        signal=int(p.get("macd_signal", 9)),
    )
    return {
        "price": closes[-1] if closes else None,
        "bars": len(closes),
        "sma_fast": sma(closes, fast_p),
        "sma_slow": sma(closes, slow_p),
        "rsi": rsi(closes, rsi_p),
        "macd": macd_out,
        "params": {"sma_fast": fast_p, "sma_slow": slow_p, "rsi_period": rsi_p},
    }
