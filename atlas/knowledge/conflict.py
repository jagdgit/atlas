"""Knowledge conflict helpers + DecisionRule (OI-B3).

Consolidator already routes evolution vs conflict; verification marks contested.
This module adds structured ``quality.conflict`` payloads, operator resolve actions,
and a deterministic DecisionRule that *recommends* hold / reactivate / supersede
without inventing a parallel knowledge store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from atlas.decision.contracts import DecisionRequest, ScoredOption

if TYPE_CHECKING:
    from atlas.decision.context import IntelligenceContext

MISSION_TYPE_KNOWLEDGE_CONFLICT = "knowledge_conflict"

RESOLVE_HOLD = "hold"
RESOLVE_SUPERSEDE = "supersede"
RESOLVE_REACTIVATE = "reactivate"
RESOLVE_ACTIONS = frozenset({RESOLVE_HOLD, RESOLVE_SUPERSEDE, RESOLVE_REACTIVATE})


def conflict_record(
    *,
    kind: str,
    signal: str = "",
    peer_ids: list[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured why-conflict payload stored on ``findings.quality.conflict``."""
    return {
        "kind": kind,  # same_time | cross_source | verification
        "signal": signal,
        "peer_ids": list(peer_ids or []),
        "detail": dict(detail or {}),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_conflict_quality(
    store: Any,
    finding_id: str,
    conflict: dict[str, Any],
) -> None:
    """Best-effort write of ``quality.conflict`` onto a finding (no parallel store)."""
    if not finding_id or not conflict:
        return
    if hasattr(store, "merge_quality"):
        try:
            store.merge_quality(str(finding_id), {"conflict": conflict})
            return
        except Exception:  # noqa: BLE001
            pass
    rows = getattr(store, "rows", None)
    if isinstance(rows, dict) and finding_id in rows:
        quality = dict(rows[finding_id].get("quality") or {})
        quality["conflict"] = conflict
        rows[finding_id]["quality"] = quality


class KnowledgeConflictDecisionRule:
    """Recommend how to handle a contested finding (OI-B3) — never invents truth."""

    mission_type = MISSION_TYPE_KNOWLEDGE_CONFLICT
    VERSION = "1"

    def score(
        self, request: DecisionRequest, context: "IntelligenceContext"
    ) -> list[ScoredOption]:
        finding = request.context.get("finding")
        if not isinstance(finding, dict):
            finding_id = str(request.context.get("finding_id") or "").strip()
            finding = self._load_finding(context, finding_id) if finding_id else None
        if not isinstance(finding, dict):
            return [
                ScoredOption(
                    key="hold",
                    score=0.5,
                    text="Hold — contested finding not available in context",
                    rationale="Cannot resolve without the contested finding payload.",
                    tags=("knowledge_conflict", "hold"),
                )
            ]

        status = str(finding.get("status") or "")
        contra = finding.get("contradicting") or finding.get("contradicting_sources") or []
        n_contra = len(contra) if isinstance(contra, list) else (1 if contra else 0)
        quality = finding.get("quality") if isinstance(finding.get("quality"), dict) else {}
        conflict = quality.get("conflict") if isinstance(quality.get("conflict"), dict) else {}
        kind = str(conflict.get("kind") or ("cross_source" if n_contra else "unknown"))
        stmt = str(finding.get("statement") or "")[:120]
        fid = str(finding.get("id") or "")

        hold_score = 0.55
        reactivate_score = 0.35
        supersede_score = 0.45
        if n_contra >= 2:
            hold_score = 0.7
            supersede_score = 0.55
            reactivate_score = 0.2
        elif n_contra == 0 and status == "contested":
            reactivate_score = 0.65
            hold_score = 0.4
            supersede_score = 0.3
        elif kind == "same_time":
            hold_score = 0.65
            supersede_score = 0.5

        why_bits = [f"status={status}", f"contradicting={n_contra}", f"kind={kind}"]
        if conflict.get("signal"):
            why_bits.append(f"signal={conflict['signal']}")

        return [
            ScoredOption(
                key="hold",
                score=hold_score,
                text=f"Hold contested claim — gather more evidence ({stmt})",
                rationale="Keep contested until corroboration clarifies; " + ", ".join(why_bits),
                tags=("knowledge_conflict", "hold"),
                knowledge_refs=[fid] if fid else [],
            ),
            ScoredOption(
                key="reactivate",
                score=reactivate_score,
                text=f"Reactivate as active (operator override) — {stmt}",
                rationale=(
                    "Operator may clear or override contradicting evidence; "
                    + ", ".join(why_bits)
                ),
                tags=("knowledge_conflict", "reactivate"),
                knowledge_refs=[fid] if fid else [],
                side_effecting=True,
            ),
            ScoredOption(
                key="supersede",
                score=supersede_score,
                text=f"Deprecate contested claim (peer / newer wins) — {stmt}",
                rationale=(
                    "Retire this head when the operator judges the conflicting view correct; "
                    + ", ".join(why_bits)
                ),
                tags=("knowledge_conflict", "supersede"),
                knowledge_refs=[fid] if fid else [],
                side_effecting=True,
            ),
        ]

    @staticmethod
    def _load_finding(context: "IntelligenceContext", finding_id: str) -> dict[str, Any] | None:
        knowledge = getattr(context, "knowledge", None)
        if knowledge is None:
            return None
        get = getattr(knowledge, "get_finding", None) or getattr(knowledge, "get", None)
        if get is None:
            return None
        try:
            row = get(finding_id)
            return row if isinstance(row, dict) else None
        except Exception:  # noqa: BLE001
            return None
