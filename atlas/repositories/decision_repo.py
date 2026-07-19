"""Repository for the Decision Engine journal — ``decision.decisions`` (Phase D · §D.1, P9).

Append-only. Persists the full P9 record of every decision (the canonical "Explain this" payload) so a
mission's choices are reproducible + interrogable. Also backs the capability-gap backlog (P15) and the
pending-approval feed (P14). Repositories are the only layer with SQL (ADR-0027).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

if TYPE_CHECKING:
    from atlas.decision.contracts import Decision

_COLS = (
    "id, mission_id, mission_type, config_id, config_version, action, action_kind, why, "
    "decision_rule, rule_version, evidence_refs, knowledge_refs, experience_refs, model_versions, "
    "policy_ids, confidence, confidence_score, alternatives_rejected, requires_approval, status, "
    "created_at"
)


def _json_safe(value: Any) -> Any:
    """Normalize UUIDs/datetimes nested in refs so they serialize cleanly into JSONB."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class DecisionRepository(BaseRepository):
    def record(self, decision: "Decision") -> dict[str, Any]:
        """Insert one decision (the P9 record) and return the stored row."""
        return self.fetch_one(
            f"""
            INSERT INTO decision.decisions (
                mission_id, mission_type, config_id, config_version, action, action_kind, why,
                decision_rule, rule_version, evidence_refs, knowledge_refs, experience_refs,
                model_versions, policy_ids, confidence, confidence_score, alternatives_rejected,
                requires_approval, status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s
            )
            RETURNING {_COLS}
            """,
            (
                str(decision.mission_id) if decision.mission_id else None,
                decision.mission_type,
                str(decision.config_id) if decision.config_id else None,
                decision.config_version,
                Jsonb(_json_safe(decision.action)),
                decision.action_kind,
                decision.why,
                decision.decision_rule,
                decision.rule_version,
                Jsonb(_json_safe(decision.evidence_refs)),
                Jsonb(_json_safe(decision.knowledge_refs)),
                Jsonb(_json_safe(decision.experience_refs)),
                Jsonb(_json_safe(decision.model_versions)),
                Jsonb(_json_safe(decision.policy_ids)),
                decision.confidence,
                decision.confidence_score,
                Jsonb(_json_safe(decision.alternatives_rejected)),
                decision.requires_approval,
                decision.status,
            ),
        )

    def get(self, decision_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_COLS} FROM decision.decisions WHERE id = %s", (str(decision_id),)
        )

    def list(
        self,
        *,
        mission_id: UUID | str | None = None,
        mission_type: str | None = None,
        action_kind: str | None = None,
        requires_approval: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if mission_id is not None:
            clauses.append("mission_id = %s")
            params.append(str(mission_id))
        if mission_type is not None:
            clauses.append("mission_type = %s")
            params.append(mission_type)
        if action_kind is not None:
            clauses.append("action_kind = %s")
            params.append(action_kind)
        if requires_approval is not None:
            clauses.append("requires_approval = %s")
            params.append(requires_approval)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self.fetch_all(
            f"SELECT {_COLS} FROM decision.decisions {where} ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )

    def list_gaps(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """The capability-gap backlog (P15) — what Atlas couldn't do, newest first."""
        return self.list(action_kind="capability_gap", limit=limit)

    def count(self) -> int:
        return int(self.fetch_val("SELECT count(*) FROM decision.decisions") or 0)
