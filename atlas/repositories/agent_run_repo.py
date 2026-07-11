"""Repository for the ``agent`` schema — agents, runs, and steps.

The only layer permitted to hold SQL for agent state (ADR-0027). Agents and the
AgentService call these methods; they never issue SQL themselves.

A run is the durable record of one agent invocation (what was asked, what came
back). Steps form the ordered trace of how the answer was produced (retrieval,
generation), which makes agent behaviour observable and recoverable.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

VALID_RUN_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}


class AgentRunRepository(BaseRepository):
    # --- agents catalog -------------------------------------------------
    def upsert_agent(
        self,
        name: str,
        kind: str,
        *,
        description: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register an agent (or update its catalog row) and return it."""
        return self.fetch_one(
            """
            INSERT INTO agent.agents (name, kind, description, config)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
                SET kind = EXCLUDED.kind,
                    description = EXCLUDED.description,
                    config = EXCLUDED.config,
                    updated_at = now()
            RETURNING *
            """,
            (name, kind, description, Jsonb(config or {})),
        )

    def get_agent_by_name(self, name: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM agent.agents WHERE name = %s", (name,)
        )

    # --- runs -----------------------------------------------------------
    def open_run(
        self,
        agent_name: str,
        agent_input: dict[str, Any] | None = None,
        *,
        agent_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Create a run in 'running' state and return the row."""
        return self.fetch_one(
            """
            INSERT INTO agent.runs
                (agent_id, agent_name, status, input, started_at)
            VALUES (%s, %s, 'running', %s, now())
            RETURNING *
            """,
            (
                str(agent_id) if agent_id is not None else None,
                agent_name,
                Jsonb(agent_input or {}),
            ),
        )

    def finish_run(
        self, run_id: UUID | str, output: dict[str, Any] | None = None
    ) -> bool:
        return (
            self.execute(
                """
                UPDATE agent.runs
                SET status = 'completed', output = %s, finished_at = now()
                WHERE id = %s
                """,
                (Jsonb(output) if output is not None else None, str(run_id)),
            )
            > 0
        )

    def fail_run(self, run_id: UUID | str, error: str) -> bool:
        return (
            self.execute(
                """
                UPDATE agent.runs
                SET status = 'failed', error = %s, finished_at = now()
                WHERE id = %s
                """,
                (error, str(run_id)),
            )
            > 0
        )

    def get_run(self, run_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM agent.runs WHERE id = %s", (str(run_id),)
        )

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT * FROM agent.runs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )

    # --- steps ----------------------------------------------------------
    def add_step(
        self,
        run_id: UUID | str,
        ordinal: int,
        kind: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO agent.steps (run_id, ordinal, kind, detail)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (str(run_id), ordinal, kind, Jsonb(detail or {})),
        )

    def list_steps(self, run_id: UUID | str) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT * FROM agent.steps
            WHERE run_id = %s
            ORDER BY ordinal ASC
            """,
            (str(run_id),),
        )
