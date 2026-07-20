"""SelfImprovementDecisionRule — rank eval regressions into next actions (Phase D · §D.10).

Scores analysis findings from the hermetic baseline suite into ``investigate`` /
``propose_fix`` / ``hold`` options. ``propose_fix`` is **side-effecting** when the
worker asks for gated actions (P14) — it opens the human-approval gate; Atlas never
silently mutates itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from atlas.decision.contracts import DecisionRequest, ScoredOption

if TYPE_CHECKING:
    from atlas.decision.context import IntelligenceContext

MISSION_TYPE_SELF_IMPROVEMENT = "self_improvement"

_HOLD_SCORE = 0.3
_INVESTIGATE_BASE = 1.0
_FIX_BASE = 1.2
_SEVERITY_BONUS = {"high": 0.5, "medium": 0.25, "low": 0.0}


class SelfImprovementDecisionRule:
    """Deterministic ranking of eval findings → investigate / propose_fix / hold."""

    mission_type = MISSION_TYPE_SELF_IMPROVEMENT
    VERSION = "1.0.0"

    def score(
        self, request: DecisionRequest, context: "IntelligenceContext"
    ) -> list[ScoredOption]:
        ctx = request.context or {}
        findings = list(ctx.get("findings") or [])
        gate_fixes = bool(ctx.get("gate_fixes", True))

        hold = ScoredOption(
            key="hold",
            score=_HOLD_SCORE,
            text="hold — eval suite healthy this cycle",
            tags=("hold",),
            rationale="no regressions or floor breaches",
            payload={"kind": "hold"},
        )
        if not findings:
            return [hold]

        options: list[ScoredOption] = [hold]
        for finding in findings:
            fid = str(finding.get("id") or "").strip()
            metric = str(finding.get("metric") or "unknown")
            if not fid:
                continue
            severity = str(finding.get("severity") or "medium").lower()
            kind = str(finding.get("kind") or "regression")
            bonus = _SEVERITY_BONUS.get(severity, 0.0)

            options.append(
                ScoredOption(
                    key=f"investigate:{fid}",
                    score=_INVESTIGATE_BASE + bonus,
                    text=f"investigate {metric} ({kind})",
                    tags=("investigate", "eval", severity, kind),
                    rationale=(
                        f"{kind} on {metric}: current={finding.get('current')}, "
                        f"previous={finding.get('previous')}, floor={finding.get('floor')}"
                    ),
                    evidence_refs=[fid],
                    payload={
                        "kind": "investigate",
                        "finding_id": fid,
                        "finding": finding,
                    },
                )
            )
            # Gated fix proposal — operator must approve before anything is recorded as intent.
            options.append(
                ScoredOption(
                    key=f"propose_fix:{fid}",
                    score=_FIX_BASE + bonus,
                    text=f"propose fix for {metric}",
                    tags=("propose_fix", "eval", severity, kind, metric.split(".")[0]),
                    rationale=f"operator-gated remediation intent for {metric}",
                    evidence_refs=[fid],
                    side_effecting=gate_fixes,
                    payload={
                        "kind": "propose_fix",
                        "finding_id": fid,
                        "finding": finding,
                        "suggested_action": _suggest(finding),
                    },
                )
            )
        return options


def _suggest(finding: dict[str, Any]) -> str:
    metric = str(finding.get("metric") or "")
    kind = str(finding.get("kind") or "")
    if "retrieval" in metric:
        return "Review retrieval ranking / embeddings; re-run hermetic retrieval corpus."
    if "synthesis" in metric or "merge" in metric or "contradiction" in metric:
        return "Review claim grouping / contradiction detection; inspect synthesis fixtures."
    if "freshness" in metric or "supersession" in metric:
        return "Review knowledge lifecycle freshness/supersession policy cases."
    if "provenance" in metric:
        return "Review provenance completeness on knowledge entities."
    if kind == "regression":
        return "Compare last two baseline captures; bisect recent consolidator/reader changes."
    return "Inspect the failing eval section and update fixtures or code as needed."
