"""Repository for ``learning.events`` / ``learning.experiences`` (S18b, D11/§5d).

The only SQL layer for the Learning Pipeline. Returns typed models (ADR-0036).
Governance/promotion *logic* (propose → apply → revert, policy defaults, observing
completed jobs) lives in ``LearningService``; this layer persists state atomically.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.models.learning import ComponentObservation, Experience, LearningEvent
from atlas.repositories.base import BaseRepository

_EVENT_COLS = (
    "id, source_type, source_id, store, policy, level, status, summary, reason, "
    "origin, project, ref_id, metadata, created_at, updated_at, reviewed_at"
)
_EXP_COLS = (
    "id, title, problem, diagnosis, actions, mistakes, solution, lessons, tags, "
    "source_job_id, policy, status, payload, bias_enabled, created_at, updated_at"
)
_COMP_COLS = (
    "id, component_key, component_version, corpus, profile, metrics, "
    "source_job_id, experience_id, event_id, created_at"
)


class LearningRepository(BaseRepository):
    # --- events ---------------------------------------------------------
    def record_event(
        self,
        source_type: str,
        store: str,
        *,
        source_id: str | None = None,
        policy: str = "temporary",
        level: int = 1,
        status: str = "proposed",
        summary: str = "",
        reason: str = "",
        origin: str = "",
        project: str | None = None,
        ref_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LearningEvent:
        row = self.fetch_one(
            f"""
            INSERT INTO learning.events
                (source_type, source_id, store, policy, level, status, summary,
                 reason, origin, project, ref_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_EVENT_COLS}
            """,
            (
                source_type, source_id, store, policy, level, status, summary,
                reason, origin, project, ref_id, Jsonb(metadata or {}),
            ),
        )
        return LearningEvent.from_row(row)

    def get_event(self, event_id: UUID | str) -> LearningEvent | None:
        row = self.fetch_one(
            f"SELECT {_EVENT_COLS} FROM learning.events WHERE id = %s", (str(event_id),)
        )
        return LearningEvent.from_row(row) if row else None

    def list_events(
        self,
        *,
        status: str | None = None,
        store: str | None = None,
        limit: int = 50,
    ) -> list[LearningEvent]:
        clauses, params = [], []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if store:
            clauses.append("store = %s")
            params.append(store)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.fetch_all(
            f"SELECT {_EVENT_COLS} FROM learning.events {where} "
            f"ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
        return LearningEvent.from_rows(rows)

    def set_event_status(
        self,
        event_id: UUID | str,
        status: str,
        *,
        policy: str | None = None,
        level: int | None = None,
        ref_id: str | None = None,
        reviewed: bool = True,
    ) -> bool:
        return (
            self.execute(
                """
                UPDATE learning.events
                SET status = %s,
                    policy = COALESCE(%s, policy),
                    level = COALESCE(%s, level),
                    ref_id = COALESCE(%s, ref_id),
                    reviewed_at = CASE WHEN %s THEN now() ELSE reviewed_at END,
                    updated_at = now()
                WHERE id = %s
                """,
                (status, policy, level, ref_id, reviewed, str(event_id)),
            )
            > 0
        )

    def count_events(self, *, status: str | None = None) -> int:
        if status:
            return (
                self.fetch_val(
                    "SELECT count(*) FROM learning.events WHERE status = %s", (status,)
                )
                or 0
            )
        return self.fetch_val("SELECT count(*) FROM learning.events") or 0

    # --- experiences ----------------------------------------------------
    def add_experience(
        self,
        *,
        title: str = "",
        problem: str = "",
        diagnosis: str = "",
        actions: list[Any] | None = None,
        mistakes: str = "",
        solution: str = "",
        lessons: str = "",
        tags: list[str] | None = None,
        source_job_id: str | None = None,
        policy: str = "temporary",
        payload: dict[str, Any] | None = None,
        bias_enabled: bool = False,
    ) -> Experience:
        row = self.fetch_one(
            f"""
            INSERT INTO learning.experiences
                (title, problem, diagnosis, actions, mistakes, solution, lessons,
                 tags, source_job_id, policy, payload, bias_enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_EXP_COLS}
            """,
            (
                title, problem, diagnosis, Jsonb(actions or []), mistakes, solution,
                lessons, Jsonb(tags or []), source_job_id, policy,
                Jsonb(payload or {}), bool(bias_enabled),
            ),
        )
        return Experience.from_row(row)

    def get_experience(self, exp_id: UUID | str) -> Experience | None:
        row = self.fetch_one(
            f"SELECT {_EXP_COLS} FROM learning.experiences WHERE id = %s", (str(exp_id),)
        )
        return Experience.from_row(row) if row else None

    def list_experiences(self, *, limit: int = 50) -> list[Experience]:
        rows = self.fetch_all(
            f"SELECT {_EXP_COLS} FROM learning.experiences "
            f"WHERE status = 'active' ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return Experience.from_rows(rows)

    def search_experiences(self, query: str, *, limit: int = 5) -> list[Experience]:
        """Lexical recall across the human-readable fields (no embeddings in v1)."""
        like = f"%{query.strip()}%"
        rows = self.fetch_all(
            f"""
            SELECT {_EXP_COLS} FROM learning.experiences
            WHERE status = 'active'
              AND (title ILIKE %s OR problem ILIKE %s OR solution ILIKE %s
                   OR lessons ILIKE %s
                   OR payload::text ILIKE %s)
            ORDER BY created_at DESC LIMIT %s
            """,
            (like, like, like, like, like, limit),
        )
        return Experience.from_rows(rows)

    def set_experience_status(self, exp_id: UUID | str, status: str) -> bool:
        return (
            self.execute(
                "UPDATE learning.experiences SET status = %s, updated_at = now() "
                "WHERE id = %s",
                (status, str(exp_id)),
            )
            > 0
        )

    def set_bias_enabled(self, exp_id: UUID | str, enabled: bool) -> bool:
        return (
            self.execute(
                "UPDATE learning.experiences SET bias_enabled = %s, updated_at = now() "
                "WHERE id = %s AND status = 'active'",
                (bool(enabled), str(exp_id)),
            )
            > 0
        )

    def list_bias_enabled(self, *, limit: int = 50) -> list[Experience]:
        rows = self.fetch_all(
            f"""
            SELECT {_EXP_COLS} FROM learning.experiences
            WHERE status = 'active' AND bias_enabled = true
            ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        )
        return Experience.from_rows(rows)

    def count_experiences(self) -> int:
        return (
            self.fetch_val(
                "SELECT count(*) FROM learning.experiences WHERE status = 'active'"
            )
            or 0
        )

    # --- component observations -----------------------------------------
    def add_component_observation(
        self,
        *,
        component_key: str,
        component_version: str = "1",
        corpus: str | None = None,
        profile: str | None = None,
        metrics: dict[str, Any] | None = None,
        source_job_id: str | None = None,
        experience_id: str | None = None,
        event_id: str | None = None,
    ) -> ComponentObservation:
        row = self.fetch_one(
            f"""
            INSERT INTO learning.component_observations
                (component_key, component_version, corpus, profile, metrics,
                 source_job_id, experience_id, event_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COMP_COLS}
            """,
            (
                component_key,
                str(component_version or "1"),
                corpus,
                profile,
                Jsonb(metrics or {}),
                source_job_id,
                experience_id,
                event_id,
            ),
        )
        return ComponentObservation.from_row(row)

    def list_component_observations(
        self,
        *,
        component_key: str | None = None,
        limit: int = 50,
    ) -> list[ComponentObservation]:
        clauses, params = [], []
        if component_key:
            clauses.append("component_key = %s")
            params.append(component_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.fetch_all(
            f"SELECT {_COMP_COLS} FROM learning.component_observations {where} "
            f"ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
        return ComponentObservation.from_rows(rows)
