"""Operator void of invalid paper fills — restore cash, drop positions.

Used when a lab traded under the wrong feed (e.g. daily bars labeled “intraday”).
Does not invent prices: positions are deleted, cash is restored to starting_cash,
and an adjustment is journaled. Optional blotter wipe so KPIs do not keep the
voided session as “today’s experiments.”
"""

from __future__ import annotations

from typing import Any


def void_book_to_starting_cash(
    repo: Any,
    portfolio_id: Any,
    *,
    restore_cash: float | None = None,
    wipe_trades: bool = True,
    note: str,
    mission_id: str | None = None,
) -> dict[str, Any]:
    """Flatten positions and restore cash. Returns a summary (no network)."""
    port = repo.get_portfolio(portfolio_id)
    if port is None:
        return {"ok": False, "reason": "no_portfolio"}
    old_cash = float(port.get("cash") or 0)
    old_realized = float(port.get("realized_pnl") or 0)
    target = (
        float(restore_cash)
        if restore_cash is not None
        else float(port.get("starting_cash") or 0)
    )
    positions = list(repo.list_positions(portfolio_id) or [])
    dropped = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol") or "")
        if not sym:
            continue
        dropped.append(
            {
                "symbol": sym,
                "quantity": pos.get("quantity"),
                "avg_price": pos.get("avg_price"),
            }
        )
        repo.delete_position(portfolio_id, sym)
    # Zero realized P&L from the voided experiment.
    repo.update_portfolio_cash(
        portfolio_id,
        cash=target,
        realized_pnl_delta=-old_realized,
    )
    trades_deleted = 0
    if wipe_trades and hasattr(repo, "delete_trades"):
        trades_deleted = int(repo.delete_trades(portfolio_id) or 0)
    elif wipe_trades and hasattr(repo, "trades"):
        before = len(repo.trades)
        pid = str(portfolio_id)
        repo.trades[:] = [t for t in repo.trades if str(t.get("portfolio_id")) != pid]
        trades_deleted = before - len(repo.trades)
    if hasattr(repo, "record_cash_movement"):
        repo.record_cash_movement(
            portfolio_id=portfolio_id,
            mission_id=mission_id or port.get("mission_id"),
            kind="adjustment",
            amount=target - old_cash,
            cash_after=target,
            note=note,
            metadata={
                "voided_positions": dropped,
                "old_cash": old_cash,
                "old_realized_pnl": old_realized,
                "trades_deleted": trades_deleted,
            },
        )
    return {
        "ok": True,
        "portfolio_id": str(portfolio_id),
        "name": port.get("name"),
        "old_cash": old_cash,
        "new_cash": target,
        "voided_positions": dropped,
        "trades_deleted": trades_deleted,
        "old_realized_pnl": old_realized,
    }
