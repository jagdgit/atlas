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

VERSION = "di.4.fundamentals"
STORE_REL = Path("investment") / "fundamentals"
IMPORT_DROP_REL = Path("imports") / "fundamentals"
DEFAULT_PROGRAM = "market_intelligence"
SOURCE_OPERATOR = "operator_import"
SOURCE_SCREENER_EXPORT = "screener_export"

# Schema v2 — importable fields (never invent missing ones).
# Industry/peer medians are optional operator evidence only — never computed.
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
    "industry_pe_median",
    "industry_pb_median",
    "industry_roe_median",
)

# Columns for learner gap-fill CSV (operator paste/Screener export target).
LEARNER_TEMPLATE_COLUMNS: tuple[str, ...] = (
    "symbol",
    "pe",
    "fcf",
    "roe",
    "roce",
    "debt_to_equity",
    "operating_margin",
    "promoter_holding",
    "pb",
    "price",
    "shares",
    "sector",
    "industry_pe_median",
    "industry_pb_median",
    "as_of",
    "source",
    "note",
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
    "industry pe median": "industry_pe_median",
    "industry_pe_median": "industry_pe_median",
    "industry average pe": "industry_pe_median",
    "industry_avg_pe": "industry_pe_median",
    "peer pe median": "industry_pe_median",
    "peer_pe_median": "industry_pe_median",
    "industry pb median": "industry_pb_median",
    "industry_pb_median": "industry_pb_median",
    "industry average pb": "industry_pb_median",
    "peer pb median": "industry_pb_median",
    "industry roe median": "industry_roe_median",
    "industry_roe_median": "industry_roe_median",
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
    "industry_pe_median": ("valuation", "mos"),
    "industry_pb_median": ("valuation",),
    "industry_roe_median": ("financial_health", "profitability"),
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


def learner_fundamentals_gaps(
    data_dir: str | Path | None,
    symbols: list[str],
    *,
    program_id: str = DEFAULT_PROGRAM,
    critical_fields: tuple[str, ...] = ("pe", "fcf", "roe", "debt_to_equity"),
) -> dict[str, Any]:
    """DI.4 honesty — which learner symbols still lack PE/FCF/etc. Never invent."""
    want = [str(s).strip() for s in symbols if str(s).strip()]
    gaps: list[dict[str, Any]] = []
    present = 0
    missing_pe = 0
    missing_fcf = 0
    with_industry_pe = 0
    for sym in want:
        row = get_symbol(data_dir, sym, program_id=program_id) or {}
        missing = [f for f in critical_fields if row.get(f) is None]
        # fcf alias
        if "fcf" in missing and row.get("free_cash_flow") is not None:
            missing = [f for f in missing if f != "fcf"]
        if row.get("industry_pe_median") is not None:
            with_industry_pe += 1
        if not row:
            missing_pe += 1
            missing_fcf += 1
            gaps.append(
                {
                    "symbol": sym,
                    "missing": list(critical_fields),
                    "status": "no_row",
                    "evidence_sufficiency": "missing",
                }
            )
            continue
        present += 1
        if row.get("pe") is None:
            missing_pe += 1
        if row.get("fcf") is None and row.get("free_cash_flow") is None:
            missing_fcf += 1
        if missing:
            gaps.append(
                {
                    "symbol": sym,
                    "missing": missing,
                    "status": "partial",
                    "evidence_sufficiency": row.get("evidence_sufficiency") or "weak",
                    "fields_present": row.get("fields_present") or [],
                }
            )
    return {
        "program_id": program_id,
        "symbols_checked": len(want),
        "symbols_with_row": present,
        "symbols_with_gaps": len(gaps),
        "missing_pe": missing_pe,
        "missing_fcf": missing_fcf,
        "with_industry_pe_median": with_industry_pe,
        "critical_fields": list(critical_fields),
        "gaps": gaps[:80],
        "honesty": (
            "Missing PE/FCF are real gaps — Atlas must not invent industry averages. "
            "Import Screener CSV or drop into imports/fundamentals/. "
            "Optional industry_*_median columns are operator evidence only."
        ),
        "import_hint": (
            "GET /v1/market/fundamentals/learner-template → fill → "
            "POST /v1/market/fundamentals/import (or import-drop)"
        ),
    }


def peer_context(row: dict[str, Any] | None) -> dict[str, Any]:
    """Honest PE/peer lens — never invent industry medians."""
    fund = row if isinstance(row, dict) else {}
    pe = _to_float(fund.get("pe"))
    ind_pe = _to_float(fund.get("industry_pe_median"))
    pb = _to_float(fund.get("pb"))
    ind_pb = _to_float(fund.get("industry_pb_median"))
    out: dict[str, Any] = {
        "pe": pe,
        "industry_pe_median": ind_pe,
        "pb": pb,
        "industry_pb_median": ind_pb,
        "pe_vs_industry_median_pct": None,
        "may_claim_below_industry_pe": False,
        "fair_pe_is_not_industry_average": True,
        "honesty": (
            "fair_pe (when present on valuation) is a quality heuristic — "
            "not an industry average. Only imported industry_*_median counts "
            "as peer/industry evidence."
        ),
    }
    if pe is not None and ind_pe is not None and ind_pe > 0:
        vs = round(100.0 * (ind_pe - pe) / pe, 2)
        out["pe_vs_industry_median_pct"] = vs
        out["may_claim_below_industry_pe"] = pe < ind_pe
        out["honesty"] = (
            f"PE {pe} vs imported industry median {ind_pe} "
            f"({'below' if pe < ind_pe else 'at/above'} median)."
        )
    elif pe is not None and ind_pe is None:
        out["honesty"] = (
            f"PE {pe} present but industry_pe_median missing — "
            "do not claim 'below industry average'."
        )
    elif pe is None:
        out["honesty"] = "PE missing — valuation peer lens unavailable."
    return out


def learner_gap_fill_template(
    data_dir: str | Path | None,
    symbols: list[str],
    *,
    program_id: str = DEFAULT_PROGRAM,
    only_gaps: bool = True,
) -> dict[str, Any]:
    """Build CSV + rows for operator to fill learner PE/FCF gaps (DI.4 deepen).

    Prefills known fields; leaves missing critical cells empty. Never invents.
    """
    want = [normalize_symbol(s) for s in symbols if str(s).strip()]
    want = [s for s in want if s]
    # de-dupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for s in want:
        if s not in seen:
            seen.add(s)
            ordered.append(s)

    gaps_doc = learner_fundamentals_gaps(
        data_dir, ordered, program_id=program_id
    )
    gap_syms = {g["symbol"] for g in gaps_doc.get("gaps") or []}
    # normalize gap symbols
    gap_syms = {normalize_symbol(s) for s in gap_syms}

    rows_out: list[dict[str, Any]] = []
    for sym in ordered:
        if only_gaps and sym not in gap_syms:
            # still include if completely missing pe/fcf check via gap set
            continue
        row = get_symbol(data_dir, sym, program_id=program_id) or {}
        line: dict[str, Any] = {"symbol": sym}
        for col in LEARNER_TEMPLATE_COLUMNS:
            if col == "symbol":
                continue
            val = row.get(col)
            if col == "fcf" and val is None:
                val = row.get("free_cash_flow")
            if col == "source":
                line[col] = val or SOURCE_OPERATOR
            elif col == "as_of":
                line[col] = val or ""
            elif col == "note":
                missing = [
                    f
                    for f in ("pe", "fcf", "roe", "debt_to_equity")
                    if row.get(f) is None
                    and not (f == "fcf" and row.get("free_cash_flow") is not None)
                ]
                line[col] = (
                    f"fill: {','.join(missing)}" if missing else (val or "")
                )
            else:
                line[col] = val if val is not None else ""
        rows_out.append(line)

    # If only_gaps filtered everything but symbols exist without gaps, return empty
    # template header still useful — include all when only_gaps and no gap rows
    if only_gaps and not rows_out and ordered:
        # all covered — return empty with note
        pass

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(LEARNER_TEMPLATE_COLUMNS))
    writer.writeheader()
    for line in rows_out:
        writer.writerow({k: line.get(k, "") for k in LEARNER_TEMPLATE_COLUMNS})
    csv_text = buf.getvalue()

    return {
        "version": VERSION,
        "program_id": program_id,
        "only_gaps": only_gaps,
        "symbols_requested": len(ordered),
        "rows": rows_out,
        "row_count": len(rows_out),
        "csv": csv_text,
        "columns": list(LEARNER_TEMPLATE_COLUMNS),
        "gaps": gaps_doc,
        "drop_dir": str(import_drop_dir(data_dir)) if data_dir else None,
        "help": (
            "1) Download/copy csv  2) Fill empty pe/fcf/… from Screener export "
            "3) Optional: add industry_pe_median for peer honesty "
            "4) POST /v1/market/fundamentals/import {\"csv\": \"...\"} "
            "or drop file into imports/fundamentals/"
        ),
        "honesty": (
            "Empty cells stay empty until you import — Atlas never invents "
            "PE, FCF, or industry medians."
        ),
    }


def fundamentals_view(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    limit: int = 40,
    gap_symbols: list[str] | None = None,
) -> dict[str, Any]:
    doc = load_store(data_dir, program_id)
    symbols = doc.get("symbols") or {}
    rows = []
    pe_count = 0
    fcf_count = 0
    industry_pe_count = 0
    for sym, row in list(symbols.items())[: max(1, int(limit))]:
        if isinstance(row, dict):
            if row.get("pe") is not None:
                pe_count += 1
            if row.get("fcf") is not None or row.get("free_cash_flow") is not None:
                fcf_count += 1
            if row.get("industry_pe_median") is not None:
                industry_pe_count += 1
            peer = peer_context(row)
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
                    "fcf": row.get("fcf") or row.get("free_cash_flow"),
                    "industry_pe_median": row.get("industry_pe_median"),
                    "peer_context": peer,
                }
            )
    # full-store coverage (not just limited rows)
    all_pe = sum(
        1
        for r in symbols.values()
        if isinstance(r, dict) and r.get("pe") is not None
    )
    all_fcf = sum(
        1
        for r in symbols.values()
        if isinstance(r, dict)
        and (r.get("fcf") is not None or r.get("free_cash_flow") is not None)
    )
    all_ind = sum(
        1
        for r in symbols.values()
        if isinstance(r, dict) and r.get("industry_pe_median") is not None
    )
    drop = import_drop_dir(data_dir) if data_dir else None
    out: dict[str, Any] = {
        "count": len(symbols),
        "rows": rows,
        "coverage": {
            "symbols": len(symbols),
            "with_pe": all_pe,
            "with_fcf": all_fcf,
            "with_industry_pe_median": all_ind,
            "pe_coverage_pct": round(100.0 * all_pe / max(1, len(symbols)), 1)
            if symbols
            else 0.0,
            "note": (
                "Empty PE/FCF is honest incomplete evidence — not a valuation signal."
                if all_pe == 0
                else (
                    None
                    if all_ind
                    else (
                        "PE present but industry_pe_median mostly missing — "
                        "do not claim 'below industry average'."
                    )
                )
            ),
        },
        "schema_fields": list(SCHEMA_FIELDS),
        "learner_template_columns": list(LEARNER_TEMPLATE_COLUMNS),
        "field_to_sections": {k: list(v) for k, v in FIELD_TO_SECTIONS.items()},
        "drop_dir": str(drop) if drop else None,
        "path": str(store_path(data_dir, program_id)) if data_dir else None,
        "version": VERSION,
        "guide": (
            "Export from Screener.in (ToS-safe CSV) or paste JSON. "
            "Required: symbol column. Useful: ROE, ROCE, Debt to equity, "
            "Operating margin, Promoter holding, Sales growth, PE, FCF. "
            "Optional peer honesty: industry_pe_median / industry_pb_median. "
            "GET /v1/market/fundamentals/learner-template for gap-fill CSV."
        ),
    }
    if gap_symbols:
        out["learner_gaps"] = learner_fundamentals_gaps(
            data_dir, gap_symbols, program_id=program_id
        )
    return out
