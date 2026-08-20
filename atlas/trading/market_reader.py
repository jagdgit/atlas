"""MarketReader service — select + normalize feed adapters (MI.3).

Missions ask for bars by symbol/instrument; they do not import concrete adapters.
"""

from __future__ import annotations

import logging
import time
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
    VERSION = "mi.3.4-stab0-session-fresh"
    # Paced tip refresh: enough for open-book marks, not a watchlist Yahoo storm.
    REFRESH_WINDOW_S = 60.0
    REFRESH_MAX_PER_WINDOW = 3

    def __init__(
        self,
        *,
        assets: Any | None = None,
        market_data: Any | None = None,
        market_data_service: Any | None = None,
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
        self._mds = market_data_service
        self._refresh_times: list[float] = []
        self._intraday_cache: dict[str, tuple[float, dict[str, Any]]] = {}
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

    def bind_market_data_service(self, mds: Any | None) -> None:
        """OI-STAB0 — attach MarketDataService for tip cache + Yahoo audit."""
        self._mds = mds

    def _note_mds(
        self,
        symbol: str,
        *,
        source: str,
        bars: list[Any] | None,
        worker: str = "market_reader",
    ) -> None:
        mds = self._mds
        if mds is None and self._data_dir:
            try:
                from atlas.investment.market_data_service import get_market_data_service

                mds = get_market_data_service(self._data_dir)
                self._mds = mds
            except Exception:  # noqa: BLE001
                return
        if mds is None or not hasattr(mds, "note_bars"):
            return
        try:
            mds.note_bars(symbol, source=source, bars=bars, worker=worker)
        except Exception:  # noqa: BLE001
            self._logger.debug("market_data note_bars failed", exc_info=True)

    def list_providers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "registered": True,
                "default": name == self._default,
            }
            for name in sorted(self._adapters)
        ]

    def _yahoo_cooldown_s(self) -> float:
        if not self._data_dir:
            return 0.0
        try:
            from atlas.investment.yahoo_fundamentals import get_yahoo_rate_gate

            return float(get_yahoo_rate_gate(self._data_dir).remaining_cooldown_s() or 0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _may_network_refresh(self) -> bool:
        if self._yahoo_cooldown_s() > 0:
            return False
        now = time.time()
        self._refresh_times = [
            t for t in self._refresh_times if now - t < self.REFRESH_WINDOW_S
        ]
        return len(self._refresh_times) < self.REFRESH_MAX_PER_WINDOW

    def _note_network_refresh(self) -> None:
        self._refresh_times.append(time.time())

    def _yahoo_intraday_bars(
        self,
        symbol: str,
        *,
        adapter: Any,
        asset: str | None,
        limit: int,
        interval: str,
        range: str,
    ) -> dict[str, Any]:
        """LOOP0 L5 — 5m chart into bars_intraday, never daily market/bars."""
        from atlas.investment.intraday_bars import (
            CACHE_TTL_S,
            INTERVAL,
            load_day_bars,
            persist_day_bars,
        )

        iv = interval if interval in {"5m", "1m"} else INTERVAL
        cache_key = f"{symbol}|{iv}|{range}"
        now = time.time()
        hit = self._intraday_cache.get(cache_key)
        if hit is not None and (now - hit[0]) < CACHE_TTL_S:
            cached = dict(hit[1])
            cached["note"] = "intraday_cache"
            return cached

        persisted = load_day_bars(self._data_dir, symbol, limit=limit) if self._data_dir else []
        network_note = ""
        bars: list[Any] | None = None
        if self._may_network_refresh():
            try:
                self._note_network_refresh()
                bars = adapter.fetch_bars(
                    symbol,
                    limit=max(int(limit or 0), 80),
                    asset=asset,
                    range=range or "1d",
                    interval=iv,
                )
            except CapabilityGap as exc:
                network_note = str(exc)[:200]
                bars = None
        else:
            cool = self._yahoo_cooldown_s()
            network_note = (
                f"yahoo_cooldown {cool:.0f}s" if cool > 0 else "refresh_budget"
            )

        if bars:
            if self._data_dir:
                try:
                    persist_day_bars(
                        self._data_dir,
                        symbol,
                        list(bars),
                        provider="yahoo",
                        interval=iv,
                    )
                except Exception:  # noqa: BLE001
                    self._logger.debug("persist 5m bars failed for %s", symbol, exc_info=True)
            move = pct_move(bars)
            clipped = bars[-max(1, int(limit)) :] if limit else bars
            doc = {
                "provider": "yahoo",
                "symbol": symbol,
                "asset": asset,
                "bars": clipped,
                "count": len(clipped),
                "pct_move": move,
                "version": self.VERSION,
                "source": "yahoo_intraday",
                "interval": iv,
                "note": "session_5m" if iv == "5m" else f"session_{iv}",
            }
            self._intraday_cache[cache_key] = (now, dict(doc))
            self._note_mds(symbol, source="yahoo_intraday", bars=clipped, worker="market_reader")
            return doc

        if persisted:
            move = pct_move(persisted)
            doc = {
                "provider": "yahoo_intraday_stale",
                "symbol": symbol,
                "asset": asset,
                "bars": persisted,
                "count": len(persisted),
                "pct_move": move,
                "version": self.VERSION,
                "source": "bars_intraday_stale",
                "interval": iv,
                "note": network_note or "stale_intraday_fallback",
            }
            self._intraday_cache[cache_key] = (now, dict(doc))
            self._note_mds(
                symbol, source="bars_intraday_stale", bars=persisted, worker="market_reader"
            )
            return doc

        raise CapabilityGap(
            "market_data:yahoo",
            network_note or "no 5m bars and yahoo refresh unavailable",
        )

    def _persist_fetched_bars(self, symbol: str, bars: list[Any] | None) -> None:
        if not self._data_dir or not bars:
            return
        try:
            from atlas.investment.bar_store import persist_symbol_bars

            persist_symbol_bars(self._data_dir, symbol, list(bars), provider="yahoo")
        except Exception:  # noqa: BLE001
            self._logger.debug("persist yahoo tip failed for %s", symbol, exc_info=True)

    def _durable_yahoo_bars(
        self,
        symbol: str,
        *,
        limit: int,
        allow_stale: bool = False,
        require_session_fresh: bool = False,
    ) -> list[Any] | None:
        """Return durable OHLCV as Bar-like dicts when fresh enough; else None.

        ``require_session_fresh`` — last bar date ≥ last completed NSE session.
        ``allow_stale=True`` — last-resort during Yahoo cooldown: use priced+history
        durable bars even when freshness failed (honest mark, not invent).
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
            if require_session_fresh:
                ok = bool(ready.get("priced") and ready.get("session_fresh"))
            else:
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
        interval: str | None = None,
        range: str | None = None,
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
        iv = str(interval or "1d").strip().lower() or "1d"
        if prov == "yahoo" and iv in {"5m", "1m"}:
            return self._yahoo_intraday_bars(
                symbol,
                adapter=adapter,
                asset=asset,
                limit=limit,
                interval=iv,
                range=str(range or "1d"),
            )
        # OI-MKT-COV / OI-STAB0: session-fresh durable first. If the tip is older
        # than the last NSE session, paced Yahoo refresh + persist (paper sim
        # must mark live). Cooldown / budget → honest stale durable, never invent.
        if prov == "yahoo":
            session_bars = self._durable_yahoo_bars(
                symbol, limit=limit, require_session_fresh=True
            )
            if session_bars:
                move = pct_move(session_bars)
                self._note_mds(
                    symbol,
                    source="durable_bar_store",
                    bars=session_bars,
                    worker="market_reader",
                )
                return {
                    "provider": "yahoo_durable",
                    "symbol": symbol,
                    "asset": asset,
                    "bars": session_bars,
                    "count": len(session_bars),
                    "pct_move": move,
                    "version": self.VERSION,
                    "source": "durable_bar_store",
                    "note": "session_fresh",
                }
            network_note = ""
            if self._may_network_refresh():
                try:
                    self._note_network_refresh()
                    bars = adapter.fetch_bars(
                        symbol,
                        limit=max(int(limit or 0), 40),
                        asset=asset,
                        range="2mo",
                        interval="1d",
                    )
                    if bars:
                        self._persist_fetched_bars(symbol, bars)
                        move = pct_move(bars)
                        self._note_mds(
                            symbol,
                            source="yahoo_network",
                            bars=bars,
                            worker="market_reader",
                        )
                        return {
                            "provider": prov,
                            "symbol": symbol,
                            "asset": asset,
                            "bars": bars,
                            "count": len(bars),
                            "pct_move": move,
                            "version": self.VERSION,
                            "source": "yahoo_network",
                            "note": "session_tip_refresh",
                        }
                    network_note = "yahoo_empty"
                except CapabilityGap as exc:
                    network_note = str(exc)[:200]
            else:
                cool = self._yahoo_cooldown_s()
                network_note = (
                    f"yahoo_cooldown {cool:.0f}s"
                    if cool > 0
                    else "refresh_budget"
                )
            stale = self._durable_yahoo_bars(symbol, limit=limit, allow_stale=True)
            if stale:
                move = pct_move(stale)
                self._note_mds(
                    symbol,
                    source="durable_bar_store_stale",
                    bars=stale,
                    worker="market_reader",
                )
                return {
                    "provider": "yahoo_durable_stale",
                    "symbol": symbol,
                    "asset": asset,
                    "bars": stale,
                    "count": len(stale),
                    "pct_move": move,
                    "version": self.VERSION,
                    "source": "durable_bar_store_stale",
                    "note": network_note or "stale_durable_fallback",
                }
            if network_note:
                raise CapabilityGap(
                    "market_data:yahoo",
                    network_note or "no durable bars and yahoo refresh unavailable",
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
