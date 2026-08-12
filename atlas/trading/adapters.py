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
    """Opt-in live tape via Yahoo chart API (no API key; network required).

    Shares the fundamentals rate gate / cooldown so chart bursts do not starve
    quoteSummary (OI-RLD Yahoo IP budget).
    """

    name = "yahoo"
    CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    def __init__(
        self,
        *,
        enabled: bool = False,
        timeout: float = 20.0,
        opener: Any | None = None,
        cache_ttl_s: float = 300.0,
        data_dir: str | None = None,
        rate_gate: Any | None = None,
        chart_interval_s: float = 0.85,
        logger: logging.Logger | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._timeout = float(timeout)
        self._opener = opener  # injectable for tests: callable(url) -> dict
        # TTL cache cuts chart storms (paper ticks every ~15s) so fundamentals
        # crumb recovery is not starved by the same IP.
        self._cache_ttl_s = max(0.0, float(cache_ttl_s))
        self._cache: dict[str, tuple[float, list[Bar]]] = {}
        self._data_dir = data_dir
        self._chart_interval_s = max(0.05, float(chart_interval_s))
        self._logger = logger or logging.getLogger("atlas.trading.adapters.yahoo")
        self._gate = rate_gate
        if self._gate is None and opener is None and data_dir:
            try:
                from atlas.investment.yahoo_fundamentals import get_yahoo_rate_gate

                self._gate = get_yahoo_rate_gate(data_dir)
            except Exception:  # noqa: BLE001
                self._gate = None

    def fetch_bars(
        self, symbol: str, *, limit: int = 100, **kwargs: Any
    ) -> list[Bar]:
        import time

        from atlas.investment.symbol_aliases import resolve_yahoo_symbol

        requested = (symbol or "").strip()
        if not requested:
            return []
        resolved = resolve_yahoo_symbol(requested)
        sym = resolved.yahoo
        cache_key = f"{resolved.canonical or sym}|{kwargs.get('range') or '3mo'}|{kwargs.get('interval') or '1d'}"
        if not sym:
            return []
        if not self._enabled:
            raise CapabilityGap(
                "market_data:yahoo",
                "yahoo provider disabled — set market.yahoo_enabled: true to opt in (OI-D1)",
            )
        now = time.time()
        hit = self._cache.get(cache_key)
        if (
            self._cache_ttl_s > 0
            and hit is not None
            and (now - hit[0]) < self._cache_ttl_s
        ):
            bars = list(hit[1])
            if limit > 0:
                bars = bars[-limit:]
            return bars
        # During fundamentals 429 cooldown: refuse network (caller uses durable).
        if self._gate is not None and self._opener is None:
            rem = float(self._gate.remaining_cooldown_s() or 0)
            if rem > 0:
                raise CapabilityGap(
                    "market_data:yahoo",
                    f"yahoo chart paused — rate-gate cooldown {rem:.0f}s "
                    "(prefer durable market/bars)",
                )
            try:
                self._gate.wait_chart(chart_interval_s=self._chart_interval_s)
            except Exception:  # noqa: BLE001
                pass
        url = self.CHART_URL.format(symbol=sym) + (
            f"?interval={str(kwargs.get('interval') or '1d')}"
            f"&range={str(kwargs.get('range') or '3mo')}"
        )
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
        if self._cache_ttl_s > 0:
            self._cache[cache_key] = (now, list(bars))
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
            if resp.status_code in {429, 401, 403} and self._gate is not None:
                try:
                    self._gate.on_block(resp.status_code)
                except Exception:  # noqa: BLE001
                    pass
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


class AlphaVantageAdapter:
    """Live daily OHLCV via Alpha Vantage when ``ATLAS_ALPHAVANTAGE_API_KEY`` is set."""

    name = "alphavantage"
    QUERY_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        *,
        api_key_env: str = "ATLAS_ALPHAVANTAGE_API_KEY",
        enabled: bool = True,
        timeout: float = 25.0,
        opener: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._api_key_env = api_key_env
        self._enabled = enabled
        self._timeout = float(timeout)
        self._opener = opener
        self._logger = logger or logging.getLogger("atlas.trading.adapters.alphavantage")

    def fetch_bars(
        self, symbol: str, *, limit: int = 100, **kwargs: Any
    ) -> list[Bar]:
        sym = (symbol or "").strip()
        if not sym:
            return []
        if not self._enabled:
            raise CapabilityGap(
                "market_data:alphavantage",
                "alphavantage provider disabled in config",
            )
        key = (os.environ.get(self._api_key_env) or "").strip()
        if not key:
            raise CapabilityGap(
                "market_data:alphavantage",
                f"set {self._api_key_env} to enable live Alpha Vantage feeds (OI-D1)",
            )
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": sym,
            "outputsize": "compact",
            "apikey": key,
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.QUERY_URL}?{qs}"
        try:
            payload = self._fetch_json(url)
        except CapabilityGap:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CapabilityGap(
                "market_data:alphavantage",
                f"fetch failed for {sym}: {exc}",
            ) from exc
        if isinstance(payload, dict) and payload.get("Note"):
            raise CapabilityGap(
                "market_data:alphavantage",
                f"Alpha Vantage rate limit / note: {payload.get('Note')}",
            )
        if isinstance(payload, dict) and payload.get("Error Message"):
            raise CapabilityGap(
                "market_data:alphavantage",
                str(payload.get("Error Message")),
            )
        bars = self._parse_daily(payload)
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
                    "market_data:alphavantage",
                    f"HTTP {resp.status_code} from Alpha Vantage",
                )
            return resp.json()

    @staticmethod
    def _parse_daily(payload: dict[str, Any]) -> list[Bar]:
        series = payload.get("Time Series (Daily)") or {}
        if not isinstance(series, dict) or not series:
            return []
        # API returns newest-first keyed by YYYY-MM-DD; emit oldest→newest.
        bars: list[Bar] = []
        for day in sorted(series.keys()):
            row = series.get(day) or {}
            try:
                o = float(row.get("1. open"))
                h = float(row.get("2. high"))
                low = float(row.get("3. low"))
                c = float(row.get("4. close"))
                vol = float(row.get("5. volume") or 0.0)
            except (TypeError, ValueError):
                continue
            bars.append(
                {"t": day, "open": o, "high": h, "low": low, "close": c, "volume": vol}
            )
        return bars


class PolygonAdapter:
    """Live daily aggregates via Polygon.io when ``ATLAS_POLYGON_API_KEY`` is set."""

    name = "polygon"
    AGGS_URL = (
        "https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
    )

    def __init__(
        self,
        *,
        api_key_env: str = "ATLAS_POLYGON_API_KEY",
        enabled: bool = True,
        timeout: float = 25.0,
        lookback_days: int = 90,
        opener: Any | None = None,
        clock: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._api_key_env = api_key_env
        self._enabled = enabled
        self._timeout = float(timeout)
        self._lookback_days = max(5, int(lookback_days))
        self._opener = opener
        self._clock = clock  # injectable date for tests: callable() -> date
        self._logger = logger or logging.getLogger("atlas.trading.adapters.polygon")

    def fetch_bars(
        self, symbol: str, *, limit: int = 100, **kwargs: Any
    ) -> list[Bar]:
        sym = (symbol or "").strip().upper()
        if not sym:
            return []
        if not self._enabled:
            raise CapabilityGap(
                "market_data:polygon",
                "polygon provider disabled in config",
            )
        key = (os.environ.get(self._api_key_env) or "").strip()
        if not key:
            raise CapabilityGap(
                "market_data:polygon",
                f"set {self._api_key_env} to enable live Polygon feeds (OI-D1)",
            )
        end, start = self._window()
        url = self.AGGS_URL.format(symbol=sym, start=start, end=end)
        url = f"{url}?adjusted=true&sort=asc&limit=50000&apiKey={key}"
        try:
            payload = self._fetch_json(url)
        except CapabilityGap:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CapabilityGap(
                "market_data:polygon",
                f"fetch failed for {sym}: {exc}",
            ) from exc
        status = str(payload.get("status") or "").lower()
        if status and status not in {"ok", "delayed"}:
            raise CapabilityGap(
                "market_data:polygon",
                f"Polygon status={payload.get('status')!r} for {sym}",
            )
        bars = self._parse_aggs(payload)
        if limit > 0:
            bars = bars[-limit:]
        return bars

    def _window(self) -> tuple[str, str]:
        from datetime import date, timedelta

        today = self._clock() if self._clock is not None else date.today()
        start = today - timedelta(days=self._lookback_days)
        return today.isoformat(), start.isoformat()

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
                    "market_data:polygon",
                    f"HTTP {resp.status_code} from Polygon",
                )
            return resp.json()

    @staticmethod
    def _parse_aggs(payload: dict[str, Any]) -> list[Bar]:
        rows = payload.get("results") or []
        bars: list[Bar] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                c = float(row["c"])
            except (KeyError, TypeError, ValueError):
                continue
            bars.append(
                {
                    "t": row.get("t"),
                    "open": float(row["o"]) if row.get("o") is not None else c,
                    "high": float(row["h"]) if row.get("h") is not None else c,
                    "low": float(row["l"]) if row.get("l") is not None else c,
                    "close": c,
                    "volume": float(row.get("v") or 0.0),
                }
            )
        return bars


class StooqAdapter:
    """Free daily history via Stooq CSV (no API key). Opt-in by selecting provider=stooq.

    India NSE: SYMBOL.NS → symbol.in on Stooq. US bare symbols → symbol.us.
    """

    name = "stooq"
    CSV_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        opener: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._timeout = float(timeout)
        self._opener = opener  # callable(url) -> str/bytes CSV
        self._logger = logger or logging.getLogger("atlas.trading.adapters.stooq")

    def fetch_bars(
        self, symbol: str, *, limit: int = 100, **kwargs: Any
    ) -> list[Bar]:
        sym = (symbol or "").strip()
        if not sym:
            return []
        stooq_sym = self.to_stooq_symbol(sym)
        url = self.CSV_URL.format(symbol=stooq_sym)
        try:
            text = self._fetch_text(url)
        except CapabilityGap:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CapabilityGap(
                "market_data:stooq",
                f"fetch failed for {sym} ({stooq_sym}): {exc}",
            ) from exc
        bars = self._parse_csv(text)
        if not bars:
            raise CapabilityGap(
                "market_data:stooq",
                f"no bars for {sym} (stooq={stooq_sym}) — check symbol mapping",
            )
        if limit > 0:
            bars = bars[-limit:]
        return bars

    @staticmethod
    def to_stooq_symbol(symbol: str) -> str:
        s = (symbol or "").strip().upper()
        if s.endswith(".NS"):
            return f"{s[:-3].lower()}.in"
        if s.endswith(".BO"):
            return f"{s[:-3].lower()}.in"
        if "." in s:
            return s.lower()
        # Bare tickers: assume US on Stooq
        return f"{s.lower()}.us"

    def _fetch_text(self, url: str) -> str:
        if self._opener is not None:
            data = self._opener(url)
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")
            return str(data)
        import httpx

        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": "AtlasMarketReader/1.0"},
        ) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                raise CapabilityGap(
                    "market_data:stooq",
                    f"HTTP {resp.status_code} from Stooq",
                )
            return resp.text

    @staticmethod
    def _parse_csv(text: str) -> list[Bar]:
        import csv
        import io
        from datetime import datetime, timezone

        raw = (text or "").strip()
        if not raw or raw.lower().startswith("<!"):
            return []
        reader = csv.DictReader(io.StringIO(raw))
        bars: list[Bar] = []
        for row in reader:
            if not isinstance(row, dict):
                continue
            # Stooq headers: Date,Open,High,Low,Close,Volume
            date_s = row.get("Date") or row.get("date")
            close_s = row.get("Close") or row.get("close")
            if not date_s or close_s is None or close_s == "":
                continue
            try:
                c = float(close_s)
                dt = datetime.strptime(str(date_s).strip()[:10], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                ts = int(dt.timestamp())
            except (TypeError, ValueError):
                continue

            def _f(key: str, fallback: float) -> float:
                v = row.get(key) or row.get(key.lower())
                if v is None or v == "":
                    return fallback
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return fallback

            bars.append(
                {
                    "t": ts,
                    "open": _f("Open", c),
                    "high": _f("High", c),
                    "low": _f("Low", c),
                    "close": c,
                    "volume": _f("Volume", 0.0),
                }
            )
        return bars


class KeyedProviderAdapter:
    """Placeholder for NSE / BSE — requires API key + exchange ToS path (OI-D1)."""

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
        # Keys present but exchange ToS / live client not wired yet — still honest.
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
