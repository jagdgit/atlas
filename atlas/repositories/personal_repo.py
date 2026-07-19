"""Repository for the Personal Intelligence store — ``personal.facts`` + ``personal.events``
(Phase C · §C.7, CC7/A9).

A curated profile of the owner (identity/skills/timeline/professional), each fact carrying provenance +
confidence and a governed ``inferred → verified/rejected`` lifecycle, plus an append-only journal of
every mutation (before/after snapshots) so edits are explainable (P9) and reversible — mirroring the
Policy store (C.5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

FACT_CATEGORIES = ("identity", "skill", "timeline", "professional")
FACT_STATES = ("inferred", "verified", "rejected")
EVENT_ACTIONS = (
    "inferred", "confirmed", "corrected", "rejected", "updated", "deleted", "reverted",
)


def _json_safe(value: Any) -> Any:
    """Normalize a fact row (UUIDs, datetimes) into a JSON-serializable snapshot for the journal."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


_FACT_COLS = (
    "id, category, key, subject, statement, value, state, confidence, confidence_score, "
    "source, provenance, created_by, created_at, updated_at"
)


class PersonalRepository(BaseRepository):
    # --- facts ----------------------------------------------------------
    def upsert(
        self,
        category: str,
        key: str,
        *,
        subject: str = "",
        statement: str = "",
        value: dict[str, Any] | None = None,
        state: str = "inferred",
        confidence: str | None = None,
        confidence_score: float = 0.0,
        source: str | None = None,
        provenance: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Insert a fact; if (category, key, subject) exists, refresh its inferred belief in place.

        Re-inference (CC7) NEVER downgrades operator decisions: a ``verified`` fact keeps its
        ``verified`` state (its statement/value are left as the operator confirmed them) and a
        ``rejected`` fact stays ``rejected`` — only provenance/confidence telemetry is refreshed.
        """
        if category not in FACT_CATEGORIES:
            raise ValueError(f"invalid personal fact category: {category}")
        if state not in FACT_STATES:
            raise ValueError(f"invalid personal fact state: {state}")
        return self.fetch_one(
            f"""
            INSERT INTO personal.facts
                (category, key, subject, statement, value, state, confidence,
                 confidence_score, source, provenance, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (category, key, subject) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                confidence_score = EXCLUDED.confidence_score,
                source = EXCLUDED.source,
                provenance = EXCLUDED.provenance,
                -- Only refresh the belief body while the fact is still machine-owned (inferred).
                statement = CASE WHEN personal.facts.state = 'inferred'
                            THEN EXCLUDED.statement ELSE personal.facts.statement END,
                value = CASE WHEN personal.facts.state = 'inferred'
                        THEN EXCLUDED.value ELSE personal.facts.value END,
                updated_at = now()
            RETURNING {_FACT_COLS}
            """,
            (
                category, key, subject, statement, Jsonb(value or {}), state, confidence,
                confidence_score, source, Jsonb(provenance or {}), created_by,
            ),
        )

    def get(self, fact_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_FACT_COLS} FROM personal.facts WHERE id = %s", (str(fact_id),)
        )

    def get_by_natural(
        self, category: str, key: str, subject: str = ""
    ) -> dict[str, Any] | None:
        return self.fetch_one(
            f"""
            SELECT {_FACT_COLS} FROM personal.facts
            WHERE category = %s AND key = %s AND subject = %s
            """,
            (category, key, subject),
        )

    def list(
        self,
        *,
        category: str | None = None,
        state: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category is not None:
            clauses.append("category = %s")
            params.append(category)
        if state is not None:
            clauses.append("state = %s")
            params.append(state)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self.fetch_all(
            f"""
            SELECT {_FACT_COLS} FROM personal.facts
            {where}
            ORDER BY confidence_score DESC, updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def set_state(self, fact_id: UUID | str, state: str) -> dict[str, Any] | None:
        if state not in FACT_STATES:
            raise ValueError(f"invalid personal fact state: {state}")
        return self.fetch_one(
            f"UPDATE personal.facts SET state = %s, updated_at = now() "
            f"WHERE id = %s RETURNING {_FACT_COLS}",
            (state, str(fact_id)),
        )

    def update(
        self,
        fact_id: UUID | str,
        *,
        statement: str | None = None,
        value: dict[str, Any] | None = None,
        state: str | None = None,
        confidence: str | None = None,
        confidence_score: float | None = None,
    ) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = []
        if statement is not None:
            sets.append("statement = %s")
            params.append(statement)
        if value is not None:
            sets.append("value = %s")
            params.append(Jsonb(value))
        if state is not None:
            if state not in FACT_STATES:
                raise ValueError(f"invalid personal fact state: {state}")
            sets.append("state = %s")
            params.append(state)
        if confidence is not None:
            sets.append("confidence = %s")
            params.append(confidence)
        if confidence_score is not None:
            sets.append("confidence_score = %s")
            params.append(confidence_score)
        if not sets:
            return self.get(fact_id)
        sets.append("updated_at = now()")
        params.append(str(fact_id))
        return self.fetch_one(
            f"UPDATE personal.facts SET {', '.join(sets)} WHERE id = %s RETURNING {_FACT_COLS}",
            tuple(params),
        )

    def delete(self, fact_id: UUID | str) -> bool:
        return self.execute("DELETE FROM personal.facts WHERE id = %s", (str(fact_id),)) > 0

    def restore(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Re-insert a previously deleted fact from its journal snapshot (keeps the same id)."""
        return self.fetch_one(
            f"""
            INSERT INTO personal.facts
                (id, category, key, subject, statement, value, state, confidence,
                 confidence_score, source, provenance, created_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                category = EXCLUDED.category, key = EXCLUDED.key, subject = EXCLUDED.subject,
                statement = EXCLUDED.statement, value = EXCLUDED.value, state = EXCLUDED.state,
                confidence = EXCLUDED.confidence, confidence_score = EXCLUDED.confidence_score,
                source = EXCLUDED.source, provenance = EXCLUDED.provenance, updated_at = now()
            RETURNING {_FACT_COLS}
            """,
            (
                str(snapshot["id"]), snapshot["category"], snapshot["key"],
                snapshot.get("subject", ""), snapshot.get("statement", ""),
                Jsonb(snapshot.get("value") or {}), snapshot.get("state", "inferred"),
                snapshot.get("confidence"), float(snapshot.get("confidence_score", 0.0) or 0.0),
                snapshot.get("source"), Jsonb(snapshot.get("provenance") or {}),
                snapshot.get("created_by"),
            ),
        )

    # --- journal --------------------------------------------------------
    def record_event(
        self,
        fact_id: UUID | str | None,
        action: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        if action not in EVENT_ACTIONS:
            raise ValueError(f"invalid personal event action: {action}")
        return self.fetch_one(
            """
            INSERT INTO personal.events (fact_id, action, before, after, actor)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, fact_id, action, before, after, actor, created_at
            """,
            (
                str(fact_id) if fact_id else None,
                action,
                Jsonb(_json_safe(before)) if before is not None else None,
                Jsonb(_json_safe(after)) if after is not None else None,
                actor,
            ),
        )

    def get_event(self, event_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT id, fact_id, action, before, after, actor, created_at "
            "FROM personal.events WHERE id = %s",
            (str(event_id),),
        )

    def list_events(
        self, *, fact_id: UUID | str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if fact_id is not None:
            return self.fetch_all(
                "SELECT id, fact_id, action, before, after, actor, created_at "
                "FROM personal.events WHERE fact_id = %s ORDER BY created_at DESC LIMIT %s",
                (str(fact_id), limit),
            )
        return self.fetch_all(
            "SELECT id, fact_id, action, before, after, actor, created_at "
            "FROM personal.events ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
