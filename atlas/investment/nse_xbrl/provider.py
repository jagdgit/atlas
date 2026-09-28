"""FEA-facing NSE/XBRL provider. Prefer this over Yahoo for statement facts."""

from __future__ import annotations

import json
import logging
import ssl
import threading
from datetime import date, datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from atlas.investment.nse_xbrl.calculations import calculate_metrics
from atlas.investment.nse_xbrl.coverage import SLICE_FIELDS, fundamentals_coverage
from atlas.investment.nse_xbrl.filing_selection import is_fy_filing, select_canonical_filing
from atlas.investment.nse_xbrl.identity import resolve_identity, resolve_nse_code
from atlas.investment.nse_xbrl.parser import parse_xbrl

VERSION = "nse.provider.v1"
SOURCE = "nse_xbrl"
_log = logging.getLogger("atlas.investment.nse_xbrl")

_NSE_HOME = "https://www.nseindia.com/"
_NSE_FILINGS = (
    "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
)
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NSE_FILINGS,
}

_MONTHS = {
    name: idx
    for idx, name in enumerate(
        "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), start=1
    )
}
_SESSION_LOCK = threading.Lock()
_SESSION_OPENER: Any = None
_SESSION_WARM = False
_NSE_PACE_LOCK = threading.Lock()
_NSE_LAST_REQUEST = 0.0
_NSE_MIN_INTERVAL_S = 0.4
_NSE_SEM = threading.BoundedSemaphore(3)
_NSE_CONCURRENCY = 3


def _nse_code(symbol: str) -> str:
    """Listed NSE ticker (aliases: HBLPOWER → HBLENGINE)."""
    return resolve_nse_code(symbol)


def _bare_code(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if ":" in s:
        s = s.split(":", 1)[-1]
    return s.replace(".NS", "").replace(".BO", "")


def parse_nse_date(raw: Any) -> str | None:
    """NSE broadcast / qe_Date → ISO YYYY-MM-DD. Do not invent."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    text = str(raw).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            pass
    token = text.split()[0].replace("/", "-")
    parts = token.split("-")
    if len(parts) != 3:
        return None
    try:
        if parts[1].isdigit():
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 2000
            return date(y, m, d).isoformat()
        month = _MONTHS.get(parts[1][:3].upper())
        if not month:
            return None
        return date(int(parts[2]), month, int(parts[0])).isoformat()
    except (TypeError, ValueError):
        return None


def _inbox_xml(data_dir: str | Path | None, symbol: str) -> str | None:
    if not data_dir:
        return None
    codes = []
    for c in (_nse_code(symbol), _bare_code(symbol)):
        if c and c not in codes:
            codes.append(c)
    root = Path(data_dir)
    for code in codes:
        for p in (
            root / "investment" / "fundamentals" / "raw" / "nse_xbrl" / "inbox" / f"{code}.xml",
            root / "investment" / "nse_xbrl" / "inbox" / f"{code}.xml",
        ):
            if p.is_file():
                return p.read_text(encoding="utf-8")
    return None


def _session_opener() -> Any:
    global _SESSION_OPENER
    if _SESSION_OPENER is None:
        jar = CookieJar()
        _SESSION_OPENER = build_opener(
            HTTPCookieProcessor(jar),
            HTTPSHandler(context=ssl.create_default_context()),
        )
    return _SESSION_OPENER


def _warmup_nse(opener: Any) -> None:
    global _SESSION_WARM
    if opener is not _SESSION_OPENER:
        for url in (_NSE_HOME, _NSE_FILINGS):
            req = Request(url, headers=_NSE_HEADERS)
            try:
                opener.open(req, timeout=20).read(64)
            except (HTTPError, URLError, TimeoutError, OSError):
                _log.debug("nse warmup skipped", exc_info=True)
        return
    with _SESSION_LOCK:
        if _SESSION_WARM:
            return
        for url in (_NSE_HOME, _NSE_FILINGS):
            req = Request(url, headers=_NSE_HEADERS)
            try:
                opener.open(req, timeout=20).read(64)
            except (HTTPError, URLError, TimeoutError, OSError):
                _log.debug("nse warmup skipped", exc_info=True)
        _SESSION_WARM = True


def configure_nse_pool(*, concurrency: int = 3, min_interval_s: float = 0.4) -> None:
    """Shared NSE cookie session + slot/pace. Call from the FEA dispatcher, not per worker."""
    global _NSE_SEM, _NSE_CONCURRENCY, _NSE_MIN_INTERVAL_S
    n = max(1, min(int(concurrency or 3), 4))
    pace = max(0.15, float(min_interval_s or 0.4))
    with _NSE_PACE_LOCK:
        _NSE_CONCURRENCY = n
        _NSE_MIN_INTERVAL_S = pace
        _NSE_SEM = threading.BoundedSemaphore(n)


def _pace_nse() -> None:
    import time as _time

    global _NSE_LAST_REQUEST
    with _NSE_PACE_LOCK:
        wait = _NSE_MIN_INTERVAL_S - (_time.monotonic() - _NSE_LAST_REQUEST)
        if wait > 0:
            _time.sleep(wait)
        _NSE_LAST_REQUEST = _time.monotonic()


def _http_get(url: str, *, opener: Any | None = None, timeout: float = 20.0) -> tuple[int, bytes]:
    if opener is not None:
        got = opener(url)
        if isinstance(got, tuple) and len(got) == 2:
            return int(got[0]), got[1] if isinstance(got[1], bytes) else str(got[1]).encode("utf-8")
        if isinstance(got, bytes):
            return 200, got
        return 200, str(got).encode("utf-8")
    _NSE_SEM.acquire()
    try:
        _pace_nse()
        sess = _session_opener()
        _warmup_nse(sess)
        req = Request(url, headers=_NSE_HEADERS)
        with sess.open(req, timeout=timeout) as resp:  # noqa: S310 — operator-approved exchange fetch
            return int(getattr(resp, "status", 200) or 200), resp.read()
    finally:
        _NSE_SEM.release()


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "filingList"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
    return []


def _row_to_filing(row: dict[str, Any], *, symbol: str) -> dict[str, Any] | None:
    kind = str(row.get("type") or row.get("filingType") or row.get("submissionType") or "")
    if "GOVERNANCE" in kind.upper():
        return None
    xurl = str(row.get("xbrl") or row.get("xbrlUrl") or row.get("XBRL") or "").strip()
    if not xurl:
        return None
    period_end = parse_nse_date(
        row.get("qe_Date")
        or row.get("toDate")
        or row.get("periodEnd")
        or row.get("to_date")
        or row.get("period")
    )
    period_start = parse_nse_date(
        row.get("fromDate")
        or row.get("from_date")
        or row.get("periodStart")
        or row.get("from")
    )
    duration_days = None
    if period_start and period_end:
        try:
            duration_days = (
                date.fromisoformat(period_end) - date.fromisoformat(period_start)
            ).days + 1
        except ValueError:
            duration_days = None
    available = parse_nse_date(
        row.get("broadcast_Date")
        or row.get("broadCastDate")
        or row.get("broadcastTime")
        or row.get("filingDate")
        or row.get("date")
    )
    scope_raw = str(row.get("consolidated") or row.get("relType") or "CONSOLIDATED")
    return {
        "symbol": symbol,
        "period_end": period_end,
        "period_start": period_start,
        "duration_days": duration_days,
        "scope": scope_raw,
        "audited": row.get("audited"),
        "submission_type": kind or row.get("type_Sub"),
        "broadcast_time": available,
        "available_at": available,
        "revision_n": row.get("revision") or (1 if str(row.get("type_Sub") or "").lower() == "original" else 0),
        "xbrl_url": xurl,
        "superseded": bool(row.get("superseded"))
        or str(row.get("type_Sub") or "").lower() in {"revised", "revision"},
        "filing_type": kind,
    }


def _is_financials(filing: dict[str, Any]) -> bool:
    kind = str(filing.get("filing_type") or filing.get("submission_type") or "").upper()
    if not kind:
        return True
    return "FINANCIAL" in kind or "INDAS" in kind or "RESULT" in kind


def _is_audited(filing: dict[str, Any]) -> bool:
    return str(filing.get("audited") or "").strip().lower() in {"audited", "true", "1"}


def _prior_year_candidate(
    canonical: dict[str, Any] | None,
    financials: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Earlier FY (~12 months) for beginning equity. Prefer annual over a prior quarter."""
    if not canonical:
        return None
    try:
        can_end = date.fromisoformat(str(canonical.get("period_end") or "")[:10])
    except ValueError:
        return None
    scored: list[tuple[int, int, int, int, dict[str, Any]]] = []
    can_url = canonical.get("xbrl_url")
    for f in financials:
        if f.get("xbrl_url") == can_url:
            continue
        try:
            end = date.fromisoformat(str(f.get("period_end") or "")[:10])
        except ValueError:
            continue
        if end >= can_end:
            continue
        delta = (can_end - end).days
        fy = 1 if is_fy_filing(f) else 0
        yearish = 1 if 300 <= delta <= 430 else 0
        if not fy and not yearish:
            continue
        audited = 1 if _is_audited(f) else 0
        scored.append((fy, yearish, audited, abs(delta - 365), f))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3]))
    return scored[0][4]


def _pick_statement_filings(filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canonical FY (not latest Q1) + prior year for beginning equity."""
    financials = [f for f in filings if _is_financials(f) and f.get("xbrl_url")]
    sel = select_canonical_filing(financials, prefer_audited=True)
    canonical = sel.get("canonical") if sel.get("ok") else None
    fy_rows = [f for f in financials if is_fy_filing(f)]
    fy_rows.sort(key=lambda f: str(f.get("period_end") or ""), reverse=True)
    if fy_rows and (canonical is None or not is_fy_filing(canonical)):
        canonical = fy_rows[0]
    if canonical is None and financials:
        canonical = dict(financials[0])
    picked: list[dict[str, Any]] = []
    if canonical:
        picked.append({**canonical, "canonical": True, "role": "canonical"})
    prior = _prior_year_candidate(canonical, financials)
    if prior:
        picked.append({**prior, "canonical": False, "role": "prior_year"})
        return picked
    cons_audited = [
        f
        for f in financials
        if _is_audited(f)
        and "STAND" not in str(f.get("scope") or "").upper()
    ]
    cons_audited.sort(key=lambda f: str(f.get("period_end") or ""), reverse=True)
    can_end = str((canonical or {}).get("period_end") or "")
    for f in cons_audited:
        end = str(f.get("period_end") or "")
        if not end or end == can_end:
            continue
        if f.get("xbrl_url") == (canonical or {}).get("xbrl_url"):
            continue
        picked.append({**f, "canonical": False, "role": "prior_year"})
        break
    return picked


def _download_xml(url: str, *, opener: Any | None) -> str | None:
    try:
        status, blob = _http_get(url, opener=opener)
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    if status >= 400 or not blob:
        return None
    text = blob.decode("utf-8", errors="replace") if not isinstance(blob, str) else blob
    raw = blob if isinstance(blob, (bytes, bytearray)) else text.encode("utf-8")
    if raw.lstrip().startswith(b"<") or text.lstrip().startswith("<"):
        return text if text.lstrip().startswith("<") else raw.decode("utf-8", errors="replace")
    return None


def fetch_nse_xbrl(
    symbol: str,
    *,
    data_dir: str | Path | None = None,
    opener: Any | None = None,
    xml_text: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Load XBRL: injected text → inbox file → NSE Integrated Filing. Explicit nse_unavailable on miss."""
    code = _nse_code(symbol) or _bare_code(symbol)
    if xml_text:
        texts = list(xml_text) if isinstance(xml_text, (list, tuple)) else [xml_text]
        documents = [
            {
                "xml": t,
                "canonical": i == len(texts) - 1,
                "scope": "CONSOLIDATED",
                "role": "canonical" if i == len(texts) - 1 else "prior",
            }
            for i, t in enumerate(texts)
            if t
        ]
        return {
            "ok": True,
            "source": "injected",
            "xml": texts[-1] if texts else xml_text,
            "documents": documents,
            "nse_code": code,
            "filings": [
                {
                    "symbol": code,
                    "scope": "CONSOLIDATED",
                    "period_end": None,
                    "available_at": None,
                    "canonical": True,
                }
            ],
        }
    inbox = _inbox_xml(data_dir, symbol)
    if inbox:
        return {
            "ok": True,
            "source": "inbox",
            "xml": inbox,
            "nse_code": code,
            "filings": [
                {
                    "symbol": code,
                    "scope": "CONSOLIDATED",
                    "available_at": None,
                    "canonical": True,
                }
            ],
        }
    if not code:
        return {"ok": False, "reason": "nse_unavailable", "error": "no_nse_code"}

    enc = quote(code, safe="")
    to = date.today()
    fr = to - timedelta(days=800)
    fr_s = fr.strftime("%d-%m-%Y")
    to_s = to.strftime("%d-%m-%Y")
    listing_urls: list[tuple[str, str | None]] = [
        (
            "https://www.nseindia.com/api/integrated-filing-results"
            f"?index=equities&symbol={enc}&size=50",
            None,
        ),
        (
            "https://www.nseindia.com/api/corporates-financial-results"
            f"?index=equities&symbol={enc}&period=Annual"
            f"&from_date={fr_s}&to_date={to_s}",
            "FY",
        ),
        (
            "https://www.nseindia.com/api/corporates-financial-results"
            f"?index=equities&symbol={enc}&period=Quarterly"
            f"&from_date={fr_s}&to_date={to_s}",
            "Q",
        ),
    ]
    filings: list[dict[str, Any]] = []
    seen_xbrl: set[str] = set()
    last_url = listing_urls[0][0]
    last_error = None
    for url, period_kind in listing_urls:
        last_url = url
        try:
            status, body = _http_get(url, opener=opener)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}:{exc}"[:200]
            continue
        if status >= 400 or not body:
            last_error = f"http_{status}"
            continue
        text = body.decode("utf-8", errors="replace")
        if text.lstrip().startswith("<"):
            return {
                "ok": True,
                "source": "nse_http_xml",
                "xml": text,
                "url": url,
                "nse_code": code,
                "filings": [],
            }
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            last_error = "non_xml_non_json"
            continue
        for row in _payload_rows(payload):
            filing = _row_to_filing(row, symbol=code)
            if not filing:
                continue
            if period_kind and not filing.get("period_kind"):
                filing["period_kind"] = period_kind
            xurl = str(filing.get("xbrl_url") or "")
            if xurl and xurl in seen_xbrl:
                continue
            if xurl:
                seen_xbrl.add(xurl)
            filings.append(filing)
    if not filings:
        return {
            "ok": False,
            "reason": "nse_unavailable",
            "error": last_error or "no_xbrl_body",
            "filings": filings,
            "url": last_url,
            "nse_code": code,
        }

    picked = _pick_statement_filings(filings)
    documents: list[dict[str, Any]] = []
    for item in picked:
        xurl = str(item.get("xbrl_url") or "")
        xml_body = _download_xml(xurl, opener=opener) if xurl else None
        if not xml_body:
            continue
        documents.append({**item, "xml": xml_body, "url": xurl})
    if not documents:
        return {
            "ok": False,
            "reason": "nse_unavailable",
            "error": "no_xbrl_body",
            "filings": filings,
            "url": last_url,
            "nse_code": code,
        }
    sel = select_canonical_filing(filings, prefer_audited=True)
    canonical_xml = next((d["xml"] for d in documents if d.get("canonical")), documents[0]["xml"])
    return {
        "ok": True,
        "source": "nse_http",
        "xml": canonical_xml,
        "documents": documents,
        "filings": filings,
        "selection": sel,
        "url": last_url,
        "nse_code": code,
    }


def _dedupe_conflicts(items: list[Any] | None) -> list[Any]:
    """Keep one copy of each conflict_type+field+note. Re-acquire must not explode the list."""
    seen: set[tuple[str, str, str]] = set()
    out: list[Any] = []
    for c in items or []:
        if isinstance(c, dict):
            key = (
                str(c.get("conflict_type") or ""),
                str(c.get("field") or ""),
                str(c.get("note") or "")[:180],
            )
        else:
            key = ("_str", str(c), "")
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _conflict(
    field: str,
    atlas_val: float | None,
    other_val: Any,
    *,
    conflict_type: str,
) -> dict[str, Any] | None:
    try:
        oth = float(other_val)
    except (TypeError, ValueError):
        return None
    if atlas_val is None:
        return None
    # 0.5pp for pct-like; 2% relative otherwise
    if field in {"roe"}:
        if abs(atlas_val - oth) <= 0.5:
            return None
    else:
        denom = max(abs(atlas_val), abs(oth), 1e-9)
        if abs(atlas_val - oth) / denom <= 0.02:
            return None
    return {
        "field": field,
        "conflict_type": conflict_type,
        "atlas": atlas_val,
        "other": oth,
        "other_source": "yahoo_or_store",
    }


def acquire_from_nse(
    data_dir: str | Path | None,
    symbol: str,
    *,
    program_id: str = "market_intelligence",
    price: float | None = None,
    evidence_as_of: str | None = None,
    xml_text: str | list[str] | tuple[str, ...] | None = None,
    opener: Any | None = None,
    eps_fy_fallback: bool = False,
    push_store: bool = True,
    available_at: str | None = None,
) -> dict[str, Any]:
    """Parse NSE (or fixture) → calc → optional upsert into existing fundamentals store."""
    from atlas.investment.fundamentals import get_symbol, normalize_symbol, upsert_rows
    from atlas.investment.nse_xbrl.raw_store import store_raw as _store

    sym = normalize_symbol(symbol)
    fetched = fetch_nse_xbrl(
        symbol, data_dir=data_dir, opener=opener, xml_text=xml_text
    )
    out: dict[str, Any] = {
        "version": VERSION,
        "kind": "NSE_XBRL_ACQUIRE",
        "symbol": sym,
        "ok": False,
        "provider": SOURCE,
        "acquired": [],
        "still_missing": list(SLICE_FIELDS),
        "coverage": None,
        "plc_a": None,
    }
    if not fetched.get("ok"):
        out["reason"] = fetched.get("reason") or "nse_unavailable"
        out["fetch"] = {k: fetched.get(k) for k in ("error", "http_status", "url")}
        ident = resolve_identity(sym, data_dir=str(data_dir) if data_dir else None)
        cov = fundamentals_coverage(fundamentals=get_symbol(data_dir, sym, program_id=program_id) if data_dir else {}, identity=ident)
        out["coverage"] = cov
        out["identity"] = ident
        return out

    sel = fetched.get("selection") if isinstance(fetched.get("selection"), dict) else {}
    canonical = sel.get("canonical") if isinstance(sel.get("canonical"), dict) else {}
    documents = list(fetched.get("documents") or [])
    if not documents and fetched.get("xml"):
        documents = [
            {
                "xml": fetched.get("xml"),
                "canonical": True,
                "available_at": available_at
                or canonical.get("available_at")
                or evidence_as_of,
                "filed_at": canonical.get("filed_at") or canonical.get("broadcast_time"),
                "scope": canonical.get("scope") or "CONSOLIDATED",
                "period_end": canonical.get("period_end"),
                "role": "canonical",
            }
        ]
    facts: list[dict[str, Any]] = []
    stored: dict[str, Any] = {"ok": False}
    parsed: dict[str, Any] = {"ok": False, "facts": []}
    parse_errors: list[str] = []
    for doc in documents:
        xml = str(doc.get("xml") or "")
        if not xml:
            continue
        meta = {
            "source": fetched.get("source"),
            "canonical": bool(doc.get("canonical")),
            "role": doc.get("role"),
            "available_at": available_at
            or parse_nse_date(doc.get("available_at"))
            or parse_nse_date(doc.get("broadcast_time"))
            or parse_nse_date(canonical.get("available_at"))
            or evidence_as_of,
            "filed_at": parse_nse_date(doc.get("filed_at") or doc.get("broadcast_time"))
            or canonical.get("filed_at")
            or canonical.get("broadcast_time"),
            "scope": doc.get("scope") or canonical.get("scope") or "CONSOLIDATED",
            "period_end": parse_nse_date(doc.get("period_end")) or doc.get("period_end"),
            "nse_code": fetched.get("nse_code"),
        }
        this_store = (
            _store(data_dir, symbol=sym, xml_text=xml, meta=meta) if data_dir else {"ok": False}
        )
        if doc.get("canonical") or not stored.get("ok"):
            stored = this_store
        one = parse_xbrl(
            xml,
            symbol=sym,
            source_document=this_store.get("path"),
            filed_at=meta.get("filed_at"),
            available_at=meta.get("available_at"),
            default_scope=str(meta.get("scope") or "CONSOLIDATED"),
        )
        if one.get("ok"):
            parsed = one
            facts.extend(one.get("facts") or [])
        else:
            parse_errors.append(str(one.get("reason") or "parse_failure"))
    out["parse"] = {
        "ok": bool(facts),
        "status": parsed.get("status") if facts else "RETRY",
        "reason": None if facts else (parse_errors[0] if parse_errors else parsed.get("reason")),
        "fact_n": len(facts),
        "raw_evidence_id": parsed.get("raw_evidence_id") or stored.get("raw_evidence_id"),
        "documents_n": len(documents),
    }
    if not facts:
        out["reason"] = out["parse"]["reason"] or "parse_failure"
        out["ok"] = False
        return out
    parsed = {**parsed, "ok": True, "facts": facts, "fact_n": len(facts)}

    px = price
    if px is None and data_dir:
        try:
            from atlas.investment.bar_store import load_bars

            bars = load_bars(data_dir, sym, limit=1) or load_bars(
                data_dir, _nse_code(sym), limit=1
            )
            last = bars[-1] if bars else None
            if isinstance(last, dict) and last.get("close") is not None:
                px = float(last["close"])
        except Exception:  # noqa: BLE001
            _log.debug("nse price from bars skipped", exc_info=True)
    calc = calculate_metrics(
        parsed.get("facts") or [],
        price=px,
        eps_fy_fallback=eps_fy_fallback,
        evidence_as_of=evidence_as_of,
    )
    out["calculation"] = {
        "unknown": calc.get("unknown"),
        "excluded_look_ahead_n": calc.get("excluded_look_ahead_n"),
        "metrics": {
            k: {kk: vv for kk, vv in (v or {}).items() if kk != "inputs"}
            if isinstance(v, dict)
            else v
            for k, v in (calc.get("metrics") or {}).items()
        },
    }

    prev = get_symbol(data_dir, sym, program_id=program_id) if data_dir else {}
    ident = resolve_identity(
        sym,
        data_dir=str(data_dir) if data_dir else None,
        fundamentals=prev,
    )
    row: dict[str, Any] = {
        "symbol": sym,
        "source": SOURCE,
        "as_of": evidence_as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "nse_raw_evidence_id": parsed.get("raw_evidence_id"),
        "eps_basis": (calc.get("metrics") or {}).get("eps", {}).get("eps_basis"),
    }
    acquired: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = list(calc.get("conflicts") or [])
    mets = calc.get("metrics") or {}
    for field in ("pe", "roe", "debt_to_equity", "fcf"):
        m = mets.get(field) if isinstance(mets.get(field), dict) else {}
        if m.get("status") != "VALID" or m.get("value") is None:
            continue
        val = m["value"]
        row[field] = val
        if field == "fcf":
            row["free_cash_flow"] = val
        other = (prev or {}).get(field)
        ctype = {
            "pe": "EPS_BASIS",
            "roe": "CALCULATION",
            "debt_to_equity": "DEBT_DEFINITION",
            "fcf": "CALCULATION",
        }[field]
        c = _conflict(field, float(val), other, conflict_type=ctype)
        if c:
            conflicts.append(c)
        acquired.append(
            {
                "field": field,
                "value": val,
                "provider": SOURCE,
                "value_type": m.get("value_type") or "derived",
                "formula": m.get("formula"),
                "inputs": m.get("inputs"),
                "eps_basis": m.get("eps_basis"),
                "definition_id": m.get("definition_id"),
            }
        )
    if ident.get("sector_ok"):
        row["sector"] = ident.get("sector")
        acquired.append(
            {
                "field": "sector",
                "value": ident.get("sector"),
                "provider": ident.get("source") or "universe_catalog",
                "value_type": "reported",
            }
        )
    if ident.get("identity_ok"):
        row["name"] = ident.get("name")
        acquired.append(
            {
                "field": "identity",
                "value": ident.get("name"),
                "provider": ident.get("source") or "universe_catalog",
                "value_type": "reported",
            }
        )
    if conflicts:
        row["evidence_conflicts"] = _dedupe_conflicts(
            list((prev or {}).get("evidence_conflicts") or []) + conflicts
        )
        out["conflicts"] = _dedupe_conflicts(conflicts)

    if push_store and data_dir and (acquired or row.get("nse_raw_evidence_id")):
        try:
            from atlas.investment.fundamentals import load_store, save_store

            upsert_rows(
                data_dir,
                [row],
                program_id=program_id,
                source=SOURCE,
                note="NSE/XBRL vertical slice → Atlas calc",
                merge_screener=False,
            )
            doc = load_store(data_dir, program_id)
            stored_sym = dict((doc.get("symbols") or {}).get(sym) or {})
            changed = False
            for field in ("pe", "roe", "debt_to_equity", "fcf", "free_cash_flow"):
                metric_key = "fcf" if field in {"fcf", "free_cash_flow"} else field
                m = mets.get(metric_key) if isinstance(mets.get(metric_key), dict) else {}
                if m.get("status") == "VALID":
                    continue
                if stored_sym.get("source") == SOURCE and stored_sym.get(field) is not None:
                    stored_sym.pop(field, None)
                    changed = True
            if changed:
                doc.setdefault("symbols", {})[sym] = stored_sym
                save_store(data_dir, doc, program_id)
        except Exception as exc:  # noqa: BLE001
            out["store_error"] = type(exc).__name__

    stored_row = (
        get_symbol(data_dir, sym, program_id=program_id) if data_dir else row
    ) or row
    cov = fundamentals_coverage(
        fundamentals=stored_row, identity=ident, metrics=calc
    )
    out["acquired"] = acquired
    out["still_missing"] = list(cov.get("missing") or [])
    out["coverage"] = cov
    out["identity"] = ident
    out["ok"] = bool(acquired) and parsed.get("ok")
    out["reason"] = "complete" if cov.get("complete") else ("partial" if acquired else "calc_unknown")
    out["raw"] = stored.get("path") if isinstance(stored, dict) else None
    return out
