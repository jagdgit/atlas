"""Market feed adapters (MI.3 / OI-D1) — Market Program domain, not platform OS.

Normalize OHLCV bars from swappable sources. Default is hermetic asset replay
(fixture/CSV via :class:`~atlas.readers.market_data.MarketDataReader`). Live
providers are opt-in and raise :class:`~atlas.decision.rules.CapabilityGap`
when keys or network are unavailable (P15 honesty).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

from atlas.decision.rules import CapabilityGap

# Normalized bar shape (same as MarketDataReader artifact bars).
Bar = dict[str, Any]


@runtime_checkable
class MarketFeedAdapter(Protocol):
    """One OHLCV source behind MarketReader."""

    name: str

    def fetch_bars(self, symbol: str, *, limit: int = 100, **kwargs: Any) -> list[Bar]:
        """Return newest-last bars for ``symbol`` (may be empty)."""


class AssetReplayAdapter:
    """Replay bars from a ``market_data`` Asset via MarketDataReader (DD6 default)."""

    name = "asset_replay"

    def __init__(
        self,
        *,
        assets: Any,
        market_data: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._reader = market_data
        self._logger = logger or logging.getLogger("atlas.trading.adapters.asset_replay")

    def fetch_bars(
        self,
        symbol: str,
        *,
        limit: int = 100,
        asset: str | None = None,
        **kwargs: Any,
    ) -> list[Bar]:
        asset_name = (asset or symbol or "").strip()
        if not asset_name:
            raise CapabilityGap(
                "market_data:asset",
                "asset_replay needs an asset name (or instruments[].asset)",
            )
        row = self._resolve_asset(asset_name)
        if row is None:
            raise CapabilityGap(
                f"market_data:asset:{asset_name}",
                f"no market_data asset named '{asset_name}' — register sample feed first",
            )
        artifact = self._reader.read(str(row["id"]))
        if artifact.get("outcome") != "ok":
            raise CapabilityGap(
                f"market_data:read:{asset_name}",
                str(artifact.get("reason") or artifact.get("outcome") or "read failed"),
            )
        bars = list(artifact.get("bars") or [])
        if limit > 0:
            bars = bars[-limit:]
        return bars

    def _resolve_asset(self, name: str) -> dict[str, Any] | None:
        get = getattr(self._assets, "get_by_name", None)
        if callable(get):
            try:
                row = get("market_data", name)
            except TypeError:
                row = get(name)
            if row:
                if isinstance(row, dict):
                    return row
                return {
                    "id": getattr(row, "id", None),
                    "name": getattr(row, "name", name),
                    "kind": getattr(row, "kind", "market_data"),
                }
        return None


class YahooFinanceAdapter:
    """Opt-in live tape via Yahoo chart API (no API key; network required)."""

    name = "yahoo"
    CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    def __init__(
        self,
        *,
        enabled: bool = False,
        timeout: float = 20.0,
        opener: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._timeout = float(timeout)
        self._opener = opener  # injectable for tests: callable(url) -> dict
        self._logger = logger or logging.getLogger("atlas.trading.adapters.yahoo")

    def fetch_bars(
        self, symbol: str, *, limit: int = 100, **kwargs: Any
    ) -> list[Bar]:
        sym = (symbol or "").strip()
        if not sym:
            return []
        if not self._enabled:
            raise CapabilityGap(
                "market_data:yahoo",
                "yahoo provider disabled — set market.yahoo_enabled: true to opt in (OI-D1)",
            )
        url = self.CHART_URL.format(symbol=sym) + f"?interval=1d&range=3mo"
        try:
            payload = self._fetch_json(url)
        except CapabilityGap:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CapabilityGap(
                "market_data:yahoo",
                f"fetch failed for {sym}: {exc}",
            ) from exc
        bars = self._parse_chart(payload)
        if limit > 0:
            bars = bars[-limit:]
        return bars

    def _fetch_json(self, url: str) -> dict[str, Any]:
        if self._opener is not None:
            data = self._opener(url)
            return data if isinstance(data, dict) else json.loads(data)
        import httpx

        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": "AtlasMarketReader/1.0"},
        ) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                raise CapabilityGap(
                    "market_data:yahoo",
                    f"HTTP {resp.status_code} from Yahoo chart API",
                )
            return resp.json()

    @staticmethod
    def _parse_chart(payload: dict[str, Any]) -> list[Bar]:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return []
        row = result[0] or {}
        timestamps = row.get("timestamp") or []
        quote = ((row.get("indicators") or {}).get("quote") or [{}])[0] or {}
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        bars: list[Bar] = []
        for i, ts in enumerate(timestamps):
            close = closes[i] if i < len(closes) else None
            if close is None:
                continue
            try:
                c = float(close)
            except (TypeError, ValueError):
                continue
            bars.append(
                {
                    "t": ts,
                    "open": float(opens[i]) if i < len(opens) and opens[i] is not None else c,
                    "high": float(highs[i]) if i < len(highs) and highs[i] is not None else c,
                    "low": float(lows[i]) if i < len(lows) and lows[i] is not None else c,
                    "close": c,
                    "volume": float(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0.0,
                }
            )
        return bars


class KeyedProviderAdapter:
    """Placeholder for Polygon / Alpha Vantage / NSE — requires API key env."""

    def __init__(
        self,
        name: str,
        *,
        api_key_env: str,
        enabled: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self._api_key_env = api_key_env
        self._enabled = enabled
        self._logger = logger or logging.getLogger(f"atlas.trading.adapters.{name}")

    def fetch_bars(
        self, symbol: str, *, limit: int = 100, **kwargs: Any
    ) -> list[Bar]:
        if not self._enabled:
            raise CapabilityGap(
                f"market_data:{self.name}",
                f"{self.name} provider disabled in config",
            )
        key = (os.environ.get(self._api_key_env) or "").strip()
        if not key:
            raise CapabilityGap(
                f"market_data:{self.name}",
                f"set {self._api_key_env} to enable live {self.name} feeds (OI-D1)",
            )
        # Keys present but live client not wired yet — still honest.
        raise CapabilityGap(
            f"market_data:{self.name}",
            f"{self.name} adapter skeleton — key detected; live client lands with exchange ToS path",
        )


def pct_move(bars: list[Bar]) -> float | None:
    """Percent change from first to last close; None if insufficient data."""
    if len(bars) < 2:
        return None
    try:
        first = float(bars[0]["close"])
        last = float(bars[-1]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if first == 0:
        return None
    return ((last - first) / first) * 100.0
