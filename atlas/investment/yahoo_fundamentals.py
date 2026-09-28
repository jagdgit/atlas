"""LI.2 — Yahoo fundamentals provider (medium confidence, never sole truth).

Uses Yahoo quoteSummary JSON (same ToS/network posture as chart bars). Opt-in;
injectable opener for hermetic tests. Does not require the yfinance package.

Yahoo (2024+) requires a session cookie + crumb for quoteSummary; unauthenticated
calls return HTTP 401. Chart bars may still work without crumb — fundamentals do not.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from atlas.investment.evidence_providers import make_evidence_value
from atlas.investment.fundamentals import normalize_symbol

_log = logging.getLogger("atlas.investment.yahoo_fundamentals")

VERSION = "li.2.yahoo_fundamentals"
PROVIDER_ID = "yahoo_fundamentals"
QUOTE_SUMMARY_URL = (
    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    "?modules=defaultKeyStatistics,financialData,summaryDetail,price,"
    "cashflowStatementHistory"
)
CRUMB_URLS = (
    "https://query1.finance.yahoo.com/v1/test/getcrumb",
    "https://query2.finance.yahoo.com/v1/test/getcrumb",
)
COOKIE_SEED_URL = "https://fc.yahoo.com"
# Browser-like UA — Yahoo rejects short custom agents on quoteSummary (HTTP 401).
YAHOO_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_crumb_lock = threading.Lock()
_cached_crumb: str | None = None

# Slow-and-steady Yahoo pacing (shared process + durable cooldown file).
# 429 storms on getcrumb are common — prefer longer gaps over hammering.
DEFAULT_MIN_INTERVAL_S = 8.0
DEFAULT_BACKOFF_START_S = 120.0
DEFAULT_BACKOFF_MAX_S = 900.0  # 15 minutes
DEFAULT_BACKOFF_MULT = 2.0
DEFAULT_BATCH_SIZE = 3

# DP-YAH2 — single shared Yahoo priority (higher wins the IP).
YAHOO_PRIORITY_LIVE_MARKS = 100  # open-book / paper chart tips
YAHOO_PRIORITY_OPEN_BOOK_ENRICH = 50  # holdings fundamentals
YAHOO_PRIORITY_UNIVERSE = 10  # hist bootstrap / watchlist scrape
_PRIORITY_HOLD_S = 45.0

_gate_singleton_lock = threading.Lock()
_rate_gate: YahooRateGate | None = None


class YahooPriorityDenied(Exception):
    """Raised when a lower-priority Yahoo caller must yield (no network)."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "denied")
        super().__init__(self.reason)


class YahooRateGate:
    """Process-wide Yahoo request pacing + durable cooldown after 429/401 storms."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        backoff_start_s: float = DEFAULT_BACKOFF_START_S,
        backoff_max_s: float = DEFAULT_BACKOFF_MAX_S,
        backoff_mult: float = DEFAULT_BACKOFF_MULT,
    ) -> None:
        self.min_interval_s = float(min_interval_s)
        self.backoff_start_s = float(backoff_start_s)
        self.backoff_max_s = float(backoff_max_s)
        self.backoff_mult = float(backoff_mult)
        self._path: Path | None = None
        if data_dir:
            root = Path(data_dir) / "investment" / "fundamentals"
            root.mkdir(parents=True, exist_ok=True)
            self._path = root / "yahoo_rate_gate.json"
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._cooldown_until = 0.0
        self._backoff_s = self.backoff_start_s
        self._consecutive_blocks = 0
        self._last_block_status: int | None = None
        self._priority_hold = 0
        self._priority_hold_until = 0.0
        self._fundamentals_busy = False
        self._load()

    def _load(self) -> None:
        if not self._path or not self._path.is_file():
            return
        try:
            doc = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        if not isinstance(doc, dict):
            return
        self._last_request_at = float(doc.get("last_request_at") or 0)
        self._cooldown_until = float(doc.get("cooldown_until") or 0)
        self._backoff_s = float(doc.get("backoff_s") or self.backoff_start_s)
        self._consecutive_blocks = int(doc.get("consecutive_blocks") or 0)
        try:
            self._last_block_status = (
                int(doc["last_block_status"])
                if doc.get("last_block_status") is not None
                else None
            )
        except (TypeError, ValueError):
            self._last_block_status = None

    def _save(self) -> None:
        if not self._path:
            return
        doc = {
            "version": "lq.7.yahoo_rate_gate",
            "last_request_at": self._last_request_at,
            "cooldown_until": self._cooldown_until,
            "backoff_s": self._backoff_s,
            "consecutive_blocks": self._consecutive_blocks,
            "last_block_status": self._last_block_status,
            "min_interval_s": self.min_interval_s,
        }
        try:
            self._path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            _log.debug("yahoo rate gate save failed", exc_info=True)

    def remaining_cooldown_s(self) -> float:
        with self._lock:
            return max(0.0, self._cooldown_until - time.time())

    def status(self) -> dict[str, Any]:
        rem = self.remaining_cooldown_s()
        with self._lock:
            hold_rem = max(0.0, self._priority_hold_until - time.time())
            return {
                "version": "lq.7.yahoo_rate_gate",
                "ready": rem <= 0,
                "cooldown_remaining_s": round(rem, 1),
                "cooldown_until": self._cooldown_until or None,
                "min_interval_s": self.min_interval_s,
                "backoff_s": self._backoff_s,
                "consecutive_blocks": self._consecutive_blocks,
                "last_block_status": self._last_block_status,
                "priority_hold": self._priority_hold if hold_rem > 0 else 0,
                "priority_hold_remaining_s": round(hold_rem, 1),
                "honesty": (
                    "Slow-and-steady: ~1 Yahoo request every "
                    f"{self.min_interval_s:.0f}s; on 429/401 cool down up to "
                    f"{self.backoff_max_s:.0f}s then resume remaining gaps. "
                    "Priority: live marks ≫ open-book enrich ≫ universe."
                ),
            }

    def may_network(
        self,
        priority: int = YAHOO_PRIORITY_LIVE_MARKS,
        *,
        now=None,
    ) -> tuple[bool, str]:
        """DP-YAH2 — admit Yahoo network by priority (no sleep).

        RTH: only live marks. Off-hours: lower priority yields while a higher
        priority hold is active (open-book enrich beats universe scrape).
        """
        try:
            pri = int(priority)
        except (TypeError, ValueError):
            pri = YAHOO_PRIORITY_LIVE_MARKS
        rem = self.remaining_cooldown_s()
        if rem > 0:
            return False, "cooldown"
        if pri < YAHOO_PRIORITY_LIVE_MARKS and yahoo_background_should_yield_to_live(
            now=now
        ):
            return False, "rth_live_only"
        with self._lock:
            hold_until = float(self._priority_hold_until or 0)
            hold_pri = int(self._priority_hold or 0)
        if time.time() < hold_until and pri < hold_pri:
            return False, "yield_to_higher_priority"
        return True, "ok"

    def _note_priority_hold(self, priority: int) -> None:
        try:
            pri = int(priority)
        except (TypeError, ValueError):
            return
        if pri < YAHOO_PRIORITY_OPEN_BOOK_ENRICH:
            return
        with self._lock:
            self._priority_hold = max(int(self._priority_hold or 0), pri)
            self._priority_hold_until = time.time() + _PRIORITY_HOLD_S

    def wait(
        self,
        *,
        respect_cooldown: bool = True,
        priority: int = YAHOO_PRIORITY_LIVE_MARKS,
    ) -> float:
        """Block until it is polite to hit Yahoo. Returns seconds waited.

        ``respect_cooldown=False`` only enforces min-interval (legacy fallbacks).
        Prefer hard-pausing enrich / chart network while cooldown is active.
        Raises ``YahooPriorityDenied`` when priority/RTH policy forbids network.
        """
        if respect_cooldown:
            ok, reason = self.may_network(priority)
            # Never sleep through a 429 cooldown — that is the consecutive_blocks storm.
            if not ok:
                raise YahooPriorityDenied(reason)
        with self._lock:
            now = time.time()
            target = self._last_request_at + self.min_interval_s
            delay = max(0.0, target - now)
        if delay > 0:
            time.sleep(delay)
        with self._lock:
            self._last_request_at = time.time()
            self._save()
        self._note_priority_hold(priority)
        return delay

    def wait_chart(self, *, chart_interval_s: float = 0.85) -> float:
        """Pace chart API on the shared IP budget; honor fundamentals cooldown.

        Live marks always use ``YAHOO_PRIORITY_LIVE_MARKS`` (RTH-safe).
        """
        ok, reason = self.may_network(YAHOO_PRIORITY_LIVE_MARKS)
        if not ok:
            # Live marks must not wait-out fundamentals cooldown (Zerodha is the tape).
            raise YahooPriorityDenied(reason)
        interval = max(0.05, float(chart_interval_s))
        with self._lock:
            now = time.time()
            target = self._last_request_at + interval
            delay = max(0.0, target - now)
        if delay > 0:
            time.sleep(delay)
        with self._lock:
            self._last_request_at = time.time()
            self._save()
        self._note_priority_hold(YAHOO_PRIORITY_LIVE_MARKS)
        return delay

    def on_success(self) -> None:
        with self._lock:
            self._consecutive_blocks = 0
            self._backoff_s = self.backoff_start_s
            self._last_block_status = None
            if self._cooldown_until > time.time():
                self._cooldown_until = 0.0
            self._save()

    def try_begin_fundamentals(self) -> tuple[bool, str]:
        """Exclusive slot for quoteSummary / FEA / enrich (not live-mark charts)."""
        ok, reason = self.may_network(YAHOO_PRIORITY_OPEN_BOOK_ENRICH)
        if not ok:
            return False, reason
        with self._lock:
            if self._fundamentals_busy:
                return False, "fundamentals_busy"
            self._fundamentals_busy = True
        return True, "ok"

    def end_fundamentals(self) -> None:
        with self._lock:
            self._fundamentals_busy = False

    def on_block(self, status_code: int | None = 429) -> float:
        """Record a rate/auth block; returns cooldown seconds applied.

        While already cooling, do **not** increment ``consecutive_blocks`` —
        extra callers must not turn one 429 into a 1524-count storm.
        """
        with self._lock:
            already = self._cooldown_until > time.time()
            code = int(status_code) if status_code else 429
            self._last_block_status = code
            if already:
                cool = max(0.0, self._cooldown_until - time.time())
                self._save()
                return cool
            self._consecutive_blocks += 1
            cool = min(self.backoff_max_s, self._backoff_s)
            # 401 crumb storms: shorter first pause; 429: full backoff ladder
            if code == 401 and self._consecutive_blocks == 1:
                cool = min(cool, 45.0)
            self._cooldown_until = time.time() + cool
            self._backoff_s = min(self.backoff_max_s, cool * self.backoff_mult)
            self._save()
            _log.warning(
                "yahoo rate gate: HTTP %s → cooldown %.0fs (blocks=%s)",
                code,
                cool,
                self._consecutive_blocks,
            )
            try:
                from atlas.activity import record_activity

                # Throttle journal noise: emit on first block and every 25 thereafter
                if self._consecutive_blocks == 1 or self._consecutive_blocks % 25 == 0:
                    record_activity(
                        domain="market",
                        worker="yahoo_rate_gate",
                        action="yahoo_cooldown",
                        result="deferred",
                        summary=(
                            f"Yahoo rate gate entered cooldown {cool:.0f}s "
                            f"(HTTP {code}, consecutive_blocks={self._consecutive_blocks})"
                        ),
                        evidence={
                            "status_code": code,
                            "cooldown_s": cool,
                            "consecutive_blocks": self._consecutive_blocks,
                        },
                    )
            except Exception:  # noqa: BLE001
                pass
            # Append request audit line (OI-STAB0 Day 1)
            try:
                if self._path:
                    audit = self._path.parent.parent / "yahoo_request_audit.jsonl"
                    audit.parent.mkdir(parents=True, exist_ok=True)
                    with audit.open("a", encoding="utf-8") as fh:
                        fh.write(
                            json.dumps(
                                {
                                    "ts": time.time(),
                                    "worker": "yahoo_rate_gate",
                                    "symbol": None,
                                    "url_class": "rate_gate",
                                    "status": code,
                                    "cache_hit": False,
                                    "cooldown_s": cool,
                                    "consecutive_blocks": self._consecutive_blocks,
                                }
                            )
                            + "\n"
                        )
            except Exception:  # noqa: BLE001
                pass
            return cool


def get_yahoo_rate_gate(data_dir: str | Path | None = None) -> YahooRateGate:
    """Shared gate so API + worker honor the same cooldown file."""
    global _rate_gate
    with _gate_singleton_lock:
        if _rate_gate is None:
            _rate_gate = YahooRateGate(data_dir=data_dir)
        elif data_dir and _rate_gate._path is None:
            # Late-bind durable path once data_dir is known
            root = Path(data_dir) / "investment" / "fundamentals"
            root.mkdir(parents=True, exist_ok=True)
            _rate_gate._path = root / "yahoo_rate_gate.json"
            _rate_gate._load()
        return _rate_gate


def reset_yahoo_rate_gate_for_tests() -> None:
    """Test helper — drop process singleton (does not delete disk file)."""
    global _rate_gate
    with _gate_singleton_lock:
        _rate_gate = None


def is_yahoo_rate_block_error(err: str | None) -> bool:
    text = str(err or "").lower()
    return "http 429" in text or "http 401" in text or "getcrumb" in text


def yahoo_background_should_yield_to_live(*, now=None) -> bool:
    """True during NSE RTH — hist/enrich Yahoo must yield so paper marks can refresh.

    One IP. Background jobs keep their workers running; they just skip network.
    """
    try:
        from atlas.trading.sessions import is_session_open

        return bool(is_session_open("nse_equity", now=now))
    except Exception:  # noqa: BLE001
        return False


def _f(val: Any) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, dict) and "raw" in val:
        val = val.get("raw")
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_quote_summary(payload: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    """Map Yahoo quoteSummary modules → Atlas fundamental fields + evidence."""
    result = (payload.get("quoteSummary") or {}).get("result") or []
    if not result:
        return {"symbol": normalize_symbol(symbol), "fields": {}, "evidence": []}
    row = result[0] or {}
    stats = row.get("defaultKeyStatistics") or {}
    fin = row.get("financialData") or {}
    summary = row.get("summaryDetail") or {}
    price = row.get("price") or {}

    fields: dict[str, Any] = {}
    mapping = [
        ("pe", _f(stats.get("trailingPE")) or _f(summary.get("trailingPE"))),
        ("pb", _f(stats.get("priceToBook"))),
        ("market_cap", _f(price.get("marketCap")) or _f(summary.get("marketCap"))),
        ("shares", _f(stats.get("sharesOutstanding"))),
        ("fcf", _f(fin.get("freeCashflow"))),
        ("roe", _f(fin.get("returnOnEquity"))),
        ("debt_to_equity", _f(fin.get("debtToEquity"))),
        ("operating_margin", _f(fin.get("operatingMargins"))),
        ("net_margin", _f(fin.get("profitMargins"))),
        ("price", _f(price.get("regularMarketPrice")) or _f(fin.get("currentPrice"))),
    ]
    for key, val in mapping:
        if val is not None:
            # Yahoo ROE/margins often as fraction
            if key in {"roe", "operating_margin", "net_margin"} and abs(val) <= 1.5:
                val = val * 100.0
            # debtToEquity sometimes as percent-like 40 meaning 0.4 — keep as reported
            fields[key] = val

    # Earnings calendar timestamp when Yahoo exposes it (never invent commentary).
    earn_raw = stats.get("earningsTimestamp") or stats.get("earningsTimestampStart")
    earn_ts = None
    if isinstance(earn_raw, dict):
        earn_ts = _f(earn_raw.get("raw"))
    else:
        earn_ts = _f(earn_raw)
    if earn_ts is not None and earn_ts > 0:
        try:
            from datetime import datetime, timezone

            fields["earnings_date"] = datetime.fromtimestamp(
                float(earn_ts), tz=timezone.utc
            ).date().isoformat()
        except (OSError, OverflowError, ValueError):
            pass

    # Derive FCF from cashflow statement when freeCashflow module is empty
    # (common for some .NS names). Capex is typically negative on Yahoo.
    fcf_derived = False
    if fields.get("fcf") is None:
        cash_hist = row.get("cashflowStatementHistory") or {}
        statements = cash_hist.get("cashflowStatements") or []
        if statements and isinstance(statements[0], dict):
            st0 = statements[0]
            op_cf = _f(st0.get("totalCashFromOperatingActivities"))
            capex = _f(st0.get("capitalExpenditures"))
            period = None
            end = st0.get("endDate")
            if isinstance(end, dict) and end.get("fmt"):
                period = str(end.get("fmt"))
            elif isinstance(end, dict) and end.get("raw"):
                try:
                    from datetime import datetime, timezone

                    period = datetime.fromtimestamp(
                        float(end["raw"]), tz=timezone.utc
                    ).date().isoformat()
                except (OSError, OverflowError, TypeError, ValueError):
                    period = None
            if op_cf is not None and capex is not None:
                fields["fcf"] = op_cf + capex
                fcf_derived = True
                fields["_fcf_derive"] = {
                    "value_type": "derived",
                    "formula": "operating_cash_flow + capital_expenditures",
                    "inputs": {
                        "operating_cash_flow": op_cf,
                        "capital_expenditures": capex,
                    },
                    "period": period,
                    "note": (
                        "Yahoo freeCashflow empty — FCF derived from cashflow "
                        "statement (CapEx typically negative on Yahoo)."
                    ),
                }

    derive_meta = fields.pop("_fcf_derive", None) if "_fcf_derive" in fields else None
    evidence = []
    for k, v in fields.items():
        raw_ref: dict[str, Any] = {
            "symbol": normalize_symbol(symbol),
            "module": (
                "cashflowStatementHistory"
                if (k == "fcf" and fcf_derived)
                else "quoteSummary"
            ),
            "value_type": "reported",
        }
        if k == "fcf" and isinstance(derive_meta, dict):
            raw_ref.update(derive_meta)
        elif k == "fcf":
            raw_ref["value_type"] = "reported"
            raw_ref["yahoo_field"] = "financialData.freeCashflow"
        evidence.append(
            make_evidence_value(
                field=k,
                value=v,
                provider=PROVIDER_ID,
                source=PROVIDER_ID,
                raw_ref=raw_ref,
                ttl_hours=168,
            )
        )
    return {
        "symbol": normalize_symbol(symbol),
        "fields": fields,
        "evidence": evidence,
        "provider": PROVIDER_ID,
        "version": VERSION,
        "fcf_value_type": (
            "derived" if fcf_derived else ("reported" if fields.get("fcf") is not None else None)
        ),
    }


def parse_quote_html(html: str, *, symbol: str) -> dict[str, Any]:
    """Best-effort fields from Yahoo quote HTML when JSON APIs are blocked.

    Medium confidence only — used as Tier C fallback, never invented.
    """
    import re

    text = html or ""
    fields: dict[str, Any] = {}

    def _grab(*patterns: str) -> float | None:
        for pat in patterns:
            m = re.search(pat, text, re.I | re.S)
            if not m:
                continue
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                continue
        return None

    pe = _grab(
        r'trailingPE"[^>]*>\s*([0-9.]+)',
        r'trailingPE\\":\{\\"raw\\":([0-9.]+)',
        r'"trailingPE":\{"raw":([0-9.]+)',
    )
    if pe is not None:
        fields["pe"] = pe
    pb = _grab(
        r'priceToBook\\":\{\\"raw\\":([0-9.]+)',
        r'"priceToBook":\{"raw":([0-9.]+)',
    )
    if pb is not None:
        fields["pb"] = pb
    # Prefer INR quote page price near market; avoid unrelated embeds when possible
    price = _grab(
        r'data-symbol="' + re.escape(normalize_symbol(symbol)) + r'"[^>]*data-field="regularMarketPrice"[^>]*value="([0-9.]+)"',
        r'fin-streamer[^>]*data-field="regularMarketPrice"[^>]*value="([0-9.]+)"',
    )
    if price is not None:
        fields["price"] = price
    roe = _grab(r'returnOnEquity\\":\{\\"raw\\":([-0-9.]+)', r'"returnOnEquity":\{"raw":([-0-9.]+)')
    if roe is not None:
        if abs(roe) <= 1.5:
            roe *= 100.0
        fields["roe"] = roe
    fcf = _grab(r'freeCashflow\\":\{\\"raw\\":([-0-9.]+)', r'"freeCashflow":\{"raw":([-0-9.]+)')
    if fcf is not None:
        fields["fcf"] = fcf
    de = _grab(r'debtToEquity\\":\{\\"raw\\":([-0-9.]+)', r'"debtToEquity":\{"raw":([-0-9.]+)')
    if de is not None:
        fields["debt_to_equity"] = de

    evidence = [
        make_evidence_value(
            field=k,
            value=v,
            provider=PROVIDER_ID,
            source=PROVIDER_ID,
            raw_ref={"symbol": normalize_symbol(symbol), "module": "quote_html_fallback"},
            ttl_hours=168,
        )
        for k, v in fields.items()
    ]
    return {
        "symbol": normalize_symbol(symbol),
        "fields": fields,
        "evidence": evidence,
        "provider": PROVIDER_ID,
        "version": VERSION,
        "fallback": "quote_html",
    }


def parse_chart_meta(payload: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    """Price (and light meta) from Yahoo chart API — works without crumb."""
    result = (payload.get("chart") or {}).get("result") or []
    fields: dict[str, Any] = {}
    if result:
        meta = result[0].get("meta") if isinstance(result[0], dict) else {}
        price = _f((meta or {}).get("regularMarketPrice"))
        if price is not None:
            fields["price"] = price
    evidence = [
        make_evidence_value(
            field=k,
            value=v,
            provider=PROVIDER_ID,
            source=PROVIDER_ID,
            raw_ref={"symbol": normalize_symbol(symbol), "module": "chart"},
            ttl_hours=24,
        )
        for k, v in fields.items()
    ]
    return {
        "symbol": normalize_symbol(symbol),
        "fields": fields,
        "evidence": evidence,
        "provider": PROVIDER_ID,
        "version": VERSION,
        "fallback": "chart",
    }


def _with_crumb(url: str, crumb: str) -> str:
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["crumb"] = crumb
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def clear_yahoo_crumb_cache() -> None:
    """Test helper — drop process-wide crumb cache."""
    global _cached_crumb
    with _crumb_lock:
        _cached_crumb = None


class YahooFundamentalsProvider:
    """Opt-in Yahoo fundamentals: quoteSummary (+ crumb), then chart/HTML fallbacks."""

    name = PROVIDER_ID

    def __init__(
        self,
        *,
        enabled: bool = False,
        timeout: float = 20.0,
        opener: Any | None = None,
        logger: logging.Logger | None = None,
        rate_gate: YahooRateGate | None = None,
        data_dir: str | Path | None = None,
        yahoo_priority: int = YAHOO_PRIORITY_OPEN_BOOK_ENRICH,
    ) -> None:
        self._enabled = bool(enabled)
        self._timeout = float(timeout)
        self._opener = opener
        self._logger = logger or _log
        self._client: Any | None = None
        self._session_crumb: str | None = None
        self._yahoo_priority = int(yahoo_priority or YAHOO_PRIORITY_OPEN_BOOK_ENRICH)
        # Hermetic tests: no live pacing
        self._gate = None if opener is not None else (rate_gate or get_yahoo_rate_gate(data_dir))

    def _pace(
        self,
        *,
        respect_cooldown: bool = True,
        priority: int | None = None,
    ) -> None:
        if self._gate is not None:
            pri = self._yahoo_priority if priority is None else int(priority)
            self._gate.wait(respect_cooldown=respect_cooldown, priority=pri)

    def _note_http(self, status_code: int, *, clears_cooldown: bool = True) -> None:
        if self._gate is None:
            return
        if status_code in {429, 401, 403}:
            self._gate.on_block(status_code)
        elif status_code < 400 and clears_cooldown:
            self._gate.on_success()

    def fetch_symbol(self, symbol: str) -> dict[str, Any]:
        sym = normalize_symbol(symbol)
        if not sym:
            return {"symbol": sym, "fields": {}, "evidence": [], "error": "empty_symbol"}
        if not self._enabled:
            return {
                "symbol": sym,
                "fields": {},
                "evidence": [],
                "error": "yahoo_fundamentals_disabled",
                "hint": "Enable market.yahoo_enabled or pass enabled=True for enrich",
            }
        # Hermetic tests inject opener — keep quoteSummary-only path
        if self._opener is not None:
            url = QUOTE_SUMMARY_URL.format(symbol=sym)
            try:
                payload = self._fetch_json(url)
            except Exception as exc:  # noqa: BLE001
                return {"symbol": sym, "fields": {}, "evidence": [], "error": str(exc)[:200]}
            parsed = parse_quote_summary(
                payload if isinstance(payload, dict) else {}, symbol=sym
            )
            if not parsed.get("fields"):
                parsed["error"] = "empty_quote_summary"
            return parsed

        # Hard-pause while cooldown is armed — do not burn shared IP on fallbacks.
        cooldown = (
            self._gate.remaining_cooldown_s() if self._gate is not None else 0.0
        )
        if cooldown > 0:
            return {
                "symbol": sym,
                "fields": {},
                "evidence": [],
                "error": f"yahoo_cooldown ({cooldown:.0f}s)",
                "rate_limited": True,
                "hint": (
                    "Yahoo enrich paused during rate-gate cooldown. "
                    "Prefer Screener/CSV for FCF; resume after cooldown."
                ),
            }

        # Exclusive fundamentals slot — FEA/enrich cannot stack 429s.
        if self._gate is not None:
            ok, reason = self._gate.try_begin_fundamentals()
            if not ok:
                return {
                    "symbol": sym,
                    "fields": {},
                    "evidence": [],
                    "error": f"yahoo_priority_denied ({reason})",
                    "rate_limited": True,
                    "priority_denied": reason,
                    "hint": (
                        "Yahoo enrich deferred — cooldown, live marks, or another "
                        "fundamentals caller owns the shared IP budget."
                    ),
                }

        try:
            return self._fetch_symbol_network(sym)
        finally:
            if self._gate is not None:
                self._gate.end_fundamentals()

    def _fetch_symbol_network(self, sym: str) -> dict[str, Any]:
        primary_err: str | None = None
        try:
            payload = self._fetch_json(QUOTE_SUMMARY_URL.format(symbol=sym))
            parsed = parse_quote_summary(
                payload if isinstance(payload, dict) else {}, symbol=sym
            )
            if parsed.get("fields"):
                return parsed
            primary_err = "empty_quote_summary"
        except YahooPriorityDenied as exc:
            return {
                "symbol": sym,
                "fields": {},
                "evidence": [],
                "error": f"yahoo_priority_denied ({exc.reason})",
                "rate_limited": True,
                "priority_denied": exc.reason,
            }
        except Exception as exc:  # noqa: BLE001
            primary_err = str(exc)[:180]
            self._logger.debug("yahoo quoteSummary failed %s: %s", sym, exc)
            if is_yahoo_rate_block_error(primary_err):
                return {
                    "symbol": sym,
                    "fields": {},
                    "evidence": [],
                    "error": primary_err,
                    "rate_limited": True,
                    "hint": (
                        "Yahoo quoteSummary blocked — cooldown armed; "
                        "no chart/HTML probes this tick."
                    ),
                }

        # Fallbacks only when quoteSummary returned empty (not rate-blocked).
        merged: dict[str, Any] = {}
        evidence: list[dict[str, Any]] = []
        used: list[str] = []
        fallback_blocked = False
        try:
            chart = self._fetch_chart(sym)
            if chart.get("fields"):
                merged.update(chart["fields"])
                evidence.extend(chart.get("evidence") or [])
                used.append("chart")
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("yahoo chart fallback failed %s: %s", sym, exc)
            if is_yahoo_rate_block_error(str(exc)):
                fallback_blocked = True
        try:
            html_doc = self._fetch_quote_html(sym)
            if html_doc.get("fields"):
                for k, v in html_doc["fields"].items():
                    if merged.get(k) is None:
                        merged[k] = v
                evidence.extend(html_doc.get("evidence") or [])
                used.append("quote_html")
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("yahoo html fallback failed %s: %s", sym, exc)
            if is_yahoo_rate_block_error(str(exc)):
                fallback_blocked = True

        if not merged:
            return {
                "symbol": sym,
                "fields": {},
                "evidence": [],
                "error": primary_err or "yahoo_fundamentals_unavailable",
                "rate_limited": fallback_blocked,
                "hint": (
                    "Yahoo JSON APIs blocked (401/429). Retry later, or import "
                    "Screener CSV on Invest intel (Tier B)."
                ),
            }
        out_evidence = [
            make_evidence_value(
                field=k,
                value=v,
                provider=PROVIDER_ID,
                source=PROVIDER_ID,
                raw_ref={
                    "symbol": sym,
                    "module": "+".join(used) or "fallback",
                    "primary_error": primary_err,
                },
                ttl_hours=168,
            )
            for k, v in merged.items()
        ]
        return {
            "symbol": sym,
            "fields": merged,
            "evidence": out_evidence,
            "provider": PROVIDER_ID,
            "version": VERSION,
            "fallback": "+".join(used),
            "warning": primary_err,
        }

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx

        self._client = httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "User-Agent": YAHOO_USER_AGENT,
                "Accept": "application/json,text/javascript,text/html,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        return self._client

    def _obtain_crumb(self, client: Any, *, force: bool = False) -> str:
        global _cached_crumb
        with _crumb_lock:
            if not force and (self._session_crumb or _cached_crumb):
                crumb = self._session_crumb or _cached_crumb
                assert crumb
                return crumb
        # Seed cookies via quote page (more reliable than fc.yahoo alone)
        self._pace()
        try:
            seed = client.get(COOKIE_SEED_URL)
            self._note_http(getattr(seed, "status_code", 200) or 200)
        except Exception:  # noqa: BLE001
            self._logger.debug("yahoo cookie seed failed", exc_info=True)
        last_status = None
        crumb = ""
        for crumb_url in CRUMB_URLS:
            self._pace()
            resp = client.get(crumb_url)
            last_status = resp.status_code
            if resp.status_code in {429, 401, 403}:
                self._note_http(resp.status_code)
                # Do not hammer alternate crumb hosts during a block
                break
            if resp.status_code >= 400:
                continue
            crumb = str(resp.text or "").strip()
            if crumb and "<" not in crumb:
                self._note_http(resp.status_code)
                break
            crumb = ""
        if not crumb:
            # Rate/auth already noted inside the loop — do not double-arm cooldown.
            raise RuntimeError(
                f"HTTP {last_status or '?'} from Yahoo getcrumb "
                "(fundamentals auth blocked — cooldown armed; resume later)"
            )
        with _crumb_lock:
            _cached_crumb = crumb
            self._session_crumb = crumb
        return crumb

    def _fetch_json(self, url: str) -> dict[str, Any]:
        if self._opener is not None:
            data = self._opener(url)
            return data if isinstance(data, dict) else json.loads(data)

        client = self._ensure_client()
        crumb = self._obtain_crumb(client)
        self._pace()
        authed = _with_crumb(url, crumb)
        resp = client.get(authed)
        # Soft crumb expiry: one refresh without arming cooldown yet
        if resp.status_code in {401, 403}:
            clear_yahoo_crumb_cache()
            self._session_crumb = None
            crumb = self._obtain_crumb(client, force=True)
            self._pace()
            resp = client.get(_with_crumb(url, crumb))
        if resp.status_code == 429:
            self._note_http(429)
            raise RuntimeError(
                "HTTP 429 from Yahoo quoteSummary (rate limited — cooldown armed)"
            )
        if resp.status_code >= 400:
            self._note_http(resp.status_code)
            raise RuntimeError(
                f"HTTP {resp.status_code} from Yahoo quoteSummary "
                "(after crumb auth)"
            )
        self._note_http(resp.status_code)
        return resp.json()

    def _fetch_chart(self, symbol: str) -> dict[str, Any]:
        import httpx

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            "?interval=1d&range=5d"
        )
        # Share IP budget with fundamentals gate; honor cooldown (prefer durable bars).
        self._pace(respect_cooldown=True)
        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": "AtlasMarketReader/1.0"},
        ) as client:
            resp = client.get(url)
            if resp.status_code in {429, 401, 403}:
                self._note_http(resp.status_code, clears_cooldown=False)
                raise RuntimeError(f"HTTP {resp.status_code} from Yahoo chart")
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} from Yahoo chart")
            # Chart success must not clear crumb cooldown (different Yahoo surface).
            return parse_chart_meta(resp.json(), symbol=symbol)

    def _fetch_quote_html(self, symbol: str) -> dict[str, Any]:
        client = self._ensure_client()
        self._pace(respect_cooldown=True)
        resp = client.get(f"https://finance.yahoo.com/quote/{symbol}")
        status = int(getattr(resp, "status_code", 0) or 0)
        body = resp.text or ""
        # Yahoo often soft-blocks with tiny HTTP 404 bodies (not a real missing page).
        soft_404 = status == 404 and len(body) < 2000
        if status in {429, 401, 403} or soft_404:
            self._note_http(429 if soft_404 else status, clears_cooldown=False)
            raise RuntimeError(
                f"HTTP {status} from Yahoo quote page"
                + (" (soft block)" if soft_404 else "")
            )
        if status >= 400:
            raise RuntimeError(f"HTTP {status} from Yahoo quote page")
        # HTML success must not clear crumb cooldown.
        self._note_http(status, clears_cooldown=False)
        return parse_quote_html(body, symbol=symbol)
