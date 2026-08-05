"""Repository for Decision Intelligence attributions — ``decision.attributions`` (DI.Attr)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

_COLS = (
    "id, created_at, decision_id, symbol, portfolio_key, trigger, checkpoint, "
    "grades, payload, payload_version"
)


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


class DecisionAttributionRepository(BaseRepository):
    def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.fetch_one(
            f"""
            INSERT INTO decision.attributions (
                id, decision_id, symbol, portfolio_key, trigger, checkpoint,
                grades, payload, payload_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COLS}
            """,
            (
                str(row["id"]),
                str(row["decision_id"]) if row.get("decision_id") else None,
                row["symbol"],
                row["portfolio_key"],
                row.get("trigger") or "exit",
                row.get("checkpoint"),
                Jsonb(_json_safe(row.get("grades") or {})),
                Jsonb(_json_safe(row.get("payload") or {})),
                row.get("payload_version") or "di.attr.1",
            ),
        )

    def get(self, attribution_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_COLS} FROM decision.attributions WHERE id = %s",
            (str(attribution_id),),
        )

    def list_for_decision(
        self, *, decision_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM decision.attributions
            WHERE decision_id = %s
            ORDER BY created_at DESC LIMIT %s
            """,
            (str(decision_id), limit),
        )

    def latest_for_decision(self, decision_id: str) -> dict[str, Any] | None:
        rows = self.list_for_decision(decision_id=decision_id, limit=1)
        return rows[0] if rows else None

    def list_portfolio(
        self, *, portfolio_key: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM decision.attributions
            WHERE portfolio_key = %s
            ORDER BY created_at DESC LIMIT %s
            """,
            (portfolio_key, limit),
        )
