#!/usr/bin/env python3
"""Void invalid daily-bar fills on the India Intraday lab and restore starting cash.

Those 18 Aug cash-equity buys were not true intraday (Yahoo 1d). L5 switches the
lab to 5-minute bars; this script flattens the book so the next session starts
from the original cash, not leftover invalid holdings.

Does not touch india_equity_learner or india_fno_learner.
"""

from __future__ import annotations

import json
import sys

from atlas.config import get_config
from atlas.database.connection import DatabaseManager
from atlas.investment.lab_book_reset import void_book_to_starting_cash
from atlas.investment.portfolios import sync_live_cash
from atlas.repositories.sim_repo import SimTradingRepository

LAB = "equity_intraday_learner"
NOTE = (
    "L5 operator void: 18 Aug fills used daily Yahoo bars, not 5m. "
    "Positions dropped; cash restored to starting_cash. Not a market sell."
)


def main() -> int:
    dry = "--apply" not in sys.argv
    db = DatabaseManager(get_config().database)
    repo = SimTradingRepository(db)
    rows = repo.fetch_all(
        "SELECT id, name, mission_id, starting_cash, cash, realized_pnl "
        "FROM sim.portfolios WHERE name = %s",
        (LAB,),
    )
    if not rows:
        print(f"no sim.portfolios row named {LAB}")
        return 1
    for row in rows:
        positions = repo.list_positions(row["id"])
        trades_n = repo.count_trades(row["id"])
        print(
            json.dumps(
                {
                    "id": str(row["id"]),
                    "cash": row["cash"],
                    "starting_cash": row["starting_cash"],
                    "realized_pnl": row["realized_pnl"],
                    "positions": [
                        {
                            "symbol": p.get("symbol"),
                            "qty": p.get("quantity"),
                            "avg": p.get("avg_price"),
                        }
                        for p in positions
                    ],
                    "trade_count": trades_n,
                    "dry_run": dry,
                },
                default=str,
            )
        )
        if dry:
            continue
        out = void_book_to_starting_cash(
            repo,
            row["id"],
            restore_cash=float(row["starting_cash"] or 50_000),
            wipe_trades=True,
            note=NOTE,
            mission_id=str(row["mission_id"]) if row.get("mission_id") else None,
        )
        try:
            sync_live_cash(
                LAB,
                float(out["new_cash"]),
                mission_id=str(row["mission_id"]) if row.get("mission_id") else None,
            )
        except Exception as exc:  # noqa: BLE001
            print("registry sync skipped:", exc)
        print("applied", json.dumps(out, default=str))
    if dry:
        print("dry-run only — re-run with --apply to restore cash and drop positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
