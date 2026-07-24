"""Daily Learning Governance Report — Layer 2 (OI-MP3 / MP3).

Answers *Did Atlas actually learn?* and *Did Atlas become better?* without the
operator asking. Aggregates Knowledge / Experience / Decisions / sim portfolio —
not a per-video Learning Report and not a Research answer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any


class GovernanceReportService:
    """Build the Daily Learning Governance Report (philosophy Layer 2)."""

    name = "governance"
    VERSION = "mp.3"

    def __init__(
        self,
        *,
        knowledge: Any | None = None,
        learning: Any | None = None,
        decisions: Any | None = None,
        portfolio: Any | None = None,
        events: Any | None = None,
        coverage: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._learning = learning
        self._decisions = decisions
        self._portfolio = portfolio
        self._events = events
        self._coverage = coverage
        self._logger = logger or logging.getLogger("atlas.governance")

    def daily(self, *, limit: int = 200) -> dict[str, Any]:
        """Compile today's governance snapshot (counts + honest gaps)."""
        findings = self._list_findings(limit=limit)
        by_claim = _count_by(findings, "claim_type")
        by_status = _count_by(findings, "status")
        by_maturity = _count_by(findings, "maturity")
        unverified = sum(
            1
            for f in findings
            if str(f.get("maturity") or "").lower() in {"candidate", "unverified", ""}
            or str(f.get("status") or "").lower() == "unverified"
        )
        contested = sum(
            1 for f in findings if str(f.get("status") or "").lower() == "contested"
        )
        concepts = by_claim.get("concept", 0)
        entities = by_claim.get("entity", 0)
        relationships = by_claim.get("relationship", 0) + by_claim.get("fact", 0)
        claims = by_claim.get("claim", 0)

        experiences = self._list_experiences(limit=limit)
        lessons = len(experiences)
        market_lessons = sum(
            1
            for e in experiences
            if "markets" in {str(t).lower() for t in (e.get("tags") or [])}
            or str(e.get("domain") or "").lower() == "markets"
            or "investment_mentor" in {str(t).lower() for t in (e.get("tags") or [])}
        )

        decision_rows = self._list_decisions(limit=limit)
        decisions_n = len(decision_rows)
        gaps = sum(
            1
            for d in decision_rows
            if str(d.get("action_kind") or "") == "capability_gap"
        )

        portfolio_block = self._portfolio_snapshot()
        coverage_block = self._coverage_summary()
        failed = self._failed_learning_signals(limit=40)

        sections = {
            "knowledge": {
                "findings_scanned": len(findings),
                "concepts": concepts,
                "entities": entities,
                "relationships": relationships,
                "claims": claims,
                "by_claim_type": by_claim,
                "by_status": by_status,
                "by_maturity": by_maturity,
                "unverified_or_candidate": unverified,
                "contested": contested,
            },
            "experience": {
                "lessons": lessons,
                "market_lessons": market_lessons,
            },
            "decisions": {
                "count": decisions_n,
                "capability_gaps": gaps,
            },
            "portfolio": portfolio_block,
            "coverage": coverage_block,
            "failed_learning": failed,
        }

        headline = {
            "new_concepts": concepts,
            "new_entities": entities,
            "new_relationships": relationships,
            "lessons_learned": lessons,
            "knowledge_conflicts": contested,
            "failed_learning": int(failed.get("count") or 0),
            "capability_gaps": gaps,
            "portfolio_return_pct": portfolio_block.get("total_return_pct"),
        }

        narrative = _narrative(headline, sections)
        return {
            "report_kind": "learning_governance",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "headline": headline,
            "sections": sections,
            "narrative": narrative,
            "note": (
                "Layer 2 Daily Learning Governance Report (OI-MP3) — "
                "not a per-media Learning Report"
            ),
            "version": self.VERSION,
        }

    def _list_findings(self, *, limit: int) -> list[dict[str, Any]]:
        if self._knowledge is None:
            return []
        try:
            return list(self._knowledge.list_findings(limit=limit) or [])
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("list_findings skipped: %s", exc)
            return []

    def _list_experiences(self, *, limit: int) -> list[dict[str, Any]]:
        if self._learning is None:
            return []
        try:
            return list(self._learning.list_experiences(limit=limit) or [])
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("list_experiences skipped: %s", exc)
            return []

    def _list_decisions(self, *, limit: int) -> list[dict[str, Any]]:
        if self._decisions is None:
            return []
        try:
            if hasattr(self._decisions, "list"):
                return list(self._decisions.list(limit=limit) or [])
            if hasattr(self._decisions, "recent"):
                return list(self._decisions.recent(limit=limit) or [])
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("list decisions skipped: %s", exc)
        return []

    def _portfolio_snapshot(self) -> dict[str, Any]:
        if self._portfolio is None:
            return {"available": False}
        try:
            # Prefer a recent mission portfolio if the service exposes list/ensure.
            ensure = getattr(self._portfolio, "ensure_portfolio", None)
            snap = getattr(self._portfolio, "snapshot", None)
            if callable(ensure) and callable(snap):
                # Non-destructive: only snapshot if we can list without creating.
                list_fn = getattr(self._portfolio, "list_portfolios", None)
                if callable(list_fn):
                    rows = list_fn(limit=5) or []
                    if rows:
                        pid = rows[0].get("id") if isinstance(rows[0], dict) else getattr(rows[0], "id", None)
                        if pid:
                            s = snap(pid) or {}
                            return {
                                "available": True,
                                "equity": s.get("equity"),
                                "cash": s.get("cash"),
                                "total_return_pct": s.get("total_return_pct")
                                or s.get("return_pct"),
                            }
            return {"available": False, "note": "no portfolio rows"}
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("portfolio snapshot skipped: %s", exc)
            return {"available": False, "error": str(exc)}

    def _coverage_summary(self) -> dict[str, Any]:
        if self._coverage is None:
            return {"available": False}
        try:
            summary = self._coverage.summary()
            if isinstance(summary, dict):
                return {"available": True, **summary}
            return {"available": True, "raw": summary}
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("coverage summary skipped: %s", exc)
            return {"available": False}

    def _failed_learning_signals(self, *, limit: int) -> dict[str, Any]:
        """Best-effort: capability gaps + contested knowledge as failure signals."""
        items: list[str] = []
        if self._decisions is not None and hasattr(self._decisions, "list_gaps"):
            try:
                for g in self._decisions.list_gaps(limit=limit) or []:
                    items.append(
                        f"capability_gap: {g.get('capability') or g.get('why') or g}"
                    )
            except Exception:  # noqa: BLE001
                pass
        return {"count": len(items), "samples": items[:10]}


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "unknown").strip().lower() or "unknown"
        out[k] = out.get(k, 0) + 1
    return out


def _narrative(headline: dict[str, Any], sections: dict[str, Any]) -> str:
    lines = [
        "Daily Learning Governance Report",
        f"  New concepts                 {headline.get('new_concepts', 0)}",
        f"  New entities                 {headline.get('new_entities', 0)}",
        f"  New relationships            {headline.get('new_relationships', 0)}",
        f"  Lessons learned              {headline.get('lessons_learned', 0)}",
        f"  Knowledge conflicts          {headline.get('knowledge_conflicts', 0)}",
        f"  Failed learning signals      {headline.get('failed_learning', 0)}",
        f"  Capability gaps (decisions)  {headline.get('capability_gaps', 0)}",
    ]
    ret = headline.get("portfolio_return_pct")
    if ret is not None:
        lines.append(f"  Portfolio performance        {ret:+.2f}%")
    else:
        lines.append("  Portfolio performance        n/a")
    unver = (sections.get("knowledge") or {}).get("unverified_or_candidate", 0)
    lines.append(f"  Still unverified/candidate   {unver}")
    return "\n".join(lines)
