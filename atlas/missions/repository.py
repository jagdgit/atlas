"""Repository for ``mission.missions`` / ``mission.journal`` (Phase A · §A.1).

The only SQL layer for mission state (ADR-0027); returns typed models (ADR-0036).
Lifecycle *logic* (valid transitions, journaling, events) lives in ``MissionService``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.mission import Mission, MissionJournalEntry
from atlas.repositories.base import BaseRepository

_MISSION_COLS = (
    "id, title, objective, status, success_criteria, knowledge_domains, "
    "active_config_id, scheduling_policy, priority, criticality, budget, "
    "deadline, importance, labels, metadata, template_id, template_version, "
    "created_at, updated_at"
)
_JOURNAL_COLS = "id, mission_id, action, reason, refs, ts"


class MissionRepository(BaseRepository):
    # --- missions -------------------------------------------------------
    def create(
        self,
        *,
        title: str,
        objective: str = "",
        scheduling_policy: str,
        priority: int,
        criticality: str,
        budget: dict[str, Any] | None = None,
        deadline: Any | None = None,
        importance: str | None = None,
        labels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        knowledge_domains: list[str] | None = None,
        success_criteria: dict[str, Any] | None = None,
        template_id: str | None = None,
        template_version: int | None = None,
        status: str = "draft",
    ) -> Mission:
        row = self.fetch_one(
            f"""
            INSERT INTO mission.missions (
                title, objective, status, success_criteria, knowledge_domains,
                scheduling_policy, priority, criticality, budget, deadline, importance,
                labels, metadata, template_id, template_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_MISSION_COLS}
            """,
            (
                title,
                objective,
                status,
                Jsonb(success_criteria or {}),
                list(knowledge_domains or []),
                scheduling_policy,
                priority,
                criticality,
                Jsonb(budget or {}),
                deadline,
                importance,
                list(labels or []),
                Jsonb(metadata or {}),
                template_id,
                template_version,
            ),
        )
        return Mission.from_row(row)

    def get(self, mission_id: UUID | str) -> Mission | None:
        row = self.fetch_one(
            f"SELECT {_MISSION_COLS} FROM mission.missions WHERE id = %s",
            (str(mission_id),),
        )
        return Mission.from_row(row) if row else None

    def list(
        self,
        *,
        status: str | None = None,
        label: str | None = None,
        limit: int = 100,
    ) -> list[Mission]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if label is not None:
            clauses.append("labels @> ARRAY[%s]::text[]")
            params.append(label)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.fetch_all(
            f"""
            SELECT {_MISSION_COLS} FROM mission.missions
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return Mission.from_rows(rows)

    def set_status(self, mission_id: UUID | str, status: str) -> bool:
        return (
            self.execute(
                """
                UPDATE mission.missions
                SET status = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, str(mission_id)),
            )
            > 0
        )

    def set_active_config(self, mission_id: UUID | str, config_id: str) -> bool:
        return (
            self.execute(
                """
                UPDATE mission.missions
                SET active_config_id = %s, updated_at = now()
                WHERE id = %s
                """,
                (config_id, str(mission_id)),
            )
            > 0
        )

    def update_arbitration(
        self,
        mission_id: UUID | str,
        *,
        scheduling_policy: str | None = None,
        priority: int | None = None,
        criticality: str | None = None,
        budget: dict[str, Any] | None = None,
    ) -> bool:
        return (
            self.execute(
                """
                UPDATE mission.missions
                SET scheduling_policy = COALESCE(%s, scheduling_policy),
                    priority = COALESCE(%s, priority),
                    criticality = COALESCE(%s, criticality),
                    budget = COALESCE(%s, budget),
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    scheduling_policy,
                    priority,
                    criticality,
                    Jsonb(budget) if budget is not None else None,
                    str(mission_id),
                ),
            )
            > 0
        )

    # --- journal --------------------------------------------------------
    def add_journal(
        self,
        mission_id: UUID | str,
        action: str,
        reason: str = "",
        refs: dict[str, Any] | None = None,
    ) -> MissionJournalEntry:
        row = self.fetch_one(
            f"""
            INSERT INTO mission.journal (mission_id, action, reason, refs)
            VALUES (%s, %s, %s, %s)
            RETURNING {_JOURNAL_COLS}
            """,
            (str(mission_id), action, reason, Jsonb(refs or {})),
        )
        return MissionJournalEntry.from_row(row)

    def list_journal(
        self, mission_id: UUID | str, *, limit: int = 100
    ) -> list[MissionJournalEntry]:
        rows = self.fetch_all(
            f"""
            SELECT {_JOURNAL_COLS} FROM mission.journal
            WHERE mission_id = %s
            ORDER BY ts DESC
            LIMIT %s
            """,
            (str(mission_id), limit),
        )
        return MissionJournalEntry.from_rows(rows)

    # --- owned jobs (provenance aggregation, Q2) ------------------------
    def list_job_ids(self, mission_id: UUID | str) -> list[str]:
        rows = self.fetch_all(
            "SELECT id FROM job.jobs WHERE mission_id = %s ORDER BY created_at DESC",
            (str(mission_id),),
        )
        return [str(r["id"]) for r in rows]
