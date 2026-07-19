"""Repository for the decision approval gate — ``decision.approvals`` (Phase D · §D.3, P14).

One row per side-effecting decision awaiting the operator, mutated through its lifecycle
(proposed → approved → applied → reverted, or → rejected). Every transition is emitted to
``audit.events`` by the service; before/after snapshots are stored so an applied action can be reverted.
Repositories are the only layer with SQL (ADR-0027).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

STATUSES = ("proposed", "approved", "rejected", "applied", "reverted")

_COLS = (
    "id, decision_id, mission_id, mission_type, action, status, note, requested_by, requested_at, "
    "decided_by, decided_at, applied_at, before, after, updated_at"
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class ApprovalRepository(BaseRepository):
    def create(
        self,
        *,
        decision_id: UUID | str | None,
        mission_id: UUID | str | None,
        mission_type: str,
        action: dict[str, Any],
        requested_by: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            f"""
            INSERT INTO decision.approvals
                (decision_id, mission_id, mission_type, action, requested_by, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {_COLS}
            """,
            (
                str(decision_id) if decision_id else None,
                str(mission_id) if mission_id else None,
                mission_type,
                Jsonb(_json_safe(action or {})),
                requested_by,
                note,
            ),
        )

    def get(self, approval_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_COLS} FROM decision.approvals WHERE id = %s", (str(approval_id),)
        )

    def list(
        self,
        *,
        status: str | None = None,
        mission_id: UUID | str | None = None,
        mission_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if mission_id is not None:
            clauses.append("mission_id = %s")
            params.append(str(mission_id))
        if mission_type is not None:
            clauses.append("mission_type = %s")
            params.append(mission_type)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self.fetch_all(
            f"SELECT {_COLS} FROM decision.approvals {where} ORDER BY requested_at DESC LIMIT %s",
            tuple(params),
        )

    def transition(
        self,
        approval_id: UUID | str,
        status: str,
        *,
        actor: str | None = None,
        note: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> dict[str, Any] | None:
        """Move a row to ``status``, stamping the right who/when and optional before/after snapshots."""
        if status not in STATUSES:
            raise ValueError(f"invalid approval status: {status}")
        sets = ["status = %s", "updated_at = now()"]
        params: list[Any] = [status]
        if actor is not None:
            sets.append("decided_by = %s")
            params.append(actor)
        if note is not None:
            sets.append("note = %s")
            params.append(note)
        if status in ("approved", "rejected"):
            sets.append("decided_at = now()")
        if status == "applied":
            sets.append("applied_at = now()")
        if before is not None:
            sets.append("before = %s")
            params.append(Jsonb(_json_safe(before)))
        if after is not None:
            sets.append("after = %s")
            params.append(Jsonb(_json_safe(after)))
        params.append(str(approval_id))
        return self.fetch_one(
            f"UPDATE decision.approvals SET {', '.join(sets)} WHERE id = %s RETURNING {_COLS}",
            tuple(params),
        )

    def count(self) -> int:
        return int(self.fetch_val("SELECT count(*) FROM decision.approvals") or 0)
