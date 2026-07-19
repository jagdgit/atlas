"""Repository for the virtual (simulation-only) trading portfolio — ``sim.*`` (Phase D · §D.6, P10).

Portfolios (cash + realized P&L), current positions (one row per open symbol), and an append-only
trade blotter where every fill links back to the ``decision.decisions`` row that caused it (P9).
Simulation only: no real broker, no real money (P10). Repositories are the only layer with SQL
(ADR-0027).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from atlas.repositories.base import BaseRepository

_PORTFOLIO_COLS = (
    "id, mission_id, name, base_currency, starting_cash, cash, realized_pnl, metadata, "
    "created_at, updated_at"
)
_POSITION_COLS = "id, portfolio_id, symbol, quantity, avg_price, updated_at"
_TRADE_COLS = (
    "id, portfolio_id, mission_id, decision_id, symbol, side, quantity, price, fee, "
    "cash_after, realized_pnl, created_at"
)


class SimTradingRepository(BaseRepository):
    # --- portfolios -----------------------------------------------------
    def ensure_portfolio(
        self,
        *,
        mission_id: UUID | str | None,
        name: str = "default",
        base_currency: str = "USD",
        starting_cash: float = 0.0,
    ) -> dict[str, Any]:
        """Get-or-create the (mission, name) portfolio, seeding cash on first creation."""
        existing = self.fetch_one(
            f"SELECT {_PORTFOLIO_COLS} FROM sim.portfolios "
            "WHERE mission_id IS NOT DISTINCT FROM %s AND name = %s",
            (str(mission_id) if mission_id else None, name),
        )
        if existing is not None:
            return existing
        return self.fetch_one(
            f"""
            INSERT INTO sim.portfolios (mission_id, name, base_currency, starting_cash, cash)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {_PORTFOLIO_COLS}
            """,
            (
                str(mission_id) if mission_id else None,
                name,
                base_currency,
                float(starting_cash),
                float(starting_cash),
            ),
        )

    def get_portfolio(self, portfolio_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_PORTFOLIO_COLS} FROM sim.portfolios WHERE id = %s", (str(portfolio_id),)
        )

    def update_portfolio_cash(
        self, portfolio_id: UUID | str, *, cash: float, realized_pnl_delta: float = 0.0
    ) -> dict[str, Any] | None:
        return self.fetch_one(
            f"""
            UPDATE sim.portfolios
               SET cash = %s, realized_pnl = realized_pnl + %s, updated_at = now()
             WHERE id = %s
            RETURNING {_PORTFOLIO_COLS}
            """,
            (float(cash), float(realized_pnl_delta), str(portfolio_id)),
        )

    # --- positions ------------------------------------------------------
    def get_position(self, portfolio_id: UUID | str, symbol: str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_POSITION_COLS} FROM sim.positions WHERE portfolio_id = %s AND symbol = %s",
            (str(portfolio_id), symbol),
        )

    def list_positions(self, portfolio_id: UUID | str) -> list[dict[str, Any]]:
        return self.fetch_all(
            f"SELECT {_POSITION_COLS} FROM sim.positions WHERE portfolio_id = %s ORDER BY symbol",
            (str(portfolio_id),),
        )

    def upsert_position(
        self, portfolio_id: UUID | str, symbol: str, *, quantity: float, avg_price: float
    ) -> dict[str, Any]:
        return self.fetch_one(
            f"""
            INSERT INTO sim.positions (portfolio_id, symbol, quantity, avg_price)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (portfolio_id, symbol)
            DO UPDATE SET quantity = EXCLUDED.quantity, avg_price = EXCLUDED.avg_price,
                          updated_at = now()
            RETURNING {_POSITION_COLS}
            """,
            (str(portfolio_id), symbol, float(quantity), float(avg_price)),
        )

    def delete_position(self, portfolio_id: UUID | str, symbol: str) -> int:
        return self.execute(
            "DELETE FROM sim.positions WHERE portfolio_id = %s AND symbol = %s",
            (str(portfolio_id), symbol),
        )

    # --- trades ---------------------------------------------------------
    def record_trade(
        self,
        *,
        portfolio_id: UUID | str,
        mission_id: UUID | str | None,
        decision_id: UUID | str | None,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        cash_after: float,
        realized_pnl: float,
    ) -> dict[str, Any]:
        return self.fetch_one(
            f"""
            INSERT INTO sim.trades
                (portfolio_id, mission_id, decision_id, symbol, side, quantity, price, fee,
                 cash_after, realized_pnl)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_TRADE_COLS}
            """,
            (
                str(portfolio_id),
                str(mission_id) if mission_id else None,
                str(decision_id) if decision_id else None,
                symbol,
                side,
                float(quantity),
                float(price),
                float(fee),
                float(cash_after),
                float(realized_pnl),
            ),
        )

    def list_trades(
        self, portfolio_id: UUID | str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            f"SELECT {_TRADE_COLS} FROM sim.trades WHERE portfolio_id = %s "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (str(portfolio_id), limit),
        )

    def count_trades(self, portfolio_id: UUID | str) -> int:
        return int(
            self.fetch_val(
                "SELECT count(*) FROM sim.trades WHERE portfolio_id = %s", (str(portfolio_id),)
            )
            or 0
        )
