"""MarketReader service — select + normalize feed adapters (MI.3).

Missions ask for bars by symbol/instrument; they do not import concrete adapters.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.decision.rules import CapabilityGap
from atlas.trading.adapters import (
    AssetReplayAdapter,
    KeyedProviderAdapter,
    YahooFinanceAdapter,
    pct_move,
)


class MarketReaderService:
    """Facade over Market feed adapters (Market Program)."""

    name = "market_reader"
    VERSION = "mi.3"

    def __init__(
        self,
        *,
        assets: Any | None = None,
        market_data: Any | None = None,
        default_provider: str = "asset_replay",
        yahoo_enabled: bool = False,
        polygon_api_key_env: str = "ATLAS_POLYGON_API_KEY",
        alphavantage_api_key_env: str = "ATLAS_ALPHAVANTAGE_API_KEY",
        yahoo_opener: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._default = (default_provider or "asset_replay").strip().lower()
        self._logger = logger or logging.getLogger("atlas.trading.market_reader")
        self._adapters: dict[str, Any] = {}
        if assets is not None and market_data is not None:
            self._adapters["asset_replay"] = AssetReplayAdapter(
                assets=assets, market_data=market_data, logger=self._logger
            )
        self._adapters["yahoo"] = YahooFinanceAdapter(
            enabled=yahoo_enabled, opener=yahoo_opener, logger=self._logger
        )
        self._adapters["polygon"] = KeyedProviderAdapter(
            "polygon", api_key_env=polygon_api_key_env, logger=self._logger
        )
        self._adapters["alphavantage"] = KeyedProviderAdapter(
            "alphavantage", api_key_env=alphavantage_api_key_env, logger=self._logger
        )
        # Aliases for planned Indian-exchange adapters (same skeleton until ToS path).
        self._adapters["nse"] = KeyedProviderAdapter(
            "nse", api_key_env="ATLAS_NSE_API_KEY", logger=self._logger
        )
        self._adapters["bse"] = KeyedProviderAdapter(
            "bse", api_key_env="ATLAS_BSE_API_KEY", logger=self._logger
        )

    def list_providers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "registered": True,
                "default": name == self._default,
            }
            for name in sorted(self._adapters)
        ]

    def bars_for(
        self,
        symbol: str,
        *,
        provider: str | None = None,
        asset: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch normalized bars; never fabricates data on failure (P15)."""
        prov = (provider or self._default or "asset_replay").strip().lower()
        # Prefer asset replay when an asset name is supplied.
        if asset and "asset_replay" in self._adapters:
            prov = "asset_replay"
        adapter = self._adapters.get(prov)
        if adapter is None:
            raise CapabilityGap(
                f"market_data:{prov}",
                f"unknown MarketReader provider '{prov}' — known: {sorted(self._adapters)}",
            )
        bars = adapter.fetch_bars(symbol, limit=limit, asset=asset)
        move = pct_move(bars)
        return {
            "provider": prov,
            "symbol": symbol,
            "asset": asset,
            "bars": bars,
            "count": len(bars),
            "pct_move": move,
            "version": self.VERSION,
        }
