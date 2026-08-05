"""Repository for Decision Intelligence packets — ``decision.packets`` (DI.1).

Append-only. No UPDATE/DELETE methods — corrections are new packets.
SQL only lives here (ADR-0027).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

_COLS = (
    "decision_id, created_at, ts_ist, symbol, action, portfolio_key, mission_id, "
    "strategy_tag, setup_tag, parent_decision_id, prior_thesis_id, engine_decision_id, "
    "fill_trade_id, payload, payload_version"
)

ALLOWED_ACTIONS = frozenset({"buy", "sell", "hold", "watch", "reduce"})


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class DecisionPacketRepository(BaseRepository):
    """Postgres authoritative store for frozen Decision Packets."""

    def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        action = str(row.get("action") or "")
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"invalid packet action {action!r}")
        return self.fetch_one(
            f"""
            INSERT INTO decision.packets (
                decision_id, ts_ist, symbol, action, portfolio_key, mission_id,
                strategy_tag, setup_tag, parent_decision_id, prior_thesis_id,
                engine_decision_id, fill_trade_id, payload, payload_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            RETURNING {_COLS}
            """,
            (
                str(row["decision_id"]),
                row["ts_ist"],
                row["symbol"],
                action,
                row["portfolio_key"],
                row.get("mission_id"),
                row["strategy_tag"],
                row.get("setup_tag"),
                str(row["parent_decision_id"]) if row.get("parent_decision_id") else None,
                row.get("prior_thesis_id"),
                row.get("engine_decision_id"),
                row.get("fill_trade_id"),
                Jsonb(_json_safe(row["payload"])),
                row.get("payload_version") or "di.packet.1",
            ),
        )

    def get(self, decision_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_COLS} FROM decision.packets WHERE decision_id = %s",
            (str(decision_id),),
        )

    def list_day(
        self,
        *,
        portfolio_key: str,
        ts_ist: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM decision.packets
            WHERE portfolio_key = %s AND ts_ist = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (portfolio_key, ts_ist, limit),
        )

    def list_symbol(
        self,
        *,
        symbol: str,
        limit: int = 20,
        portfolio_key: str | None = None,
    ) -> list[dict[str, Any]]:
        if portfolio_key:
            return self.fetch_all(
                f"""
                SELECT {_COLS} FROM decision.packets
                WHERE symbol = %s AND portfolio_key = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (symbol, portfolio_key, limit),
            )
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM decision.packets
            WHERE symbol = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (symbol, limit),
        )

    def list_day_strategy_symbols(
        self,
        *,
        portfolio_key: str,
        ts_ist: str,
        strategy_tag: str,
    ) -> set[str]:
        rows = self.fetch_all(
            """
            SELECT DISTINCT symbol FROM decision.packets
            WHERE portfolio_key = %s AND ts_ist = %s AND strategy_tag = %s
            """,
            (portfolio_key, ts_ist, strategy_tag),
        )
        return {str(r["symbol"]) for r in rows if r.get("symbol")}
