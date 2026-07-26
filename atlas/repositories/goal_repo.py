"""Repository for durable Goals — ``system.goals`` (OX.3).

Objectives first; Program / Portfolio are optional links, not the Goal's identity.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

GOAL_STATUSES = ("active", "paused", "completed", "archived")

_COLS = (
    "id, title, objective, status, success_criteria, program_id, portfolio_key, "
    "portfolio_id, progress, metadata, created_at, updated_at"
)


class GoalRepository(BaseRepository):
    def create(
        self,
        *,
        title: str,
        objective: dict[str, Any] | None = None,
        status: str = "active",
        success_criteria: dict[str, Any] | None = None,
        program_id: str | None = None,
        portfolio_key: str | None = None,
        portfolio_id: str | None = None,
        progress: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        status = (status or "active").strip().lower()
        if status not in GOAL_STATUSES:
            raise ValueError(f"invalid goal status: {status}")
        return self.fetch_one(
            f"""
            INSERT INTO system.goals (
                title, objective, status, success_criteria,
                program_id, portfolio_key, portfolio_id, progress, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COLS}
            """,
            (
                title.strip(),
                Jsonb(objective or {"text": title.strip()}),
                status,
                Jsonb(success_criteria) if success_criteria is not None else None,
                program_id,
                portfolio_key,
                portfolio_id,
                Jsonb(progress or {}),
                Jsonb(metadata or {}),
            ),
        )

    def get(self, goal_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_COLS} FROM system.goals WHERE id = %s", (str(goal_id),)
        )

    def list(
        self,
        *,
        status: str | None = None,
        program_id: str | None = None,
        portfolio_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if program_id:
            clauses.append("program_id = %s")
            params.append(program_id)
        if portfolio_key:
            clauses.append("portfolio_key = %s")
            params.append(portfolio_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 200)))
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM system.goals
            {where}
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Resolve goals by objective/title text (not only portfolio name)."""
        q = (query or "").strip()
        if not q:
            return []
        like = f"%{q}%"
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM system.goals
            WHERE status <> 'archived'
              AND (
                    title ILIKE %s
                 OR coalesce(objective->>'text', '') ILIKE %s
                 OR coalesce(objective->>'intent', '') ILIKE %s
                 OR coalesce(success_criteria->>'text', '') ILIKE %s
              )
            ORDER BY
              CASE WHEN status = 'active' THEN 0 ELSE 1 END,
              updated_at DESC
            LIMIT %s
            """,
            (like, like, like, like, max(1, min(int(limit), 50))),
        )

    def update(
        self,
        goal_id: UUID | str,
        *,
        title: str | None = None,
        objective: dict[str, Any] | None = None,
        status: str | None = None,
        success_criteria: dict[str, Any] | None = None,
        program_id: str | None = None,
        portfolio_key: str | None = None,
        portfolio_id: str | None = None,
        progress: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        clear_success_criteria: bool = False,
    ) -> dict[str, Any] | None:
        row = self.get(goal_id)
        if row is None:
            return None
        if status is not None:
            status = status.strip().lower()
            if status not in GOAL_STATUSES:
                raise ValueError(f"invalid goal status: {status}")
        new_criteria = row.get("success_criteria")
        if clear_success_criteria:
            new_criteria = None
        elif success_criteria is not None:
            new_criteria = success_criteria
        return self.fetch_one(
            f"""
            UPDATE system.goals SET
                title = %s,
                objective = %s,
                status = %s,
                success_criteria = %s,
                program_id = %s,
                portfolio_key = %s,
                portfolio_id = %s,
                progress = %s,
                metadata = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING {_COLS}
            """,
            (
                title if title is not None else row["title"],
                Jsonb(objective if objective is not None else (row.get("objective") or {})),
                status if status is not None else row["status"],
                Jsonb(new_criteria) if new_criteria is not None else None,
                program_id if program_id is not None else row.get("program_id"),
                portfolio_key if portfolio_key is not None else row.get("portfolio_key"),
                portfolio_id if portfolio_id is not None else row.get("portfolio_id"),
                Jsonb(progress if progress is not None else (row.get("progress") or {})),
                Jsonb(metadata if metadata is not None else (row.get("metadata") or {})),
                str(goal_id),
            ),
        )

    def link(
        self,
        goal_id: UUID | str,
        *,
        program_id: str | None = None,
        portfolio_key: str | None = None,
        portfolio_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self.update(
            goal_id,
            program_id=program_id,
            portfolio_key=portfolio_key,
            portfolio_id=portfolio_id,
        )


class InMemoryGoalRepository:
    """Hermetic stand-in for unit tests (same surface as GoalRepository)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: dict[str, dict[str, Any]] = {}

    def create(self, *, title: str, objective=None, status="active",
               success_criteria=None, program_id=None, portfolio_key=None,
               portfolio_id=None, progress=None, metadata=None) -> dict[str, Any]:
        status = (status or "active").strip().lower()
        if status not in GOAL_STATUSES:
            raise ValueError(f"invalid goal status: {status}")
        gid = str(uuid.uuid4())
        now = time.time()
        row = {
            "id": gid,
            "title": title.strip(),
            "objective": objective or {"text": title.strip()},
            "status": status,
            "success_criteria": success_criteria,
            "program_id": program_id,
            "portfolio_key": portfolio_key,
            "portfolio_id": portfolio_id,
            "progress": progress or {},
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._rows[gid] = row
            return dict(row)

    def get(self, goal_id: UUID | str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(str(goal_id))
            return dict(row) if row else None

    def list(self, *, status=None, program_id=None, portfolio_key=None, limit=50):
        with self._lock:
            rows = [dict(r) for r in self._rows.values()]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if program_id:
            rows = [r for r in rows if r.get("program_id") == program_id]
        if portfolio_key:
            rows = [r for r in rows if r.get("portfolio_key") == portfolio_key]
        rows.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
        return rows[: max(1, min(int(limit), 200))]

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        with self._lock:
            rows = [dict(r) for r in self._rows.values()]
        out = []
        for r in rows:
            if r.get("status") == "archived":
                continue
            obj = r.get("objective") or {}
            crit = r.get("success_criteria") or {}
            blob = " ".join(
                [
                    str(r.get("title") or ""),
                    str(obj.get("text") or ""),
                    str(obj.get("intent") or ""),
                    str(crit.get("text") or "") if isinstance(crit, dict) else "",
                ]
            ).lower()
            if q in blob:
                out.append(r)
        out.sort(
            key=lambda r: (
                0 if r.get("status") == "active" else 1,
                -float(r.get("updated_at") or 0),
            )
        )
        return out[: max(1, min(int(limit), 50))]

    def update(self, goal_id, *, title=None, objective=None, status=None,
               success_criteria=None, program_id=None, portfolio_key=None,
               portfolio_id=None, progress=None, metadata=None,
               clear_success_criteria=False):
        with self._lock:
            row = self._rows.get(str(goal_id))
            if row is None:
                return None
            if status is not None:
                status = status.strip().lower()
                if status not in GOAL_STATUSES:
                    raise ValueError(f"invalid goal status: {status}")
                row["status"] = status
            if title is not None:
                row["title"] = title
            if objective is not None:
                row["objective"] = objective
            if clear_success_criteria:
                row["success_criteria"] = None
            elif success_criteria is not None:
                row["success_criteria"] = success_criteria
            if program_id is not None:
                row["program_id"] = program_id
            if portfolio_key is not None:
                row["portfolio_key"] = portfolio_key
            if portfolio_id is not None:
                row["portfolio_id"] = portfolio_id
            if progress is not None:
                row["progress"] = progress
            if metadata is not None:
                row["metadata"] = metadata
            row["updated_at"] = time.time()
            return dict(row)

    def link(self, goal_id, *, program_id=None, portfolio_key=None, portfolio_id=None):
        return self.update(
            goal_id,
            program_id=program_id,
            portfolio_key=portfolio_key,
            portfolio_id=portfolio_id,
        )
