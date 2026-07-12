"""ResearchService — the gather → verify → decide loop (S21).

This is the orchestrator that turns the S13–S18 research tools and the S15 Verification
Engine / Evidence Graph into an autonomous, bounded research loop:

    for each planned query (scholar first, then web):
        gather sources  → add to a single EvidenceGraph claim
        verify_claim    → recompute calculated confidence + numeric convergence
        decide(iter)    → stop when the Evidence Budget is satisfied (convergence,
                          not a fixed count) or the iteration cap is hit; else continue
    → render a verified scientific-review report

Design goals:
- **Deterministic core, hermetic tests.** The query plan and numeric extraction are pure
  functions; the search providers are resolved through the capability registry (or
  injected directly), so the whole loop runs offline with fakes.
- **Honest + resilient (R2/R3).** No scholar/search capability ⇒ ``unavailable``; a
  provider that errors is skipped; the loop never raises into the caller.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from atlas.evidence.models import (
    Claim,
    EvidenceGraph,
    EvidenceItem,
    Source,
)
from atlas.research.classifier import classify
from atlas.verification.engine import EvidenceBudget

RESEARCH_OK = "ok"
RESEARCH_EMPTY = "empty"
RESEARCH_UNAVAILABLE = "unavailable"
RESEARCH_ERROR = "error"

# Query refinements appended to the cleaned objective, tried in order. Scholar (higher
# evidence levels) is tried before web for each variant.
_VARIANTS = ("", "data", "study", "measurement", "statistics", "review")
_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:do\s+(?:a|an)\s+)?(?:deep[\s-]?dive|research|investigate|"
    r"look\s+into|study|gather\s+evidence|find\s+evidence|find\s+out)\b"
    r"\s*(?:on|about|into|for|regarding|the\s+topic\s+of)?\s*[:,-]?\s*",
    re.IGNORECASE,
)
# A number that is not a bare 4-digit year (years are noise for convergence).
_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def clean_objective(objective: str) -> str:
    return _PREFIX_RE.sub("", objective or "").strip() or (objective or "").strip()


def query_plan(objective: str, *, max_iterations: int) -> list[tuple[str, str]]:
    """Deterministic (mode, query) plan: scholar then web, over query variants."""
    base = clean_objective(objective)
    plan: list[tuple[str, str]] = []
    for suffix in _VARIANTS:
        query = f"{base} {suffix}".strip()
        plan.append(("scholar", query))
        plan.append(("web", query))
    return plan[:max_iterations]


def extract_value(text: str) -> float | None:
    """First non-year number in ``text`` (drives convergence), or None."""
    if not text:
        return None
    for token in _NUMBER_RE.findall(text):
        cleaned = token.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        # Skip bare 4-digit years (e.g. "2021") which would pollute convergence.
        if cleaned.isdigit() and len(cleaned) == 4 and 1800 <= value <= 2100:
            continue
        return value
    return None


@dataclass(frozen=True)
class _Gathered:
    source: Source
    value: float | None
    snippet: str


class ResearchService:
    name = "research"

    def __init__(
        self,
        verification,
        reports,
        *,
        capabilities=None,
        scholar=None,
        search=None,
        per_query: int = 5,
        logger: logging.Logger | None = None,
    ) -> None:
        self._verification = verification
        self._reports = reports
        self._capabilities = capabilities
        self._scholar = scholar
        self._search = search
        self._per_query = per_query
        self._logger = logger or logging.getLogger("atlas.research")

    # --- capability -----------------------------------------------------
    def research(
        self,
        objective: str,
        *,
        budget: dict[str, Any] | None = None,
        max_iterations: int | None = None,
        per_query: int | None = None,
    ) -> dict[str, Any]:
        objective = (objective or "").strip()
        if not objective:
            return {"outcome": RESEARCH_ERROR, "reason": "empty objective"}

        scholar = self._resolve("scholar", self._scholar)
        search = self._resolve("search", self._search)
        if scholar is None and search is None:
            return {
                "outcome": RESEARCH_UNAVAILABLE,
                "objective": objective,
                "reason": "no research providers available (need scholar and/or search)",
            }

        eb = self._budget(budget, max_iterations)
        n = per_query or self._per_query
        graph = EvidenceGraph()
        claim = Claim(id="c1", statement=objective)
        graph.add_claim(claim)

        seen: set[str] = set()
        log: list[dict[str, Any]] = []
        decision = None
        iterations = 0

        # Only plan rounds for providers we actually have, then apply the iteration cap
        # to real gathering rounds (a missing provider must not burn the budget).
        full_plan = query_plan(objective, max_iterations=len(_VARIANTS) * 2)
        plan = [
            (mode, query) for mode, query in full_plan
            if (mode == "scholar" and scholar is not None)
            or (mode == "web" and search is not None)
        ][: eb.max_search_iterations]

        for mode, query in plan:
            provider = scholar if mode == "scholar" else search
            iterations += 1
            added = self._absorb(self._gather(mode, provider, query, n), claim, graph, seen)
            self._verification.verify_claim(claim)
            decision = self._verification.decide(claim, iteration=iterations, budget=eb)
            log.append({
                "iteration": iterations,
                "mode": mode,
                "query": query,
                "added": added,
                "total_sources": len(claim.evidence),
                "convergence": round(decision.convergence, 3),
                "decision": decision.decision,
            })
            if decision.should_stop:
                break

        if not claim.evidence:
            return {
                "outcome": RESEARCH_EMPTY,
                "objective": objective,
                "iterations": iterations,
                "reason": "no evidence gathered from the available providers",
                "log": log,
            }

        report_bundle = self._render(objective, graph, eb)
        return {
            "outcome": RESEARCH_OK,
            "objective": objective,
            "iterations": iterations,
            "stopped": decision.as_dict() if decision is not None else None,
            "claim": claim.as_dict(),
            "graph": graph.as_dict(),
            "verification": report_bundle.get("verification"),
            "report": report_bundle.get("report"),
            "log": log,
        }

    # --- gather ---------------------------------------------------------
    def _gather(self, mode: str, provider, query: str, n: int) -> list[_Gathered]:
        try:
            if mode == "scholar":
                resp = provider.search_scholar(query, max_results=n)
                if getattr(resp, "outcome", None) != "ok":
                    return []
                out = []
                for paper in getattr(resp, "papers", []):
                    src = Source.from_dict(paper.as_source())
                    text = getattr(paper, "abstract", "") or getattr(paper, "title", "")
                    out.append(_Gathered(src, extract_value(text), text[:300]))
                return out
            resp = provider.search_web(query, max_results=n)
            if getattr(resp, "outcome", None) != "ok":
                return []
            out = []
            for hit in getattr(resp, "hits", []):
                url = getattr(hit, "url", "") or ""
                sid = url or (getattr(hit, "title", "") or "")[:60]
                if not sid:
                    continue
                # §2.2 fix (C3): classify the source instead of hardcoding L2, so the
                # peer-reviewed / government / preprint signal reaches the Evidence
                # Budget (a web hit to ieeexplore is L4, to arxiv L3, to a forum L1).
                cls = classify(url)
                src = Source(
                    id=sid, title=getattr(hit, "title", ""), url=url,
                    evidence_level=cls.evidence_level, kind=cls.kind,
                )
                snippet = getattr(hit, "snippet", "") or ""
                out.append(_Gathered(src, extract_value(snippet), snippet[:300]))
            return out
        except Exception:  # noqa: BLE001 - a bad provider must not crash the loop (R3)
            self._logger.exception("research provider %s failed", mode)
            return []

    @staticmethod
    def _absorb(
        gathered: list[_Gathered], claim: Claim, graph: EvidenceGraph, seen: set[str]
    ) -> int:
        added = 0
        for item in gathered:
            if item.source.id in seen:
                continue
            seen.add(item.source.id)
            graph.add_source(item.source)
            claim.evidence.append(EvidenceItem(
                source_id=item.source.id,
                evidence_level=item.source.evidence_level,
                extracted_value=item.value,
                snippet=item.snippet,
            ))
            added += 1
        return added

    def _render(self, objective: str, graph: EvidenceGraph, eb: EvidenceBudget) -> dict[str, Any]:
        try:
            return self._reports.report(objective, graph.as_dict(), budget=eb.as_dict())
        except Exception:  # noqa: BLE001 - a report must never fail the research result
            self._logger.exception("report generation failed")
            return {}

    # --- helpers --------------------------------------------------------
    def _resolve(self, name: str, injected):
        if injected is not None:
            return injected
        caps = self._capabilities
        if caps is not None and caps.has(name):
            try:
                return caps.get(name)
            except Exception:  # noqa: BLE001 - registry miss => provider unavailable
                return None
        return None

    def _budget(self, override: dict[str, Any] | None, max_iterations: int | None) -> EvidenceBudget:
        base = getattr(self._verification, "default_budget", None) or EvidenceBudget()
        eb = EvidenceBudget(
            min_sources=base.min_sources,
            min_peer_reviewed=base.min_peer_reviewed,
            min_government=base.min_government,
            convergence=base.convergence,
            max_search_iterations=base.max_search_iterations,
        )
        for key in ("min_sources", "min_peer_reviewed", "min_government",
                    "convergence", "max_search_iterations"):
            if override and key in override and override[key] is not None:
                setattr(eb, key, override[key])
        if max_iterations is not None:
            eb.max_search_iterations = max_iterations
        return eb

    # --- lifecycle (registered as a service) ---------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self):
        from atlas.services.base import HealthStatus

        have = [n for n in ("scholar", "search")
                if self._resolve(n, getattr(self, f"_{n}")) is not None]
        return HealthStatus(
            healthy=True,
            detail=(f"research ready (providers: {', '.join(have)})" if have
                    else "research idle (no scholar/search providers)"),
            data={"providers": have},
        )
