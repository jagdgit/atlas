"""Seed FeatureComputers — wrap existing Atlas indicators / ranking inputs.

Missing stays missing (never invent 0). Genealogy fields live on the computer
so FEL.1 can persist them without a new store.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.fel.contracts import FeatureStatus
from atlas.trading.indicators import rsi as rsi_fn
from atlas.trading.indicators import sma as sma_fn


def _closes(pit: dict[str, Any]) -> list[float]:
    raw = pit.get("closes")
    if raw is None:
        raw = pit.get("values")
    if not isinstance(raw, (list, tuple)):
        bars = pit.get("bars")
        if isinstance(bars, list):
            out: list[float] = []
            for bar in bars:
                if isinstance(bar, dict):
                    close = bar.get("close")
                    if close is not None:
                        try:
                            out.append(float(close))
                        except (TypeError, ValueError):
                            continue
            return out
        return []
    out = []
    for v in raw:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _volumes(pit: dict[str, Any]) -> list[float]:
    raw = pit.get("volumes")
    if isinstance(raw, (list, tuple)):
        out: list[float] = []
        for v in raw:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                continue
        return out
    bars = pit.get("bars")
    if isinstance(bars, list):
        out = []
        for bar in bars:
            if isinstance(bar, dict) and bar.get("volume") is not None:
                try:
                    out.append(float(bar["volume"]))
                except (TypeError, ValueError):
                    continue
        return out
    return []


class _SeedComputer:
    sources: tuple[str, ...] = ("bars",)
    timeframe: str = "1d"
    lookback: int = 20
    status: FeatureStatus = "registered"
    origin: str = "wrap"
    hypothesis_id: str | None = None
    scientist_reason: str = "wrap of existing Atlas indicator"
    tested_for: tuple[str, ...] = ("buy_name",)
    derived_from: tuple[str, ...] = ()
    source_concepts: tuple[str, ...] = ()
    formula: str = ""
    availability_time: str = "session_close"


class SmaComputer(_SeedComputer):
    feature_id = "sma"
    version = "1"
    lookback = 20
    formula = "sma(closes, lookback)"
    source_concepts = ("price", "trend")

    def compute(self, pit_context: dict[str, Any]) -> float | None:
        period = int(pit_context.get("period") or self.lookback)
        return sma_fn(_closes(pit_context), period)


class RsiComputer(_SeedComputer):
    feature_id = "rsi"
    version = "1"
    lookback = 14
    formula = "wilder_rsi(closes, lookback)"
    source_concepts = ("price", "momentum")

    def compute(self, pit_context: dict[str, Any]) -> float | None:
        period = int(pit_context.get("period") or self.lookback)
        return rsi_fn(_closes(pit_context), period)


class MomentumComputer(_SeedComputer):
    feature_id = "momentum"
    version = "1"
    lookback = 20
    formula = "0.6*ret(short)+0.4*ret(long)  # ranking._momentum_return"
    scientist_reason = "wrap of ranking short/long return used by ranking_v1"
    source_concepts = ("price", "momentum")

    def compute(self, pit_context: dict[str, Any]) -> float | None:
        from atlas.investment.ranking import _momentum_return

        bars = pit_context.get("bars")
        if not isinstance(bars, list):
            closes = _closes(pit_context)
            bars = [{"close": c} for c in closes]
        short_n = int(pit_context.get("lookback_short") or 5)
        long_n = int(pit_context.get("lookback_long") or self.lookback)
        return _momentum_return(bars, short_n=short_n, long_n=long_n)


class RsVsBenchmarkComputer(_SeedComputer):
    feature_id = "rs_vs_benchmark"
    version = "1"
    lookback = 20
    formula = "ret(symbol, lookback) - ret(benchmark, lookback)"
    scientist_reason = "relative strength vs benchmark (NIFTY when provided)"
    source_concepts = ("price", "relative_strength")
    sources = ("bars", "benchmark_bars")

    def compute(self, pit_context: dict[str, Any]) -> float | None:
        closes = _closes(pit_context)
        bench_ctx = {
            "closes": pit_context.get("benchmark_closes"),
            "bars": pit_context.get("benchmark_bars"),
        }
        bench = _closes(bench_ctx)
        n = int(pit_context.get("period") or self.lookback)
        if len(closes) < n + 1 or len(bench) < n + 1:
            return None
        start_s, last_s = closes[-1 - n], closes[-1]
        start_b, last_b = bench[-1 - n], bench[-1]
        if start_s == 0 or start_b == 0:
            return None
        return (last_s / start_s - 1.0) - (last_b / start_b - 1.0)


class Volume5dComputer(_SeedComputer):
    feature_id = "volume_5d"
    version = "1"
    lookback = 5
    formula = "mean(volumes[-5:])"
    scientist_reason = "short volume window; parent of volume_acceleration"
    source_concepts = ("volume", "liquidity")

    def compute(self, pit_context: dict[str, Any]) -> float | None:
        vols = _volumes(pit_context)
        n = int(pit_context.get("period") or self.lookback)
        if len(vols) < n:
            return None
        window = vols[-n:]
        return sum(window) / n


class Volume20dComputer(_SeedComputer):
    feature_id = "volume_20d"
    version = "1"
    lookback = 20
    formula = "mean(volumes[-20:])"
    scientist_reason = "mean volume lookback; seed for volume_acceleration"
    source_concepts = ("volume", "liquidity")

    def compute(self, pit_context: dict[str, Any]) -> float | None:
        vols = _volumes(pit_context)
        n = int(pit_context.get("period") or self.lookback)
        if len(vols) < n:
            return None
        window = vols[-n:]
        return sum(window) / n


class VolumeAccelerationComputer(_SeedComputer):
    """Candidate for the first named experiment — not promoted, not in the live book."""

    feature_id = "volume_acceleration_20d"
    version = "1"
    lookback = 20
    status: FeatureStatus = "candidate"
    origin = "hypothesis"
    hypothesis_id = "H-buy_name-vol-accel"
    scientist_reason = "Unusual participation may confirm price movement"
    lesson_eligible = True  # CLC.3 — caution only; live_control stays false
    derived_from = ("volume_5d", "volume_20d")
    tested_for = ("buy_name",)
    source_concepts = ("volume", "momentum", "liquidity")
    formula = "mean(volumes[-5:]) / mean(volumes[-20:]) - 1"

    def compute(self, pit_context: dict[str, Any]) -> float | None:
        vols = _volumes(pit_context)
        n = int(pit_context.get("period") or self.lookback)
        short = max(2, n // 4)
        if len(vols) < n:
            return None
        recent = vols[-short:]
        base = vols[-n:]
        mean_recent = sum(recent) / len(recent)
        mean_base = sum(base) / len(base)
        if mean_base == 0:
            return None
        return mean_recent / mean_base - 1.0


def seed_feature_computers() -> list[Any]:
    return [
        SmaComputer(),
        RsiComputer(),
        MomentumComputer(),
        RsVsBenchmarkComputer(),
        Volume5dComputer(),
        Volume20dComputer(),
        VolumeAccelerationComputer(),
    ]
