"""Repositories for the Recovery Manager (Phase 0 · §2.8, P1/P4).

``RecoveryRepository`` records durable, re-entrant startup-recovery runs
(``system.recovery_runs``). ``CheckpointRepository`` backs the checkpoint foundation
(``system.checkpoints``) — upsertable resume points for long-running work.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository


class RecoveryRepository(BaseRepository):
    def mark_stale_running_interrupted(self) -> int:
        """Any run left ``running`` (a crash mid-recovery) becomes ``interrupted``."""
        return self.execute(
            """
            UPDATE system.recovery_runs
            SET status = 'interrupted', finished_at = now()
            WHERE status = 'running'
            """
        )

    def begin(self, host: str | None) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO system.recovery_runs (host, status)
            VALUES (%s, 'running')
            RETURNING *
            """,
            (host,),
        )

    def finish(
        self, run_id: str, status: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            UPDATE system.recovery_runs
            SET status = %s, steps = %s, finished_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status, Jsonb(steps), run_id),
        )

    def last(self) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM system.recovery_runs ORDER BY started_at DESC LIMIT 1"
        )


class CheckpointRepository(BaseRepository):
    def save(
        self, owner_type: str, owner_id: str, state: dict[str, Any], *, label: str = "default"
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO system.checkpoints (owner_type, owner_id, label, state)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (owner_type, owner_id, label) DO UPDATE
                SET state = EXCLUDED.state, updated_at = now()
            RETURNING *
            """,
            (owner_type, owner_id, label, Jsonb(state or {})),
        )

    def load(
        self, owner_type: str, owner_id: str, *, label: str = "default"
    ) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            SELECT * FROM system.checkpoints
            WHERE owner_type = %s AND owner_id = %s AND label = %s
            """,
            (owner_type, owner_id, label),
        )

    def clear(self, owner_type: str, owner_id: str, *, label: str | None = None) -> int:
        if label is not None:
            return self.execute(
                """
                DELETE FROM system.checkpoints
                WHERE owner_type = %s AND owner_id = %s AND label = %s
                """,
                (owner_type, owner_id, label),
            )
        return self.execute(
            "DELETE FROM system.checkpoints WHERE owner_type = %s AND owner_id = %s",
            (owner_type, owner_id),
        )

    def most_recent(self) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM system.checkpoints ORDER BY updated_at DESC LIMIT 1"
        )
