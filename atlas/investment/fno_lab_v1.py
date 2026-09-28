"""F&O Lab v1 — operable expansion contract (indices + bounded stock seed).

Universe (configured, not “whatever Zerodha returns”):
  • four index underliers: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY
  • fixed liquid stock-F&O seed (~20–50 names)

Per eligible underlier (same pipe as FNO-PAPER-001):
  fresh spot → nearest FUT expiry → ATM CE/PE → fresh option LTP
    → liquidity gate (SKIP if missing) → 1-lot paper apply_trade
    → experience → Cognitive Core (REVIEWED | honest UNREVIEWED)

Equity horizon audit stays necessary but does **not** gate this lab.
Widening = edit the seed file, not the cognitive plumbing.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.fno_contract import (
    INDEX_UNIVERSE,
    family_for_symbol,
    is_index_underlier,
    option_right,
)

_log = logging.getLogger("atlas.investment.fno_lab_v1")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "fno.lab.v1.1"
LABORATORY_ID = "india_fno_learner"
LAB_ROLE = "derivatives_controlled_experiments"
SEED_REL = Path("investment") / "fno" / "lab_v1_seed.json"
POLICY_REL = Path("investment") / "fno" / "lab_v1_policy.json"
INTEGRITY_REL = Path("investment") / "fno" / "lab_v1_integrity"
PREDICTION_REL = Path("investment") / "fno" / "lab_v1_predictions"
REASON_EXPERIMENT_CLOSE = "fno_lab_v1_experiment_close"
# NSE F&O cash market close — after this, Lab v1 option experiments must flatten.
FNO_FLAT_AFTER = time(15, 30)
FNO_SESSION_OPEN = time(9, 15)
# Bounded control-linked premium E[R] model id (not a valued option pricer).
ENTRY_ER_MODEL = "fno_lab_v1_control_signal.v1"

# Stable short tags for experiment families (FNO-ATM-REL-001).
_INDEX_SHORT = {
    "NIFTY": "NIF",
    "BANKNIFTY": "BNF",
    "FINNIFTY": "FIN",
    "MIDCPNIFTY": "MID",
}

# Explicit first training population — liquid NSE F&O names (Kite ``name`` field).
# Widen later by editing the seed file / config; do not scrape the whole master.
DEFAULT_STOCK_SEED: tuple[str, ...] = (
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "BHARTIARTL",
    "ITC",
    "LT",
    "AXISBANK",
    "KOTAKBANK",
    "BAJFINANCE",
    "MARUTI",
    "SUNPHARMA",
    "TITAN",
    "ASIANPAINT",
    "WIPRO",
    "HCLTECH",
    "ULTRACEMCO",
    "POWERGRID",
    "NTPC",
    "ONGC",
    "COALINDIA",
    "TATASTEEL",
    "JSWSTEEL",
    "ADANIENT",
    "ADANIPORTS",
    "M&M",
    "TATAMOTORS",
    "HINDUNILVR",
)

SKIP_NO_SPOT = "no_fresh_spot"
SKIP_NO_FUT = "no_nearest_fut"
SKIP_NO_ATM = "no_atm_contract"
SKIP_NO_LTP = "no_fresh_option_ltp"
SKIP_INSUFFICIENT_CASH = "insufficient_cash"
SKIP_NOT_IN_UNIVERSE = "not_in_lab_v1_universe"
SKIP_SESSION_CLOSED = "session_closed"


def normalize_underlier(symbol: str | None) -> str:
    key = str(symbol or "").strip().upper()
    if ":" in key:
        key = key.split(":", 1)[-1]
    if key.endswith(".NS") or key.endswith(".BO"):
        key = key.rsplit(".", 1)[0]
    return key


def index_underliers() -> tuple[str, ...]:
    return tuple(INDEX_UNIVERSE)


def seed_path(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / SEED_REL


def load_stock_seed(data_dir: str | Path | None = None) -> list[str]:
    """Configured stock seed; falls back to DEFAULT_STOCK_SEED."""
    path = seed_path(data_dir)
    if path is not None and path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            raw = doc.get("stock_seed") if isinstance(doc, dict) else None
            if isinstance(raw, list) and raw:
                out = [normalize_underlier(x) for x in raw if str(x).strip()]
                return [x for x in out if x]
        except (OSError, json.JSONDecodeError) as exc:
            _log.debug("lab_v1 seed load failed: %s", exc, exc_info=True)
    return [normalize_underlier(x) for x in DEFAULT_STOCK_SEED]


def persist_stock_seed(
    data_dir: str | Path | None,
    names: list[str] | None = None,
) -> dict[str, Any]:
    path = seed_path(data_dir)
    payload = {
        "version": VERSION,
        "laboratory_id": LABORATORY_ID,
        "index_underliers": list(INDEX_UNIVERSE),
        "stock_seed": list(names) if names is not None else list(DEFAULT_STOCK_SEED),
        "note": (
            "Fixed training population. Expand by editing this file — "
            "not by dumping the full NFO master into the lab."
        ),
    }
    if path is None:
        return {"ok": False, "reason": "no_data_dir", **payload}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path), **payload}
    except OSError as exc:
        _log.debug("lab_v1 seed persist failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error", **payload}


def universe(data_dir: str | Path | None = None) -> dict[str, Any]:
    stocks = load_stock_seed(data_dir)
    return {
        "version": VERSION,
        "index_underliers": list(INDEX_UNIVERSE),
        "stock_seed": stocks,
        "all_underliers": list(INDEX_UNIVERSE) + stocks,
        "count": len(INDEX_UNIVERSE) + len(stocks),
    }


def underlying_type(symbol: str | None) -> str:
    key = normalize_underlier(symbol)
    if is_index_underlier(key) or family_for_symbol(key) in INDEX_UNIVERSE:
        return "index"
    return "stock"


def is_eligible_underlier(
    symbol: str | None,
    *,
    data_dir: str | Path | None = None,
    stock_seed: list[str] | None = None,
) -> bool:
    key = normalize_underlier(symbol)
    if not key:
        return False
    if is_index_underlier(key):
        return True
    seed = stock_seed if stock_seed is not None else load_stock_seed(data_dir)
    return key in {normalize_underlier(x) for x in seed}


def family_short(underlying: str | None) -> str:
    key = normalize_underlier(underlying)
    if key in _INDEX_SHORT:
        return _INDEX_SHORT[key]
    # Strip non-alnum for M&M → MM, keep readable prefix.
    cleaned = re.sub(r"[^A-Z0-9]", "", key)
    return (cleaned[:3] or "UNK")


def experiment_family_id(
    underlying: str | None,
    *,
    structure: str = "ATM",
    right: str | None = None,
) -> str:
    """Stable family id — not a single-trade id.

    Example: FNO-ATM-REL-001 for RELIANCE ATM experiments.
    Right (CE/PE) lives in attribution; family groups repeated structure.
    """
    short = family_short(underlying)
    struct = str(structure or "ATM").strip().upper() or "ATM"
    _ = right  # reserved — keep family stable across CE/PE of same ATM structure
    return f"FNO-{struct}-{short}-001"


def prediction_path(
    data_dir: str | Path | None,
    *,
    option_symbol: str | None = None,
) -> Path | None:
    if not data_dir or not option_symbol:
        return None
    key = re.sub(r"[^A-Z0-9]+", "_", str(option_symbol).strip().upper()) or "UNK"
    return Path(data_dir) / PREDICTION_REL / f"{key}.json"


def build_entry_prediction(
    *,
    underlying: str | None,
    option_symbol: str | None,
    right: str | None,
    entry_premium: float | None,
    sma_margin: float | None = None,
    control_action: str | None = None,
    entry_reason: str | None = None,
    decision_id: str | None = None,
    trade_id: str | None = None,
    entry_time: datetime | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Decide-time E[R] for a Lab v1 option BUY — persisted before outcome.

    Bounded control-signal heuristic (not Black–Scholes / not L5 claim).
    Long ATM premium → expected_direction=up; horizon=session_flat.
    """
    und = normalize_underlier(underlying)
    right_u = str(right or "").strip().upper() or None
    tsym = str(option_symbol or "").strip().upper()
    try:
        margin = float(sma_margin) if sma_margin is not None else 0.0
    except (TypeError, ValueError):
        margin = 0.0
    # Buy only fires when margin ≠ 0; map |margin| → [0,1] strength.
    strength = min(1.0, abs(margin) / 0.005) if abs(margin) > 1e-12 else 0.5
    expected_return = round(0.01 + 0.07 * strength, 4)  # 1%–8% of premium (decimal)
    predicted_probability = round(0.45 + 0.25 * strength, 3)  # 0.45–0.70
    clock = entry_time or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    family = experiment_family_id(und, right=right_u)
    evid = list(evidence or [])
    if not evid:
        evid = [
            f"control=sma_cross_rsi.v1 action={control_action or 'buy'}",
            f"sma_margin={margin}",
            f"right={right_u}",
            f"entry_premium={entry_premium}",
            "horizon=session_flat (must flatten by 15:30 IST)",
            "live_orders=false",
        ]
    return {
        "version": VERSION,
        "kind": "FNO_LAB_V1_ENTRY_PREDICTION",
        "prediction_status": "stated",
        "laboratory_id": LABORATORY_ID,
        "lab_role": LAB_ROLE,
        "decision_id": decision_id,
        "experiment_id": family,
        "experiment_family": family,
        "underlying": und,
        "underlying_type": underlying_type(und),
        "contract": tsym,
        "option_type": right_u,
        "direction": "long_premium",
        "expected_direction": "up",
        "entry_time": clock.isoformat(),
        "entry_premium": entry_premium,
        "expected_return": expected_return,
        "predicted_probability": predicted_probability,
        "expected_move": expected_return,
        "prediction_horizon": "session_flat",
        "er_model": ENTRY_ER_MODEL,
        "er_completeness": 1.0,
        "opportunity_confidence": predicted_probability,
        "reason": str(entry_reason or f"v1_buy_atm_{right_u or 'opt'}").strip(),
        "thesis": (
            f"Control SMA margin {margin:+.5f} → long ATM {right_u}; "
            f"expect premium E[R]={expected_return:.2%} over session_flat."
        ),
        "key_evidence": evid[:12],
        "uncertainty": [
            "Not a valued option model — control-linked provisional E[R]",
            "Vol / regime between entry and session_flat unknown",
            "Single RT is not a validated lesson",
        ],
        "trade_id": trade_id,
        "control_action": control_action,
        "sma_margin": margin,
        "live_orders": False,
        "honesty": (
            "Decide-time prediction persisted before outcome. "
            f"Model={ENTRY_ER_MODEL}. Not L5 until outcome→error→attribution→lesson validates."
        ),
    }


def persist_entry_prediction(
    data_dir: str | Path | None,
    prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    """Durable open-experiment prediction (keyed by option tradingsymbol)."""
    pred = prediction if isinstance(prediction, dict) else {}
    path = prediction_path(data_dir, option_symbol=str(pred.get("contract") or ""))
    if path is None or not pred:
        return {"ok": False, "reason": "no_path_or_prediction"}
    body = dict(pred)
    body["recorded_at"] = datetime.now(timezone.utc).isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path), **body}
    except OSError as exc:
        _log.debug("lab_v1 prediction persist failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error"}


def load_entry_prediction(
    data_dir: str | Path | None,
    *,
    option_symbol: str | None = None,
) -> dict[str, Any] | None:
    path = prediction_path(data_dir, option_symbol=option_symbol)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def bind_entry_prediction_trade(
    data_dir: str | Path | None,
    *,
    option_symbol: str,
    trade_id: str | None = None,
    decision_id: str | None = None,
) -> dict[str, Any] | None:
    """Attach fill ids to the already-persisted decide-time prediction."""
    pred = load_entry_prediction(data_dir, option_symbol=option_symbol)
    if not pred:
        return None
    if trade_id:
        pred["trade_id"] = str(trade_id)
    if decision_id:
        pred["decision_id"] = str(decision_id)
    persist_entry_prediction(data_dir, pred)
    return pred


def expected_block_from_prediction(prediction: dict[str, Any] | None) -> dict[str, Any]:
    """Shape decide-time prediction for DI packets / EXPERIENCE ``expected``."""
    p = prediction if isinstance(prediction, dict) else {}
    if not p or p.get("prediction_status") == "prediction_absent":
        return {
            "prediction_status": "prediction_absent",
            "expected_return": None,
            "expected_direction": None,
            "honesty": "prediction_absent — no decide-time E[R]",
        }
    return {
        "prediction_status": "stated",
        "expected_return": p.get("expected_return"),
        "expected_direction": p.get("expected_direction") or "up",
        "expected_move": p.get("expected_move"),
        "predicted_probability": p.get("predicted_probability"),
        "prediction_horizon": p.get("prediction_horizon") or "session_flat",
        "er_model": p.get("er_model") or ENTRY_ER_MODEL,
        "er_completeness": p.get("er_completeness"),
        "opportunity_confidence": p.get("opportunity_confidence")
        or p.get("predicted_probability"),
        "decision_id": p.get("decision_id"),
        "experiment_id": p.get("experiment_id") or p.get("experiment_family"),
        "thesis": p.get("thesis"),
        "reason": p.get("reason"),
        "key_evidence": list(p.get("key_evidence") or [])[:12],
        "uncertainty": list(p.get("uncertainty") or [])[:8],
        "entry_time": p.get("entry_time"),
        "entry_premium": p.get("entry_premium"),
        "fno_lab_v1_prediction": True,
        "honesty": p.get("honesty"),
    }


def instrument_rows_for_seed(
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Mission/portfolio instrument list: indices + stock seed underliers."""
    rows: list[dict[str, Any]] = []
    for sym in INDEX_UNIVERSE:
        rows.append(
            {
                "symbol": sym,
                "asset_class": "futures",
                "underlying_type": "index",
                "note": f"fno.lab.v1 index underlier ({sym})",
            }
        )
    for sym in load_stock_seed(data_dir):
        rows.append(
            {
                "symbol": sym,
                "asset_class": "futures",
                "underlying_type": "stock",
                "note": "fno.lab.v1 stock-F&O seed underlier",
            }
        )
    return rows


def attribution(
    *,
    underlying: str,
    future_contract: dict[str, Any] | None = None,
    option_contract: dict[str, Any] | None = None,
    entry_ltp: float | None = None,
    exit_ltp: float | None = None,
    experiment_id: str | None = None,
    trade_id: str | None = None,
    entry_reason: str | None = None,
    exit_reason: str | None = None,
    cognitive_review: str | None = None,
    learning_status: str | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    """Identity block so Core answers *what instrument / what experiment*."""
    fut = future_contract if isinstance(future_contract, dict) else {}
    opt = option_contract if isinstance(option_contract, dict) else {}
    right = str(opt.get("instrument_type") or opt.get("right") or "").upper() or None
    und = normalize_underlier(underlying)
    return {
        "laboratory_id": LABORATORY_ID,
        "lab_role": LAB_ROLE,
        "lab_version": VERSION,
        "underlying": und,
        "underlying_type": underlying_type(und),
        "experiment_family": experiment_family_id(und, right=right),
        "future_contract": fut.get("tradingsymbol"),
        "option_contract": opt.get("tradingsymbol"),
        "option_type": right,
        "strike": opt.get("strike"),
        "expiry": opt.get("expiry") or fut.get("expiry"),
        "entry_ltp": entry_ltp,
        "exit_ltp": exit_ltp,
        "lot_size": opt.get("lot_size") or fut.get("lot_size"),
        "experiment_id": experiment_id or experiment_family_id(und, right=right),
        "trade_id": trade_id,
        "entry_reason": entry_reason,
        "exit_reason": exit_reason,
        "cognitive_review": cognitive_review or "UNREVIEWED",
        "learning_status": learning_status
        or ("SKIPPED" if skip_reason else "PROVISIONAL — pending RT"),
        "skip_reason": skip_reason,
        "live_orders": False,
        "writing": False,
        "uses_l4_index_proxy": False,
    }


def policy(data_dir: str | Path | None = None) -> dict[str, Any]:
    uni = universe(data_dir)
    return {
        "version": VERSION,
        "laboratory_id": LABORATORY_ID,
        "lab_role": LAB_ROLE,
        "live_orders": False,
        "writing": False,
        "quantity": "1_lot",
        "uses_l4_index_proxy": False,
        "cash_equity_alts": False,
        "universe": uni,
        "contract_selection": {
            "fut": "nearest_unexpired",
            "option": "ATM CE/PE same expiry",
            "liquidity_gate": "fresh spot + fresh option LTP or SKIP",
        },
        "exit_lifecycle": {
            "policy": "session_flat",
            "reason_code": REASON_EXPERIMENT_CLOSE,
            "rule": (
                "Lab v1 option experiments must not overnight. "
                "ENTRY → defined exit (session close / explicit experiment_close) → "
                "SELL → realized P&L → experience → Cognitive Core."
            ),
            "flat_after_ist": "15:30",
            "allows_avg_cost_mark_when_ltp_missing": True,
            "honesty": (
                "avg_cost mark is an integrity flatten of last resort — stamped "
                "mark_source=avg_cost_mark_unavailable, never claimed as live LTP."
            ),
        },
        "cognitive": {
            "reviewed_or_unreviewed": True,
            "single_trade_is_not_a_validated_lesson": True,
            "experiment_family_vs_trade_id": True,
            "decide_time_er": (
                "ATM BUY persists entry prediction (fno_lab_v1_control_signal.v1) "
                "before outcome; session_flat close consumes it for prediction_error."
            ),
        },
        "expansion_rule": (
            "seed → experiences → coverage/data problems → repeated behaviours → "
            "lessons with attribution → revise seed/rules → expand"
        ),
        "equity_horizon_audit": "parallel_not_prerequisite",
        "honesty": (
            "Controlled paper training population. Not an edge claim. "
            "Not the full NFO master. Missing data SKIPs — never invents fills."
        ),
    }


def persist_policy(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {"ok": False, "reason": "no_data_dir"}
    path = Path(data_dir) / POLICY_REL
    body = policy(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path), **body}
    except OSError as exc:
        _log.debug("lab_v1 policy persist failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error"}


def to_ist(now: datetime | None = None) -> datetime:
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(_IST)


def must_flatten_experiments(now: datetime | None = None) -> bool:
    """True when Lab v1 option inventory must be flat (after 15:30 IST / weekend)."""
    ist = to_ist(now)
    if ist.weekday() >= 5:
        return True
    t = ist.time().replace(tzinfo=None)
    return t >= FNO_FLAT_AFTER or t < FNO_SESSION_OPEN


def flatten_session_date(now: datetime | None = None) -> str:
    """IST session date the overnight F&O flatten belongs to."""
    ist = to_ist(now)
    if ist.time().replace(tzinfo=None) < FNO_SESSION_OPEN:
        from datetime import timedelta

        return (ist.date() - timedelta(days=1)).isoformat()
    return ist.date().isoformat()


def is_lab_v1_option_position(symbol: str | None) -> bool:
    """True for NFO CE/PE experiment lots (never cash underliers)."""
    return option_right(str(symbol or "")) is not None


def underlying_from_option_tsym(symbol: str | None) -> str:
    """Best-effort underlier from option tradingsymbol (RELIANCE25SEP2800CE → RELIANCE)."""
    key = str(symbol or "").strip().upper()
    if ":" in key:
        key = key.split(":", 1)[-1]
    right = option_right(key)
    if right:
        key = key[: -len(right)]
    # Strip trailing YYMON + strike digits if present
    m = re.match(r"^([A-Z&]+)(\d{2}[A-Z]{3}\d+)?$", key)
    if m:
        return m.group(1)
    # Fallback: cut at first digit
    for i, ch in enumerate(key):
        if ch.isdigit():
            return key[:i] or key
    return key


def open_option_positions(positions: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol") or "").strip()
        if not is_lab_v1_option_position(sym):
            continue
        try:
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if abs(qty) <= 1e-12:
            continue
        out.append(dict(pos))
    return out


def integrity_path(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
) -> Path | None:
    if not data_dir:
        return None
    day = as_of_ist or flatten_session_date()
    return Path(data_dir) / INTEGRITY_REL / f"{day}.json"


def load_integrity(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    path = integrity_path(data_dir, as_of_ist=as_of_ist)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load_flatten_outcomes(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
) -> list[dict[str, Any]]:
    """Prior closed-experiment outcomes — must survive empty rewrites when already flat."""
    doc = load_integrity(data_dir, as_of_ist=as_of_ist)
    if not doc:
        return []
    out = [o for o in (doc.get("flatten_outcomes") or []) if isinstance(o, dict)]
    return out


def _merge_flatten_outcomes(
    prior: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Union by (symbol, trade_id|status); fresh closed rows win over prior for same symbol."""
    by_key: dict[str, dict[str, Any]] = {}
    for o in prior + fresh:
        if not isinstance(o, dict):
            continue
        sym = str(o.get("symbol") or "").strip().upper()
        if not sym:
            continue
        tid = str(o.get("trade_id") or "").strip()
        key = f"{sym}|{tid}" if tid else f"{sym}|{o.get('status')}"
        by_key[key] = o
    # Prefer closed rows when duplicate symbols without trade_id collide
    closed_by_sym: dict[str, dict[str, Any]] = {}
    other: list[dict[str, Any]] = []
    for o in by_key.values():
        sym = str(o.get("symbol") or "").strip().upper()
        if str(o.get("status") or "") == "closed":
            closed_by_sym[sym] = o
        else:
            other.append(o)
    merged = list(closed_by_sym.values()) + [
        o for o in other if str(o.get("symbol") or "").strip().upper() not in closed_by_sym
    ]
    return merged[-40:]


def provisional_lesson_candidate(att: dict[str, Any] | None) -> str:
    """Honest single-RT lesson text — never a validated policy claim."""
    a = att if isinstance(att, dict) else {}
    und = a.get("underlying") or "?"
    right = a.get("option_type") or "?"
    mark = a.get("mark_source") or "unknown_mark"
    try:
        pnl = float(a["realized_pnl"]) if a.get("realized_pnl") is not None else None
    except (TypeError, ValueError):
        pnl = None
    pnl_s = f"₹{pnl:+.2f}" if pnl is not None else "n/a"
    return (
        f"Lab v1 {und} ATM {right} session_flat close: realized {pnl_s} "
        f"(mark={mark}). Controlled paper sample — not a strategy edge; "
        f"prediction_absent until decide-time E[R] is attached at entry."
    )


def build_cognitive_block(
    att: dict[str, Any] | None,
    *,
    advice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cognitive seam for Lab v1 closes — REVIEWED or honest UNREVIEWED."""
    a = dict(att) if isinstance(att, dict) else {}
    adv = advice if isinstance(advice, dict) else {}
    review = str(
        adv.get("review_status") or a.get("cognitive_review") or "UNREVIEWED"
    )
    lesson = str(adv.get("summary") or adv.get("interpretation") or "").strip()
    if not lesson:
        lesson = provisional_lesson_candidate(a)
    skip = adv.get("skip_reason") or adv.get("reason")
    return {
        "laboratory_id": LABORATORY_ID,
        "lab_role": LAB_ROLE,
        "lab_version": VERSION,
        "experiment_family": a.get("experiment_family"),
        "experiment_id": a.get("experiment_id") or a.get("experiment_family"),
        "underlying": a.get("underlying"),
        "option_contract": a.get("option_contract"),
        "option_type": a.get("option_type"),
        "exit_reason": a.get("exit_reason") or REASON_EXPERIMENT_CLOSE,
        "mark_source": a.get("mark_source"),
        "realized_pnl": a.get("realized_pnl"),
        "trade_id": a.get("trade_id"),
        "cognitive_review": review,
        "lesson_candidate": lesson,
        "learning_status": (
            "PROVISIONAL — insufficient sample / prediction_absent"
            if review != "REVIEWED"
            else str(adv.get("learning_status") or "PROVISIONAL — single RT")
        ),
        "skip_reason": skip,
        "advice": adv or None,
        "live_orders": False,
        "honesty": (
            "Single controlled close is not L5. UNREVIEWED means Core did not "
            "complete a REVIEWED pass — never invent REVIEWED."
        ),
    }


def apply_cognitive_to_attribution(
    att: dict[str, Any] | None,
    *,
    advice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp attribution + nested cognitive block after Core (or honest UNREVIEWED)."""
    a = dict(att) if isinstance(att, dict) else {}
    cog = build_cognitive_block(a, advice=advice)
    a["cognitive_review"] = cog.get("cognitive_review") or "UNREVIEWED"
    a["learning_status"] = cog.get("learning_status")
    a["cognitive"] = cog
    a["lesson_candidate"] = cog.get("lesson_candidate")
    return a


def record_experiment_integrity(
    data_dir: str | Path | None,
    *,
    positions: list[Any] | None,
    must_be_flat: bool,
    flatten_outcomes: list[Any] | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Durable proof: Lab v1 option experiments are flat overnight.

    Empty ``flatten_outcomes`` on a later tick must not erase prior closed-experiment
    rows for the same IST session date.
    """
    day = as_of_ist or flatten_session_date()
    open_opts = open_option_positions(positions)
    n_open = len(open_opts)
    fresh = [o for o in (flatten_outcomes or []) if isinstance(o, dict)]
    prior = load_flatten_outcomes(data_dir, as_of_ist=day)
    outcomes = _merge_flatten_outcomes(prior, fresh)
    closed_n = sum(1 for o in outcomes if str(o.get("status") or "") == "closed")
    blocked_n = sum(1 for o in outcomes if str(o.get("status") or "").startswith("blocked"))
    if must_be_flat and n_open == 0:
        status = "flat_ok"
    elif must_be_flat and n_open > 0:
        status = "overnight_open"
    elif n_open > 0:
        status = "experiments_open"
    else:
        status = "flat_ok"
    doc = {
        "version": VERSION,
        "kind": "FNO_LAB_V1_INTEGRITY",
        "laboratory_id": LABORATORY_ID,
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "must_be_flat": bool(must_be_flat),
        "exit_policy": "session_flat",
        "overnight_option_positions": n_open,
        "overnight_positions_ok": n_open == 0 if must_be_flat else True,
        "open_symbols": [str(p.get("symbol") or "") for p in open_opts],
        "status": status,
        "flatten_outcomes_n": len(outcomes),
        "flatten_closed_n": closed_n,
        "flatten_blocked_n": blocked_n,
        "flatten_outcomes": outcomes[-20:],
        "honesty": (
            "Lab v1 option experiments must close same session. "
            "Open overnight inventory blocks learning (no outcome → no attribution). "
            "Prior flatten_outcomes are preserved across empty flat rewrites."
        ),
    }
    path = integrity_path(data_dir, as_of_ist=day)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
            doc["path"] = str(path)
            doc["ok"] = True
        except OSError as exc:
            _log.debug("lab_v1 integrity persist failed: %s", exc, exc_info=True)
            doc["ok"] = False
    else:
        doc["ok"] = False
    return doc
