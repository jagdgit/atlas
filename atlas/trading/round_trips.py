"""FIFO round-trip reconstruction from the sim blotter (operator UI / learning).

The book uses average-cost accounting for cash and ``realized_pnl``. This helper
walks fills oldest→newest and matches sells against open buy lots so the Market
UI can show bought-at / sold-at rows without inventing a second P&L truth:

* ``buy_price`` / ``bought_at`` — FIFO lot that funded the sell
* ``sell_price`` / ``sold_at`` — the sell fill
* ``realized_pnl`` — pro-rata share of the sell row's book ``realized_pnl``
  (avg-cost economics), not a recompute from FIFO prices
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _ts(row: dict[str, Any]) -> str:
    raw = row.get("created_at")
    if raw is None:
        return ""
    return raw.isoformat() if hasattr(raw, "isoformat") else str(raw)


def build_closed_round_trips(
    trades: list[dict[str, Any]],
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Match sells to open buys (FIFO). ``trades`` may be newest-first or mixed."""
    if not trades:
        return []
    stamped = any(_ts(t) for t in trades)
    if stamped:
        chrono = sorted(
            trades,
            key=lambda t: (_ts(t) or "", str(t.get("id") or "")),
        )
    else:
        # In-memory / tests often omit created_at; repo returns newest-first.
        chrono = list(reversed(trades))

    open_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    closed: list[dict[str, Any]] = []

    for trade in chrono:
        symbol = str(trade.get("symbol") or "").strip()
        if not symbol:
            continue
        side = str(trade.get("side") or "").lower()
        try:
            qty = float(trade.get("quantity") or 0.0)
            price = float(trade.get("price") or 0.0)
            fee = float(trade.get("fee") or 0.0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue

        if side == "buy":
            open_lots[symbol].append(
                {
                    "qty": qty,
                    "price": price,
                    "fee": fee,
                    "bought_at": _ts(trade),
                    "buy_trade_id": trade.get("id"),
                }
            )
            continue

        if side != "sell":
            continue

        try:
            sell_realized = float(trade.get("realized_pnl") or 0.0)
        except (TypeError, ValueError):
            sell_realized = 0.0
        remaining = qty
        lots = open_lots[symbol]
        fees_doc = trade.get("fees") if isinstance(trade.get("fees"), dict) else {}

        while remaining > 1e-9 and lots:
            lot = lots[0]
            take = min(remaining, float(lot["qty"]))
            lot_qty = float(lot["qty"])
            frac_lot = take / lot_qty if lot_qty > 1e-12 else 0.0
            buy_fee_part = float(lot["fee"]) * frac_lot
            frac_sell = take / qty if qty > 1e-12 else 0.0
            sell_fee_part = fee * frac_sell
            realized_part = sell_realized * frac_sell
            tax_part = 0.0
            for k in ("stt", "stamp", "tds", "gst", "exchange", "brokerage"):
                try:
                    tax_part += float(fees_doc.get(k) or 0.0) * frac_sell
                except (TypeError, ValueError):
                    continue

            closed.append(
                {
                    "symbol": symbol,
                    "quantity": round(take, 6),
                    "buy_price": round(float(lot["price"]), 6),
                    "bought_at": lot["bought_at"],
                    "sell_price": round(price, 6),
                    "sold_at": _ts(trade),
                    "buy_fee": round(buy_fee_part, 4),
                    "sell_fee": round(sell_fee_part, 4),
                    "fees": round(buy_fee_part + sell_fee_part, 4),
                    "taxes_and_charges": round(tax_part + buy_fee_part, 4),
                    "realized_pnl": round(realized_part, 4),
                    "buy_trade_id": lot.get("buy_trade_id"),
                    "sell_trade_id": trade.get("id"),
                    "decision_id": trade.get("decision_id"),
                }
            )

            lot["qty"] = lot_qty - take
            lot["fee"] = float(lot["fee"]) - buy_fee_part
            if lot["qty"] <= 1e-9:
                lots.pop(0)
            remaining -= take

        if remaining > 1e-6:
            # Sell without matching buy (data gap / reset) — still surface the close.
            frac = remaining / qty if qty > 1e-12 else 1.0
            closed.append(
                {
                    "symbol": symbol,
                    "quantity": round(remaining, 6),
                    "buy_price": None,
                    "bought_at": None,
                    "sell_price": round(price, 6),
                    "sold_at": _ts(trade),
                    "buy_fee": 0.0,
                    "sell_fee": round(fee * frac, 4),
                    "fees": round(fee * frac, 4),
                    "taxes_and_charges": round(fee * frac, 4),
                    "realized_pnl": round(sell_realized * frac, 4),
                    "buy_trade_id": None,
                    "sell_trade_id": trade.get("id"),
                    "decision_id": trade.get("decision_id"),
                    "unmatched_buy": True,
                }
            )

    # Newest closes first for the UI.
    closed.sort(key=lambda r: (str(r.get("sold_at") or ""), str(r.get("symbol") or "")), reverse=True)
    return closed[: max(0, int(limit))]


def summarize_taxes_and_pnl(
    *,
    fee_components: dict[str, float] | None,
    fees_paid: float,
    withdrawal_tds: float,
    realized_pnl: float,
    unrealized_pnl: float,
    total_pnl: float | None,
    closed_round_trips: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Roll-up block for per-lab tax / P&L tables."""
    comps = dict(fee_components or {})
    trade_taxes = round(
        float(comps.get("stt") or 0)
        + float(comps.get("stamp") or 0)
        + float(comps.get("tds") or 0)
        + float(comps.get("gst") or 0)
        + float(comps.get("exchange") or 0),
        4,
    )
    brokerage = round(float(comps.get("brokerage") or 0), 4)
    w_tds = round(float(withdrawal_tds or 0), 4)
    total_taxes = round(trade_taxes + w_tds, 4)
    total_charges = round(float(fees_paid or 0) + w_tds, 4)
    closed_pnl = round(
        sum(float(r.get("realized_pnl") or 0) for r in (closed_round_trips or [])),
        4,
    )
    return {
        "brokerage": brokerage,
        "stt": round(float(comps.get("stt") or 0), 4),
        "stamp": round(float(comps.get("stamp") or 0), 4),
        "gst": round(float(comps.get("gst") or 0), 4),
        "exchange": round(float(comps.get("exchange") or 0), 4),
        "trade_tds": round(float(comps.get("tds") or 0), 4),
        "withdrawal_tds": w_tds,
        "trade_taxes": trade_taxes,
        "total_taxes": total_taxes,
        "fees_paid": round(float(fees_paid or 0), 4),
        "total_charges": total_charges,
        "realized_pnl": round(float(realized_pnl or 0), 4),
        "unrealized_pnl": round(float(unrealized_pnl or 0), 4),
        "closed_round_trip_pnl": closed_pnl,
        "total_pnl": None if total_pnl is None else round(float(total_pnl), 4),
    }
