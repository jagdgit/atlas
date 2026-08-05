"""Repository for Decision Intelligence timeline + revisits (DI.2).

Append-only timeline events. Revisit rows may flip ``pending`` → ``done|skipped``
(status only — never rewrite packet belief).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

_EVENT_COLS = (
    "id, created_at, symbol, kind, decision_id, payload, payload_version"
)
_REVISIT_COLS = (
    "id, created_at, decision_id, symbol, portfolio_key, checkpoint, due_ist, "
    "status, completed_at, timeline_event_id, payload, payload_version"
)

TIMELINE_KINDS = frozenset(
    {
        "observation",
        "fundamentals_update",
        "research_refresh",
        "thesis_change",
        "decision",
        "revisit",
        "market_mark",
        "outcome",
        "lesson",
    }
)
CHECKPOINTS = frozenset({"day1", "week1", "month1", "quarter", "exit"})


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


class DecisionTimelineRepository(BaseRepository):
    def insert_event(self, row: dict[str, Any]) -> dict[str, Any]:
        kind = str(row.get("kind") or "")
        if kind not in TIMELINE_KINDS:
            raise ValueError(f"invalid timeline kind {kind!r}")
        return self.fetch_one(
            f"""
            INSERT INTO decision.timeline_events (
                id, symbol, kind, decision_id, payload, payload_version
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {_EVENT_COLS}
            """,
            (
                str(row["id"]),
                row["symbol"],
                kind,
                str(row["decision_id"]) if row.get("decision_id") else None,
                Jsonb(_json_safe(row.get("payload") or {})),
                row.get("payload_version") or "di.timeline.1",
            ),
        )

    def list_symbol(
        self, *, symbol: str, limit: int = 100, kind: str | None = None
    ) -> list[dict[str, Any]]:
        if kind:
            return self.fetch_all(
                f"""
                SELECT {_EVENT_COLS} FROM decision.timeline_events
                WHERE symbol = %s AND kind = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (symbol, kind, limit),
            )
        return self.fetch_all(
            f"""
            SELECT {_EVENT_COLS} FROM decision.timeline_events
            WHERE symbol = %s
            ORDER BY created_at DESC LIMIT %s
            """,
            (symbol, limit),
        )

    def list_for_decision(
        self, *, decision_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            f"""
            SELECT {_EVENT_COLS} FROM decision.timeline_events
            WHERE decision_id = %s
            ORDER BY created_at ASC LIMIT %s
            """,
            (str(decision_id), limit),
        )

    def insert_revisit(self, row: dict[str, Any]) -> dict[str, Any] | None:
        checkpoint = str(row.get("checkpoint") or "")
        if checkpoint not in CHECKPOINTS:
            raise ValueError(f"invalid checkpoint {checkpoint!r}")
        return self.fetch_one(
            f"""
            INSERT INTO decision.revisits (
                id, decision_id, symbol, portfolio_key, checkpoint, due_ist,
                status, payload, payload_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (decision_id, checkpoint) DO NOTHING
            RETURNING {_REVISIT_COLS}
            """,
            (
                str(row["id"]),
                str(row["decision_id"]) if row.get("decision_id") else None,
                row["symbol"],
                row["portfolio_key"],
                checkpoint,
                row["due_ist"],
                row.get("status") or "pending",
                Jsonb(_json_safe(row.get("payload") or {})),
                row.get("payload_version") or "di.revisit.1",
            ),
        )

    def list_due(
        self,
        *,
        as_of_ist: str,
        portfolio_key: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        if portfolio_key:
            return self.fetch_all(
                f"""
                SELECT {_REVISIT_COLS} FROM decision.revisits
                WHERE status = 'pending' AND due_ist <= %s AND portfolio_key = %s
                ORDER BY due_ist ASC LIMIT %s
                """,
                (as_of_ist, portfolio_key, limit),
            )
        return self.fetch_all(
            f"""
            SELECT {_REVISIT_COLS} FROM decision.revisits
            WHERE status = 'pending' AND due_ist <= %s
            ORDER BY due_ist ASC LIMIT %s
            """,
            (as_of_ist, limit),
        )

    def complete_revisit(
        self,
        revisit_id: str,
        *,
        status: str = "done",
        timeline_event_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if status not in {"done", "skipped"}:
            raise ValueError(f"invalid revisit status {status!r}")
        merge = Jsonb(_json_safe(payload or {}))
        return self.fetch_one(
            f"""
            UPDATE decision.revisits
            SET status = %s,
                completed_at = now(),
                timeline_event_id = COALESCE(%s, timeline_event_id),
                payload = payload || %s
            WHERE id = %s AND status = 'pending'
            RETURNING {_REVISIT_COLS}
            """,
            (
                status,
                str(timeline_event_id) if timeline_event_id else None,
                merge,
                str(revisit_id),
            ),
        )

    def counts(self, *, portfolio_key: str | None = None) -> dict[str, int]:
        if portfolio_key:
            rows = self.fetch_all(
                """
                SELECT status, COUNT(*)::int AS n
                FROM decision.revisits
                WHERE portfolio_key = %s
                GROUP BY status
                """,
                (portfolio_key,),
            )
        else:
            rows = self.fetch_all(
                """
                SELECT status, COUNT(*)::int AS n
                FROM decision.revisits
                GROUP BY status
                """
            )
        out = {"pending": 0, "done": 0, "skipped": 0}
        for r in rows:
            key = str(r.get("status") or "")
            if key in out:
                out[key] = int(r.get("n") or 0)
        return out
