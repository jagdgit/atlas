"""Synthetic OHLCV helpers for paper-trading setup (fixture/replay path).

Live market providers are deferred (OI-D1). Operators can register real JSON/CSV feeds, or
ask Atlas to mint a deterministic sample series so a Paper-Trading mission can start
learning-by-doing without external credentials.
"""

from __future__ import annotations

import json
import math
from typing import Any


def sample_bars(
    *,
    n: int = 60,
    start: float = 100.0,
    seed: int = 1,
) -> list[dict[str, Any]]:
    """Deterministic fake OHLCV bars (enough for SMA/RSI warmup)."""
    n = max(5, min(int(n), 500))
    bars: list[dict[str, Any]] = []
    price = float(start)
    for i in range(n):
        # Mild deterministic drift + oscillation — no randomness required.
        delta = math.sin((i + seed) / 5.0) * 1.5 + 0.05
        open_p = price
        close_p = max(1.0, price + delta)
        high_p = max(open_p, close_p) + 0.4
        low_p = min(open_p, close_p) - 0.4
        bars.append(
            {
                "t": i,
                "open": round(open_p, 4),
                "high": round(high_p, 4),
                "low": round(low_p, 4),
                "close": round(close_p, 4),
                "volume": 1000 + (i * 7) % 500,
            }
        )
        price = close_p
    return bars


def bars_to_json_bytes(bars: list[dict[str, Any]]) -> bytes:
    return json.dumps(bars, separators=(",", ":")).encode("utf-8")


def register_market_feed(
    assets: Any,
    *,
    name: str,
    symbol: str,
    data: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    generate_sample: bool = False,
    sample_bars_n: int = 60,
    sample_start: float = 100.0,
) -> dict[str, Any]:
    """Register (or version) a ``market_data`` asset. Returns asset + version rows + name.

    Prefer an explicit ``data`` payload (JSON/CSV bytes). When ``generate_sample`` is true
    and no data is given, mint a deterministic fixture series so paper trading can run.
    """
    name = (name or "").strip()
    symbol = (symbol or name or "SYM").strip() or "SYM"
    if not name:
        name = f"{symbol.lower()}-feed"

    meta_filename = filename
    payload = data
    ctype = content_type

    if payload is None or payload == b"":
        if not generate_sample:
            raise ValueError("market data bytes required (or set generate_sample=true)")
        payload = bars_to_json_bytes(
            sample_bars(n=sample_bars_n, start=sample_start)
        )
        meta_filename = meta_filename or f"{name}.json"
        ctype = ctype or "application/json"

    if not meta_filename:
        # Reader picks parser from metadata.filename extension.
        if (ctype or "").endswith("csv") or (ctype or "") == "text/csv":
            meta_filename = f"{name}.csv"
        else:
            meta_filename = f"{name}.json"
            ctype = ctype or "application/json"

    result = assets.register(
        "market_data",
        name,
        payload,
        content_type=ctype or "application/json",
        metadata={"filename": meta_filename, "symbol": symbol},
    )
    asset = result.get("asset") or {}
    version = result.get("version") or {}
    return {
        "name": name,
        "kind": "market_data",
        "symbol": symbol,
        "asset_id": str(asset.get("id") or ""),
        "version": int(version.get("version") or asset.get("current_version") or 1),
        "filename": meta_filename,
        "generated_sample": bool(generate_sample and (data is None or data == b"")),
    }
