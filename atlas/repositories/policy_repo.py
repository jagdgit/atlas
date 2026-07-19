"""Repository for the Policy store — ``policy.rules`` + ``policy.events`` (Phase C · §C.5, CC8).

Operator rules that *influence* retrieval/advice (prefer/avoid/trust/distrust), plus an append-only
journal of every mutation (before/after snapshots) so edits are explainable (P9) and reversible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

RULE_KINDS = ("prefer", "avoid", "trust", "distrust")
EVENT_ACTIONS = ("created", "updated", "disabled", "enabled", "deleted", "reverted")


def _json_safe(value: Any) -> Any:
    """Normalize a rule row (UUIDs, datetimes) into a JSON-serializable snapshot for the journal."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value

_RULE_COLS = (
    "id, scope, subject, rule, strength, enabled, provenance, created_by, created_at, updated_at"
)


class PolicyRepository(BaseRepository):
    # --- rules ----------------------------------------------------------
    def create(
        self,
        scope: str,
        subject: str,
        rule: str,
        *,
        strength: float = 1.0,
        enabled: bool = True,
        provenance: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Insert a rule; if (scope, subject, rule) already exists, update it in place (upsert)."""
        if rule not in RULE_KINDS:
            raise ValueError(f"invalid policy rule kind: {rule}")
        return self.fetch_one(
            f"""
            INSERT INTO policy.rules (scope, subject, rule, strength, enabled, provenance, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scope, subject, rule) DO UPDATE SET
                strength = EXCLUDED.strength,
                enabled = EXCLUDED.enabled,
                provenance = EXCLUDED.provenance,
                created_by = COALESCE(policy.rules.created_by, EXCLUDED.created_by),
                updated_at = now()
            RETURNING {_RULE_COLS}
            """,
            (scope, subject, rule, strength, enabled,
             Jsonb(provenance or {}), created_by),
        )

    def get(self, rule_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_RULE_COLS} FROM policy.rules WHERE id = %s", (str(rule_id),)
        )

    def get_by_natural(self, scope: str, subject: str, rule: str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"""
            SELECT {_RULE_COLS} FROM policy.rules
            WHERE scope = %s AND subject = %s AND rule = %s
            """,
            (scope, subject, rule),
        )

    def list(
        self,
        *,
        scope: str | None = None,
        rule: str | None = None,
        enabled: bool | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if scope is not None:
            clauses.append("scope = %s")
            params.append(scope)
        if rule is not None:
            clauses.append("rule = %s")
            params.append(rule)
        if enabled is not None:
            clauses.append("enabled = %s")
            params.append(enabled)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self.fetch_all(
            f"""
            SELECT {_RULE_COLS} FROM policy.rules
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def update(
        self,
        rule_id: UUID | str,
        *,
        subject: str | None = None,
        strength: float | None = None,
        enabled: bool | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = []
        if subject is not None:
            sets.append("subject = %s")
            params.append(subject)
        if strength is not None:
            sets.append("strength = %s")
            params.append(strength)
        if enabled is not None:
            sets.append("enabled = %s")
            params.append(enabled)
        if provenance is not None:
            sets.append("provenance = %s")
            params.append(Jsonb(provenance))
        if not sets:
            return self.get(rule_id)
        sets.append("updated_at = now()")
        params.append(str(rule_id))
        return self.fetch_one(
            f"UPDATE policy.rules SET {', '.join(sets)} WHERE id = %s RETURNING {_RULE_COLS}",
            tuple(params),
        )

    def set_enabled(self, rule_id: UUID | str, enabled: bool) -> dict[str, Any] | None:
        return self.update(rule_id, enabled=enabled)

    def delete(self, rule_id: UUID | str) -> bool:
        return self.execute("DELETE FROM policy.rules WHERE id = %s", (str(rule_id),)) > 0

    def restore(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Re-insert a previously deleted rule from its journal snapshot (keeps the same id)."""
        return self.fetch_one(
            """
            INSERT INTO policy.rules
                (id, scope, subject, rule, strength, enabled, provenance, created_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                scope = EXCLUDED.scope, subject = EXCLUDED.subject, rule = EXCLUDED.rule,
                strength = EXCLUDED.strength, enabled = EXCLUDED.enabled,
                provenance = EXCLUDED.provenance, updated_at = now()
            RETURNING {}
            """.format(_RULE_COLS),
            (
                str(snapshot["id"]), snapshot["scope"], snapshot["subject"], snapshot["rule"],
                float(snapshot.get("strength", 1.0)), bool(snapshot.get("enabled", True)),
                Jsonb(snapshot.get("provenance") or {}), snapshot.get("created_by"),
            ),
        )

    # --- journal --------------------------------------------------------
    def record_event(
        self,
        rule_id: UUID | str | None,
        action: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        if action not in EVENT_ACTIONS:
            raise ValueError(f"invalid policy event action: {action}")
        return self.fetch_one(
            """
            INSERT INTO policy.events (rule_id, action, before, after, actor)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, rule_id, action, before, after, actor, created_at
            """,
            (
                str(rule_id) if rule_id else None,
                action,
                Jsonb(_json_safe(before)) if before is not None else None,
                Jsonb(_json_safe(after)) if after is not None else None,
                actor,
            ),
        )

    def get_event(self, event_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT id, rule_id, action, before, after, actor, created_at "
            "FROM policy.events WHERE id = %s",
            (str(event_id),),
        )

    def list_events(
        self, *, rule_id: UUID | str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if rule_id is not None:
            return self.fetch_all(
                "SELECT id, rule_id, action, before, after, actor, created_at "
                "FROM policy.events WHERE rule_id = %s ORDER BY created_at DESC LIMIT %s",
                (str(rule_id), limit),
            )
        return self.fetch_all(
            "SELECT id, rule_id, action, before, after, actor, created_at "
            "FROM policy.events ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
