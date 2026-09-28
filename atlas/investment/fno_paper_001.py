"""FNO-PAPER-001 — controlled one-shot NIFTY ATM paper round-trip.

Purpose: prove the **production** F&O paper path (not the synthetic never_orders
CLC lab, not L4 index-proxy fallback):

    fresh spot → fresh ATM CE/PE → option LTP → apply_trade BUY
        → position → option LTP → apply_trade SELL → realized P&L

live_orders stays false. Cash-equity alts stay forbidden. Missing freshness
fails honestly — never invents a fill.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.fno_contract import (
    ADAPTER_ID,
    CONTROL_STRATEGY_VERSION,
    PHASE2_UNDERLYING,
    ist_as_of,
    persist_phase2_bundle,
    resolve_phase2_bundle,
    size_one_option_lot,
)

_log = logging.getLogger("atlas.investment.fno_paper_001")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "fno.paper.001.v1"
EXPERIMENT_ID = "FNO-PAPER-001"
STATE_KEY = "fno_paper_001"
STRATEGY_TAG = "fno_paper_001"
INSTRUMENT_PATH = "fno_paper_001"
EXPERIMENT_REL = Path("investment") / "fno" / "experiments"

# Max age for "fresh" LTP / spot when an as_of timestamp is supplied (seconds).
FRESH_LTP_MAX_AGE_S = 15 * 60


def experiment_path(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / EXPERIMENT_REL / f"{EXPERIMENT_ID}.json"


def load_experiment(data_dir: str | Path | None) -> dict[str, Any] | None:
    path = experiment_path(data_dir)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def persist_experiment(data_dir: str | Path | None, doc: dict[str, Any]) -> dict[str, Any]:
    path = experiment_path(data_dir)
    payload = dict(doc or {})
    payload.setdefault("experiment_id", EXPERIMENT_ID)
    payload.setdefault("version", VERSION)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    if path is None:
        payload["ok"] = False
        payload["reason"] = "no_data_dir"
        return payload
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        payload["ok"] = True
        payload["path"] = str(path)
        return payload
    except OSError as exc:
        _log.debug("FNO-PAPER-001 persist failed: %s", exc, exc_info=True)
        payload["ok"] = False
        payload["reason"] = "persist_error"
        return payload


def _env_armed() -> bool:
    raw = (os.environ.get("ATLAS_FNO_PAPER_001") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def is_armed(
    cfg: dict[str, Any] | None,
    state: dict[str, Any] | None,
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """True when the operator wants FNO-PAPER-001 to run on this lab tick.

    Durable experiment status wins over a lingering ``ATLAS_FNO_PAPER_001`` env
    arm so a slow cognitive tick cannot overlap into a second entry. In-flight
    ``entered`` still arms so the exit leg can finish.
    """
    cfg = cfg or {}
    force = bool(cfg.get("fno_paper_001_force"))
    st = (state or {}).get(STATE_KEY)
    doc = st if isinstance(st, dict) else {}
    status = str(doc.get("status") or "")
    if status in {"complete", "exited"} and not force:
        return False
    # Worker checkpoint can lag the on-disk experiment during a long tick.
    disk = load_experiment(data_dir)
    disk_status = str((disk or {}).get("status") or "") if isinstance(disk, dict) else ""
    if (
        disk_status in {"complete", "exited"}
        and status not in {"entered", "armed"}
        and not force
    ):
        return False
    if force or cfg.get("fno_paper_001"):
        return True
    if _env_armed():
        return True
    return status in {"armed", "entered"}


def policy() -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "version": VERSION,
        "live_orders": False,
        "writing": False,
        "underlying": PHASE2_UNDERLYING,
        "quantity": "1_lot",
        "uses_l4_index_proxy": False,
        "cash_equity_alts": False,
        "honesty": (
            "Controlled paper proof of the production F&O executor. "
            "Not a strategy edge claim. Not live orders."
        ),
    }


def _fail(reason: str, **extra: Any) -> dict[str, Any]:
    body = {
        "ok": False,
        "experiment_id": EXPERIMENT_ID,
        "version": VERSION,
        "live_orders": False,
        "reason": reason,
        "status": "failed",
    }
    body.update(extra)
    return body


def plan_entry(
    *,
    spot: float | None,
    instrument_rows: list[dict[str, Any]] | None,
    cash: float,
    ce_ltp: float | None,
    pe_ltp: float | None,
    now: datetime | None = None,
    right: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build a paper BUY plan or fail honestly when freshness is missing."""
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    day = ist_as_of(clock)

    for pos in open_positions or []:
        if not isinstance(pos, dict):
            continue
        try:
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty > 1e-12:
            return _fail(
                "book_not_flat",
                honesty="FNO-PAPER-001 requires a flat book before the controlled entry.",
            )

    try:
        spot_f = float(spot) if spot is not None else 0.0
    except (TypeError, ValueError):
        spot_f = 0.0
    if spot_f <= 0:
        return _fail(
            "no_fresh_spot",
            honesty="Need a live NIFTY underlier mark — refuse to invent spot.",
        )

    bundle = resolve_phase2_bundle(
        instrument_rows, symbol=PHASE2_UNDERLYING, spot=spot_f, as_of=clock
    )
    if not bundle.get("ok"):
        return _fail(
            str(bundle.get("reason") or "atm_unresolved"),
            spot=spot_f,
            honesty="Fresh ATM CE/PE resolution failed — no fill.",
            bundle=bundle,
        )
    if str(bundle.get("as_of") or "") != day.isoformat():
        return _fail(
            "atm_stale_day",
            spot=spot_f,
            as_of=bundle.get("as_of"),
            want=day.isoformat(),
            honesty="ATM bundle as_of must be today's IST day.",
            bundle=bundle,
        )

    if data_dir:
        try:
            persist_phase2_bundle(data_dir, bundle)
        except Exception:  # noqa: BLE001
            _log.debug("FNO-PAPER-001 ATM persist skipped", exc_info=True)

    want = str(right or "CE").strip().upper()
    if want not in {"CE", "PE"}:
        want = "CE"
    contract = bundle.get("ce") if want == "CE" else bundle.get("pe")
    if not isinstance(contract, dict) or not contract.get("ok"):
        # Prefer the other side if requested side missing.
        alt = bundle.get("pe") if want == "CE" else bundle.get("ce")
        if isinstance(alt, dict) and alt.get("ok"):
            contract = alt
            want = "PE" if want == "CE" else "CE"
        else:
            return _fail(
                "no_atm_contract",
                spot=spot_f,
                honesty="Neither ATM CE nor PE resolved.",
                bundle=bundle,
            )

    tsym = str(contract.get("tradingsymbol") or "").strip().upper()
    if not tsym:
        return _fail("no_tradingsymbol", bundle=bundle)

    ltp_raw = ce_ltp if want == "CE" else pe_ltp
    try:
        ltp = float(ltp_raw) if ltp_raw is not None else 0.0
    except (TypeError, ValueError):
        ltp = 0.0
    if ltp <= 0:
        return _fail(
            "no_fresh_option_ltp",
            symbol=tsym,
            right=want,
            spot=spot_f,
            honesty=(
                f"Need live premium LTP for {tsym} — refuse fake fill / refuse L4 fallback."
            ),
            bundle=bundle,
        )

    lot = int(contract.get("lot_size") or 65)
    sized = size_one_option_lot(lot_size=lot, premium=ltp, cash=float(cash or 0))
    if not sized.get("ok"):
        return _fail(
            str(sized.get("reason") or "insufficient_premium"),
            symbol=tsym,
            right=want,
            premium=ltp,
            cash=cash,
            sized=sized,
            honesty="1 lot premium debit not affordable — no fill.",
            bundle=bundle,
        )

    return {
        "ok": True,
        "experiment_id": EXPERIMENT_ID,
        "version": VERSION,
        "status": "planned_entry",
        "live_orders": False,
        "writing": False,
        "uses_l4_index_proxy": False,
        "side": "buy",
        "right": want,
        "symbol": tsym,
        "qty": float(sized["qty"]),
        "price": ltp,
        "lot_size": lot,
        "debit": sized.get("debit"),
        "spot": spot_f,
        "atm_strike": bundle.get("atm_strike"),
        "expiry": contract.get("expiry"),
        "as_of_ist": day.isoformat(),
        "contract": contract,
        "bundle": bundle,
        "adapter_id": ADAPTER_ID,
        "control_strategy": CONTROL_STRATEGY_VERSION,
        "strategy_tag": STRATEGY_TAG,
        "instrument_path": INSTRUMENT_PATH,
        "reason": "fno_paper_001_controlled_entry",
        "honesty": (
            "Controlled paper BUY — production apply_trade path. "
            "Not a strategy verdict. live_orders=false."
        ),
    }


def plan_exit(
    *,
    symbol: str,
    qty: float,
    option_ltp: float | None,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a paper SELL plan for the open FNO-PAPER-001 lot."""
    tsym = str(symbol or "").strip().upper()
    try:
        q = float(qty)
    except (TypeError, ValueError):
        q = 0.0
    if not tsym or q <= 1e-12:
        return _fail("no_open_paper_001_position")
    try:
        ltp = float(option_ltp) if option_ltp is not None else 0.0
    except (TypeError, ValueError):
        ltp = 0.0
    if ltp <= 0:
        return _fail(
            "no_fresh_option_ltp_exit",
            symbol=tsym,
            qty=q,
            honesty="Need live premium LTP to close — refuse avg-cost fake exit.",
            entry=entry,
        )
    return {
        "ok": True,
        "experiment_id": EXPERIMENT_ID,
        "version": VERSION,
        "status": "planned_exit",
        "live_orders": False,
        "side": "sell",
        "symbol": tsym,
        "qty": q,
        "price": ltp,
        "strategy_tag": STRATEGY_TAG,
        "instrument_path": INSTRUMENT_PATH,
        "reason": "fno_paper_001_controlled_exit",
        "entry": entry,
        "honesty": (
            "Controlled paper SELL — production apply_trade path. live_orders=false."
        ),
    }


def acceptance_checklist(doc: dict[str, Any] | None) -> dict[str, Any]:
    """Operator acceptance mirror — all must be true for COMPLETE."""
    d = doc if isinstance(doc, dict) else {}
    entry = d.get("entry") if isinstance(d.get("entry"), dict) else {}
    exit_ = d.get("exit") if isinstance(d.get("exit"), dict) else {}
    checks = {
        "candidate": bool(d.get("armed") or entry or d.get("status")),
        "atm_resolution": bool(entry.get("atm_strike") or entry.get("bundle_ok")),
        "option_ltp": bool(entry.get("price")),
        "paper_buy": bool(entry.get("trade_id")),
        "sim_trades_trade_id": bool(entry.get("trade_id")),
        "position": bool(entry.get("symbol") and entry.get("qty")),
        "mark_on_option_ltp": bool(entry.get("price")),
        "sell": bool(exit_.get("trade_id")),
        "realized_pnl_recorded": exit_.get("realized_pnl") is not None,
        "isolation": d.get("live_orders") is False and d.get("cash_equity_alts") is False,
        "live_orders_false": d.get("live_orders") is False,
    }
    checks["complete"] = all(checks.values()) and str(d.get("status") or "") in {
        "exited",
        "complete",
    }
    return checks


def provisional_lesson_candidate(doc: dict[str, Any] | None) -> str:
    """Deterministic lesson sketch — not a validated FEL lesson."""
    d = doc if isinstance(doc, dict) else {}
    entry = d.get("entry") if isinstance(d.get("entry"), dict) else {}
    exit_ = d.get("exit") if isinstance(d.get("exit"), dict) else {}
    sym = str(entry.get("symbol") or "?")
    right = str(entry.get("right") or "?")
    spot = entry.get("spot")
    entry_px = entry.get("price")
    exit_px = exit_.get("price")
    pnl = exit_.get("realized_pnl")
    try:
        spot_s = f"₹{float(spot):.2f}" if spot is not None else "unknown"
    except (TypeError, ValueError):
        spot_s = "unknown"
    try:
        ep = float(entry_px) if entry_px is not None else None
        xp = float(exit_px) if exit_px is not None else None
        prem_move = None if ep is None or xp is None else xp - ep
    except (TypeError, ValueError):
        prem_move = None
    prem_s = f"{prem_move:+.2f}" if prem_move is not None else "n/a"
    try:
        pnl_s = f"₹{float(pnl):+.2f}" if pnl is not None else "n/a"
    except (TypeError, ValueError):
        pnl_s = "n/a"
    return (
        f"ATM {right} ({sym}) paper lot: premium Δ={prem_s} with underlier≈{spot_s}; "
        f"realized {pnl_s}. One controlled sample — not a policy change."
    )


def build_cognitive_block(
    doc: dict[str, Any] | None,
    *,
    advice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cognitive seam for operator mail — honest UNREVIEWED when Core silent."""
    d = doc if isinstance(doc, dict) else {}
    entry = d.get("entry") if isinstance(d.get("entry"), dict) else {}
    exit_ = d.get("exit") if isinstance(d.get("exit"), dict) else {}
    adv = advice if isinstance(advice, dict) else {}
    review = str(adv.get("review_status") or "UNREVIEWED")
    lesson = str(adv.get("summary") or adv.get("interpretation") or "").strip()
    if not lesson:
        lesson = provisional_lesson_candidate(d)
    return {
        "experiment_id": EXPERIMENT_ID,
        "laboratory_id": "india_fno_learner",
        "lab_role": "derivatives_controlled_experiments",
        "horizon": "minutes→days (experiment-scoped)",
        "control": CONTROL_STRATEGY_VERSION,
        "adapter_id": ADAPTER_ID,
        "action_entry": "BUY",
        "action_exit": "SELL" if exit_ else None,
        "reason": "controlled paper experiment (FNO-PAPER-001)",
        "cognitive_review": review,
        "lesson_candidate": lesson,
        "learning_status": (
            "PROVISIONAL — insufficient sample"
            if review != "REVIEWED"
            else str(adv.get("learning_status") or "PROVISIONAL — single RT")
        ),
        "next": (
            "Observe additional F&O outcomes before changing policy. "
            "Retrieve this experience on the next F&O decision packet."
        ),
        "live_orders": False,
        "symbol": entry.get("symbol"),
        "right": entry.get("right"),
        "spot": entry.get("spot"),
        "atm_strike": entry.get("atm_strike"),
        "entry_premium": entry.get("price"),
        "exit_premium": exit_.get("price"),
        "qty": entry.get("qty"),
        "realized_pnl": exit_.get("realized_pnl"),
        "entry_trade_id": entry.get("trade_id"),
        "exit_trade_id": exit_.get("trade_id"),
        "holding": "1 tick (same-tick exit)" if exit_ else "open",
        "advice": adv or None,
    }


def format_experience_email(
    doc: dict[str, Any] | None,
    *,
    advice: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Operator-facing F&O paper experience — execution + cognitive chain."""
    d = doc if isinstance(doc, dict) else {}
    entry = d.get("entry") if isinstance(d.get("entry"), dict) else {}
    exit_ = d.get("exit") if isinstance(d.get("exit"), dict) else {}
    cog = build_cognitive_block(d, advice=advice)
    sym = str(entry.get("symbol") or "?")
    right = str(entry.get("right") or "?")
    try:
        qty = float(entry.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    try:
        pnl = float(exit_.get("realized_pnl")) if exit_.get("realized_pnl") is not None else None
    except (TypeError, ValueError):
        pnl = None
    pnl_s = f"₹{pnl:+.2f}" if pnl is not None else "n/a"
    subject = (
        f"[Atlas][india_fno_learner] F&O PAPER EXPERIENCE {EXPERIMENT_ID} "
        f"{right} {sym} PnL={pnl_s}"
    )
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "ATLAS — F&O PAPER EXPERIENCE",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "Experiment",
        f"  {EXPERIMENT_ID}",
        f"  NIFTY ATM {right}",
        f"  1 lot × {qty:g}",
        f"  live_orders={cog.get('live_orders')}",
        "",
        "DECISION",
        "  Action: BUY → SELL (controlled paper)",
        f"  Reason: {cog.get('reason')}",
        f"  Control: {cog.get('control')}",
        f"  Cognitive review: {cog.get('cognitive_review')}",
        "",
        "CONTEXT",
        f"  Spot: {entry.get('spot')}",
        f"  ATM strike: {entry.get('atm_strike')}",
        f"  Contract: {sym}",
        f"  Entry premium LTP: {entry.get('price')}",
        f"  Exit premium LTP: {exit_.get('price')}",
        f"  Entry trade_id: {entry.get('trade_id')}",
        f"  Exit trade_id: {exit_.get('trade_id')}",
        "",
        "EXPERIENCE",
        "  Entry → Exit",
        f"  Holding time: {cog.get('holding')}",
        f"  Realized PnL: {pnl_s}",
        "",
        "COGNITIVE INTERPRETATION",
        "  Lesson candidate:",
        f"    {cog.get('lesson_candidate')}",
        "",
        "  Evidence:",
        f"    {EXPERIMENT_ID}",
        "",
        f"  Learning status: {cog.get('learning_status')}",
        "",
        "  Next:",
        f"    {cog.get('next')}",
        "",
        "LAB ROLE (horizon clock)",
        "  Equity swing — days→weeks; few thesis-driven decisions",
        "  Intraday — minutes→same day; flat overnight",
        "  F&O — controlled derivatives experiments → Cognitive Core",
        "",
        "Honesty: execution + cognitive-loop integration test.",
        "Not a claim that options are profitable. Not live orders.",
        "— Atlas Resource OS / F&O paper laboratory",
    ]
    return subject, "\n".join(lines)


def fill_decision_doc(
    *,
    side: str,
    doc: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich per-fill trade email with cognitive fields (not vanity)."""
    d = doc if isinstance(doc, dict) else {}
    p = plan if isinstance(plan, dict) else {}
    entry = d.get("entry") if isinstance(d.get("entry"), dict) else {}
    return {
        "action": str(side or "").lower(),
        "status": "fno_paper_001",
        "rationale": p.get("reason") or d.get("reason") or "controlled paper experiment",
        "rule": CONTROL_STRATEGY_VERSION,
        "cognitive_review": "UNREVIEWED",
        "experiment_id": EXPERIMENT_ID,
        "lab_role": "derivatives_controlled_experiments",
        "learning_status": "PROVISIONAL — path proof / pending RT complete",
        "spot": entry.get("spot") or p.get("spot"),
        "atm_strike": entry.get("atm_strike") or p.get("atm_strike"),
        "right": entry.get("right") or p.get("right"),
        "live_orders": False,
        "honesty": (
            "Fill is real paper sim.trade. Cognitive interpretation lands on "
            "round-trip complete email."
        ),
    }
