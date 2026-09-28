"""OI-MDPH0 — Market Data Provider Health (Zerodha-first).

Deterministic controller for broker-authorized live data trustworthiness.
Human owns login/2FA only; Atlas owns detect → prompt → store → probe → gate.

LOCKED (2026-09-03):
  - LIVE-REQUIRED labs (intraday/F&O) PAUSE when not READY (no silent Yahoo)
  - NON-LIVE labs CONTINUE on labeled alternate sources
  - Operational NOT_EVALUABLE ≠ investment learning failure
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.zerodha_feed import ZerodhaMarketFeed, _ist_today

_log = logging.getLogger("atlas.investment.mdph")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "mdph.provider_health.v1"
STORE_REL = Path("investment") / "market_data_provider"

STATUS_READY = "READY"
STATUS_LOGIN_REQUIRED = "LOGIN_REQUIRED"
STATUS_EXPIRED = "EXPIRED"
STATUS_DEGRADED = "DEGRADED"
STATUS_ERROR = "ERROR"

FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

INSTRUMENT_VALID = "VALID"
INSTRUMENT_INVALID = "INVALID"
INSTRUMENT_STALE = "STALE"
INSTRUMENT_ABSENT = "ABSENT"

REASON_PROVIDER_LOGIN_REQUIRED = "PROVIDER_LOGIN_REQUIRED"
REASON_PROVIDER_DEGRADED = "PROVIDER_DEGRADED"
REASON_PROVIDER_ERROR = "PROVIDER_ERROR"
REASON_PROVIDER_EXPIRED = "PROVIDER_EXPIRED"
REASON_DATA_STALE = "DATA_STALE"
REASON_INSTRUMENT_STALE = "INSTRUMENT_STALE"
REASON_INSTRUMENT_INVALID = "INSTRUMENT_INVALID"
REASON_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"

DECISION_NOT_EVALUABLE = "NOT_EVALUABLE"

# Probe hysteresis
_DEFAULT_FRESHNESS_MAX_AGE_MS = 120_000.0  # 2 min for LIVE_LTP
_REPROBE_WINDOW = 3
_REPROBE_PASS_NEED = 2
_DEGRADED_TO_ERROR_FAILS = 5
_MIN_REPROBE_INTERVAL_S = 30.0

_lock = threading.Lock()
_probe_results: list[bool] = []
_last_reprobe_mono: float = 0.0
_consecutive_fails: int = 0


def reset_probe_state_for_tests() -> None:
    """Clear hysteresis state (unit tests only)."""
    global _last_reprobe_mono, _consecutive_fails
    with _lock:
        _probe_results.clear()
        _last_reprobe_mono = 0.0
        _consecutive_fails = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ist_day() -> str:
    return _ist_today().isoformat()


def _health_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL / "zerodha_health.json"


def _instrument_meta_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL / "zerodha_instruments_meta.json"


def load_health(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {}
    path = _health_path(data_dir)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_health(data_dir: str | Path | None, doc: dict[str, Any]) -> None:
    if not data_dir:
        return
    path = _health_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("mdph health write failed", exc_info=True)


def load_instrument_meta(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {}
    path = _instrument_meta_path(data_dir)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_instrument_meta(data_dir: str | Path | None, doc: dict[str, Any]) -> None:
    if not data_dir:
        return
    path = _instrument_meta_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("mdph instrument meta write failed", exc_info=True)


def freshness_of(
    *,
    as_of: str | None,
    received_at: str | None = None,
    max_age_ms: float = _DEFAULT_FRESHNESS_MAX_AGE_MS,
) -> tuple[str, float | None]:
    """Return (FRESH|STALE|UNKNOWN, age_ms)."""
    if not as_of and not received_at:
        return UNKNOWN, None
    raw = received_at or as_of
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_ms = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds() * 1000.0
        if age_ms < 0:
            age_ms = 0.0
        if age_ms <= float(max_age_ms):
            return FRESH, age_ms
        return STALE, age_ms
    except (TypeError, ValueError):
        return UNKNOWN, None


def observation_provenance(
    *,
    provider: str = "zerodha",
    endpoint: str = "ltp",
    provider_status: str,
    symbol: str,
    price: Any = None,
    as_of: str | None = None,
    received_at: str | None = None,
    instrument_token: Any = None,
    instrument_dump_date: str | None = None,
    max_age_ms: float = _DEFAULT_FRESHNESS_MAX_AGE_MS,
) -> dict[str, Any]:
    recv = received_at or _now_iso()
    fresh, age_ms = freshness_of(as_of=as_of or recv, received_at=recv, max_age_ms=max_age_ms)
    return {
        "source_provider": provider,
        "source_endpoint": endpoint,
        "provider_status": provider_status,
        "symbol": str(symbol or "").upper(),
        "price": price,
        "as_of": as_of or recv,
        "received_at": recv,
        "age_ms": age_ms,
        "market_session": _session_label(),
        "data_class": "LIVE_LTP" if endpoint == "ltp" else endpoint.upper(),
        "freshness": fresh,
        "instrument_token": instrument_token,
        "instrument_dump_date": instrument_dump_date,
        "version": VERSION,
    }


def _session_label() -> str:
    now = datetime.now(_IST).time()
    from datetime import time as dtime

    if now >= dtime(9, 15) and now < dtime(15, 30):
        return "RTH"
    if now >= dtime(15, 30) and now < dtime(16, 0):
        return "POST"
    return "CLOSED"


def reason_for_status(status: str) -> str:
    return {
        STATUS_LOGIN_REQUIRED: REASON_PROVIDER_LOGIN_REQUIRED,
        STATUS_EXPIRED: REASON_PROVIDER_EXPIRED,
        STATUS_DEGRADED: REASON_PROVIDER_DEGRADED,
        STATUS_ERROR: REASON_PROVIDER_ERROR,
    }.get(status, REASON_PROVIDER_ERROR)


def live_trading_allowed(health: dict[str, Any]) -> bool:
    """Live-required labs may only proceed when READY and LTP not STALE."""
    if str(health.get("status") or "") != STATUS_READY:
        return False
    if str(health.get("freshness") or FRESH) == STALE:
        return False
    if str(health.get("instrument_master") or "") == INSTRUMENT_INVALID:
        return False
    return True


def not_evaluable_payload(health: dict[str, Any]) -> dict[str, Any]:
    status = str(health.get("status") or STATUS_ERROR)
    reason = reason_for_status(status)
    if str(health.get("freshness")) == STALE and status == STATUS_READY:
        reason = REASON_DATA_STALE
    if str(health.get("instrument_master")) == INSTRUMENT_INVALID:
        reason = REASON_INSTRUMENT_INVALID
    elif str(health.get("instrument_master")) == INSTRUMENT_STALE and status == STATUS_READY:
        # Soft: still allow READY if LTP ok, but surface code when gating instruments
        pass
    return {
        "decision_status": DECISION_NOT_EVALUABLE,
        "reason_code": reason,
        "class": "operational",
        "provider": "zerodha",
        "provider_status": status,
        "version": VERSION,
    }


def _record_probe(ok: bool) -> tuple[int, int]:
    """Return (passes, total) in rolling window."""
    global _consecutive_fails
    with _lock:
        _probe_results.append(bool(ok))
        del _probe_results[:-_REPROBE_WINDOW]
        if ok:
            _consecutive_fails = 0
        else:
            _consecutive_fails += 1
        passes = sum(1 for x in _probe_results if x)
        return passes, len(_probe_results)


def probe_ltp(feed: ZerodhaMarketFeed, *, symbol: str = "RELIANCE.NS") -> dict[str, Any]:
    """Smoke LTP; returns ok + provenance fields (no secrets)."""
    out = feed.get_ltp(symbol)
    received = _now_iso()
    if not out.get("ok"):
        return {
            "ok": False,
            "error": out.get("error"),
            "received_at": received,
            "symbol": symbol,
        }
    prices = out.get("prices") or {}
    mark = prices.get(symbol) or {}
    as_of = mark.get("as_of") or received
    fresh, age_ms = freshness_of(as_of=as_of, received_at=received)
    return {
        "ok": True,
        "symbol": symbol,
        "last": mark.get("last"),
        "as_of": as_of,
        "received_at": received,
        "age_ms": age_ms,
        "freshness": fresh,
        "instrument_token": mark.get("instrument_token"),
        "source": mark.get("source") or "zerodha",
    }


def probe_historical(
    feed: ZerodhaMarketFeed,
    *,
    symbol: str = "RELIANCE.NS",
    interval: str = "5minute",
    limit: int = 5,
) -> dict[str, Any]:
    """Smoke Kite historical candles (needed by live-required OHLCV paths)."""
    out = feed.get_historical_bars(symbol, interval=interval, limit=limit)
    received = _now_iso()
    if not out.get("ok"):
        return {
            "ok": False,
            "error": out.get("error"),
            "received_at": received,
            "symbol": symbol,
            "interval": interval,
        }
    bars = out.get("bars") or []
    tip = bars[-1] if bars else {}
    return {
        "ok": True,
        "symbol": symbol,
        "interval": out.get("interval") or interval,
        "bar_count": len(bars),
        "tip_close": tip.get("close"),
        "tip_t": tip.get("t") or tip.get("date"),
        "instrument_token": out.get("instrument_token"),
        "received_at": received,
        "source": "zerodha",
    }


def refresh_instrument_master(
    feed: ZerodhaMarketFeed,
    data_dir: str | Path | None,
    *,
    required_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Lightweight instrument integrity: list NSE instruments + map required symbols."""
    day = _ist_day()
    if not feed.has_session:
        meta = {
            "status": INSTRUMENT_ABSENT,
            "ist_day": day,
            "updated_at": _now_iso(),
            "reason": "no_session",
        }
        save_instrument_meta(data_dir, meta)
        return meta
    if not feed._init_client(require_session=True) or feed._client is None:  # noqa: SLF001
        meta = {
            "status": INSTRUMENT_INVALID,
            "ist_day": day,
            "updated_at": _now_iso(),
            "reason": "client_unavailable",
        }
        save_instrument_meta(data_dir, meta)
        return meta
    try:
        rows = feed._client.instruments("NSE")  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        meta = {
            "status": INSTRUMENT_INVALID,
            "ist_day": day,
            "updated_at": _now_iso(),
            "reason": f"{type(exc).__name__}: {exc}"[:200],
        }
        save_instrument_meta(data_dir, meta)
        return meta

    if not isinstance(rows, list) or len(rows) < 1000:
        meta = {
            "status": INSTRUMENT_INVALID,
            "ist_day": day,
            "updated_at": _now_iso(),
            "reason": f"unexpected_count:{len(rows) if isinstance(rows, list) else type(rows)}",
            "count": len(rows) if isinstance(rows, list) else 0,
        }
        save_instrument_meta(data_dir, meta)
        return meta

    # Build tradingsymbol → token for equity EQ
    by_sym: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("instrument_type") or "").upper() not in {"EQ", ""}:
            # Still allow EQ primarily
            if str(row.get("segment") or "").upper() not in {"NSE", "NSE.EQ", ""}:
                continue
        tsym = str(row.get("tradingsymbol") or "").upper()
        tok = row.get("instrument_token")
        if tsym and tok is not None:
            by_sym[tsym] = int(tok)

    required = required_symbols or ["RELIANCE", "INFY", "TCS", "SBIN", "HDFCBANK"]
    mappings: dict[str, Any] = {}
    missing: list[str] = []
    for atlas_sym in required:
        clean = ZerodhaMarketFeed.format_symbol(atlas_sym)
        tok = by_sym.get(clean)
        if tok is None:
            missing.append(atlas_sym)
            mappings[atlas_sym] = {"status": "MISSING", "tradingsymbol": clean}
        else:
            mappings[atlas_sym] = {
                "status": "VALID",
                "exchange": "NSE",
                "tradingsymbol": clean,
                "instrument_token": tok,
            }

    status = INSTRUMENT_VALID if not missing else INSTRUMENT_INVALID
    # Day stamp: if dump from prior day file existed, mark STALE when day differs
    prev = load_instrument_meta(data_dir)
    if prev.get("ist_day") and prev.get("ist_day") != day and status == INSTRUMENT_VALID:
        # Fresh fetch today → VALID; STALE only if we *didn't* refresh
        pass

    meta = {
        "status": status,
        "ist_day": day,
        "updated_at": _now_iso(),
        "count": len(rows),
        "equity_map_size": len(by_sym),
        "missing_required": missing,
        "mappings": mappings,
        "version": VERSION,
    }
    save_instrument_meta(data_dir, meta)
    return meta


def evaluate_zerodha_health(
    data_dir: str | Path | None,
    *,
    feed: ZerodhaMarketFeed | None = None,
    probe: bool = True,
    refresh_instruments: bool = False,
    force_reprobe: bool = False,
) -> dict[str, Any]:
    """Compute + persist provider health (state machine with hysteresis)."""
    global _last_reprobe_mono

    data_dir = Path(data_dir) if data_dir else None
    feed = feed or ZerodhaMarketFeed.from_env(data_dir=data_dir)
    prev = load_health(data_dir)
    day = _ist_day()
    inst_meta = load_instrument_meta(data_dir)

    doc: dict[str, Any] = {
        "version": VERSION,
        "provider": "zerodha",
        "trading_date": day,
        "configured": feed.is_configured,
        "login_url_path": "/zerodha/login",
        "updated_at": _now_iso(),
    }

    if not feed.is_configured:
        doc.update(
            {
                "status": STATUS_ERROR,
                "token_valid": False,
                "ltp_probe": "FAIL",
                "reason_code": REASON_NOT_CONFIGURED,
                "instrument_master": INSTRUMENT_ABSENT,
                "cta": None,
                "live_trading_allowed": False,
            }
        )
        save_health(data_dir, doc)
        return doc

    if not feed.has_session:
        # Day roll or never logged in
        status = STATUS_LOGIN_REQUIRED
        if prev.get("status") == STATUS_READY and prev.get("trading_date") != day:
            status = STATUS_EXPIRED
        doc.update(
            {
                "status": status,
                "token_valid": False,
                "ltp_probe": "FAIL",
                "reason_code": reason_for_status(status),
                "instrument_master": inst_meta.get("status") or INSTRUMENT_ABSENT,
                "cta": "/zerodha/login",
                "message": "Zerodha authentication required before live market session.",
                "live_trading_allowed": False,
                "freshness": UNKNOWN,
            }
        )
        save_health(data_dir, doc)
        return doc

    # Cheap status read: reuse same-day health when caller did not ask to probe
    if (
        not probe
        and not force_reprobe
        and prev.get("trading_date") == day
        and prev.get("token_valid")
        and prev.get("status")
    ):
        doc = dict(prev)
        doc.update(
            {
                "version": VERSION,
                "provider": "zerodha",
                "trading_date": day,
                "configured": True,
                "login_url_path": "/zerodha/login",
                "updated_at": _now_iso(),
                "instrument_master": (
                    INSTRUMENT_STALE
                    if inst_meta.get("ist_day") and inst_meta.get("ist_day") != day
                    else (inst_meta.get("status") or prev.get("instrument_master") or INSTRUMENT_ABSENT)
                ),
            }
        )
        doc["live_trading_allowed"] = live_trading_allowed(doc)
        doc["live_required_labs"] = ["equity_intraday_learner", "india_fno_learner"]
        doc["non_live_labs"] = ["india_equity_learner"]
        return doc

    # Session present for today — LTP probe with DEGRADED hysteresis
    do_probe = True
    now_mono = time.monotonic()
    if (
        not force_reprobe
        and prev.get("status") == STATUS_DEGRADED
        and (now_mono - _last_reprobe_mono) < _MIN_REPROBE_INTERVAL_S
    ):
        # Keep prior DEGRADED briefly between reprobes
        do_probe = False

    if do_probe:
        _last_reprobe_mono = now_mono
        ltp = probe_ltp(feed)
        passes, total = _record_probe(bool(ltp.get("ok")))
    else:
        with _lock:
            passes = sum(1 for x in _probe_results if x)
            total = len(_probe_results)
        ltp = {
            "ok": False,
            "skipped": True,
            "error": prev.get("last_ltp_error") or "reprobe_deferred",
            "as_of": prev.get("last_ltp_as_of"),
            "received_at": prev.get("last_ltp_received_at"),
            "freshness": prev.get("freshness"),
        }

    if refresh_instruments or not inst_meta or inst_meta.get("ist_day") != day:
        inst_meta = refresh_instrument_master(feed, data_dir)

    inst_status = str(inst_meta.get("status") or INSTRUMENT_ABSENT)
    if inst_meta.get("ist_day") and inst_meta.get("ist_day") != day:
        inst_status = INSTRUMENT_STALE

    if ltp.get("ok"):
        status = STATUS_READY
        # If coming from DEGRADED, require majority pass
        if prev.get("status") in {STATUS_DEGRADED, STATUS_ERROR} and total >= _REPROBE_WINDOW:
            if passes < _REPROBE_PASS_NEED:
                status = STATUS_DEGRADED
        doc.update(
            {
                "status": status,
                "token_valid": True,
                "ltp_probe": "PASS" if status == STATUS_READY else "FAIL",
                "last_successful_ltp": ltp.get("received_at"),
                "last_ltp_as_of": ltp.get("as_of"),
                "last_ltp_received_at": ltp.get("received_at"),
                "last_ltp_symbol": ltp.get("symbol"),
                "last_ltp_price": ltp.get("last"),
                "freshness": ltp.get("freshness") or FRESH,
                "age_ms": ltp.get("age_ms"),
                "instrument_master": inst_status,
                "instrument_count": inst_meta.get("count"),
                "probe_window_passes": passes,
                "probe_window_total": total,
                "cta": None,
                "message": None,
                "reason_code": None,
            }
        )
        # Historical candles (soft): needed for live OHLCV; do not demote READY alone
        if force_reprobe or refresh_instruments:
            hist = probe_historical(feed)
            if hist.get("ok"):
                doc["hist_probe"] = "PASS"
                doc["hist_bar_count"] = hist.get("bar_count")
                doc["hist_tip_close"] = hist.get("tip_close")
                doc["hist_interval"] = hist.get("interval")
                doc["hist_error"] = None
            else:
                doc["hist_probe"] = "FAIL"
                doc["hist_error"] = hist.get("error")
                if status == STATUS_READY:
                    doc["message"] = (
                        "LTP READY but historical candles failed — "
                        "live OHLCV labs may gap until hist works."
                    )
        else:
            doc["hist_probe"] = prev.get("hist_probe")
            doc["hist_bar_count"] = prev.get("hist_bar_count")
            doc["hist_tip_close"] = prev.get("hist_tip_close")
            doc["hist_interval"] = prev.get("hist_interval")
            doc["hist_error"] = prev.get("hist_error")
    else:
        # Failure path
        with _lock:
            fails = _consecutive_fails
        err = str(ltp.get("error") or "")
        auth_dead = any(
            needle in err
            for needle in (
                "TokenException",
                "Incorrect `api_key` or `access_token`",
                "Incorrect api_key or access_token",
                "Invalid `api_key`",
                "invalid token",
                "session expired",
            )
        )
        if auth_dead:
            # Session file present but rejected by Kite — not a valid login.
            try:
                feed.clear_session()
            except Exception:  # noqa: BLE001
                pass
            doc.update(
                {
                    "status": STATUS_LOGIN_REQUIRED,
                    "token_valid": False,
                    "ltp_probe": "FAIL",
                    "last_ltp_error": err,
                    "last_ltp_received_at": ltp.get("received_at"),
                    "freshness": UNKNOWN,
                    "instrument_master": inst_status,
                    "probe_window_passes": passes,
                    "probe_window_total": total,
                    "consecutive_fails": fails,
                    "cta": "/zerodha/login",
                    "message": (
                        "Zerodha session rejected (bad/expired access_token). "
                        "Re-login via /zerodha/login — kite.zerodha.com web login "
                        "does not create a Kite Connect API session for Atlas."
                    ),
                    "reason_code": REASON_PROVIDER_LOGIN_REQUIRED,
                }
            )
            doc["live_trading_allowed"] = False
            doc["live_required_labs"] = ["equity_intraday_learner", "india_fno_learner"]
            doc["non_live_labs"] = ["india_equity_learner"]
            save_health(data_dir, doc)
            return doc
        if prev.get("status") == STATUS_READY or prev.get("status") == STATUS_DEGRADED:
            status = STATUS_ERROR if fails >= _DEGRADED_TO_ERROR_FAILS else STATUS_DEGRADED
        elif prev.get("status") == STATUS_ERROR:
            status = STATUS_ERROR
        else:
            status = STATUS_DEGRADED
        doc.update(
            {
                "status": status,
                "token_valid": True,
                "ltp_probe": "FAIL",
                "last_ltp_error": ltp.get("error"),
                "last_ltp_received_at": ltp.get("received_at"),
                "freshness": STALE if prev.get("last_ltp_as_of") else UNKNOWN,
                "last_ltp_as_of": prev.get("last_ltp_as_of"),
                "instrument_master": inst_status,
                "probe_window_passes": passes,
                "probe_window_total": total,
                "consecutive_fails": fails,
                "cta": "/zerodha/login" if status == STATUS_ERROR else None,
                "message": (
                    "Zerodha live data degraded — live-required labs paused; recovering."
                    if status == STATUS_DEGRADED
                    else "Zerodha live data error — live-required labs paused."
                ),
                "reason_code": reason_for_status(status),
            }
        )

    doc["live_trading_allowed"] = live_trading_allowed(doc)
    doc["live_required_labs"] = ["equity_intraday_learner", "india_fno_learner"]
    doc["non_live_labs"] = ["india_equity_learner"]
    save_health(data_dir, doc)
    return doc


def provider_health_tick(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scheduler handler: premarket / periodic MDPH probe."""
    payload = payload or {}
    try:
        from atlas.config import get_config

        data_dir = get_config().paths.data
    except Exception:  # noqa: BLE001
        data_dir = None
    refresh_inst = bool(payload.get("refresh_instruments"))
    # Around premarket prefer instrument refresh
    hour = datetime.now(_IST).hour
    if 7 <= hour <= 9:
        refresh_inst = True
    doc = evaluate_zerodha_health(
        data_dir,
        probe=True,
        refresh_instruments=refresh_inst,
        force_reprobe=True,
    )
    record_mdph_event(
        data_dir,
        "provider_health_tick",
        status=doc.get("status"),
        live_trading_allowed=doc.get("live_trading_allowed"),
        freshness=doc.get("freshness"),
        instrument_master=doc.get("instrument_master"),
    )
    phase2 = stamp_phase2_session(data_dir, health=doc)
    email_note = maybe_escalate_login_email(data_dir, doc)
    return {
        "ok": True,
        "status": doc.get("status"),
        "live_trading_allowed": doc.get("live_trading_allowed"),
        "trading_date": doc.get("trading_date"),
        "note": doc.get("message") or doc.get("status"),
        "email_escalate": email_note,
        "phase2": {
            "sessions_observed": phase2.get("sessions_observed"),
            "target_sessions": phase2.get("target_sessions"),
            "silent_yahoo_blocked_total": phase2.get("silent_yahoo_blocked_total"),
            "invariant_ok": phase2.get("invariant_ok"),
        },
    }


def record_mdph_event(
    data_dir: str | Path | None,
    event_type: str,
    **fields: Any,
) -> None:
    """Phase 2 observation ledger (append-only JSONL + daily counter rollup)."""
    if not data_dir:
        return
    day = _ist_day()
    root = Path(data_dir) / STORE_REL
    try:
        root.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": _now_iso(),
            "ist_day": day,
            "event": event_type,
            **fields,
        }
        with (root / "observation.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        summary_path = root / "observation_summary.json"
        summary: dict[str, Any] = {}
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summary = {}
        if not isinstance(summary, dict):
            summary = {}
        by_day = summary.setdefault("by_day", {})
        if not isinstance(by_day, dict):
            by_day = {}
            summary["by_day"] = by_day
        day_row = by_day.setdefault(day, {"silent_yahoo_blocked": 0, "events": 0})
        if not isinstance(day_row, dict):
            day_row = {"silent_yahoo_blocked": 0, "events": 0}
            by_day[day] = day_row
        day_row["events"] = int(day_row.get("events") or 0) + 1
        if event_type == "silent_yahoo_blocked":
            day_row["silent_yahoo_blocked"] = int(day_row.get("silent_yahoo_blocked") or 0) + 1
        summary["updated_at"] = _now_iso()
        summary["version"] = VERSION
        summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("mdph observation write failed", exc_info=True)


def observation_silent_sub_count(data_dir: str | Path | None, *, ist_day: str | None = None) -> int:
    """Return silent Yahoo blocked count for day (Phase 2 invariant target = events logged, not substitutions that slipped)."""
    if not data_dir:
        return 0
    day = ist_day or _ist_day()
    path = Path(data_dir) / STORE_REL / "observation_summary.json"
    if not path.is_file():
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        row = ((doc.get("by_day") or {}) if isinstance(doc, dict) else {}).get(day) or {}
        return int(row.get("silent_yahoo_blocked") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0


def reconcile_operating_state(
    data_dir: str | Path | None = None,
    *,
    feed: ZerodhaMarketFeed | None = None,
) -> dict[str, Any]:
    """MDPH.9 — post-crash / startup reconcile: trust reconstructed provider state, not process-up."""
    try:
        if data_dir is None:
            from atlas.config import get_config

            data_dir = get_config().paths.data
    except Exception:  # noqa: BLE001
        data_dir = data_dir
    doc = evaluate_zerodha_health(
        data_dir,
        feed=feed,
        probe=True,
        refresh_instruments=True,
        force_reprobe=True,
    )
    checklist = {
        "version": VERSION,
        "reconciled_at": _now_iso(),
        "trading_date": doc.get("trading_date"),
        "provider_status": doc.get("status"),
        "token_valid": doc.get("token_valid"),
        "ltp_probe": doc.get("ltp_probe"),
        "freshness": doc.get("freshness"),
        "instrument_master": doc.get("instrument_master"),
        "live_trading_allowed": doc.get("live_trading_allowed"),
        "live_required_labs_paused": not bool(doc.get("live_trading_allowed")),
        "cta": doc.get("cta"),
        "reason_code": doc.get("reason_code"),
        "ok": True,
    }
    if data_dir:
        try:
            path = Path(data_dir) / STORE_REL / "last_reconcile.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(checklist, indent=2, default=str) + "\n", encoding="utf-8")
        except OSError:
            _log.debug("mdph reconcile persist failed", exc_info=True)
    record_mdph_event(
        data_dir,
        "startup_reconcile",
        provider_status=checklist.get("provider_status"),
        live_trading_allowed=checklist.get("live_trading_allowed"),
    )
    return checklist


def maybe_escalate_login_email(
    data_dir: str | Path | None,
    health: dict[str, Any],
) -> dict[str, Any]:
    """MDPH.8 — optional ~09:00 IST LOGIN_REQUIRED email (once per IST day)."""
    status = str(health.get("status") or "")
    if status not in {STATUS_LOGIN_REQUIRED, STATUS_EXPIRED}:
        return {"sent": False, "reason": "not_login_required"}
    now = datetime.now(_IST)
    # Operator can typically complete 2FA around ~06:00 IST; escalate from then
    # (not waiting until 09:00 when live labs already need the token).
    if now.hour < 6:
        return {"sent": False, "reason": "before_06_ist"}
    day = _ist_day()
    if str(health.get("login_email_sent_ist_day") or "") == day:
        return {"sent": False, "reason": "already_sent_today"}
    # Persist intent before send to avoid double-send storms
    try:
        health = dict(health)
        health["login_email_sent_ist_day"] = day
        save_health(data_dir, health)
    except Exception:  # noqa: BLE001
        pass
    try:
        import os as _os

        from atlas.config import get_config
        from atlas.notify.email import EmailSender

        cfg = get_config()
        email_cfg = cfg.email
        password = _os.environ.get(str(getattr(email_cfg, "password_env", "") or ""), "")
        to_addrs = list(
            getattr(email_cfg, "investor_to_addrs", None)
            or getattr(email_cfg, "to_addrs", None)
            or []
        )
        sender = EmailSender(
            host=str(getattr(email_cfg, "host", "") or ""),
            port=int(getattr(email_cfg, "port", 587) or 587),
            username=str(getattr(email_cfg, "username", "") or ""),
            password=password,
            from_addr=str(getattr(email_cfg, "from_addr", "") or ""),
            to_addrs=to_addrs,
            use_tls=bool(getattr(email_cfg, "use_tls", True)),
            timeout=float(getattr(email_cfg, "timeout", 20.0) or 20.0),
        )
        if not sender.available():
            return {"sent": False, "reason": "email_not_configured"}
        cta = health.get("cta") or "/zerodha/login"
        ok = sender.send(
            subject=f"[Atlas MDPH] Zerodha {status} — live labs paused",
            body=(
                f"Provider status: {status}\n"
                f"Trading date (IST): {health.get('trading_date')}\n"
                f"Live-required labs (intraday/F&O) are paused until login.\n"
                f"Authenticate: http://127.0.0.1:8000{cta}\n"
            ),
        )
        record_mdph_event(data_dir, "login_email_escalate", status=status, ok=ok)
        return {"sent": bool(ok), "reason": "smtp_ok" if ok else "smtp_failed"}
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}


PHASE2_TARGET_SESSIONS = 5


def _phase2_path(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / "phase2_verify.json"


def load_phase2_verify(data_dir: str | Path | None) -> dict[str, Any]:
    path = _phase2_path(data_dir)
    if path is None or not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def stamp_phase2_session(
    data_dir: str | Path | None,
    *,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record today's MDPH observation day toward the ~5-session verify period."""
    day = _ist_day()
    health = health or load_health(data_dir)
    prev = load_phase2_verify(data_dir)
    sessions = list(prev.get("sessions") or [])
    by_day = {str(s.get("ist_day")): s for s in sessions if isinstance(s, dict)}
    status = str(health.get("status") or UNKNOWN)
    day_row = {
        "ist_day": day,
        "provider_status": status,
        "live_trading_allowed": bool(health.get("live_trading_allowed")),
        "ltp_probe": health.get("ltp_probe"),
        "hist_probe": health.get("hist_probe"),
        "instrument_master": health.get("instrument_master"),
        "freshness": health.get("freshness"),
        "silent_yahoo_blocked": observation_silent_sub_count(data_dir, ist_day=day),
        "updated_at": _now_iso(),
    }
    by_day[day] = day_row
    sessions = [by_day[k] for k in sorted(by_day.keys())]
    silent_total = 0
    summary = {}
    try:
        sp = Path(data_dir) / STORE_REL / "observation_summary.json" if data_dir else None
        if sp and sp.is_file():
            summary = json.loads(sp.read_text(encoding="utf-8"))
            for row in (summary.get("by_day") or {}).values():
                if isinstance(row, dict):
                    silent_total += int(row.get("silent_yahoo_blocked") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        silent_total = sum(int(s.get("silent_yahoo_blocked") or 0) for s in sessions)

    # Count only days that saw a READY probe (true observation session)
    ready_days = [
        s for s in sessions if str(s.get("provider_status")) == STATUS_READY
    ]
    doc = {
        "version": VERSION,
        "kind": "MDPH_PHASE2_VERIFY",
        "target_sessions": PHASE2_TARGET_SESSIONS,
        "sessions_observed": len(ready_days),
        "sessions": sessions[-30:],
        "silent_yahoo_blocked_total": silent_total,
        "invariant_ok": silent_total == 0,
        "complete": len(ready_days) >= PHASE2_TARGET_SESSIONS and silent_total == 0,
        "updated_at": _now_iso(),
        "note": (
            "Measure only — no strategy changes. "
            "Pass when ≥5 READY IST days and silent Yahoo blocked total stays 0."
        ),
    }
    path = _phase2_path(data_dir)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        except OSError:
            _log.debug("phase2 verify write failed", exc_info=True)
    return doc


def build_phase2_observation_report(
    data_dir: str | Path | None,
    *,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Operator scorecard for Phase 2 MDPH observation period."""
    health = health or load_health(data_dir)
    phase2 = stamp_phase2_session(data_dir, health=health) if data_dir else load_phase2_verify(data_dir)
    # Transition / status tallies from observation.jsonl
    status_counts: dict[str, int] = {}
    events = 0
    path = Path(data_dir) / STORE_REL / "observation.jsonl" if data_dir else None
    if path and path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-5000:]:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events += 1
                st = str(row.get("status") or row.get("provider_status") or "")
                if st:
                    status_counts[st] = status_counts.get(st, 0) + 1
        except OSError:
            pass
    reconcile = {}
    rp = Path(data_dir) / STORE_REL / "last_reconcile.json" if data_dir else None
    if rp and rp.is_file():
        try:
            reconcile = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reconcile = {}
    return {
        "version": VERSION,
        "kind": "MDPH_PHASE2_REPORT",
        "generated_at": _now_iso(),
        "trading_date": health.get("trading_date") or _ist_day(),
        "provider": {
            "status": health.get("status"),
            "live_trading_allowed": health.get("live_trading_allowed"),
            "ltp_probe": health.get("ltp_probe"),
            "hist_probe": health.get("hist_probe"),
            "hist_error": health.get("hist_error"),
            "freshness": health.get("freshness"),
            "instrument_master": health.get("instrument_master"),
            "cta": health.get("cta"),
        },
        "phase2": phase2,
        "event_status_counts": status_counts,
        "observation_events_sampled": events,
        "last_reconcile": reconcile,
        "invariants": {
            "silent_yahoo_blocked_total": phase2.get("silent_yahoo_blocked_total", 0),
            "silent_yahoo_ok": bool(phase2.get("invariant_ok", True)),
            "target_sessions": PHASE2_TARGET_SESSIONS,
            "sessions_observed": phase2.get("sessions_observed", 0),
        },
        "next": (
            "Phase 2 MDPH observes passively. Parallel tracks implement under activation gates "
            "(Next-₹1/competition/uncertainty/L3→L5/scientist permanent). "
            "Do not wait on 5 sessions to fix flow/capacity. "
            f"Silent Yahoo must stay 0 across {PHASE2_TARGET_SESSIONS} READY sessions."
            if not phase2.get("complete")
            else "Phase 2 complete — promote VALIDATED components; L5 still requires subsequent tests."
        ),
    }


def investment_l5_scoreboard(data_dir: str | Path | None) -> dict[str, Any]:
    """Phase 3 parallel — count independent investment L5 candidates (honest empty OK)."""
    labs = [
        "india_equity_learner",
        "equity_intraday_learner",
        "india_fno_learner",
    ]
    by_lab: dict[str, Any] = {}
    total_complete = 0
    total_records = 0
    seen_keys: set[str] = set()
    independent: list[dict[str, Any]] = []
    if data_dir:
        try:
            from atlas.investment.learning_audit import (
                classify_learning_category,
                classify_learning_level,
                load_learning_audit,
            )

            for lab in labs:
                aud = load_learning_audit(data_dir, laboratory_id=lab) or {}
                records = list(aud.get("learning_records") or [])
                complete = [r for r in records if r.get("chain_complete")]
                lab_indep: list[dict[str, Any]] = []
                for r in complete:
                    if classify_learning_category(r) == "system":
                        continue
                    level = classify_learning_level(r)
                    key = str(
                        r.get("state_hash")
                        or r.get("independence_key")
                        or r.get("experience_id")
                        or r.get("id")
                        or ""
                    )
                    if not key:
                        outcome = r.get("outcome") if isinstance(r.get("outcome"), dict) else {}
                        key = f"{lab}:{r.get('symbol')}:{outcome.get('trade_id') or r.get('id')}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    is_l5 = level == "L5"
                    lab_indep.append({**r, "_l5": is_l5, "level": level})
                    if is_l5:
                        independent.append(
                            {
                                "laboratory_id": lab,
                                "id": r.get("id"),
                                "symbol": r.get("symbol"),
                                "level": level,
                            }
                        )

                n_l5 = len([x for x in lab_indep if x.get("_l5")])
                n_l3 = len(
                    [x for x in lab_indep if str(x.get("level") or "") in {"L3", "L4", "L5"}]
                )
                by_lab[lab] = {
                    "learning_record_n": len(records),
                    "chain_complete_n": len(complete),
                    "investment_l3_plus_n": n_l3,
                    "investment_l5_candidate_n": n_l5,
                    "near_l5_n": n_l3 - n_l5,
                    "overall_state": aud.get("overall_state"),
                    "as_of_ist": aud.get("as_of_ist"),
                    "honesty": aud.get("honesty") or aud.get("skip_reason"),
                }
                total_complete += len(complete)
                total_records += len(records)
        except Exception as exc:  # noqa: BLE001
            return {
                "version": VERSION,
                "kind": "INVESTMENT_L5_SCOREBOARD",
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "have": 0,
                "target": 5,
            }
    have = len(independent)
    return {
        "version": VERSION,
        "kind": "INVESTMENT_L5_SCOREBOARD",
        "ok": True,
        "have": have,
        "target": 5,
        "learning_record_n": total_records,
        "chain_complete_n": total_complete,
        "independent_ids": [x.get("id") for x in independent[:12]],
        "by_lab": by_lab,
        "note": (
            "Independent L5 = chain_complete + non-system + distinct id + subsequent validation. "
            "Provisional CYIENT rows without lesson/validation do not count. "
            "Honest zero is success — do not invent rows."
        ),
        "generated_at": _now_iso(),
    }
