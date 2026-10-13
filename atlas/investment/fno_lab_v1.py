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
from uuid import uuid4
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
PREDICTION_BY_ID_REL = Path("investment") / "fno" / "lab_v1_predictions" / "by_id"
ENTRY_SNAPSHOT_REL = Path("investment") / "fno" / "lab_v1_entry_snapshots"
REASON_EXPERIMENT_CLOSE = "fno_lab_v1_experiment_close"
# Close-out starts before the 15:30 NSE close so the exit is tradeable; no new
# entries from here on. A close executed at/after FNO_MARKET_CLOSE is a
# bookkeeping flatten and is not learning-eligible.
FNO_FLAT_AFTER = time(15, 20)
FNO_MARKET_CLOSE = time(15, 30)
FNO_SESSION_OPEN = time(9, 15)
EXIT_AFTER_SESSION_CLOSE = "exit_after_session_close"
# Bounded control-linked premium E[R] model id (not a valued option pricer).
ENTRY_ER_MODEL = "fno_lab_v1_control_signal.v1"

# Finite paper capital — operator does not top up F&O indefinitely.
# max_open stops underlier-swarm buys; cash_floor keeps residual dry powder.
DEFAULT_CAPITAL_POLICY: dict[str, Any] = {
    "version": "fno.lab.v1.capital.v1",
    "auto_top_up": False,
    "operator_deposit_only": True,
    "max_open_option_experiments": 2,
    "cash_reserve_fraction_of_starting": 0.30,
    "honesty": (
        "Paper F&O capital is finite (starting_cash / net contributed). "
        "Atlas must not auto-deposit or void-reset to refill the book. "
        "New option BUYs stop at max_open or when cash would breach the reserve floor."
    ),
}

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
SKIP_CAPITAL_MAX_OPEN = "capital_budget_max_open"
SKIP_CAPITAL_CASH_FLOOR = "capital_budget_cash_floor"
SKIP_REENTRY_AFTER_EXIT = "reentry_after_managed_exit"

# Held-option management every tick, ATM or not. Session flatten still closes the rest.
EXIT_PREMIUM_STOP = "premium_stop"
EXIT_PREMIUM_TARGET = "premium_target"
EXIT_UNDERLIER_REVERSAL = "underlier_reversal"
MANAGED_EXIT_CODES = frozenset({EXIT_PREMIUM_STOP, EXIT_PREMIUM_TARGET, EXIT_UNDERLIER_REVERSAL})
DEFAULT_EXIT_POLICY: dict[str, Any] = {
    "version": "fno.lab.v1.exit.v1",
    "premium_stop_pct": 0.40,
    "premium_target_pct": None,
    "exit_on_underlier_reversal": True,
    "no_reentry_same_day_after_managed_exit": True,
}


def evaluate_held_option_exit(
    held: list[dict[str, Any]],
    *,
    ltp_by_symbol: dict[str, float | None],
    sma_margin: float | None,
    policy_doc: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """First held option that must exit now, or None.

    ``held`` rows: {symbol, right, qty, position:{avg_price|avg_cost}}. A missing
    LTP never triggers an exit (no invented marks); the session flatten covers it.
    """
    pol = dict(DEFAULT_EXIT_POLICY)
    pol.update({k: v for k, v in (policy_doc or {}).items() if k in DEFAULT_EXIT_POLICY})
    try:
        margin = float(sma_margin) if sma_margin is not None else None
    except (TypeError, ValueError):
        margin = None
    for row in held or []:
        sym = str(row.get("symbol") or "")
        pos = row.get("position") if isinstance(row.get("position"), dict) else {}
        try:
            entry = float(pos.get("avg_price") or pos.get("avg_cost") or 0)
            ltp = float(ltp_by_symbol.get(sym) or 0)
        except (TypeError, ValueError):
            continue
        if entry <= 0 or ltp <= 0:
            continue
        change = (ltp - entry) / entry
        code = None
        stop = pol.get("premium_stop_pct")
        target = pol.get("premium_target_pct")
        right = str(row.get("right") or "")
        if stop is not None and change <= -float(stop):
            code = EXIT_PREMIUM_STOP
        elif target is not None and change >= float(target):
            code = EXIT_PREMIUM_TARGET
        elif pol.get("exit_on_underlier_reversal") and margin is not None and (
            (right == "CE" and margin < 0) or (right == "PE" and margin > 0)
        ):
            code = EXIT_UNDERLIER_REVERSAL
        if code:
            return {
                "symbol": sym,
                "right": right,
                "qty": float(row.get("qty") or 0),
                "price": ltp,
                "entry_premium": entry,
                "premium_change_pct": round(change * 100.0, 4),
                "exit_code": code,
                "policy_version": pol["version"],
            }
    return None


def managed_exit_underliers(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_fno_learner",
    ist_day: str,
) -> set[str]:
    """Underliers that had a managed (stop/target/reversal) exit today, from trade lineage."""
    if not data_dir:
        return set()
    path = Path(data_dir) / "investment" / "trade_lineage" / laboratory_id / f"{ist_day}.jsonl"
    if not path.is_file():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("side") == "sell" and row.get("exit_reason_code") in MANAGED_EXIT_CODES:
            und = option_underlier_name(str(row.get("symbol") or ""))
            if und:
                out.add(und)
    return out


def option_underlier_name(option_symbol: str) -> str | None:
    """'NIFTY26OCT22500PE' → 'NIFTY'; weekly 'NIFTY2610622500PE' → 'NIFTY'."""
    m = re.match(
        r"^([A-Z&\-]+?)\d{2}(?:[A-Z]{3}|[1-9OND]\d{2})\d+(?:CE|PE)$",
        str(option_symbol or "").upper(),
    )
    return m.group(1) if m else None


# Operator-owned tunables. Atlas reads this file every tick and never rewrites it.
RISK_SETTINGS_REL = Path("investment") / "fno" / "lab_v1_risk_settings.json"

# (min, max, allow_null) per tunable; out-of-range values fall back to the default.
_CAPITAL_BOUNDS: dict[str, tuple[float, float, bool]] = {
    "max_open_option_experiments": (1, 10, False),
    "cash_reserve_fraction_of_starting": (0.0, 0.9, False),
}
_EXIT_BOUNDS: dict[str, tuple[float, float, bool]] = {
    "premium_stop_pct": (0.05, 0.95, True),
    "premium_target_pct": (0.05, 10.0, True),
}
_EXIT_FLAGS = ("exit_on_underlier_reversal", "no_reentry_same_day_after_managed_exit")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("F&O settings unreadable (%s): %s — using defaults", path, exc)
        return None
    return doc if isinstance(doc, dict) else None


def _apply_bounded(
    body: dict[str, Any],
    raw: dict[str, Any],
    bounds: dict[str, tuple[float, float, bool]],
    *,
    section: str,
) -> None:
    for key, (lo, hi, nullable) in bounds.items():
        if key not in raw:
            continue
        val = raw[key]
        if val is None and nullable:
            body[key] = None
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            _log.warning("F&O settings %s.%s=%r invalid — keeping %r", section, key, val, body.get(key))
            continue
        if not lo <= num <= hi:
            _log.warning(
                "F&O settings %s.%s=%r outside [%s, %s] — keeping %r", section, key, val, lo, hi, body.get(key)
            )
            continue
        body[key] = int(num) if isinstance(body.get(key), int) and not isinstance(body.get(key), bool) else num


def risk_settings_path(data_dir: str | Path | None) -> Path | None:
    return Path(data_dir) / RISK_SETTINGS_REL if data_dir else None


def capital_policy(data_dir: str | Path | None = None) -> dict[str, Any]:
    """Finite-capital rules for Lab v1 option BUYs (never auto top-up)."""
    body = dict(DEFAULT_CAPITAL_POLICY)
    if not data_dir:
        return body
    for path in (Path(data_dir) / POLICY_REL, Path(data_dir) / RISK_SETTINGS_REL):
        doc = _read_json(path)
        raw = doc.get("capital") if isinstance(doc, dict) else None
        if isinstance(raw, dict):
            _apply_bounded(body, raw, _CAPITAL_BOUNDS, section="capital")
    body["auto_top_up"] = False  # hard invariant — never auto-refill
    return body


def exit_policy(data_dir: str | Path | None = None) -> dict[str, Any]:
    """Held-option exit rules; operator file overrides defaults."""
    body = dict(DEFAULT_EXIT_POLICY)
    doc = _read_json(Path(data_dir) / RISK_SETTINGS_REL) if data_dir else None
    raw = doc.get("exit") if isinstance(doc, dict) else None
    if isinstance(raw, dict):
        _apply_bounded(body, raw, _EXIT_BOUNDS, section="exit")
        for flag in _EXIT_FLAGS:
            if isinstance(raw.get(flag), bool):
                body[flag] = raw[flag]
    return body


def write_default_risk_settings(data_dir: str | Path | None) -> dict[str, Any]:
    """Create the operator settings file with current defaults; never overwrites."""
    path = risk_settings_path(data_dir)
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    if path.exists():
        return {"ok": True, "path": str(path), "created": False}
    cap = capital_policy(data_dir)
    doc = {
        "_help": {
            "what": "F&O Lab v1 risk settings. Edit values and save; Atlas reads this every tick (no restart).",
            "capital.max_open_option_experiments": "Max open option positions at once (1-10).",
            "capital.cash_reserve_fraction_of_starting": "Cash kept untouched, as a fraction of contributed capital (0-0.9).",
            "exit.premium_stop_pct": "Exit when premium falls this fraction below entry, e.g. 0.30 = -30% (0.05-0.95, or null to disable).",
            "exit.premium_target_pct": "Exit when premium rises this fraction above entry, e.g. 0.60 = +60% (or null to disable).",
            "exit.exit_on_underlier_reversal": "true = exit a put when the trend turns up / a call when it turns down.",
            "exit.no_reentry_same_day_after_managed_exit": "true = no new entry on that underlier the same day after a stop/target/reversal exit.",
            "invalid": "Out-of-range or malformed values are ignored (default kept) and logged as a warning.",
        },
        "capital": {k: cap[k] for k in _CAPITAL_BOUNDS},
        "exit": {k: v for k, v in DEFAULT_EXIT_POLICY.items() if k != "version"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "created": True}


def count_open_option_experiments(positions: list[dict[str, Any]] | None) -> int:
    n = 0
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        try:
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 1e-12:
            continue
        if option_right(str(pos.get("symbol") or "")):
            n += 1
    return n


def evaluate_option_buy_budget(
    *,
    positions: list[dict[str, Any]] | None,
    cash: float,
    premium: float | None,
    qty: float | None,
    starting_cash: float | None = None,
    policy_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gate a new 1-lot option BUY against finite paper capital.

    Does not deposit, withdraw, or reset the book. Deny reasons are explicit
    skip codes for KPI / session notes.
    """
    pol = dict(DEFAULT_CAPITAL_POLICY)
    if isinstance(policy_doc, dict):
        pol.update({k: policy_doc[k] for k in policy_doc if k in DEFAULT_CAPITAL_POLICY or k in pol})
    pol["auto_top_up"] = False
    try:
        max_open = int(pol.get("max_open_option_experiments") or 2)
    except (TypeError, ValueError):
        max_open = 2
    max_open = max(1, max_open)
    try:
        reserve_frac = float(pol.get("cash_reserve_fraction_of_starting") or 0.30)
    except (TypeError, ValueError):
        reserve_frac = 0.30
    reserve_frac = min(0.90, max(0.0, reserve_frac))

    open_n = count_open_option_experiments(positions)
    if open_n >= max_open:
        return {
            "ok": False,
            "reason": SKIP_CAPITAL_MAX_OPEN,
            "open_option_experiments": open_n,
            "max_open_option_experiments": max_open,
            "auto_top_up": False,
            "honesty": pol.get("honesty"),
        }
    try:
        cash_f = float(cash)
    except (TypeError, ValueError):
        cash_f = 0.0
    try:
        px = float(premium) if premium is not None else 0.0
        q = float(qty) if qty is not None else 0.0
    except (TypeError, ValueError):
        px, q = 0.0, 0.0
    debit = max(0.0, px * q)
    try:
        base = float(starting_cash) if starting_cash is not None else cash_f
    except (TypeError, ValueError):
        base = cash_f
    floor = max(0.0, base * reserve_frac)
    cash_after = cash_f - debit
    if cash_after + 1e-9 < floor:
        return {
            "ok": False,
            "reason": SKIP_CAPITAL_CASH_FLOOR,
            "cash": cash_f,
            "debit": debit,
            "cash_after": cash_after,
            "cash_floor": floor,
            "starting_cash": base,
            "reserve_fraction": reserve_frac,
            "open_option_experiments": open_n,
            "auto_top_up": False,
            "honesty": pol.get("honesty"),
        }
    return {
        "ok": True,
        "reason": "within_capital_budget",
        "cash": cash_f,
        "debit": debit,
        "cash_after": cash_after,
        "cash_floor": floor,
        "open_option_experiments": open_n,
        "max_open_option_experiments": max_open,
        "auto_top_up": False,
    }


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
    """Contract pointer path (latest open prediction for a tradingsymbol)."""
    if not data_dir or not option_symbol:
        return None
    key = re.sub(r"[^A-Z0-9]+", "_", str(option_symbol).strip().upper()) or "UNK"
    return Path(data_dir) / PREDICTION_REL / f"{key}.json"


def prediction_by_id_path(
    data_dir: str | Path | None,
    *,
    prediction_id: str | None = None,
) -> Path | None:
    """Immutable prediction record path (P0.7 — survives re-entry overwrite)."""
    if not data_dir or not prediction_id:
        return None
    key = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(prediction_id).strip()) or "UNK"
    return Path(data_dir) / PREDICTION_BY_ID_REL / f"{key}.json"


def entry_snapshot_path(
    data_dir: str | Path | None,
    *,
    prediction_id: str | None = None,
) -> Path | None:
    if not data_dir or not prediction_id:
        return None
    key = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(prediction_id).strip()) or "UNK"
    return Path(data_dir) / ENTRY_SNAPSHOT_REL / f"{key}.json"


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
    features: dict[str, Any] | None = None,
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
    prediction_id = str(uuid4())
    return {
        "version": VERSION,
        "kind": "FNO_LAB_V1_ENTRY_PREDICTION",
        "prediction_id": prediction_id,
        "prediction_status": "stated",
        # OI-DELI0 P0.7 / §4.1 prediction contract
        "prediction_type": "rule_output",
        "target_variable": "option_premium_return",
        "horizon": "session_flat",
        "prediction_time": clock.isoformat(),
        "model_or_rule_version": ENTRY_ER_MODEL,
        "calibration_status": "uncalibrated_default",
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
            "p≈predicted_probability is uncalibrated_default — not a probability claim",
        ],
        "trade_id": trade_id,
        "control_action": control_action,
        "sma_margin": margin,
        "decide_time_features": dict(features) if isinstance(features, dict) else None,
        "live_orders": False,
        "honesty": (
            "Decide-time prediction persisted before outcome. "
            f"Model={ENTRY_ER_MODEL}. prediction_type=rule_output; "
            "calibration_status=uncalibrated_default. "
            "Not L5 until outcome→error→attribution→lesson validates."
        ),
    }


def persist_entry_prediction(
    data_dir: str | Path | None,
    prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    """Persist prediction by ``prediction_id``; contract file is a pointer (P0.7).

    Re-entry overwrites only the pointer — historical ``by_id`` records stay.
    """
    pred = prediction if isinstance(prediction, dict) else {}
    if not pred or not data_dir:
        return {"ok": False, "reason": "no_path_or_prediction"}
    body = dict(pred)
    if not body.get("prediction_id"):
        body["prediction_id"] = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    # recorded_at is decide time; outcome stamps (consumed) must not move it.
    body.setdefault("recorded_at", now_iso)
    by_id = prediction_by_id_path(data_dir, prediction_id=str(body["prediction_id"]))
    pointer = prediction_path(data_dir, option_symbol=str(body.get("contract") or ""))
    if by_id is None:
        return {"ok": False, "reason": "no_path_or_prediction"}
    try:
        by_id.parent.mkdir(parents=True, exist_ok=True)
        by_id.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
        if pointer is not None:
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer_doc = {
                "version": VERSION,
                "kind": "FNO_LAB_V1_PREDICTION_POINTER",
                "contract": body.get("contract"),
                "prediction_id": body["prediction_id"],
                "by_id_path": str(by_id),
                "prediction_status": body.get("prediction_status"),
                "updated_at": now_iso,
                "honesty": (
                    "Pointer only — full prediction lives under by_id. "
                    "Re-entry must not erase prior prediction_id records."
                ),
            }
            pointer.write_text(
                json.dumps(pointer_doc, indent=2, default=str) + "\n", encoding="utf-8"
            )
        return {
            "ok": True,
            "path": str(by_id),
            "pointer_path": str(pointer) if pointer else None,
            **body,
        }
    except OSError as exc:
        _log.debug("lab_v1 prediction persist failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error"}


def load_entry_prediction(
    data_dir: str | Path | None,
    *,
    option_symbol: str | None = None,
    prediction_id: str | None = None,
) -> dict[str, Any] | None:
    """Load by prediction_id, or follow the contract pointer, or legacy full-file."""
    if prediction_id:
        by_id = prediction_by_id_path(data_dir, prediction_id=prediction_id)
        if by_id is not None and by_id.is_file():
            try:
                doc = json.loads(by_id.read_text(encoding="utf-8"))
                return doc if isinstance(doc, dict) else None
            except (OSError, json.JSONDecodeError):
                return None
    path = prediction_path(data_dir, option_symbol=option_symbol)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    # Pointer → by_id
    if doc.get("kind") == "FNO_LAB_V1_PREDICTION_POINTER" or (
        doc.get("prediction_id") and not doc.get("expected_return") and doc.get("by_id_path")
    ):
        pid = str(doc.get("prediction_id") or "")
        return load_entry_prediction(data_dir, prediction_id=pid) if pid else None
    # Legacy: full prediction stored at contract path
    return doc


def persist_entry_evidence_snapshot(
    data_dir: str | Path | None,
    *,
    prediction_id: str | None,
    pack: dict[str, Any] | None,
    overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze decide-time pack/overlay evidence keyed by prediction_id (P0.7)."""
    if not data_dir or not prediction_id:
        return {"ok": False, "reason": "no_prediction_id"}
    path = entry_snapshot_path(data_dir, prediction_id=prediction_id)
    if path is None:
        return {"ok": False, "reason": "no_path"}
    pack_d = dict(pack) if isinstance(pack, dict) else {}
    overlay_d = dict(overlay) if isinstance(overlay, dict) else {}
    # Keep snapshot small — drop heavy tick arrays if present.
    pack_slim = {
        k: pack_d.get(k)
        for k in (
            "version",
            "underlying",
            "status",
            "quality_status",
            "freshness",
            "as_of",
            "spot",
            "expiry",
            "atm",
            "ce",
            "pe",
            "provider",
            "reason",
            "session",
        )
        if k in pack_d
    }
    spot_as_of = None
    if isinstance(pack_d.get("spot"), dict):
        spot_as_of = pack_d["spot"].get("as_of")
    body = {
        "version": "deli.entry_snapshot.v1",
        "prediction_id": str(prediction_id),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "pack_as_of": pack_slim.get("as_of") or spot_as_of,
        "pack": pack_slim,
        "overlay": {
            k: overlay_d.get(k)
            for k in (
                "kind",
                "symbol",
                "right",
                "price",
                "qty",
                "reason",
                "control_action",
                "adapter_id",
                "experiment_family",
            )
            if k in overlay_d
        },
        "honesty": (
            "Decide-time snapshot. Later pack overwrites must not replace this file. "
            "as_of should be ≤ fill time."
        ),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path), "prediction_id": str(prediction_id)}
    except OSError as exc:
        _log.debug("entry snapshot persist failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error"}


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
        "prediction_id": p.get("prediction_id"),
        "prediction_type": p.get("prediction_type") or "rule_output",
        "calibration_status": p.get("calibration_status") or "uncalibrated_default",
        "expected_return": p.get("expected_return"),
        "expected_direction": p.get("expected_direction") or "up",
        "expected_move": p.get("expected_move"),
        "predicted_probability": p.get("predicted_probability"),
        "prediction_horizon": p.get("prediction_horizon") or p.get("horizon") or "session_flat",
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
            "flat_after_ist": FNO_FLAT_AFTER.strftime("%H:%M"),
            "market_close_ist": FNO_MARKET_CLOSE.strftime("%H:%M"),
            "after_close_exit_learning_eligible": False,
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
        "capital": capital_policy(data_dir),
        "exit": exit_policy(data_dir),
        "expansion_rule": (
            "seed → experiences → coverage/data problems → repeated behaviours → "
            "lessons with attribution → revise seed/rules → expand"
        ),
        "equity_horizon_audit": "parallel_not_prerequisite",
        "honesty": (
            "Controlled paper training population. Not an edge claim. "
            "Not the full NFO master. Missing data SKIPs — never invents fills. "
            "Capital is finite — no auto top-up."
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
    """True when Lab v1 option inventory must be flat (from 15:20 IST / weekend)."""
    ist = to_ist(now)
    if ist.weekday() >= 5:
        return True
    t = ist.time().replace(tzinfo=None)
    return t >= FNO_FLAT_AFTER or t < FNO_SESSION_OPEN


def exit_is_tradeable(now: datetime | None = None) -> bool:
    """True when an exit at ``now`` could have been executed on NSE (09:15–15:30 weekday)."""
    ist = to_ist(now)
    if ist.weekday() >= 5:
        return False
    t = ist.time().replace(tzinfo=None)
    return FNO_SESSION_OPEN <= t < FNO_MARKET_CLOSE


def exit_learning_eligibility(now: datetime | None = None) -> dict[str, Any]:
    """Learning eligibility of a close by execution time (not by outcome)."""
    if exit_is_tradeable(now):
        return {"eligible": True, "exit_timing": "in_session", "reasons": []}
    return {
        "eligible": False,
        "exit_timing": "after_close",
        "reasons": [EXIT_AFTER_SESSION_CLOSE],
        "honesty": (
            "Close executed outside NSE hours — mark is the last traded print, "
            "not a tradeable exit. Ledger keeps it; learning must not train on it."
        ),
    }


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
