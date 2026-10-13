"""F&O shadow trades — counterfactual outcomes for signals the real book could not take.

When the Lab v1 overlay wants to BUY an ATM option but the capital budget or cash
refuses it, a shadow entry is recorded at the live premium. Shadows close on the
same session-flat clock as real experiments, at the live option LTP.

Shadows never touch the ledger, cash, positions, lineage or the paper round-trip
dataset. They are a separate, explicitly counterfactual store. Fills are assumed
at LTP with no slippage or fees — an optimistic bound, labeled as such.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from atlas.investment import fno_lab_v1 as lab_v1

_log = logging.getLogger("atlas.investment.fno_shadow")

VERSION = "fno.shadow.v1"
SHADOW_REL = Path("investment") / "fno" / "shadow"
KIND_OPEN = "FNO_SHADOW_OPEN"
KIND_CLOSE = "FNO_SHADOW_CLOSE"

SHADOW_BLOCK_REASONS = frozenset(
    {lab_v1.SKIP_CAPITAL_MAX_OPEN, lab_v1.SKIP_CAPITAL_CASH_FLOOR}
)
NOT_EVALUABLE_NO_MARK = "no_exit_mark"
NOT_EVALUABLE_MISSED_CLOSE = "missed_session_close"

HONESTY = (
    "Counterfactual — not a fill, not in the ledger. Entry and exit at Zerodha LTP "
    "with no slippage or fees (optimistic). Same-day shadows share one market move; "
    "count independent days, not rows."
)


def is_shadowable_block(reason: str | None) -> bool:
    r = str(reason or "")
    return r in SHADOW_BLOCK_REASONS or r.startswith("insufficient cash")


def shadow_path(data_dir: str | Path | None, laboratory_id: str, ist_day: str) -> Path | None:
    if not data_dir or not laboratory_id or not ist_day:
        return None
    return Path(data_dir) / SHADOW_REL / laboratory_id / f"{ist_day}.jsonl"


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _read(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def open_shadows(data_dir: str | Path | None, laboratory_id: str, ist_day: str) -> list[dict[str, Any]]:
    rows = _read(shadow_path(data_dir, laboratory_id, ist_day))
    closed = {r.get("shadow_id") for r in rows if r.get("kind") == KIND_CLOSE}
    return [r for r in rows if r.get("kind") == KIND_OPEN and r.get("shadow_id") not in closed]


def record_shadow_entry(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    underlying: str,
    control_action: str | None,
    sma_margin: float | None,
    rsi: float | None,
    spot: float | None,
    ce: dict[str, Any] | None,
    pe: dict[str, Any] | None,
    ce_ltp: float | None,
    pe_ltp: float | None,
    block_reason: str,
    capital_budget: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record one shadow BUY; at most one open shadow per underlier per IST day."""
    if str(control_action or "").lower() != "buy":
        return {"ok": False, "reason": "not_a_buy_signal"}
    if not is_shadowable_block(block_reason):
        return {"ok": False, "reason": "block_not_shadowable"}
    try:
        margin = float(sma_margin) if sma_margin is not None else None
    except (TypeError, ValueError):
        margin = None
    if margin is None or margin == 0:
        return {"ok": False, "reason": "no_direction"}
    right = "CE" if margin > 0 else "PE"
    contract = ce if right == "CE" else pe
    ltp = ce_ltp if right == "CE" else pe_ltp
    if not isinstance(contract, dict) or not contract.get("ok") or not contract.get("tradingsymbol"):
        return {"ok": False, "reason": "no_contract"}
    try:
        premium = float(ltp) if ltp is not None else None
    except (TypeError, ValueError):
        premium = None
    if premium is None or premium <= 0:
        return {"ok": False, "reason": "no_entry_mark"}
    ist = lab_v1.to_ist(now)
    if not lab_v1.exit_is_tradeable(ist):
        return {"ok": False, "reason": "outside_session"}
    day = ist.date().isoformat()
    path = shadow_path(data_dir, laboratory_id, day)
    if path is None:
        return {"ok": False, "reason": "no_path"}
    und = lab_v1.normalize_underlier(underlying)
    if any(lab_v1.normalize_underlier(r.get("underlying")) == und for r in open_shadows(data_dir, laboratory_id, day)):
        return {"ok": False, "reason": "already_open_for_underlier"}
    symbol = str(contract["tradingsymbol"])
    qty = int(contract.get("lot_size") or 25)
    prediction = lab_v1.build_entry_prediction(
        underlying=underlying,
        option_symbol=symbol,
        right=right,
        entry_premium=premium,
        sma_margin=margin,
        control_action=control_action,
        entry_reason=f"shadow_{right.lower()}",
        entry_time=ist,
    )
    row = {
        "version": VERSION,
        "kind": KIND_OPEN,
        "shadow_id": str(uuid4()),
        "laboratory_id": laboratory_id,
        "ist_day": day,
        "underlying": und,
        "symbol": symbol,
        "right": right,
        "expiry": contract.get("expiry"),
        "strike": contract.get("strike"),
        "qty": qty,
        "entry_premium": premium,
        "entry_at": ist.isoformat(),
        "block_reason": block_reason,
        "capital_budget": capital_budget,
        "features": {
            "sma_margin": margin,
            "rsi": rsi,
            "spot": spot,
            "minutes_since_open": _minutes_since_open(ist),
            "weekday": ist.weekday(),
        },
        "prediction": prediction,
        "counterfactual": True,
        "honesty": HONESTY,
    }
    _append(path, row)
    return {"ok": True, **row}


def _minutes_since_open(ist: datetime) -> int:
    open_t = lab_v1.FNO_SESSION_OPEN
    return (ist.hour * 60 + ist.minute) - (open_t.hour * 60 + open_t.minute)


def close_due_shadows(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    ltp_fn: Callable[[str], float | None],
    now: datetime | None = None,
    lookback_days: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Close open shadows once the session-flat clock hits.

    In-session close at live LTP → evaluable. After close or a missed day →
    NOT_EVALUABLE (kept for audit, never learning-eligible).
    """
    ist = lab_v1.to_ist(now)
    if not lab_v1.must_flatten_experiments(ist):
        return []
    today = ist.date().isoformat()
    days = list(lookback_days) if lookback_days is not None else _recent_days(data_dir, laboratory_id)
    eligibility = lab_v1.exit_learning_eligibility(ist)
    closed: list[dict[str, Any]] = []
    for day in days:
        path = shadow_path(data_dir, laboratory_id, day)
        for shadow in open_shadows(data_dir, laboratory_id, day):
            symbol = str(shadow.get("symbol") or "")
            exit_px = None
            if day == today:
                try:
                    exit_px = ltp_fn(symbol)
                except Exception:  # noqa: BLE001
                    exit_px = None
            if day != today:
                status, reasons = "NOT_EVALUABLE", [NOT_EVALUABLE_MISSED_CLOSE]
            elif exit_px is None:
                if eligibility.get("eligible"):
                    continue
                status, reasons = "NOT_EVALUABLE", [NOT_EVALUABLE_NO_MARK]
            elif not eligibility.get("eligible"):
                status, reasons = "NOT_EVALUABLE", list(eligibility.get("reasons") or [])
            else:
                status, reasons = "CLOSED", []
            row = _close_row(shadow, exit_px=exit_px, ist=ist, status=status, reasons=reasons)
            if path is not None:
                _append(path, row)
            closed.append(row)
    return closed


def _close_row(
    shadow: dict[str, Any],
    *,
    exit_px: float | None,
    ist: datetime,
    status: str,
    reasons: list[str],
) -> dict[str, Any]:
    entry = float(shadow.get("entry_premium") or 0)
    qty = float(shadow.get("qty") or 0)
    pnl = ret = None
    if exit_px is not None and entry > 0:
        pnl = round((float(exit_px) - entry) * qty, 2)
        ret = round((float(exit_px) - entry) / entry * 100.0, 4)
    pred = shadow.get("prediction") if isinstance(shadow.get("prediction"), dict) else {}
    expected = pred.get("expected_return")
    return {
        "version": VERSION,
        "kind": KIND_CLOSE,
        "shadow_id": shadow.get("shadow_id"),
        "laboratory_id": shadow.get("laboratory_id"),
        "ist_day": shadow.get("ist_day"),
        "symbol": shadow.get("symbol"),
        "underlying": shadow.get("underlying"),
        "right": shadow.get("right"),
        "exit_premium": exit_px,
        "exit_at": ist.isoformat(),
        "status": status,
        "learning_eligibility": {"eligible": status == "CLOSED", "reasons": reasons},
        "outcome": {
            "pnl_inr": pnl,
            "return_pct_on_premium": ret,
            "expected_return_pct": round(float(expected) * 100.0, 4) if expected is not None else None,
            "direction_match": (ret > 0) if ret is not None else None,
        },
        "counterfactual": True,
        "honesty": HONESTY,
    }


def _recent_days(data_dir: str | Path | None, laboratory_id: str, limit: int = 7) -> list[str]:
    if not data_dir:
        return []
    root = Path(data_dir) / SHADOW_REL / laboratory_id
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.jsonl"))[-limit:]


def load_shadow_outcomes(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    eligible_only: bool = True,
) -> list[dict[str, Any]]:
    """Joined OPEN+CLOSE rows; eligible_only keeps in-session closes only."""
    if not data_dir:
        return []
    root = Path(data_dir) / SHADOW_REL / laboratory_id
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.jsonl")):
        rows = _read(path)
        opens = {r["shadow_id"]: r for r in rows if r.get("kind") == KIND_OPEN and r.get("shadow_id")}
        for close in (r for r in rows if r.get("kind") == KIND_CLOSE):
            entry = opens.get(close.get("shadow_id"))
            if entry is None:
                continue
            if eligible_only and not (close.get("learning_eligibility") or {}).get("eligible"):
                continue
            out.append({"entry": entry, "exit": close})
    return out


def _real_closes_day(data_dir: str | Path, laboratory_id: str, ist_day: str) -> dict[str, Any]:
    from atlas.investment.learning_quarantine import is_learning_eligible, quarantined_ids
    from atlas.investment.learning_objects import load_learning_events

    held = quarantined_ids(data_dir, laboratory_id)
    exps = [
        e
        for e in load_learning_events(data_dir, laboratory_id, as_of_ist=ist_day)
        if e.get("kind") == "EXPERIENCE" and e.get("pnl") is not None
    ]
    eligible = [e for e in exps if is_learning_eligible(e, quarantined=held)]
    pnls = [float(e.get("pnl") or 0) for e in exps]
    return {
        "closed": len(exps),
        "eligible": len(eligible),
        "wins": sum(1 for p in pnls if p > 0),
        "pnl_inr_sum": round(sum(pnls), 2),
    }


def format_shadow_section(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    ist_day: str,
) -> list[str]:
    """Evening-mail lines: real closes vs counterfactual shadows for one day."""
    if not data_dir:
        return []
    shadow = summarize_shadow_day(data_dir, laboratory_id, ist_day)
    try:
        real = _real_closes_day(data_dir, laboratory_id, ist_day)
    except Exception:  # noqa: BLE001
        real = None
    lines = ["", f"══ F&O real vs shadow — {ist_day} ══"]
    if real is not None:
        lines.append(
            f"  Real closes: {real['closed']} (learning-eligible {real['eligible']}) · "
            f"wins {real['wins']} · P&L ₹{real['pnl_inr_sum']:,.2f}"
        )
    lines.append(
        f"  Shadows (blocked by capital/cash): opened {shadow['opened']} · "
        f"evaluable {shadow['closed_evaluable']} · not evaluable {shadow['not_evaluable']} · "
        f"still open {shadow['still_open']}"
    )
    if shadow["closed_evaluable"]:
        lines.append(
            f"  Shadow outcome: wins {shadow['wins']}/{shadow['closed_evaluable']} · "
            f"counterfactual P&L ₹{shadow['pnl_inr_sum']:,.2f}"
        )
        rows = [
            r
            for r in _read(shadow_path(data_dir, laboratory_id, ist_day))
            if r.get("kind") == KIND_CLOSE and r.get("status") == "CLOSED"
        ]
        for r in sorted(rows, key=lambda x: float((x.get("outcome") or {}).get("pnl_inr") or 0))[:10]:
            out = r.get("outcome") or {}
            lines.append(
                f"    · {r.get('symbol')}: {out.get('return_pct_on_premium')}% on premium "
                f"(₹{float(out.get('pnl_inr') or 0):,.2f})"
            )
    lines.append(
        "  Shadows are counterfactual: no ledger effect, LTP fills without slippage/fees "
        "(optimistic), same-day rows share one market move."
    )
    return lines


def summarize_shadow_day(data_dir: str | Path | None, laboratory_id: str, ist_day: str) -> dict[str, Any]:
    rows = _read(shadow_path(data_dir, laboratory_id, ist_day))
    opens = [r for r in rows if r.get("kind") == KIND_OPEN]
    closes = [r for r in rows if r.get("kind") == KIND_CLOSE]
    evaluable = [c for c in closes if c.get("status") == "CLOSED"]
    pnls = [float((c.get("outcome") or {}).get("pnl_inr") or 0) for c in evaluable]
    return {
        "version": VERSION,
        "ist_day": ist_day,
        "laboratory_id": laboratory_id,
        "opened": len(opens),
        "closed_evaluable": len(evaluable),
        "not_evaluable": len([c for c in closes if c.get("status") != "CLOSED"]),
        "still_open": len(opens) - len(closes),
        "wins": sum(1 for p in pnls if p > 0),
        "pnl_inr_sum": round(sum(pnls), 2),
        "honesty": HONESTY,
    }
