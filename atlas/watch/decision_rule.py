"""AdvisoryDecisionRule — prioritize CVE / breaking-change advisories (Phase D · §D.9).

Scores fixture advisories against mission focus (technologies/components) + severity floor
into deterministic ``recommend_advisory`` / ``hold`` options. One scoring core; registered
under both ``technology_watch`` and ``security_monitoring`` mission types (two thin templates,
one worker pattern).

Pure + deterministic (Q7). Recommend-only (P14/DD3): ``side_effecting = False``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from atlas.decision.contracts import DecisionRequest, ScoredOption

if TYPE_CHECKING:
    from atlas.decision.context import IntelligenceContext

MISSION_TYPE_TECHNOLOGY = "technology_watch"
MISSION_TYPE_SECURITY = "security_monitoring"

_HOLD_SCORE = 0.3
_BASE_SCORE = 1.0
_SEVERITY_WEIGHT = 0.5
_FOCUS_BONUS = 0.8
_KIND_BONUS = 0.4

_SEVERITY_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "moderate": 2,
    "low": 1,
    "info": 0,
    "unknown": 0,
    "": 0,
}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+._-]*", re.IGNORECASE)


class AdvisoryDecisionRule:
    """Deterministic ranking of advisories → recommend_advisory / hold.

    Construct with the mission type this instance answers for (both templates share the
    same scoring logic; the registry keys them separately).
    """

    VERSION = "1.0.0"

    def __init__(self, mission_type: str = MISSION_TYPE_TECHNOLOGY) -> None:
        if mission_type not in (MISSION_TYPE_TECHNOLOGY, MISSION_TYPE_SECURITY):
            raise ValueError(f"unsupported advisory mission_type: {mission_type!r}")
        self.mission_type = mission_type

    def score(
        self, request: DecisionRequest, context: "IntelligenceContext"
    ) -> list[ScoredOption]:
        ctx = request.context or {}
        advisories = list(ctx.get("advisories") or [])
        mode = str(ctx.get("mode") or (
            "security" if self.mission_type == MISSION_TYPE_SECURITY else "technology"
        )).lower()

        hold = ScoredOption(
            key="hold",
            score=_HOLD_SCORE,
            text="hold — no advisory worth escalating this cycle",
            tags=("hold",),
            rationale="no advisory above the floor / focus this cycle",
            payload={"kind": "hold", "mode": mode},
        )
        if not advisories:
            return [hold]

        focus = {_norm(s) for s in (ctx.get("focus") or []) if s}
        floor = _SEVERITY_RANK.get(str(ctx.get("severity_floor") or "medium").lower(), 2)

        options: list[ScoredOption] = [hold]
        for adv in advisories:
            opt = self._score_advisory(adv, focus=focus, floor=floor, mode=mode)
            if opt is not None:
                options.append(opt)
        return options

    def _score_advisory(
        self,
        adv: dict[str, Any],
        *,
        focus: set[str],
        floor: int,
        mode: str,
    ) -> ScoredOption | None:
        aid = str(adv.get("id") or "").strip()
        title = str(adv.get("title") or "").strip()
        if not aid or not title:
            return None

        severity = str(adv.get("severity") or "unknown").lower()
        sev_rank = _SEVERITY_RANK.get(severity, 0)
        if sev_rank < floor:
            return None

        package = str(adv.get("package") or adv.get("component") or "").strip()
        kind = str(adv.get("kind") or "advisory").lower()
        packages = {_norm(p) for p in (adv.get("packages") or []) if p}
        if package:
            packages.add(_norm(package))

        # Focus filter: if the mission names technologies/components, require a hit.
        if focus:
            hay = packages | _tokenize(title) | _tokenize(package)
            if not (hay & focus):
                return None

        score = _BASE_SCORE + _SEVERITY_WEIGHT * sev_rank
        if focus and (packages & focus):
            score += _FOCUS_BONUS
        # Mode-aware kind bonus: security prefers cve/vuln; technology prefers breaking/dep.
        if mode == "security" and kind in ("cve", "vulnerability", "security", "advisory"):
            score += _KIND_BONUS
        if mode == "technology" and kind in ("breaking_change", "dependency", "release", "changelog"):
            score += _KIND_BONUS

        tags = ["advisory", kind, severity, mode]
        for token in packages | _tokenize(title) | _tokenize(str(adv.get("cve") or "")):
            if len(token) >= 3:
                tags.append(token)

        rationale_parts = [f"severity={severity}"]
        if packages & focus:
            rationale_parts.append(f"focus hit: {', '.join(sorted(packages & focus)[:4])}")
        if kind:
            rationale_parts.append(f"kind={kind}")

        return ScoredOption(
            key=f"recommend:{aid}",
            score=score,
            text=f"recommend: {title}",
            tags=tuple(dict.fromkeys(tags)),
            rationale="; ".join(rationale_parts),
            evidence_refs=[adv.get("url") or aid],
            payload={
                "kind": "recommend_advisory",
                "mode": mode,
                "advisory": {
                    "id": aid,
                    "title": title,
                    "severity": severity,
                    "kind": kind,
                    "package": package,
                    "packages": sorted(packages),
                    "cve": adv.get("cve"),
                    "url": adv.get("url"),
                    "summary": str(adv.get("summary") or "")[:500],
                },
            },
        )


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _tokenize(text: str) -> set[str]:
    return {_norm(t) for t in _WORD_RE.findall(text or "") if len(t) >= 2}
