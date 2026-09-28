"""P0-A / OI-LAB-LOOP0 — same-day wash lock for swing paper books.

Invariant (execution, not a counter):

    same symbol
    + same IST trading day
    + position was fully sold (flat exit)
    + subsequent BUY
    → BUY must not execute

Partial sells while still long do **not** lock (scale-in after a trim is allowed).
Different symbols are independent. Next IST day clears the lock.

State is hydrated from the canonical fill ledger so a lost worker checkpoint
cannot re-open the oscillator.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "wash.lock.v2"
REASON_CONCENTRATION = "switch_blocked_concentration"
REASON_REENTRY = "same_day_reentry_blocked"
STATE_KEY = "wash_lock"
_IST = ZoneInfo("Asia/Kolkata")
DEFAULT_MAX_NAME_PCT = 0.40


def ist_day(now: datetime | None = None) -> str:
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(_IST).date().isoformat()


def normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def applies_to_lab(portfolio_key: str | None, *, cfg: dict[str, Any] | None = None) -> bool:
    """Swing cash-equity only. Intraday flatten and F&O packs are out of scope."""
    try:
        from atlas.investment.lab_contracts import LAB_SWING, lab_kind

        return lab_kind(portfolio_key, cfg=cfg) == LAB_SWING
    except Exception:  # noqa: BLE001
        pk = str(portfolio_key or "").strip().lower()
        return pk in {"india_equity_learner", "equity_swing_learner"} or (
            "equity" in pk and "learner" in pk and "intraday" not in pk and "fno" not in pk
        )


def _max_name_pct(cfg: dict[str, Any] | None) -> float:
    cfg = cfg or {}
    raw = cfg.get("plc_b_max_name_pct")
    if raw is None:
        raw = cfg.get("max_name_pct")
    try:
        cap = float(raw) if raw is not None else DEFAULT_MAX_NAME_PCT
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_NAME_PCT
    if cap > 1.0:
        cap = cap / 100.0
    if cap <= 0:
        return DEFAULT_MAX_NAME_PCT
    return cap


def load(state: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    day = ist_day(now)
    raw = (state or {}).get(STATE_KEY)
    doc = dict(raw) if isinstance(raw, dict) else {}
    if str(doc.get("ist_day") or "") != day:
        return {"version": VERSION, "ist_day": day, "sold": {}}
    sold = doc.get("sold") if isinstance(doc.get("sold"), dict) else {}
    return {
        "version": VERSION,
        "ist_day": day,
        "sold": {normalize_symbol(k): str(v) for k, v in sold.items() if k},
    }


def persist(state: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    state[STATE_KEY] = {
        "version": VERSION,
        "ist_day": lock.get("ist_day") or ist_day(),
        "sold": dict(lock.get("sold") or {}),
    }
    return state


def record_sale(
    state: dict[str, Any],
    symbol: str,
    *,
    reason: str,
    now: datetime | None = None,
    remaining_qty: float | None = None,
    flattened: bool | None = None,
) -> dict[str, Any]:
    """Record a same-day flat exit.

    Only a full exit locks re-entry. Pass ``flattened=True`` or
    ``remaining_qty <= 0``. Partial sells (still long) leave the lock unchanged.
    """
    lock = load(state, now=now)
    key = normalize_symbol(symbol)
    if not key:
        persist(state, lock)
        return lock

    is_flat = flattened
    if is_flat is None and remaining_qty is not None:
        try:
            is_flat = float(remaining_qty) <= 1e-9
        except (TypeError, ValueError):
            is_flat = False
    if is_flat is None:
        # Backward compatible: callers that omit qty mean "this sell exits".
        is_flat = True

    if is_flat:
        lock.setdefault("sold", {})[key] = str(reason or "sell")[:80]
    persist(state, lock)
    return lock


def hydrate_from_fills(
    state: dict[str, Any],
    trades: list[dict[str, Any]] | None,
    *,
    now: datetime | None = None,
    open_positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild today's sold map from canonical fills (oldest → newest).

    Seeds running inventory from open positions, then reverse-plays today's
    fills to recover start-of-day qty so overnight holdings are not treated
    as zero. A symbol locks when a sell on this IST day drives qty to ≤ 0.
    Later same-day buys do not clear the lock — that is the invariant.
    """
    day = ist_day(now)
    running: dict[str, float] = {}
    for p in open_positions or []:
        if not isinstance(p, dict):
            continue
        key = normalize_symbol(p.get("symbol"))
        if not key:
            continue
        try:
            qty = float(p.get("quantity") or p.get("qty") or p.get("shares") or 0)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            running[key] = qty

    rows: list[tuple[datetime, int, dict[str, Any]]] = []
    for i, t in enumerate(trades or []):
        if not isinstance(t, dict):
            continue
        ts = t.get("created_at") or t.get("ts") or t.get("filled_at") or t.get("t")
        try:
            if isinstance(ts, datetime):
                dt = ts
            else:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        if dt.astimezone(_IST).date().isoformat() != day:
            continue
        rows.append((dt, i, t))
    rows.sort(key=lambda r: (r[0], r[1]))

    # Undo today's fills (newest → oldest) to recover start-of-day inventory.
    for _dt, _i, t in reversed(rows):
        key = normalize_symbol(t.get("symbol"))
        if not key:
            continue
        try:
            qty = abs(float(t.get("quantity") or t.get("qty") or 0))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        side = str(t.get("side") or t.get("action") or "").lower()
        prev = float(running.get(key) or 0.0)
        if side == "buy":
            running[key] = max(0.0, prev - qty)
        elif side == "sell":
            running[key] = prev + qty

    sold: dict[str, str] = {}
    for _dt, _i, t in rows:
        key = normalize_symbol(t.get("symbol"))
        if not key:
            continue
        try:
            qty = abs(float(t.get("quantity") or t.get("qty") or 0))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        side = str(t.get("side") or t.get("action") or "").lower()
        prev = float(running.get(key) or 0.0)
        if side == "buy":
            running[key] = prev + qty
        elif side == "sell":
            nxt = prev - qty
            if nxt <= 1e-9:
                running[key] = 0.0
                reason = str(
                    t.get("reason")
                    or t.get("exit_reason_code")
                    or t.get("strategy_tag")
                    or "sell"
                )[:80]
                sold[key] = reason
            else:
                running[key] = nxt

    lock = {"version": VERSION, "ist_day": day, "sold": sold}
    persist(state, lock)
    return lock


def reentry_blocked(
    state: dict[str, Any] | None,
    symbol: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    lock = load(state, now=now)
    key = normalize_symbol(symbol)
    reason = (lock.get("sold") or {}).get(key)
    if not key or not reason:
        return {"blocked": False, "reason_code": None, "prior_sale": None}
    honesty = (
        f"{key} BUY blocked — same-day re-entry after sale ({reason}). "
        "Same-day re-entry is wash, not a new experience."
    )
    return {
        "blocked": True,
        "reason_code": REASON_REENTRY,
        "prior_sale": reason,
        "honesty": honesty,
        "email_subject_reason": f"{key} BUY blocked — same-day re-entry after sale",
    }


def challenger_breaches_concentration(
    *,
    equity: float,
    cash: float,
    hold_qty: float,
    hold_px: float,
    chal_px: float,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """True when an all-in switch would put the challenger over the name cap.

    Does not size down. Blocking keeps the incumbent — it does not invent a trim.
    """
    cap = _max_name_pct(cfg)
    try:
        eq = float(equity or 0)
        cash_f = float(cash or 0)
        hq = float(hold_qty or 0)
        hp = float(hold_px or 0)
        cp = float(chal_px or 0)
    except (TypeError, ValueError):
        return {
            "blocked": True,
            "reason_code": REASON_CONCENTRATION,
            "weight": None,
            "cap": cap,
            "buy_qty": 0,
            "honesty": "switch concentration pre-check missing marks — fail closed.",
        }
    if hq <= 0 or hp <= 0 or cp <= 0:
        return {
            "blocked": True,
            "reason_code": REASON_CONCENTRATION,
            "weight": None,
            "cap": cap,
            "buy_qty": 0,
            "honesty": "switch concentration pre-check missing qty/price — fail closed.",
        }
    cash_after = cash_f + (hq * hp)
    buy_qty = int(cash_after // cp)
    notional = float(buy_qty) * cp
    denom = eq if eq > 0 else cash_after
    weight = (notional / denom) if denom > 0 else 1.0
    blocked = buy_qty > 0 and weight > cap + 1e-9
    return {
        "blocked": blocked,
        "reason_code": REASON_CONCENTRATION if blocked else None,
        "weight": round(weight, 4),
        "cap": cap,
        "buy_qty": buy_qty,
        "honesty": (
            f"all-in switch would be {weight:.1%} vs name cap {cap:.0%} — keep incumbent."
            if blocked
            else "challenger name weight inside cap."
        ),
    }
