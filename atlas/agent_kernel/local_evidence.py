"""Read-only local evidence for an investigation.

Null fundamentals stay missing. A sector name is not a historical price series.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > 8_000_000:
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _close_from_bars(doc: dict[str, Any]) -> dict[str, Any] | None:
    bars = doc.get("bars")
    if not isinstance(bars, list) or not bars:
        return None
    last = bars[-1] if isinstance(bars[-1], dict) else None
    if not last or last.get("close") is None:
        return None
    return {
        "last_close": float(last["close"]),
        "as_of": last.get("date"),
        "bar_count": int(doc.get("bar_count") or len(bars)),
        "provider": doc.get("provider") or doc.get("history_provider"),
        "symbol": doc.get("symbol"),
        "source": "local_bar_store",
    }


def lookup_local(
    data_dir: str | Path | None,
    *,
    symbol: str,
    requirement: str,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any]:
    """Return a capability result for one requirement from files on disk."""
    if not data_dir or not symbol:
        return {
            "ok": False,
            "error": f"{requirement}_not_available",
            "missing": requirement,
            "citations": [],
            "invented": False,
        }
    root = Path(data_dir)
    sym = symbol.strip().upper()
    req = requirement.strip().lower()
    if req in {"price_history", "price"}:
        doc = _read(root / "market" / "bars" / f"{sym}.json")
        summary = _close_from_bars(doc) if doc else None
        if summary is None:
            comp = _completeness_item(root, sym, laboratory_id, "price_history")
            if comp and comp.get("status") == "AVAILABLE" and comp.get("value") is not None:
                summary = {
                    "last_close": float(comp["value"]),
                    "source": comp.get("source") or "evidence_completeness",
                    "as_of": comp.get("as_of"),
                    "bar_count": None,
                }
        if summary is None:
            return _miss(req)
        path = str(root / "market" / "bars" / f"{sym}.json")
        return {
            "ok": True,
            "evidence": summary,
            "citations": [path],
            "invented": False,
            "error": None,
            "missing": None,
        }
    if req in {"sector", "sector_name"}:
        research = _read(root / "investment" / "research" / "market_intelligence" / f"{sym}.json")
        sector = None
        if research:
            sector = research.get("sector") or (research.get("profile") or {}).get("sector")
            if sector is None and isinstance(research.get("identity"), dict):
                sector = research["identity"].get("sector")
        if not sector:
            return _miss(req, error="sector_name_not_available")
        return {
            "ok": True,
            "evidence": {
                "sector": str(sector),
                "source": "research_dossier",
                "symbol": sym,
            },
            "citations": [
                str(root / "investment" / "research" / "market_intelligence" / f"{sym}.json")
            ],
            "invented": False,
            "error": None,
            "missing": None,
        }
    if req in {"sector_benchmark", "sector_history", "sector_ohlcv"}:
        # A sector label is not a price series. Do not synthesize one.
        return _miss(req, error="sector_index_history_not_available", missing="durable_sector_OHLCV_provider")
    if req in {"pe", "fcf", "roe", "pb", "debt", "mos"}:
        comp = _completeness_item(root, sym, laboratory_id, req)
        research = _read(root / "investment" / "research" / "market_intelligence" / f"{sym}.json")
        value = None
        source = None
        if comp and comp.get("status") == "AVAILABLE" and comp.get("value") is not None:
            value = comp.get("value")
            source = "evidence_completeness"
        elif research and research.get(req) not in (None, "", "UNKNOWN"):
            value = research.get(req)
            source = "research_dossier"
        if value is None:
            return _miss(req, error=f"{req}_missing")
        return {
            "ok": True,
            "evidence": {"value": value, "source": source, "symbol": sym, "field": req},
            "citations": [source or "local"],
            "invented": False,
            "error": None,
            "missing": None,
        }
    return _miss(req)


def _completeness_item(
    root: Path, symbol: str, laboratory_id: str, key: str
) -> dict[str, Any] | None:
    doc = _read(
        root
        / "investment"
        / "evidence_completeness"
        / laboratory_id
        / f"{symbol}_latest.json"
    )
    if not doc:
        return None
    for item in doc.get("items") or []:
        if isinstance(item, dict) and str(item.get("key") or "").lower() == key:
            return item
    return None


def _miss(requirement: str, error: str | None = None, missing: str | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": error or f"{requirement}_not_available",
        "missing": missing or requirement,
        "citations": [],
        "invented": False,
    }


def material_gaps(
    data_dir: str | Path | None,
    *,
    symbol: str,
    laboratory_id: str = "india_equity_learner",
) -> list[dict[str, Any]]:
    if not data_dir or not symbol:
        return []
    doc = _read(
        Path(data_dir)
        / "investment"
        / "evidence_completeness"
        / laboratory_id
        / f"{symbol.strip().upper()}_latest.json"
    )
    if not doc:
        return []
    out = []
    for item in doc.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("required") and str(item.get("status") or "").upper() != "AVAILABLE":
            out.append(item)
    return out
