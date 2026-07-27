"""Durable log of market / web data fetch failures (IIP transparency).

Operators review failures on the Investment Intelligence page and can add keys,
enable providers, or supply operator snapshots when Atlas cannot reach the web.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.feed_failures")

STORE_REL = Path("market") / "feed_failures.jsonl"
MAX_LINES = 500


def store_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def record_failure(
    data_dir: str | Path | None,
    *,
    provider: str,
    symbol: str = "",
    reason: str,
    capability: str = "",
    source: str = "",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append one failure event. Never raises to callers."""
    if not data_dir:
        return None
    row: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": str(provider or "unknown"),
        "symbol": str(symbol or ""),
        "reason": str(reason or "unknown")[:500],
        "capability": str(capability or ""),
        "source": str(source or ""),
    }
    if detail:
        row["detail"] = detail
    path = store_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        _trim(path)
    except Exception:  # noqa: BLE001
        _log.debug("feed failure record skipped", exc_info=True)
        return None
    return row


def _trim(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= MAX_LINES:
            return
        path.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def list_failures(
    data_dir: str | Path | None,
    *,
    limit: int = 100,
    provider: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    if not data_dir:
        return {"items": [], "count": 0, "note": "no data_dir"}
    path = store_path(data_dir)
    if not path.is_file():
        return {"items": [], "count": 0, "path": str(path)}
    items: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if provider and str(row.get("provider") or "") != provider:
                continue
            if symbol and str(row.get("symbol") or "") != symbol:
                continue
            items.append(row)
    except Exception:  # noqa: BLE001
        _log.debug("feed failure read failed", exc_info=True)
        return {"items": [], "count": 0, "error": "read_failed"}
    items = items[-max(1, int(limit)) :]
    items.reverse()  # newest first
    # Aggregate recent reasons for operator triage
    by_reason: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    for row in items:
        r = str(row.get("reason") or "unknown")[:120]
        by_reason[r] = by_reason.get(r, 0) + 1
        p = str(row.get("provider") or "?")
        by_provider[p] = by_provider.get(p, 0) + 1
    return {
        "items": items,
        "count": len(items),
        "by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])[:20]),
        "by_provider": by_provider,
        "path": str(path),
        "help": (
            "When Atlas cannot fetch live data, failures appear here. "
            "Fix by restoring internet, enabling market.yahoo_enabled, "
            "setting API keys (Polygon/Alpha Vantage), or posting operator snapshots."
        ),
    }
