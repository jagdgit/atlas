"""F&O market-data pack. A READY Zerodha session is not an option decision.

Required chain: underlier spot → instrument master → expiry → ATM → CE/PE →
fresh LTP → validation. Any missing piece leaves the pack NOT_READY.
No guessed spot, strike, or premium.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fno.data_pack.v1"
READY = "READY"
NOT_READY = "NOT_READY"
PASS = "PASS"
MISSING = "MISSING"
NOT_COMPUTABLE = "NOT_COMPUTABLE"
NOT_REQUESTED = "NOT_REQUESTED"
STALE = "STALE"
INVALID = "INVALID"

_DEFAULT_LTP_MAX_AGE_SECONDS = 180.0


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "" or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _dt(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        clock = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            clock = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(timezone.utc)


def _age_seconds(stamp: datetime | None, now: datetime) -> float | None:
    if stamp is None:
        return None
    return (now - stamp).total_seconds()


def _quote_status(
    value: Any,
    stamp: Any,
    *,
    now: datetime,
    max_age: float,
    requested: bool,
) -> dict[str, Any]:
    if not requested:
        return {"status": NOT_REQUESTED, "value": None, "reason": "not_requested"}
    px = _f(value)
    if px is None:
        return {"status": MISSING, "value": None, "reason": "missing"}
    if px <= 0:
        return {"status": INVALID, "value": None, "reason": "price_not_positive"}
    at = _dt(stamp)
    if at is None:
        return {"status": INVALID, "value": None, "reason": "timestamp_missing"}
    age = _age_seconds(at, now)
    if age is None:
        return {"status": INVALID, "value": None, "reason": "timestamp_missing"}
    if age < -5:
        return {"status": INVALID, "value": None, "reason": "timestamp_in_future"}
    if age > max_age:
        return {"status": STALE, "value": px, "reason": "stale", "age_seconds": age}
    return {"status": PASS, "value": px, "reason": "ok", "as_of": at.isoformat(), "age_seconds": age}


def validate_ohlc(bar: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(bar, dict):
        return {"status": PASS, "reason": "no_ohlc_supplied"}
    o = _f(bar.get("open"))
    h = _f(bar.get("high"))
    l = _f(bar.get("low"))
    c = _f(bar.get("close"))
    vol = bar.get("volume")
    if None in {o, h, l, c}:
        return {"status": INVALID, "reason": "ohlc_incomplete"}
    assert o is not None and h is not None and l is not None and c is not None
    if min(o, h, l, c) <= 0:
        return {"status": INVALID, "reason": "price_not_positive"}
    if h < max(o, c) or l > min(o, c) or h < l:
        return {"status": INVALID, "reason": "ohlc_impossible"}
    if vol is not None:
        try:
            if float(vol) < 0:
                return {"status": INVALID, "reason": "volume_negative"}
        except (TypeError, ValueError):
            return {"status": INVALID, "reason": "volume_invalid"}
    return {"status": PASS, "reason": "ohlc_ok"}


def classify_tick_continuity(
    ticks: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Detect duplicate, out-of-order, and empty-gap ticks. Does not invent fills."""
    rows = [t for t in (ticks or []) if isinstance(t, dict)]
    if len(rows) < 2:
        return {"status": PASS, "duplicates": 0, "out_of_order": 0, "gaps": 0}
    dup = 0
    ooo = 0
    gaps = 0
    prev_at: datetime | None = None
    prev_px: float | None = None
    for row in rows:
        at = _dt(row.get("timestamp") or row.get("as_of"))
        px = _f(row.get("price") or row.get("ltp"))
        if at is None:
            continue
        if prev_at is not None:
            if at < prev_at:
                ooo += 1
            elif prev_px is not None and px is not None and at == prev_at and px == prev_px:
                dup += 1
            gap = (at - prev_at).total_seconds()
            expect = _f(row.get("expected_gap_seconds"))
            if expect and gap > expect * 3:
                gaps += 1
        prev_at = at
        prev_px = px
    status = PASS if dup == 0 and ooo == 0 and gaps == 0 else INVALID
    return {"status": status, "duplicates": dup, "out_of_order": ooo, "gaps": gaps}


def _instrument_ok(row: dict[str, Any] | None, *, right: str, expiry: str | None) -> dict[str, Any]:
    if not isinstance(row, dict) or not row.get("ok", True):
        if isinstance(row, dict) and row.get("reason"):
            return {"status": MISSING, "reason": str(row.get("reason")), "instrument": None}
        return {"status": NOT_REQUESTED, "reason": "not_requested", "instrument": None}
    tsym = str(row.get("tradingsymbol") or "").upper()
    got_right = str(row.get("instrument_type") or "").upper()
    if right and got_right and got_right != right:
        return {"status": INVALID, "reason": "right_mismatch", "instrument": None}
    if right and tsym and not tsym.endswith(right):
        return {"status": INVALID, "reason": "symbol_right_mismatch", "instrument": None}
    if expiry and str(row.get("expiry") or "") not in {"", expiry}:
        return {"status": INVALID, "reason": "expiry_mismatch", "instrument": None}
    if not tsym or row.get("instrument_token") in {None, ""}:
        return {"status": INVALID, "reason": "identity_incomplete", "instrument": None}
    if str(row.get("exchange") or "").upper() not in {"NFO", "BFO", ""}:
        return {"status": INVALID, "reason": "exchange_mismatch", "instrument": None}
    return {
        "status": PASS,
        "reason": "ok",
        "instrument": {
            "tradingsymbol": tsym,
            "instrument_token": row.get("instrument_token"),
            "exchange": row.get("exchange") or "NFO",
            "expiry": row.get("expiry"),
            "strike": row.get("strike"),
            "instrument_type": got_right or right,
        },
    }


def build_fno_data_pack(
    *,
    underlying: str,
    spot: float | None = None,
    spot_as_of: Any = None,
    spot_provider: str | None = None,
    instrument_rows: list[dict[str, Any]] | None = None,
    expiry: str | None = None,
    atm_strike: float | None = None,
    ce: dict[str, Any] | None = None,
    pe: dict[str, Any] | None = None,
    ce_ltp: float | None = None,
    pe_ltp: float | None = None,
    ce_ltp_as_of: Any = None,
    pe_ltp_as_of: Any = None,
    session_open: bool | None = None,
    now: datetime | None = None,
    max_age_seconds: float = _DEFAULT_LTP_MAX_AGE_SECONDS,
    ohlc: dict[str, Any] | None = None,
    ticks: list[dict[str, Any]] | None = None,
    session_ready: bool | None = None,
    requested_right: str | None = None,
    futures_master_state: str | None = None,
) -> dict[str, Any]:
    """Assemble and validate one underlier pack. Never fills a missing field."""
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    clock = clock.astimezone(timezone.utc)
    und = str(underlying or "").strip().upper()
    master_n = len(instrument_rows or [])
    typed = [
        str(r.get("instrument_type") or "").upper()
        for r in (instrument_rows or [])
        if isinstance(r, dict) and r.get("instrument_type")
    ]
    fut_n = sum(1 for t in typed if t == "FUT")
    opt_n = sum(1 for t in typed if t in {"CE", "PE"})
    # Options present but no FUT rows: the nearest-FUT expiry cannot resolve, so name the
    # dependency instead of reporting the downstream symptom (expiry_missing).
    futures_gap = bool(typed) and fut_n == 0
    spot_q = _quote_status(spot, spot_as_of, now=clock, max_age=max_age_seconds, requested=True)
    if spot is None:
        spot_q = {"status": MISSING, "value": None, "reason": "underlying_spot_unavailable"}
    elif _f(spot) is not None and _f(spot) <= 0:
        spot_q = {"status": INVALID, "value": None, "reason": "price_not_positive"}
    ce_inst = _instrument_ok(ce, right="CE", expiry=expiry)
    pe_inst = _instrument_ok(pe, right="PE", expiry=expiry)
    want = str(requested_right or "").upper()
    ce_requested = want in {"", "CE", "BOTH"}
    pe_requested = want in {"", "PE", "BOTH"}
    if ce is None and not ce_requested:
        ce_inst = {"status": NOT_REQUESTED, "reason": "not_requested", "instrument": None}
    if pe is None and not pe_requested:
        pe_inst = {"status": NOT_REQUESTED, "reason": "not_requested", "instrument": None}
    if spot_q["status"] != PASS:
        atm_status = NOT_COMPUTABLE if spot_q["status"] == MISSING else NOT_COMPUTABLE
        if ce is None:
            ce_inst = {"status": NOT_REQUESTED, "reason": "spot_unavailable", "instrument": None}
        if pe is None:
            pe_inst = {"status": NOT_REQUESTED, "reason": "spot_unavailable", "instrument": None}
    else:
        atm_px = _f(atm_strike)
        atm_status = PASS if atm_px and atm_px > 0 else NOT_COMPUTABLE
    expiry_status = PASS if expiry else MISSING
    master_status = PASS if master_n > 0 else MISSING
    ce_q = _quote_status(
        ce_ltp, ce_ltp_as_of, now=clock, max_age=max_age_seconds, requested=ce_inst.get("status") == PASS
    )
    pe_q = _quote_status(
        pe_ltp, pe_ltp_as_of, now=clock, max_age=max_age_seconds, requested=pe_inst.get("status") == PASS
    )
    if ce_inst.get("status") != PASS:
        ce_q = {"status": ce_inst.get("status") or NOT_REQUESTED, "value": None, "reason": ce_inst.get("reason")}
    if pe_inst.get("status") != PASS:
        pe_q = {"status": pe_inst.get("status") or NOT_REQUESTED, "value": None, "reason": pe_inst.get("reason")}
    if session_open is True:
        session_status = PASS
    elif session_open is False:
        session_status = INVALID
    else:
        session_status = MISSING
    ohlc_v = validate_ohlc(ohlc)
    ticks_v = classify_tick_continuity(ticks)
    identity_ok = bool(und) and master_status == PASS
    reasons = []
    if spot_q["status"] != PASS:
        reasons.append(spot_q.get("reason") or "spot_not_ready")
    if master_status != PASS:
        reasons.append("instrument_master_missing")
    elif futures_gap:
        stale = str(futures_master_state or "").upper() == "READY_STALE"
        reasons.append("futures_master_stale" if stale else "futures_master_missing")
    if expiry_status != PASS:
        reasons.append("expiry_missing")
    if atm_status != PASS:
        reasons.append("atm_not_computable")
    if session_status != PASS:
        reasons.append("session_not_open" if session_open is False else "session_unknown")
    if ohlc_v["status"] != PASS:
        reasons.append(ohlc_v["reason"])
    if ticks_v["status"] != PASS:
        reasons.append("tick_continuity")
    need_ce = want in {"", "CE", "BOTH"}
    need_pe = want in {"", "PE", "BOTH"}
    if need_ce and ce_q["status"] != PASS:
        reasons.append(f"ce:{ce_q.get('reason')}")
    if need_pe and pe_q["status"] != PASS:
        reasons.append(f"pe:{pe_q.get('reason')}")
    ready = not reasons and identity_ok
    broker = PASS if session_ready else ("MISSING" if session_ready is False else "UNKNOWN")
    return {
        "version": VERSION,
        "underlying": und,
        "status": READY if ready else NOT_READY,
        "quality_status": "TRUSTED" if ready else "UNKNOWN",
        "freshness": PASS if ready else "FAIL",
        "instrument_status": PASS if ready else "INVALID",
        "session": {"broker": broker, "market": session_status},
        "spot": spot_q,
        "instrument_master": {
            "status": master_status,
            "rows": master_n,
            "futures_rows": fut_n,
            "options_rows": opt_n,
            "futures_state": futures_master_state,
        },
        "expiry": {"status": expiry_status, "value": expiry},
        "atm": {"status": atm_status, "strike": atm_strike if atm_status == PASS else None},
        "ce": {"instrument": ce_inst, "ltp": ce_q},
        "pe": {"instrument": pe_inst, "ltp": pe_q},
        "ohlc": ohlc_v,
        "ticks": ticks_v,
        "provider": spot_provider,
        "reason": reasons[0] if reasons else "ok",
        "reasons": reasons,
        "retry": "next valid Zerodha market tick" if not ready else None,
        "decision": None,
    }


def option_decision_permitted(pack: dict[str, Any] | None) -> dict[str, Any]:
    """No option decision, no fabricated ATM, no fabricated LTP, when the pack is not ready."""
    if not isinstance(pack, dict) or pack.get("status") != READY:
        reason = (pack or {}).get("reason") if isinstance(pack, dict) else "pack_missing"
        return {
            "ok": False,
            "decision": None,
            "status": "DATA_QUALITY_FAILURE",
            "reason": reason or "fno_data_pack_not_ready",
            "pack_status": (pack or {}).get("status") if isinstance(pack, dict) else NOT_READY,
            "missing": list((pack or {}).get("reasons") or []) if isinstance(pack, dict) else [],
        }
    if pack.get("quality_status") != "TRUSTED" or pack.get("freshness") != PASS:
        return {
            "ok": False,
            "decision": None,
            "status": "DATA_QUALITY_FAILURE",
            "reason": "quality_or_freshness",
            "pack_status": NOT_READY,
        }
    if pack.get("instrument_status") != PASS:
        return {
            "ok": False,
            "decision": None,
            "status": "DATA_QUALITY_FAILURE",
            "reason": "instrument_invalid",
            "pack_status": NOT_READY,
        }
    return {
        "ok": True,
        "decision": {
            "underlying": pack.get("underlying"),
            "atm": (pack.get("atm") or {}).get("strike"),
            "ce": ((pack.get("ce") or {}).get("instrument") or {}).get("instrument"),
            "pe": ((pack.get("pe") or {}).get("instrument") or {}).get("instrument"),
            "live_orders": False,
        },
        "status": READY,
        "reason": "fno_data_pack_ready",
        "pack_status": READY,
    }


def choose_underlier_spot(
    quote: dict[str, Any] | None,
    *,
    bar_price: float | None,
    bar_as_of: Any = None,
) -> dict[str, Any]:
    """Use a live underlier quote when it has a price and a timestamp.

    A bar keeps its own timestamp. The bar date is not rewritten to "now".
    """
    row: dict[str, Any] | None = None
    if isinstance(quote, dict) and quote.get("ok") and isinstance(quote.get("prices"), dict):
        for val in quote["prices"].values():
            if isinstance(val, dict) and val.get("last") is not None:
                row = val
                break
    last = _f(row.get("last")) if isinstance(row, dict) else None
    as_of = row.get("as_of") if isinstance(row, dict) else None
    if last is not None and last > 0 and as_of:
        return {
            "price": last,
            "as_of": as_of,
            "provider": str(row.get("source") or "zerodha"),
            "source": "live_ltp",
        }
    return {
        "price": bar_price,
        "as_of": bar_as_of,
        "provider": "bar" if bar_price is not None else None,
        "source": "bar",
    }


def persist_fno_data_pack(data_dir: str | Path | None, pack: dict[str, Any]) -> str | None:
    """Write the current pack. Does not create an order."""
    if not data_dir or not isinstance(pack, dict) or not pack.get("underlying"):
        return None
    from zoneinfo import ZoneInfo

    clock = _dt(pack.get("as_of")) or datetime.now(timezone.utc)
    day = clock.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    und = str(pack["underlying"]).upper()
    path = Path(data_dir) / "investment" / "fno" / "packs" / f"{und}_{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(pack)
    body["as_of"] = clock.isoformat()
    body["live_orders"] = False
    path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
    return str(path)


def apply_pack_to_overlay(overlay: dict[str, Any] | None, pack: dict[str, Any] | None) -> dict[str, Any]:
    """A pack that is not READY cannot become an order or a cash-underlier fallback."""
    body = dict(overlay or {})
    body["fno_data_pack"] = pack
    gate = option_decision_permitted(pack)
    body["option_decision"] = gate
    if gate.get("ok"):
        return body
    body["used"] = False
    body["fallback_l4"] = False
    body["kind"] = None
    body["qty"] = 0.0
    body["reason"] = gate.get("reason") or "fno_data_pack_not_ready"
    return body


def format_fno_pack_lines(pack: dict[str, Any] | None) -> list[str]:
    if not isinstance(pack, dict):
        return []
    spot = (pack.get("spot") or {}).get("status")
    master = (pack.get("instrument_master") or {}).get("status")
    expiry = (pack.get("expiry") or {}).get("status")
    atm = (pack.get("atm") or {}).get("status")
    ce = ((pack.get("ce") or {}).get("ltp") or {}).get("status")
    pe = ((pack.get("pe") or {}).get("ltp") or {}).get("status")
    broker = ((pack.get("session") or {}).get("broker"))
    return [
        f"{pack.get('underlying')} F&O pack",
        f"  session: {broker}",
        f"  spot: {spot}",
        f"  instrument_master: {master}",
        f"  expiry: {expiry}",
        f"  ATM: {atm}",
        f"  CE LTP: {ce}",
        f"  PE LTP: {pe}",
        f"  pack: {pack.get('status')}",
        f"  reason: {pack.get('reason')}",
    ]
