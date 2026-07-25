"""System Introspection — aggregate self-analysis report (OI-F3).

Answers: what do I know? what am I uncertain about? which readers fail most?
which missions cost most? which policies constrain decisions? what should I
improve next? Aggregates existing D.10 / P15 / coverage / arbiter / governance
signals — not a new OS box.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any


class IntrospectionService:
    """Build a periodic System Introspection report from existing platform signals."""

    name = "introspection"
    VERSION = "f3.1"

    def __init__(
        self,
        *,
        knowledge: Any | None = None,
        coverage: Any | None = None,
        capabilities: Any | None = None,
        decisions: Any | None = None,
        improvement_board: Any | None = None,
        arbiter: Any | None = None,
        policy: Any | None = None,
        governance: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._coverage = coverage
        self._capabilities = capabilities
        self._decisions = decisions
        self._board = improvement_board
        self._arbiter = arbiter
        self._policy = policy
        self._governance = governance
        self._logger = logger or logging.getLogger("atlas.introspection")

    def report(self, *, limit: int = 200) -> dict[str, Any]:
        knowledge = self._knowledge_section(limit=limit)
        uncertainty = self._uncertainty_section(knowledge)
        readers = self._readers_section()
        missions = self._missions_section()
        policies = self._policies_section(limit=limit)
        gaps = self._gaps_section(limit=limit)
        improve = self._improve_section()
        sections = {
            "knowledge": knowledge,
            "uncertainty": uncertainty,
            "readers": readers,
            "missions": missions,
            "policies": policies,
            "gaps": gaps,
            "improve_next": improve,
        }
        narrative = _narrative(sections)
        return {
            "report_kind": "system_introspection",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "sections": sections,
            "narrative": narrative,
            "note": (
                "OI-F3 System Introspection — aggregates D.10 / P15 / coverage / "
                "arbiter / policy; does not replace Self-Improvement Watcher"
            ),
            "version": self.VERSION,
        }

    def _guard(self, label: str, fn: Any, default: Any) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("%s skipped: %s", label, exc)
            return default

    def _knowledge_section(self, *, limit: int) -> dict[str, Any]:
        findings = self._guard(
            "list_findings",
            lambda: list(self._knowledge.list_findings(limit=limit) or [])
            if self._knowledge is not None
            else [],
            [],
        )
        by_status: dict[str, int] = {}
        by_maturity: dict[str, int] = {}
        by_domain: dict[str, int] = {}
        for f in findings:
            st = str(f.get("status") or "unknown").lower()
            mat = str(f.get("maturity") or "unknown").lower()
            dom = str(f.get("domain") or "unknown").lower()
            by_status[st] = by_status.get(st, 0) + 1
            by_maturity[mat] = by_maturity.get(mat, 0) + 1
            by_domain[dom] = by_domain.get(dom, 0) + 1
        cov = self._guard(
            "coverage.summary",
            lambda: self._coverage.summary() if self._coverage is not None else {},
            {},
        )
        overall = cov.get("overall") if isinstance(cov, dict) else {}
        return {
            "findings_scanned": len(findings),
            "by_status": by_status,
            "by_maturity": by_maturity,
            "by_domain": by_domain,
            "coverage_overall": overall or {},
        }

    def _uncertainty_section(self, knowledge: dict[str, Any]) -> dict[str, Any]:
        by_status = knowledge.get("by_status") or {}
        by_maturity = knowledge.get("by_maturity") or {}
        contested = int(by_status.get("contested", 0))
        candidate = int(by_maturity.get("candidate", 0))
        unverified = int(by_maturity.get("unverified", 0))
        return {
            "contested": contested,
            "candidate": candidate,
            "unverified": unverified,
            "uncertain_total": contested + candidate + unverified,
        }

    def _readers_section(self) -> dict[str, Any]:
        if self._coverage is None or not hasattr(self._coverage, "reader_failures"):
            return {"available": False, "ranked": []}
        ranked = self._guard("reader_failures", self._coverage.reader_failures, [])
        return {"available": True, "ranked": list(ranked or [])[:12]}

    def _missions_section(self) -> dict[str, Any]:
        if self._arbiter is None or not hasattr(self._arbiter, "snapshot"):
            return {"available": False}
        snap = self._guard("arbiter.snapshot", self._arbiter.snapshot, {})
        if not isinstance(snap, dict):
            return {"available": False}
        llm = snap.get("llm_units_in_window") or {}
        deferrals = snap.get("deferrals") or {}
        inflight = snap.get("inflight") or {}
        cost_ranked = sorted(
            (
                {
                    "mission_id": mid,
                    "llm_units": int(units or 0),
                    "deferrals": int(deferrals.get(mid, 0) or 0),
                    "inflight": int(inflight.get(mid, 0) or 0),
                }
                for mid, units in (llm.items() if isinstance(llm, dict) else [])
            ),
            key=lambda r: (r["llm_units"], r["deferrals"]),
            reverse=True,
        )
        # Also surface deferral-heavy missions with no LLM ledger entry.
        seen = {r["mission_id"] for r in cost_ranked}
        for mid, n in (deferrals.items() if isinstance(deferrals, dict) else []):
            if mid not in seen:
                cost_ranked.append(
                    {
                        "mission_id": mid,
                        "llm_units": 0,
                        "deferrals": int(n or 0),
                        "inflight": int(inflight.get(mid, 0) or 0),
                    }
                )
        cost_ranked.sort(key=lambda r: (r["llm_units"], r["deferrals"]), reverse=True)
        return {
            "available": True,
            "total_inflight": snap.get("total_inflight"),
            "global_max": snap.get("global_max"),
            "cost_ranked": cost_ranked[:12],
        }

    def _policies_section(self, *, limit: int) -> dict[str, Any]:
        if self._policy is None:
            return {"available": False, "blocking": []}
        rows: list[dict[str, Any]] = []
        if hasattr(self._policy, "list_rules"):
            rows = self._guard(
                "policy.list_rules",
                lambda: list(self._policy.list_rules(enabled=True, limit=limit) or []),
                [],
            )
        elif hasattr(self._policy, "list"):
            rows = self._guard(
                "policy.list",
                lambda: list(self._policy.list(enabled=True, limit=limit) or []),
                [],
            )
        blocking: list[dict[str, Any]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            rule = str(r.get("rule") or r.get("effect") or "").lower()
            if rule in {"forbid", "limit", "deny", "block"}:
                blocking.append(
                    {
                        "id": str(r.get("id") or ""),
                        "rule": rule,
                        "scope": r.get("scope"),
                        "name": r.get("name") or r.get("title"),
                    }
                )
        return {
            "available": True,
            "enabled_rules": len(rows),
            "blocking": blocking[:20],
        }

    def _gaps_section(self, *, limit: int) -> dict[str, Any]:
        cap_report: dict[str, Any] = {}
        if self._capabilities is not None and hasattr(self._capabilities, "self_report_gaps"):
            cap_report = self._guard(
                "self_report_gaps",
                lambda: self._capabilities.self_report_gaps() or {},
                {},
            )
        decision_gaps: list[Any] = []
        if self._decisions is not None and hasattr(self._decisions, "list_gaps"):
            decision_gaps = self._guard(
                "list_gaps",
                lambda: list(self._decisions.list_gaps(limit=limit) or []),
                [],
            )
        return {
            "capability_report": cap_report if isinstance(cap_report, dict) else {},
            "decision_gaps": decision_gaps[:20],
            "decision_gap_count": len(decision_gaps),
        }

    def _improve_section(self) -> dict[str, Any]:
        if self._board is None or not hasattr(self._board, "snapshot"):
            return {"available": False}
        snap = self._guard("improvement_board.snapshot", self._board.snapshot, {})
        if not isinstance(snap, dict):
            return {"available": False}
        return {
            "available": True,
            "finding_count": snap.get("finding_count", 0),
            "open_recommendations": snap.get("open_recommendations", 0),
            "last_run": snap.get("last_run"),
            "recommendations": list(snap.get("recommendations") or [])[:8],
            "findings": list(snap.get("findings") or [])[:8],
        }


def _narrative(sections: dict[str, Any]) -> str:
    know = sections.get("knowledge") or {}
    unc = sections.get("uncertainty") or {}
    readers = sections.get("readers") or {}
    missions = sections.get("missions") or {}
    policies = sections.get("policies") or {}
    gaps = sections.get("gaps") or {}
    improve = sections.get("improve_next") or {}
    overall = know.get("coverage_overall") or {}
    ranked = list(readers.get("ranked") or [])
    top_reader = ranked[0] if ranked else None
    cost = list(missions.get("cost_ranked") or [])
    top_mission = cost[0] if cost else None
    cap_sum = (gaps.get("capability_report") or {}).get("summary") or {}
    lines = [
        "System Introspection Report",
        f"  Findings known               {know.get('findings_scanned', 0)}",
        f"  Coverage overall             {overall.get('coverage_pct', 'n/a')}%",
        f"  Uncertain (contested+cand)   {unc.get('uncertain_total', 0)}",
        f"  Reader failures tracked      {len(ranked)}",
    ]
    if top_reader:
        lines.append(
            f"  Worst reader                 {top_reader.get('reader')} "
            f"(failed={top_reader.get('failed', 0)})"
        )
    else:
        lines.append("  Worst reader                 n/a")
    if top_mission:
        lines.append(
            f"  Costliest mission            {top_mission.get('mission_id')} "
            f"(llm={top_mission.get('llm_units', 0)}, "
            f"deferrals={top_mission.get('deferrals', 0)})"
        )
    else:
        lines.append("  Costliest mission            n/a")
    lines.append(f"  Blocking policy rules        {len(policies.get('blocking') or [])}")
    lines.append(f"  Decision capability gaps     {gaps.get('decision_gap_count', 0)}")
    if cap_sum:
        lines.append(f"  Catalog gaps summary         {cap_sum}")
    lines.append(
        f"  Improve-next open recs       {improve.get('open_recommendations', 0)}"
    )
    return "\n".join(lines)
