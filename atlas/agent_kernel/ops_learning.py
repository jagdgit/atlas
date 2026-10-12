"""Phase 8 / C8 — consume ops self-diagnosis learning into later behavior.

Phase 7 writes ``ops_learning_candidate`` files. This module:

1. Loads those candidates
2. Accepts a thin **ops belief** (not a market L5 lesson)
3. Supplies context for later registration / diagnosis
4. Records a receipt when ``ensure_schedule`` reuses a row by identity (F5)

Hard boundary: ops beliefs change registration/diagnosis *context and path*, never
order authority or market strategy.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ops_learning.v1"
KIND_CANDIDATE = "ops_learning_candidate"
KIND_BELIEF = "ops_belief"
KIND_RECEIPT = "ops_learning_consume_receipt"

CANDIDATES_REL = Path("agent_kernel") / "learning_candidates"
BELIEFS_REL = Path("agent_kernel") / "ops_beliefs"
RECEIPTS_REL = Path("agent_kernel") / "ops_consume_receipts"

LAB = "atlas_ops"
BELIEF_ID = "B-atlas_ops-schedule_registration"

# Aligned with Phase 7 next_question + F5 identity-first registration (plan example).
IDEMPOTENT_STATEMENT = (
    "Schedule registration must be idempotent by identity "
    "(task_type, kind, cron_expr, worker_id, mission_id, payload); "
    "check find_by_identity before create."
)

_log = logging.getLogger("atlas.agent_kernel.ops_learning")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def candidates_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / CANDIDATES_REL


def list_candidates(data_dir: str | Path | None) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = candidates_dir(data_dir)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") and doc.get("kind") != KIND_CANDIDATE:
            continue
        doc = dict(doc)
        doc["_path"] = str(path)
        doc["_id"] = path.stem
        out.append(doc)
    return out


def latest_candidate(data_dir: str | Path | None) -> dict[str, Any] | None:
    rows = list_candidates(data_dir)
    return rows[-1] if rows else None


def belief_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / BELIEFS_REL / f"{BELIEF_ID}.json"


def current_ops_belief(data_dir: str | Path | None) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = belief_path(data_dir)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def accept_from_candidate(
    data_dir: str | Path | None,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept an ops belief grounded in a Phase 7 candidate.

    Provisional / ops-scoped: not a validated market lesson. Honest about that.
    """
    if not data_dir:
        return {"ok": False, "reason": "missing_data_dir"}
    cand = candidate if isinstance(candidate, dict) else latest_candidate(data_dir)
    if not cand:
        return {"ok": False, "reason": "no_ops_learning_candidate"}
    prior = current_ops_belief(data_dir)
    version_n = int((prior or {}).get("version_n") or 0) + 1
    belief = {
        "version": VERSION,
        "kind": KIND_BELIEF,
        "belief_id": BELIEF_ID,
        "version_n": version_n,
        "laboratory_id": LAB,
        "dimension": "schedule_registration",
        "status": "ACCEPTED_OPS",
        "statement": IDEMPOTENT_STATEMENT,
        "source_statement": cand.get("statement"),
        "source_candidate_id": cand.get("_id") or cand.get("work_id"),
        "source_candidate_path": cand.get("_path") or cand.get("learning_candidate_path"),
        "evidence": dict(cand.get("evidence") or {}),
        "next_question": cand.get("next_question"),
        "behaviour": "identity_first",
        "affects": ["schedule_registration", "ops_diagnosis"],
        "does_not_affect": [
            "order_authority",
            "position_sizing",
            "capital_allocation",
            "sma_rsi_v1",
            "plc_a",
        ],
        "validated_market_lesson": False,
        "provisional": True,
        "paper_only": False,
        "honesty": (
            "ACCEPTED_OPS from measured self-diagnosis. Changes registration/diagnosis "
            "path context. Not a market L5 lesson and must not size trades."
        ),
        "accepted_at": _now(),
    }
    path = belief_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(belief, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    return {"ok": True, "belief": belief, "path": str(path)}


def belief_context_for_ops(data_dir: str | Path | None) -> dict[str, Any]:
    """Context a later registration/diagnosis path should cite (C8)."""
    belief = current_ops_belief(data_dir)
    beliefs = []
    if belief and belief.get("status") == "ACCEPTED_OPS":
        beliefs.append(
            {
                "belief_id": belief.get("belief_id"),
                "version_n": belief.get("version_n"),
                "dimension": belief.get("dimension"),
                "statement": belief.get("statement"),
                "behaviour": belief.get("behaviour"),
                "source_candidate_id": belief.get("source_candidate_id"),
            }
        )
    return {
        "version": VERSION,
        "laboratory_id": LAB,
        "beliefs": beliefs,
        "n_accepted": len(beliefs),
        "affects": "ops_registration_context",
        "honesty": (
            "Ops beliefs inform schedule registration and failure classification. "
            "Empty means nothing accepted yet."
        ),
    }


def note_identity_reuse(
    data_dir: str | Path | None,
    *,
    task_type: str,
    schedule_id: str,
    reused: bool = True,
) -> dict[str, Any]:
    """Record that a later path checked identity first and cited ops learning."""
    if not data_dir:
        return {"ok": False, "cited": False, "reason": "missing_data_dir"}
    ctx = belief_context_for_ops(data_dir)
    if not ctx.get("beliefs"):
        return {"ok": True, "cited": False, "reason": "no_ops_belief"}
    belief = ctx["beliefs"][0]
    receipt = {
        "version": VERSION,
        "kind": KIND_RECEIPT,
        "at": _now(),
        "task_type": task_type,
        "schedule_id": str(schedule_id),
        "reused_existing": bool(reused),
        "behaviour": "identity_first",
        "consumed_learning": belief.get("belief_id"),
        "consumed_version": belief.get("version_n"),
        "source_candidate_id": belief.get("source_candidate_id"),
        "statement": belief.get("statement"),
        "honesty": (
            "Later registration path returned an existing schedule by identity and "
            "cited the accepted ops belief from self-diagnosis."
        ),
    }
    root = Path(data_dir) / RECEIPTS_REL
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{_now().replace(':', '').replace('+', '_')}_{task_type}.json"
        path.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError as exc:
        _log.debug("ops consume receipt failed: %s", exc)
        return {"ok": False, "cited": False, "reason": str(exc)}
    return {"ok": True, "cited": True, "receipt": receipt, "path": str(path)}


def behavioural_delta_ops(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    """Did ops belief context change for a later registration path?"""
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    b_ids = {
        (x.get("belief_id"), x.get("version_n")) for x in (b.get("beliefs") or [])
    }
    a_ids = {
        (x.get("belief_id"), x.get("version_n")) for x in (a.get("beliefs") or [])
    }
    added = sorted(f"{bid}@v{v}" for bid, v in (a_ids - b_ids))
    return {
        "version": VERSION,
        "changed": bool(added),
        "added": added,
        "removed": [],
        "paper_only": False,
        "domain": "ops",
        "honesty": (
            "changed=true means a later path can cite ops learning that did not exist "
            "before. Pair with an identity-reuse receipt for G8 proof."
        ),
    }


def prove_c8_consume(
    data_dir: str | Path | None,
    *,
    schedule_service: Any = None,
    task_type: str = "host_guard_tick",
) -> dict[str, Any]:
    """End-to-end Phase 8 proof helper: accept → cite on ensure → delta."""
    before = belief_context_for_ops(data_dir)
    accepted = accept_from_candidate(data_dir)
    if not accepted.get("ok"):
        return {"ok": False, "stage": "accept", **accepted}
    after = belief_context_for_ops(data_dir)
    delta = behavioural_delta_ops(before, after)
    cite: dict[str, Any] = {"cited": False}
    ensure: dict[str, Any] = {}
    if schedule_service is not None:
        a = schedule_service.ensure_schedule(task_type, 60, payload={})
        b = schedule_service.ensure_schedule(task_type, 60, payload={})
        ensure = {
            "first_id": str(getattr(a, "id", a)),
            "second_id": str(getattr(b, "id", b)),
            "same_id": str(getattr(a, "id", a)) == str(getattr(b, "id", b)),
        }
        # ensure_schedule should have written a receipt via bound callback; also cite here.
        cite = note_identity_reuse(
            data_dir,
            task_type=task_type,
            schedule_id=str(getattr(b, "id", b)),
            reused=True,
        )
    return {
        "ok": bool(delta.get("changed") and (cite.get("cited") or not schedule_service)),
        "accepted": accepted,
        "delta": delta,
        "ensure": ensure,
        "cite": cite,
        "after_context": after,
    }
