"""Paper-trading building blocks (Phase D · §D.6) — deterministic, simulation-only.

Indicators (pure math over OHLCV bars), the virtual portfolio (cash/positions/trades), and the
:class:`~atlas.trading.strategy.StrategyDecisionRule` that turns indicator signals into a
Decision-Engine choice. Nothing here touches a real broker or real money (P10).
"""

from atlas.trading.indicators import compute_indicators, ema, macd, rsi, sma
from atlas.trading.portfolio import PortfolioService
from atlas.trading.strategy import StrategyDecisionRule

__all__ = [
    "compute_indicators",
    "sma",
    "ema",
    "rsi",
    "macd",
    "PortfolioService",
    "StrategyDecisionRule",
]
