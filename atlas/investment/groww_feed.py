"""Groww Live Market Data Provider (OI-GROWW0).

Provides real-time LTP, OHLC, and quote data for Indian equities (.NS / .BO)
via the Groww Trade API. Designed for optional integration into Atlas's
MarketDataService with graceful fallback when credentials or the `growwapi`
package are absent.

Rate limits:
  - Live Data REST: 10 req/sec, 300 req/min
  - Websocket Feed: Up to 1,000 instrument subscriptions
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Sequence

_log = logging.getLogger("atlas.investment.groww_feed")


class GrowwMarketFeed:
    """Market feed adapter for Groww Trade API."""

    def __init__(
        self,
        auth_token: str | None = None,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self._auth_token = auth_token
        self._api_key = api_key
        self._api_secret = api_secret
        self._client: Any | None = None
        self._feed: Any | None = None
        self._initialized = False

    @property
    def is_configured(self) -> bool:
        return bool(self._auth_token or (self._api_key and self._api_secret))

    def _init_client(self) -> bool:
        if self._initialized:
            return self._client is not None
        self._initialized = True
        if not self.is_configured:
            return False
        try:
            from growwapi import GrowwAPI  # type: ignore[import-not-found]

            token = self._auth_token or self._api_key or ""
            self._client = GrowwAPI(token)
            return True
        except ImportError:
            _log.debug("growwapi package not installed (`pip install growwapi`)")
            return False
        except Exception as exc:  # noqa: BLE001
            _log.warning("failed to initialize GrowwAPI client: %s", exc)
            return False

    @staticmethod
    def format_symbol(symbol: str) -> str:
        """Convert Atlas symbol (e.g. 'RELIANCE.NS' or 'TCS') to Groww trading symbol."""
        sym = (symbol or "").strip().upper()
        if sym.endswith(".NS"):
            return sym[:-3]
        if sym.endswith(".BO"):
            return sym[:-3]
        return sym

    @staticmethod
    def format_exchange_symbol(symbol: str, exchange: str = "NSE") -> str:
        """Convert Atlas symbol to Groww exchange trading symbol format (e.g. 'NSE_RELIANCE')."""
        clean = GrowwMarketFeed.format_symbol(symbol)
        ex = "BSE" if (symbol or "").upper().endswith(".BO") else exchange
        return f"{ex}_{clean}"

    def get_ltp(
        self, symbols: str | Sequence[str], *, segment: str = "CASH"
    ) -> dict[str, Any]:
        """Fetch Last Traded Price for one or more symbols."""
        if not self._init_client() or self._client is None:
            return {"ok": False, "error": "groww_not_configured"}

        if isinstance(symbols, str):
            sym_list = [symbols]
        else:
            sym_list = list(symbols)

        if not sym_list:
            return {"ok": True, "prices": {}}

        groww_syms = [self.format_exchange_symbol(s) for s in sym_list]
        try:
            # Groww get_ltp accepts single string or tuple of exchange trading symbols
            arg: Any = groww_syms[0] if len(groww_syms) == 1 else tuple(groww_syms)
            resp = self._client.get_ltp(segment=segment, exchange_trading_symbols=arg)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            # Normalize response into symbol -> mark dict
            prices: dict[str, dict[str, Any]] = {}
            if isinstance(resp, dict):
                for raw_sym, orig_sym in zip(groww_syms, sym_list):
                    val = resp.get(raw_sym) or resp.get(self.format_symbol(orig_sym))
                    if isinstance(val, (int, float)):
                        prices[orig_sym] = {
                            "last": float(val),
                            "as_of": now_iso,
                            "source": "groww",
                        }
                    elif isinstance(val, dict) and "ltp" in val:
                        prices[orig_sym] = {
                            "last": float(val["ltp"]),
                            "as_of": now_iso,
                            "source": "groww",
                        }
            return {"ok": True, "prices": prices, "raw": resp}
        except Exception as exc:  # noqa: BLE001
            _log.warning("Groww get_ltp error: %s", exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def get_quote(
        self, symbol: str, *, exchange: str = "NSE", segment: str = "CASH"
    ) -> dict[str, Any]:
        """Fetch full quote for a symbol."""
        if not self._init_client() or self._client is None:
            return {"ok": False, "error": "groww_not_configured"}

        clean = self.format_symbol(symbol)
        ex = "BSE" if (symbol or "").upper().endswith(".BO") else exchange
        try:
            resp = self._client.get_quote(
                exchange=ex, segment=segment, trading_symbol=clean
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            mark = {
                "last": resp.get("ltp") or resp.get("last_price") or resp.get("close"),
                "open": resp.get("open"),
                "high": resp.get("high"),
                "low": resp.get("low"),
                "close": resp.get("close"),
                "volume": resp.get("volume"),
                "as_of": now_iso,
                "source": "groww",
            }
            return {"ok": True, "symbol": symbol, "mark": mark, "raw": resp}
        except Exception as exc:  # noqa: BLE001
            _log.warning("Groww get_quote error for %s: %s", symbol, exc)
            return {"ok": False, "symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
