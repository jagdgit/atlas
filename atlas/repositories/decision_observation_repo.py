"""Repository for Decision Intelligence observations — ``decision.observations`` (DI.Obs).

Append-only. SQL only (ADR-0027).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

_COLS = (
    "id, created_at, symbol, kind, payload, source, confidence, expires_at, payload_version"
)

OBSERVATION_KINDS = frozenset(
    {
        "mgmt_event",
        "operating_metric",
        "macro_event",
        "policy_event",
        "market_event",
        "filing_event",
        "news_event",
    }
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


class DecisionObservationRepository(BaseRepository):
    def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        kind = str(row.get("kind") or "")
        if kind not in OBSERVATION_KINDS:
            raise ValueError(f"invalid observation kind {kind!r}")
        return self.fetch_one(
            f"""
            INSERT INTO decision.observations (
                id, symbol, kind, payload, source, confidence, expires_at, payload_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COLS}
            """,
            (
                str(row["id"]),
                row.get("symbol"),
                kind,
                Jsonb(_json_safe(row.get("payload") or {})),
                row.get("source"),
                row.get("confidence"),
                row.get("expires_at"),
                row.get("payload_version") or "di.obs.1",
            ),
        )

    def get(self, observation_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_COLS} FROM decision.observations WHERE id = %s",
            (str(observation_id),),
        )

    def list_symbol(
        self,
        *,
        symbol: str,
        limit: int = 40,
        kind: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["symbol = %s"]
        params: list[Any] = [symbol]
        if kind:
            clauses.append("kind = %s")
            params.append(kind)
        if since is not None:
            clauses.append("created_at >= %s")
            params.append(since)
        params.append(limit)
        where = " AND ".join(clauses)
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM decision.observations
            WHERE {where}
            ORDER BY created_at DESC LIMIT %s
            """,
            tuple(params),
        )

    def list_since(
        self,
        *,
        since: datetime,
        limit: int = 100,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        if symbol:
            return self.list_symbol(symbol=symbol, limit=limit, since=since)
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM decision.observations
            WHERE created_at >= %s
            ORDER BY created_at DESC LIMIT %s
            """,
            (since, limit),
        )

    def list_recent(self, *, limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            return self.fetch_all(
                f"""
                SELECT {_COLS} FROM decision.observations
                WHERE kind = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (kind, limit),
            )
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM decision.observations
            ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        )
