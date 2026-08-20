"""LOOP0 L4 — honest NIFTY index-proxy paper lot (not live futures).

Turns a Yahoo underlier mark (^NSEI) into 1 lot × lot_size with a margin check.
KPI / evening name: **NIFTY index-proxy laboratory performance** — never “F&O performance.”
"""

from __future__ import annotations

from typing import Any

VERSION = "loop0.l4.index_proxy.v1"
VALUATION_BASIS = "index_proxy daily underlier"
KPI_LABEL = "NIFTY index-proxy laboratory performance"
STRATEGY_TAG = "index_proxy_lot"
MARGIN_FRACTION = 0.12
MAX_LOTS = 1

_NIFTY = frozenset({"NIFTY", "NIFTY50", "NIFTY-FUT", "^NSEI", "NSEI"})
_BANK = frozenset({"BANKNIFTY", "BANKNIFTY-FUT", "^NSEBANK", "NSEBANK"})


def _norm(symbol: str) -> str:
    return (symbol or "").strip().upper()


def is_fno_lab(cfg: dict[str, Any] | None, portfolio_key: str | None = None) -> bool:
    cfg = cfg or {}
    pk = str(portfolio_key or cfg.get("portfolio_key") or "").strip().lower()
    ac = str(cfg.get("asset_class") or "").strip().lower()
    pack = str(cfg.get("instrument_pack") or "").strip().lower()
    return (
        "fno" in pk
        or pk.endswith("_futures")
        or ac in {"futures", "options"}
        or pack in {"futures", "options", "fno"}
    )


def underlier_family(symbol: str) -> str | None:
    key = _norm(symbol)
    if key in _NIFTY or key.startswith("NIFTY"):
        return "nifty"
    if key in _BANK or key.startswith("BANKNIFTY"):
        return "banknifty"
    return None


def is_nifty_underlier(symbol: str) -> bool:
    return underlier_family(symbol) == "nifty"


def lot_units(
    symbol: str,
    *,
    instrument: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> int:
    from atlas.investment.packs.derivatives import default_lot_size

    ctx: dict[str, Any] = {}
    if cfg:
        ctx.update(cfg)
    if instrument:
        ctx["instrument"] = instrument
    n = int(default_lot_size(symbol, ctx))
    fam = underlier_family(symbol)
    if n <= 1 and fam == "nifty":
        return 25
    if n <= 1 and fam == "banknifty":
        return 15
    return n


def uses_index_proxy_collateral(symbol: str, qty: float) -> bool:
    """True when this fill is a whole index-proxy lot (not a 1-share cash index)."""
    if underlier_family(symbol) is None:
        return False
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return False
    lot = lot_units(symbol)
    return lot > 1 and q + 1e-9 >= float(lot)


def margin_required(qty: float, price: float, *, fraction: float = MARGIN_FRACTION) -> float:
    return abs(float(qty) * float(price) * float(fraction))


def size_one_lot(
    *,
    symbol: str,
    price: float,
    cash: float,
    held: float = 0.0,
    instrument: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    max_lots: int = MAX_LOTS,
) -> dict[str, Any]:
    """Size exactly ``max_lots`` index-proxy lots (units = lots × lot_size)."""
    lot = lot_units(symbol, instrument=instrument, cfg=cfg)
    want = int(max(1, max_lots)) * lot
    held_i = int(round(float(held or 0)))
    if held_i >= want:
        return {
            "ok": False,
            "qty": 0,
            "lot_size": lot,
            "margin": 0.0,
            "reason": f"already_open:{held_i}>={want}",
            "strategy_tag": STRATEGY_TAG,
        }
    try:
        px = float(price)
        cash_f = float(cash)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "qty": 0,
            "lot_size": lot,
            "margin": 0.0,
            "reason": "bad_price_or_cash",
            "strategy_tag": STRATEGY_TAG,
        }
    if px <= 0:
        return {
            "ok": False,
            "qty": 0,
            "lot_size": lot,
            "margin": 0.0,
            "reason": "no_mark",
            "strategy_tag": STRATEGY_TAG,
        }
    need = want - held_i
    # Round up to a whole lot
    lots_needed = max(1, (need + lot - 1) // lot)
    qty = lots_needed * lot
    margin = margin_required(qty, px)
    if cash_f + 1e-6 < margin:
        return {
            "ok": False,
            "qty": 0,
            "lot_size": lot,
            "margin": margin,
            "reason": (
                f"insufficient margin: need ~{margin:.2f} "
                f"({MARGIN_FRACTION:.0%} of notional {qty * px:.2f}); cash={cash_f:.2f}"
            ),
            "strategy_tag": "margin",
        }
    return {
        "ok": True,
        "qty": float(qty),
        "lot_size": lot,
        "margin": margin,
        "reason": "",
        "strategy_tag": STRATEGY_TAG,
        "honesty": "index-proxy paper lot on daily underlier — not live futures",
    }


def laboratory_kpi_label() -> str:
    return KPI_LABEL


def open_cash_debit(qty: float, price: float, *, fraction: float = MARGIN_FRACTION) -> float:
    """Cash posted to open 1+ index-proxy lots (margin, not full notional)."""
    return margin_required(qty, price, fraction=fraction)


def close_cash_credit(
    qty: float,
    entry: float,
    exit_px: float,
    *,
    fraction: float = MARGIN_FRACTION,
) -> float:
    """Cash returned on close: posted margin + variation (fees applied by caller)."""
    variation = (float(exit_px) - float(entry)) * float(qty)
    return margin_required(qty, entry, fraction=fraction) + variation


def position_lab_value(
    qty: float,
    avg: float,
    mark: float,
    *,
    fraction: float = MARGIN_FRACTION,
) -> tuple[float, float]:
    """(holdings_value, variation) for futures-lite MTM.

    holdings = posted margin + variation, so equity = cash + holdings
    recovers starting capital + variation − fees.
    """
    variation = (float(mark) - float(avg)) * float(qty)
    posted = margin_required(qty, avg, fraction=fraction)
    return posted + variation, variation


def rewrite_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Revalue index-proxy lots; leave cash-equity names untouched."""
    snap = dict(snapshot or {})
    rows = list(snap.get("positions") or [])
    if not rows:
        return snap
    holdings = 0.0
    unrealized = 0.0
    used_proxy = False
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        qty = float(row.get("quantity") or 0)
        avg = float(row.get("avg_price") or 0)
        mark = float(row.get("mark") if row.get("mark") is not None else avg)
        if uses_index_proxy_collateral(symbol, qty):
            value, pnl = position_lab_value(qty, avg, mark)
            used_proxy = True
            new_rows.append({**row, "value": value, "unrealized_pnl": pnl})
        else:
            value = float(row.get("value") if row.get("value") is not None else qty * mark)
            pnl = float(
                row.get("unrealized_pnl")
                if row.get("unrealized_pnl") is not None
                else (mark - avg) * qty
            )
            new_rows.append(row)
        holdings += value
        unrealized += pnl
    if not used_proxy:
        return snap
    cash = float(snap.get("cash") or 0)
    starting = float(snap.get("starting_cash") or 0)
    equity = cash + holdings
    snap["positions"] = new_rows
    snap["holdings_value"] = holdings
    snap["unrealized_pnl"] = unrealized
    snap["equity"] = equity
    snap["total_return"] = (equity - starting) / starting if starting > 0 else 0.0
    prior = str(snap.get("valuation_basis") or "")
    if "feed_gap" in prior:
        snap["valuation_basis"] = f"{VALUATION_BASIS} ({prior})"
    else:
        snap["valuation_basis"] = VALUATION_BASIS
    return snap
