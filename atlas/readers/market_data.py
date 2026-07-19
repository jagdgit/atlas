"""Market-data Reader (Phase D · PHASE_D_PLAN §D.6, BB-D6 / constitution P8/P11).

Market data enters Atlas the same way every other source does: as an **Asset**, read by a stateless
**Reader** into an **Artifact** (``Asset → Reader → Artifact``, P8/P11). This reader turns an OHLCV
fixture/replay asset (a ``.json`` list of bars or a ``.csv``) into a normalized bar artifact the
Paper-Trading worker replays. It owns no knowledge or state (P11): it reads bytes and returns an
artifact, cached in the Derived Artifact Store keyed by ``{asset_id, asset_version, reader,
reader_version}`` (BB11) so re-reading an unchanged feed is a cheap cache hit. Config-swappable to a
live feed later (DD6) — the worker only depends on the artifact shape, not the source.

Accepted bar shapes (heterogeneous fixtures, tolerant parsing):
  * ``.json`` — a list of ``{t/date, o/open, h/high, l/low, c/close, v/volume}`` objects, or an object
    with a ``bars``/``candles``/``data`` list;
  * ``.csv``  — a header row naming the columns (``date,open,high,low,close,volume`` in any order).
Rows missing a usable close are skipped; a bad feed is reported (``outcome != "ok"``), never fatal.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

MARKET_DATA_READER_ID = "market_data"
MARKET_DATA_READER_VERSION = "1.0.0"

_SUPPORTED_EXTENSIONS = (".json", ".csv")
_BAR_LIST_KEYS = ("bars", "candles", "data", "ohlcv", "prices")
_CLOSE_KEYS = ("close", "c", "adj_close", "adjclose", "price")
_OPEN_KEYS = ("open", "o")
_HIGH_KEYS = ("high", "h")
_LOW_KEYS = ("low", "l")
_VOL_KEYS = ("volume", "v", "vol")
_TIME_KEYS = ("t", "time", "timestamp", "date", "datetime")


class MarketDataReader:
    """Read an OHLCV feed asset → cached bar artifact (BB11); reuse when unchanged."""

    id = MARKET_DATA_READER_ID
    VERSION = MARKET_DATA_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts  # DerivedArtifactStore (duck-typed: get/put)
        self._logger = logger or logging.getLogger("atlas.readers.market_data")

    def supported_extensions(self) -> list[str]:
        return list(_SUPPORTED_EXTENSIONS)

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        version = self._resolve_version(asset_id, asset_version)
        if not force:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None:
                return cached
        filename = filename or self._filename_from_metadata(asset_id, version)
        data = self._assets.get_bytes(asset_id, version)
        artifact = self._extract(data, filename, asset_id, version)
        self._artifacts.put(asset_id, version, self.id, self.VERSION, artifact)
        return artifact

    # --- internals ------------------------------------------------------
    def _extract(
        self, data: bytes, filename: str | None, asset_id: str, version: int
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower() if filename else ""
        base = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "content_type": "application/json",
            "extension": suffix,
        }
        if suffix and suffix not in _SUPPORTED_EXTENSIONS:
            return {**base, "outcome": "unsupported", "bars": [], "count": 0,
                    "reason": f"unsupported market-data format: {suffix}"}
        try:
            raw = data.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {**base, "outcome": "error", "bars": [], "count": 0,
                    "reason": f"decode failed: {exc}"}
        try:
            bars = self._parse_csv(raw) if suffix == ".csv" else self._parse_json(raw)
        except Exception as exc:  # noqa: BLE001 - a malformed feed is reported, never fatal
            return {**base, "outcome": "error", "bars": [], "count": 0,
                    "reason": f"parse failed: {exc}"}
        if not bars:
            return {**base, "outcome": "empty", "bars": [], "count": 0,
                    "reason": "no usable bars (missing close prices)"}
        return {
            **base,
            "outcome": "ok",
            "reason": None,
            "bars": bars,
            "count": len(bars),
            "symbol": self._symbol_hint(asset_id, version),
        }

    def _parse_json(self, raw: str) -> list[dict[str, Any]]:
        raw = raw.strip()
        if not raw:
            return []
        doc = json.loads(raw)
        rows: list[Any]
        if isinstance(doc, dict):
            rows = []
            for key in _BAR_LIST_KEYS:
                if isinstance(doc.get(key), list):
                    rows = doc[key]
                    break
        elif isinstance(doc, list):
            rows = doc
        else:
            rows = []
        return [bar for bar in (self._normalize(r) for r in rows) if bar is not None]

    def _parse_csv(self, raw: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(raw))
        return [bar for bar in (self._normalize(r) for r in reader) if bar is not None]

    def _normalize(self, row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        lower = {str(k).strip().lower(): v for k, v in row.items()}
        close = self._first_float(lower, _CLOSE_KEYS)
        if close is None:
            return None
        return {
            "t": self._first_any(lower, _TIME_KEYS),
            "open": self._first_float(lower, _OPEN_KEYS, default=close),
            "high": self._first_float(lower, _HIGH_KEYS, default=close),
            "low": self._first_float(lower, _LOW_KEYS, default=close),
            "close": close,
            "volume": self._first_float(lower, _VOL_KEYS, default=0.0),
        }

    @staticmethod
    def _first_float(row: dict[str, Any], keys: tuple[str, ...], *, default: float | None = None) -> float | None:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                try:
                    return float(row[key])
                except (TypeError, ValueError):
                    continue
        return default

    @staticmethod
    def _first_any(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in row and row[key] not in (None, ""):
                return row[key]
        return None

    def _symbol_hint(self, asset_id: str, version: int) -> str | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) == version:
                meta = row.get("metadata") or {}
                return meta.get("symbol") or meta.get("filename")
        return None

    def _resolve_version(self, asset_id: str, asset_version: int | None) -> int:
        if asset_version is not None:
            return int(asset_version)
        versions = self._assets.versions(asset_id)
        if not versions:
            raise ValueError(f"asset has no versions: {asset_id}")
        return int(versions[0]["version"])

    def _filename_from_metadata(self, asset_id: str, version: int) -> str | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) == version:
                meta = row.get("metadata") or {}
                name = meta.get("filename")
                return str(name) if name else None
        return None
