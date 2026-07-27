"""IIP.3 — Fundamentals import layer (operator / Screener export → evidence).

Durable store under ``data/investment/fundamentals/``. No HTML scraping.
Screener.in / Trendlyne / Excel exports become first-class evidence via JSON/CSV
drop or API. Fields map into ranking quality + IRA operator snapshot ladder.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.fundamentals")

VERSION = "iip.3.fundamentals"
STORE_REL = Path("investment") / "fundamentals"
IMPORT_DROP_REL = Path("imports") / "fundamentals"
DEFAULT_PROGRAM = "market_intelligence"
SOURCE_OPERATOR = "operator_import"
SOURCE_SCREENER_EXPORT = "screener_export"

# Schema v2 — importable fields (never invent missing ones).
SCHEMA_FIELDS: tuple[str, ...] = (
    "roe",
    "roce",
    "roic",
    "debt_to_equity",
    "pe",
    "pb",
    "fcf",
    "operating_margin",
    "net_margin",
    "revenue_growth_yoy",
    "revenue_growth_qoq",
    "revenue_cagr",
    "earnings_cagr",
    "promoter_holding",
    "pledge_pct",
    "price",
    "shares",
    "market_cap",
    "sector",
)

# CSV / export header aliases → canonical field
_ALIASES: dict[str, str] = {
    "symbol": "symbol",
    "ticker": "symbol",
    "nse code": "symbol",
    "nse_code": "symbol",
    "yahoo": "symbol",
    "roe": "roe",
    "return on equity": "roe",
    "roce": "roce",
    "return on capital employed": "roce",
    "roic": "roic",
    "debt to equity": "debt_to_equity",
    "debt/equity": "debt_to_equity",
    "debt_equity": "debt_to_equity",
    "d/e": "debt_to_equity",
    "pe": "pe",
    "p/e": "pe",
    "price to earnings": "pe",
    "pb": "pb",
    "p/b": "pb",
    "fcf": "fcf",
    "free cash flow": "fcf",
    "operating margin": "operating_margin",
    "opm": "operating_margin",
    "net margin": "net_margin",
    "npm": "net_margin",
    "sales growth": "revenue_growth_yoy",
    "revenue growth": "revenue_growth_yoy",
    "revenue growth yoy": "revenue_growth_yoy",
    "sales growth yoy": "revenue_growth_yoy",
    "revenue growth qoq": "revenue_growth_qoq",
    "revenue cagr": "revenue_cagr",
    "earnings cagr": "earnings_cagr",
    "promoter holding": "promoter_holding",
    "promoter": "promoter_holding",
    "pledge": "pledge_pct",
    "pledged percentage": "pledge_pct",
    "promoter pledge": "pledge_pct",
    "price": "price",
    "current price": "price",
    "shares": "shares",
    "share count": "shares",
    "market cap": "market_cap",
    "mcap": "market_cap",
    "sector": "sector",
    "as_of": "as_of",
    "as of": "as_of",
    "source": "source",
    "note": "note",
    "name": "name",
}

# Dossier / evidence ladder mapping (IRA rule)
FIELD_TO_SECTIONS: dict[str, tuple[str, ...]] = {
    "fcf": ("cash_flow", "valuation", "mos"),
    "pe": ("valuation", "mos"),
    "pb": ("valuation",),
    "price": ("valuation", "mos"),
    "shares": ("valuation", "mos"),
    "roe": ("financial_health", "profitability"),
    "roce": ("financial_health", "profitability"),
    "roic": ("financial_health", "profitability"),
    "debt_to_equity": ("financial_health", "risks"),
    "operating_margin": ("profitability",),
    "net_margin": ("profitability",),
    "revenue_growth_yoy": ("growth", "thesis"),
    "revenue_growth_qoq": ("growth",),
    "revenue_cagr": ("growth",),
    "earnings_cagr": ("growth",),
    "promoter_holding": ("management", "governance"),
    "pledge_pct": ("management", "risks", "governance"),
}


def store_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def store_path(data_dir: str | Path, program_id: str = DEFAULT_PROGRAM) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]+", "_", program_id or DEFAULT_PROGRAM)
    return store_dir(data_dir) / f"{safe}.json"


def import_drop_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / IMPORT_DROP_REL


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    if s.endswith(".BO"):
        return s
    if not s.endswith(".NS") and "." not in s:
        return f"{s}.NS"
    return s


def _to_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("%", "")
    if not s or s.upper() in {"-", "NA", "N/A", "NULL"}:
        return None
    s = re.sub(r"\s*(cr|crore|mn|million|bn|billion)$", "", s, flags=re.I).strip()
    try:
        return float(s)
    except ValueError:
        return None


def normalize_row(
    raw: dict[str, Any], *, default_source: str = SOURCE_OPERATOR
) -> dict[str, Any] | None:
    """Map a raw dict (any header names) onto schema v2."""
    if not isinstance(raw, dict):
        return None
    mapped: dict[str, Any] = {}
    for k, v in raw.items():
        key = _ALIASES.get(str(k).strip().lower())
        if not key:
            ck = str(k).strip().lower().replace(" ", "_")
            if ck in SCHEMA_FIELDS or ck in {"symbol", "as_of", "source", "note", "name"}:
                key = ck
            else:
                continue
        mapped[key] = v

    sym = normalize_symbol(str(mapped.get("symbol") or ""))
    if not sym:
        return None

    out: dict[str, Any] = {
        "symbol": sym,
        "source": str(mapped.get("source") or default_source),
        "as_of": str(mapped.get("as_of") or time.strftime("%Y-%m-%d", time.gmtime())),
        "method": "fundamentals_import",
    }
    if mapped.get("name"):
        out["name"] = str(mapped["name"])
    if mapped.get("note"):
        out["note"] = str(mapped["note"])
    if mapped.get("sector"):
        out["sector"] = str(mapped["sector"])

    for fld in SCHEMA_FIELDS:
        if fld == "sector":
            continue
        if fld not in mapped or mapped[fld] is None or mapped[fld] == "":
            continue
        num = _to_float(mapped[fld])
        if num is None:
            continue
        # Fraction → percent for ratio-like fields when clearly fractional
        if fld in {
            "roe",
            "roce",
            "roic",
            "operating_margin",
            "net_margin",
            "promoter_holding",
            "pledge_pct",
            "revenue_growth_yoy",
            "revenue_growth_qoq",
            "revenue_cagr",
            "earnings_cagr",
        } and abs(num) <= 1.5:
            num = num * 100.0
        out[fld] = num

    if out.get("roce") is not None and out.get("roic") is None:
        out["roic"] = out["roce"]
    if out.get("revenue_growth_yoy") is not None and out.get("revenue_cagr") is None:
        out["revenue_cagr"] = out["revenue_growth_yoy"]

    present = [f for f in SCHEMA_FIELDS if out.get(f) is not None]
    out["fields_present"] = present
    out["evidence_sufficiency"] = (
        "sufficient" if len(present) >= 5 else ("weak" if present else "missing")
    )
    sections: list[str] = []
    for f in present:
        for sec in FIELD_TO_SECTIONS.get(f, ()):
            if sec not in sections:
                sections.append(sec)
    out["strengthens_sections"] = sections
    return out


def load_store(
    data_dir: str | Path | None, program_id: str = DEFAULT_PROGRAM
) -> dict[str, Any]:
    if not data_dir:
        return {"symbols": {}, "count": 0, "program_id": program_id, "version": VERSION}
    path = store_path(data_dir, program_id)
    if not path.is_file():
        return {
            "symbols": {},
            "count": 0,
            "program_id": program_id,
            "version": VERSION,
            "path": str(path),
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("version", VERSION)
            return raw
    except Exception:  # noqa: BLE001
        _log.debug("fundamentals load failed", exc_info=True)
    return {"symbols": {}, "count": 0, "program_id": program_id, "version": VERSION}


def save_store(
    data_dir: str | Path | None,
    doc: dict[str, Any],
    program_id: str = DEFAULT_PROGRAM,
) -> Path | None:
    if not data_dir:
        return None
    path = store_path(data_dir, program_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = dict(doc)
        doc["program_id"] = program_id
        doc["version"] = VERSION
        doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        doc["count"] = len(doc.get("symbols") or {})
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        _log.debug("fundamentals save failed", exc_info=True)
        return None


def upsert_rows(
    data_dir: str | Path | None,
    rows: list[dict[str, Any]] | dict[str, Any],
    *,
    program_id: str = DEFAULT_PROGRAM,
    source: str = SOURCE_OPERATOR,
    as_of: str | None = None,
    note: str = "",
    merge_screener: bool = True,
) -> dict[str, Any]:
    """Normalize + merge rows into durable store; optionally publish screener snapshot."""
    if isinstance(rows, dict) and isinstance(rows.get("symbols"), dict):
        iterable: list[Any] = [
            {"symbol": k, **(v if isinstance(v, dict) else {})}
            for k, v in rows["symbols"].items()
        ]
    elif isinstance(rows, dict) and "symbol" not in rows and not any(
        k in rows for k in ("roe", "roce", "debt_to_equity", "pe")
    ):
        iterable = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in rows.items()]
    elif isinstance(rows, list):
        iterable = rows
    elif isinstance(rows, dict):
        iterable = [rows]
    else:
        iterable = []

    normalized: list[dict[str, Any]] = []
    for raw in iterable:
        if not isinstance(raw, dict):
            continue
        raw2 = dict(raw)
        if as_of and not raw2.get("as_of"):
            raw2["as_of"] = as_of
        row = normalize_row(raw2, default_source=source)
        if row:
            normalized.append(row)

    doc = load_store(data_dir, program_id)
    symbols = dict(doc.get("symbols") or {})
    for row in normalized:
        sym = row["symbol"]
        prev = dict(symbols.get(sym) or {})
        prev.update({k: v for k, v in row.items() if v is not None})
        symbols[sym] = prev
    doc["symbols"] = symbols
    doc["count"] = len(symbols)
    doc["note"] = note or doc.get("note") or "Operator / Screener export import (IIP.3)"
    doc["last_import_count"] = len(normalized)
    path = save_store(data_dir, doc, program_id)

    screener_meta = None
    if merge_screener and normalized:
        try:
            from atlas.investment.screener_signals import publish_snapshot

            screener_rows = []
            for row in normalized:
                sc: dict[str, Any] = {
                    "symbol": row["symbol"],
                    "source": row.get("source") or source,
                    "as_of": row.get("as_of"),
                }
                for fld in (
                    "roe",
                    "roce",
                    "roic",
                    "debt_to_equity",
                    "pe",
                    "fcf",
                    "operating_margin",
                    "net_margin",
                    "revenue_cagr",
                    "earnings_cagr",
                    "promoter_holding",
                    "price",
                    "shares",
                    "sector",
                ):
                    if row.get(fld) is not None:
                        sc[fld] = row[fld]
                # Ranking historically used fraction ROE
                if sc.get("roe") is not None and float(sc["roe"]) > 1.5:
                    sc["roe"] = float(sc["roe"]) / 100.0
                if sc.get("roic") is not None and float(sc["roic"]) > 1.5:
                    sc["roic"] = float(sc["roic"]) / 100.0
                screener_rows.append(sc)
            screener_meta = publish_snapshot(
                screener_rows,
                program_id=program_id,
                source=source,
                as_of=as_of,
                note=note or "From fundamentals import (IIP.3)",
            )
        except Exception:  # noqa: BLE001
            _log.debug("screener merge skipped", exc_info=True)

    return {
        "imported": len(normalized),
        "store_count": len(symbols),
        "path": str(path) if path else None,
        "symbols": [r["symbol"] for r in normalized],
        "screener": {
            "merged": bool(screener_meta),
            "count": (screener_meta or {}).get("count"),
        },
        "version": VERSION,
        "rows": normalized[:50],
    }


def parse_csv_text(text: str, *, source: str = SOURCE_SCREENER_EXPORT) -> list[dict[str, Any]]:
    sample = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(sample))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        if not isinstance(raw, dict):
            continue
        cleaned = {str(k).strip(): v for k, v in raw.items() if k}
        cleaned.setdefault("source", source)
        rows.append(cleaned)
    return rows


def import_csv_text(
    data_dir: str | Path | None,
    text: str,
    *,
    program_id: str = DEFAULT_PROGRAM,
    source: str = SOURCE_SCREENER_EXPORT,
    note: str = "",
) -> dict[str, Any]:
    rows = parse_csv_text(text, source=source)
    return upsert_rows(
        data_dir,
        rows,
        program_id=program_id,
        source=source,
        note=note or "CSV fundamentals import",
    )


def import_json_payload(
    data_dir: str | Path | None,
    payload: Any,
    *,
    program_id: str = DEFAULT_PROGRAM,
    source: str = SOURCE_OPERATOR,
    note: str = "",
) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return upsert_rows(
        data_dir,
        payload,
        program_id=program_id,
        source=source,
        note=note or "JSON fundamentals import",
    )


def import_drop_folder(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
) -> dict[str, Any]:
    """Ingest new ``.csv`` / ``.json`` files from ``imports/fundamentals/``."""
    if not data_dir:
        return {"imported": 0, "files": [], "note": "no data_dir"}
    root = import_drop_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    done_dir = root / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    files_out: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".csv", ".json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".csv":
                result = import_csv_text(
                    data_dir, text, program_id=program_id, note=f"drop:{path.name}"
                )
            else:
                result = import_json_payload(
                    data_dir, text, program_id=program_id, note=f"drop:{path.name}"
                )
            total += int(result.get("imported") or 0)
            dest = done_dir / path.name
            path.replace(dest)
            files_out.append(
                {"file": path.name, "imported": result.get("imported"), "moved_to": str(dest)}
            )
        except Exception as exc:  # noqa: BLE001
            files_out.append({"file": path.name, "error": str(exc)[:200]})
    return {
        "imported": total,
        "files": files_out,
        "drop_dir": str(root),
        "version": VERSION,
        "help": (
            "Drop Screener CSV/JSON exports into this folder; "
            "Atlas moves them to done/ after ingest."
        ),
    }


def get_symbol(
    data_dir: str | Path | None,
    symbol: str,
    *,
    program_id: str = DEFAULT_PROGRAM,
) -> dict[str, Any] | None:
    doc = load_store(data_dir, program_id)
    row = (doc.get("symbols") or {}).get(normalize_symbol(symbol))
    return dict(row) if isinstance(row, dict) else None


def as_quality_map(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
) -> dict[str, dict[str, Any]]:
    """Quality-shaped map for ranking / discovery."""
    doc = load_store(data_dir, program_id)
    out: dict[str, dict[str, Any]] = {}
    for sym, row in (doc.get("symbols") or {}).items():
        if not isinstance(row, dict):
            continue
        q = dict(row)
        for fld in ("roe", "roic"):
            if q.get(fld) is not None and float(q[fld]) > 1.5:
                q[fld] = float(q[fld]) / 100.0
        out[sym] = q
    return out


def fundamentals_view(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    limit: int = 40,
) -> dict[str, Any]:
    doc = load_store(data_dir, program_id)
    symbols = doc.get("symbols") or {}
    rows = []
    for sym, row in list(symbols.items())[: max(1, int(limit))]:
        if isinstance(row, dict):
            rows.append(
                {
                    "symbol": sym,
                    "evidence_sufficiency": row.get("evidence_sufficiency"),
                    "fields_present": row.get("fields_present") or [],
                    "source": row.get("source"),
                    "as_of": row.get("as_of"),
                    "roe": row.get("roe"),
                    "roce": row.get("roce"),
                    "debt_to_equity": row.get("debt_to_equity"),
                    "pe": row.get("pe"),
                }
            )
    drop = import_drop_dir(data_dir) if data_dir else None
    return {
        "count": len(symbols),
        "rows": rows,
        "schema_fields": list(SCHEMA_FIELDS),
        "field_to_sections": {k: list(v) for k, v in FIELD_TO_SECTIONS.items()},
        "drop_dir": str(drop) if drop else None,
        "path": str(store_path(data_dir, program_id)) if data_dir else None,
        "version": VERSION,
        "guide": (
            "Export from Screener.in (ToS-safe CSV) or paste JSON. "
            "Required: symbol column. Useful: ROE, ROCE, Debt to equity, "
            "Operating margin, Promoter holding, Sales growth, PE, FCF."
        ),
    }
