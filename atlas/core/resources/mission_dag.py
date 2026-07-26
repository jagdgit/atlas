"""Mission DAG helpers (IR-M1).

Prefer linked child missions (Extract → Verify → Summarize) over monoliths.
Links live in ``mission.metadata["dag"]``; dependency waits reuse ``metadata.queue``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from atlas.models.mission import MISSION_ARCHIVED, MISSION_COMPLETED

# Roles used by research-style pipelines (convention, not enforced enum).
ROLE_EXTRACT = "extract"
ROLE_VERIFY = "verify"
ROLE_SUMMARIZE = "summarize"
ROLE_PARENT = "parent"
ROLE_CHILD = "child"

TERMINAL_STATUSES = frozenset({MISSION_COMPLETED, MISSION_ARCHIVED})

PIPELINE_EXTRACT_VERIFY_SUMMARIZE = (ROLE_EXTRACT, ROLE_VERIFY, ROLE_SUMMARIZE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dag_block(
    *,
    parent_id: str | None = None,
    role: str | None = None,
    children: list[str] | None = None,
    pipeline: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "parent_id": str(parent_id) if parent_id else None,
        "role": (role or ROLE_CHILD).strip().lower(),
        "children": [str(c) for c in (children or []) if c],
        "pipeline": list(pipeline or []),
        "updated_at": utc_now_iso(),
    }


def read_dag(metadata: dict[str, Any] | None) -> dict[str, Any]:
    meta = metadata if isinstance(metadata, dict) else {}
    raw = meta.get("dag")
    if not isinstance(raw, dict):
        return dag_block()
    children = raw.get("children") or []
    if not isinstance(children, list):
        children = []
    pipeline = raw.get("pipeline") or []
    if not isinstance(pipeline, list):
        pipeline = []
    return {
        "parent_id": str(raw["parent_id"]) if raw.get("parent_id") else None,
        "role": str(raw.get("role") or ROLE_CHILD).strip().lower(),
        "children": [str(c) for c in children if c],
        "pipeline": [str(p) for p in pipeline],
        "updated_at": raw.get("updated_at"),
    }


def is_terminal_status(status: str | None) -> bool:
    return (status or "").strip().lower() in TERMINAL_STATUSES


def all_deps_terminal(depends_on: list[str], status_by_id: dict[str, str]) -> bool:
    if not depends_on:
        return True
    for dep in depends_on:
        st = status_by_id.get(str(dep))
        if st is None or not is_terminal_status(st):
            return False
    return True


def dag_snapshot(mission: Any, *, children: list[Any] | None = None) -> dict[str, Any]:
    """Operator view of one mission's DAG node."""
    meta = getattr(mission, "metadata", None) or {}
    dag = read_dag(meta if isinstance(meta, dict) else {})
    child_rows = []
    for c in children or []:
        child_rows.append(
            {
                "id": str(getattr(c, "id", "")),
                "title": getattr(c, "title", None),
                "status": getattr(c, "status", None),
                "role": read_dag(getattr(c, "metadata", None)).get("role"),
            }
        )
    return {
        "mission_id": str(getattr(mission, "id", "")),
        "title": getattr(mission, "title", None),
        "status": getattr(mission, "status", None),
        "dag": dag,
        "children": child_rows,
        "version": "m1.1",
    }
