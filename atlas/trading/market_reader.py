"""MarketReader service — select + normalize feed adapters (MI.3).

Missions ask for bars by symbol/instrument; they do not import concrete adapters.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.decision.rules import CapabilityGap
from atlas.trading.adapters import (
    AlphaVantageAdapter,
    AssetReplayAdapter,
    KeyedProviderAdapter,
    PolygonAdapter,
    StooqAdapter,
    YahooFinanceAdapter,
    pct_move,
)


class MarketReaderService:
    """Facade over Market feed adapters (Market Program)."""

    name = "market_reader"
    VERSION = "mi.3.2"

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
        polygon_opener: Any | None = None,
        alphavantage_opener: Any | None = None,
        stooq_opener: Any | None = None,
        data_dir: str | None = None,
        prefer_durable_bars: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._default = (default_provider or "asset_replay").strip().lower()
        self._logger = logger or logging.getLogger("atlas.trading.market_reader")
        self._data_dir = data_dir
        self._prefer_durable = bool(prefer_durable_bars)
        self._adapters: dict[str, Any] = {}
        if assets is not None and market_data is not None:
            self._adapters["asset_replay"] = AssetReplayAdapter(
                assets=assets, market_data=market_data, logger=self._logger
            )
        self._adapters["yahoo"] = YahooFinanceAdapter(
            enabled=yahoo_enabled,
            opener=yahoo_opener,
            data_dir=data_dir,
            logger=self._logger,
        )
        self._adapters["polygon"] = PolygonAdapter(
            api_key_env=polygon_api_key_env,
            opener=polygon_opener,
            logger=self._logger,
        )
        self._adapters["alphavantage"] = AlphaVantageAdapter(
            api_key_env=alphavantage_api_key_env,
            opener=alphavantage_opener,
            logger=self._logger,
        )
        self._adapters["stooq"] = StooqAdapter(
            opener=stooq_opener, logger=self._logger
        )
        # Indian-exchange adapters stay skeletons until exchange ToS path (OI-D1).
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

    def _durable_yahoo_bars(
        self, symbol: str, *, limit: int, allow_stale: bool = False
    ) -> list[Any] | None:
        """Return durable OHLCV as Bar-like dicts when fresh enough; else None.

        ``allow_stale=True`` — last-resort during Yahoo cooldown: use priced+history
        durable bars even when calendar-freshness failed (honest mark, not invent).
        """
        if not self._prefer_durable or not self._data_dir:
            return None
        try:
            from atlas.investment.bar_store import load_bars, load_symbol_doc, symbol_readiness
            from atlas.investment.symbol_aliases import resolve_yahoo_symbol

            canon = resolve_yahoo_symbol(symbol).canonical or symbol
            doc = load_symbol_doc(self._data_dir, canon)
            if not doc and canon != symbol:
                doc = load_symbol_doc(self._data_dir, symbol)
            if not doc:
                return None
            ready = symbol_readiness(doc, min_history=5, fresh_days=5)
            # Prefer durable when priced+fresh; history soft (ranking may need less).
            ok = bool(ready.get("priced") and ready.get("fresh"))
            if not ok and allow_stale:
                ok = bool(ready.get("priced") and ready.get("history_ok"))
            if not ok:
                return None
            raw = load_bars(self._data_dir, canon, limit=limit) or load_bars(
                self._data_dir, symbol, limit=limit
            )
            if not raw:
                return None
            bars: list[Any] = []
            for b in raw:
                if not isinstance(b, dict) or b.get("close") is None:
                    continue
                try:
                    c = float(b["close"])
                    bars.append(
                        {
                            "t": str(b.get("date") or ""),
                            "date": str(b.get("date") or ""),
                            "open": float(b["open"]) if b.get("open") is not None else c,
                            "high": float(b["high"]) if b.get("high") is not None else c,
                            "low": float(b["low"]) if b.get("low") is not None else c,
                            "close": c,
                            "volume": float(b["volume"]) if b.get("volume") is not None else 0.0,
                        }
                    )
                except (TypeError, ValueError):
                    continue
            return bars or None
        except Exception:  # noqa: BLE001
            self._logger.debug("durable yahoo bars failed for %s", symbol, exc_info=True)
            return None

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
        # OI-MKT-COV: prefer durable bars for yahoo to avoid chart storms / 429.
        if prov == "yahoo":
            durable = self._durable_yahoo_bars(symbol, limit=limit)
            if durable:
                move = pct_move(durable)
                return {
                    "provider": "yahoo_durable",
                    "symbol": symbol,
                    "asset": asset,
                    "bars": durable,
                    "count": len(durable),
                    "pct_move": move,
                    "version": self.VERSION,
                    "source": "durable_bar_store",
                }
            try:
                bars = adapter.fetch_bars(symbol, limit=limit, asset=asset)
            except CapabilityGap as exc:
                # Cooldown / fetch fail → last-resort durable (may be calendar-stale)
                stale = self._durable_yahoo_bars(symbol, limit=limit, allow_stale=True)
                if stale:
                    move = pct_move(stale)
                    return {
                        "provider": "yahoo_durable_stale",
                        "symbol": symbol,
                        "asset": asset,
                        "bars": stale,
                        "count": len(stale),
                        "pct_move": move,
                        "version": self.VERSION,
                        "source": "durable_bar_store_stale",
                        "note": str(exc)[:200],
                    }
                raise
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
