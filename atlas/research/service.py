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
    CONFIDENCE_INSUFFICIENT,
    Claim,
    EvidenceGraph,
    EvidenceItem,
    Source,
)
from atlas.research.classifier import classify
from atlas.research.grouping import group_claims
from atlas.research.reader import Reader
from atlas.verification.engine import EvidenceBudget

# A candidate's abstract/snippet must have at least this much text before we treat it as
# a Tier-1 "document" worth extracting from — a 10-word web snippet is not a paper.
_MIN_TIER1_CHARS = 80

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
    full_text: str = ""  # abstract (scholar) or snippet (web); used by the deep READ path


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
        librarian=None,
        extractor=None,
        reader: Reader | None = None,
        per_query: int = 5,
        max_documents: int = 12,
        logger: logging.Logger | None = None,
    ) -> None:
        self._verification = verification
        self._reports = reports
        self._capabilities = capabilities
        self._scholar = scholar
        self._search = search
        # Stage 3, Step 5 (C4): when a Librarian (acquire+read) and a ClaimExtractor are
        # wired, research runs the real Acquire→Read→Extract→Group→Verify pipeline on
        # structured claims. Without them it degrades to the Tier-0 snippet loop (below),
        # so the class stays usable — and every legacy test — with no extra collaborators.
        self._librarian = librarian
        self._extractor = extractor
        self._reader = reader or Reader()
        self._per_query = per_query
        self._max_documents = max_documents
        self._logger = logger or logging.getLogger("atlas.research")

    # --- capability -----------------------------------------------------
    def research(
        self,
        objective: str,
        *,
        budget: dict[str, Any] | None = None,
        max_iterations: int | None = None,
        per_query: int | None = None,
        activity: Any = None,
        workspace: Any = None,
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

        # Deep pipeline (C4): read documents and extract structured claims instead of
        # scoring URLs. Requires a ClaimExtractor; the Librarian is optional (abstracts
        # alone still yield Tier-1 claims), which keeps it working when fetch is offline.
        if self._extractor is not None:
            return self._research_deep(
                objective, eb, n, scholar, search,
                activity=activity, workspace=workspace,
            )

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

    # --- deep pipeline (Stage 3, Steps 5–6 / §5d–5i, C4/C5) -------------
    def _research_deep(
        self, objective: str, eb: EvidenceBudget, n: int, scholar, search,
        *, activity: Any, workspace: Any,
    ) -> dict[str, Any]:
        """Search → acquire → read → extract → group → verify, gap-driven (C5)."""
        from atlas.research.gaps import (
            analyze_gaps,
            gap_queries,
            recommend_reading,
        )

        base = clean_objective(objective)
        graph = EvidenceGraph()
        candidates: dict[str, _Gathered] = {}
        documents: dict[str, Any] = {}
        blocked: list[dict[str, Any]] = []
        raw: list[Claim] = []
        rounds_log: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        status = None
        acquired_full = 0

        # Seed the first round with the base objective (scholar then web).
        pending_plan: list[tuple[str, str]] = []
        if scholar is not None:
            pending_plan.append(("scholar", base))
        if search is not None:
            pending_plan.append(("web", base))

        for round_i in range(1, eb.max_search_iterations + 1):
            # 1) Gather any pending gap-/seed-targeted queries.
            if pending_plan:
                before = len(candidates)
                self._absorb_candidates(
                    pending_plan, candidates, n, scholar, search, activity
                )
                rounds_log.append({
                    "round": round_i,
                    "queries": list(pending_plan),
                    "new_candidates": len(candidates) - before,
                    "total_candidates": len(candidates),
                })
                pending_plan = []

            if not candidates and not documents:
                break

            # Register sources on the graph.
            for g in candidates.values():
                if g.source.id not in graph.sources:
                    graph.add_source(g.source)

            # 2) Acquire remaining capacity (open-access first).
            remaining = max(0, self._max_documents - len(documents))
            unread = [
                g.source for sid, g in candidates.items() if sid not in documents
            ]
            if remaining > 0 and unread:
                new_docs, new_blocked, n_full = self._acquire_unread(
                    unread, remaining, workspace, activity
                )
                documents.update(new_docs)
                blocked.extend(new_blocked)
                acquired_full += n_full
                # Tier-1 fallback for anything still unread with a usable abstract.
                for sid, g in candidates.items():
                    if sid in documents or len(documents) >= self._max_documents:
                        continue
                    text = (g.full_text or "").strip()
                    if len(text) >= _MIN_TIER1_CHARS:
                        documents[sid] = self._reader.read_text(
                            text, source_id=sid, title=g.source.title, url=g.source.url,
                        )

            # 3) Extract claims from newly-read docs not yet extracted.
            extracted_ids = {c.evidence[0].source_id for c in raw if c.evidence}
            for sid, doc in documents.items():
                if sid in extracted_ids:
                    continue
                level = graph.sources[sid].evidence_level if sid in graph.sources else None
                try:
                    res = self._extractor.extract(
                        doc, evidence_level=level, activity=activity
                    )
                    raw.extend(res.claims)
                except Exception:  # noqa: BLE001
                    self._logger.exception("claim extraction failed for %s", sid)

            # 4) Group + verify (fresh each round — merging is cheap and deterministic).
            grouped = group_claims(raw)
            graph.claims.clear()
            for claim in grouped:
                graph.add_claim(claim)
                self._verification.verify_claim(claim)

            status = analyze_gaps(graph, eb)
            self._record(
                activity, "verify",
                f"Round {round_i}: {len(grouped)} claim(s) from {len(documents)} "
                f"doc(s); gaps: "
                + (", ".join(g.kind for g in status.gaps) or "none"),
            )
            if rounds_log:
                rounds_log[-1]["gaps"] = [g.kind for g in status.gaps]
                rounds_log[-1]["claims"] = len(grouped)

            # 5) Stop if budget satisfied.
            if not status.has_gaps:
                self._record(activity, "lifecycle", "Evidence budget satisfied.")
                break

            # 6) Doc-cap hit with remaining gaps → recommend further reading & stop.
            if len(documents) >= self._max_documents:
                still_unread = [
                    g.source for sid, g in candidates.items() if sid not in documents
                ]
                recommendations = recommend_reading(still_unread, status.gaps)
                self._record(
                    activity, "lifecycle",
                    f"Document cap ({self._max_documents}) reached with unmet gaps; "
                    f"recommending {len(recommendations)} further source(s).",
                )
                break

            # 7) Plan the next round from named gaps (C5) — not synonym cycling.
            pending_plan = [
                (mode, q) for mode, q in gap_queries(objective, status.gaps, base=base)
                if (mode == "scholar" and scholar is not None)
                or (mode == "web" and search is not None)
            ]
            # Drop queries we've already tried this run.
            tried = {(m, q) for entry in rounds_log for m, q in entry.get("queries", [])}
            pending_plan = [(m, q) for m, q in pending_plan if (m, q) not in tried]
            if not pending_plan:
                self._record(
                    activity, "lifecycle",
                    "No further gap-targeted queries available; stopping.",
                )
                break

        if not candidates and not documents:
            return {
                "outcome": RESEARCH_EMPTY,
                "objective": objective,
                "iterations": 0,
                "reason": "no candidate sources gathered from the available providers",
                "log": rounds_log,
            }

        grouped = list(graph.claims.values())
        verified = sum(1 for c in grouped if c.confidence != CONFIDENCE_INSUFFICIENT)
        pipeline = {
            "found": len(candidates),
            "acquired": acquired_full,
            "read": len(documents),
            "extracted": len(raw),
            "claims": len(grouped),
            "verified": verified,
            "rejected": len(grouped) - verified,
            "blocked": len(blocked),
            "rounds": len(rounds_log),
        }
        gap_note = ""
        if status is not None and status.has_gaps:
            gap_note = " Unmet gaps: " + "; ".join(g.reason for g in status.gaps) + "."
        notes = (
            f"Pipeline: found {pipeline['found']} sources → acquired {pipeline['acquired']} "
            f"full-text → read {pipeline['read']} → extracted {pipeline['extracted']} claims "
            f"→ verified {pipeline['verified']} (rejected {pipeline['rejected']}) "
            f"over {pipeline['rounds']} round(s)."
            + gap_note
        )
        self._persist_artifacts(workspace, graph, pipeline, notes)
        report_bundle = self._render(objective, graph, eb, notes=notes)
        report = report_bundle.get("report") or {}
        # Surface recommendations inside the report's next_research when present.
        if recommendations and report.get("sections"):
            rec_lines = [
                f"- {r['title']}" + (f" — {r['url']}" if r.get("url") else "")
                + f" ({r['why']})"
                for r in recommendations
            ]
            existing = report["sections"].get("next_research") or ""
            report["sections"]["next_research"] = (
                (existing.rstrip() + "\n\n" if existing else "")
                + "Recommended further reading:\n" + "\n".join(rec_lines)
            )
            if report.get("markdown"):
                report["markdown"] = report["markdown"].rstrip() + (
                    "\n\n## Recommended Further Reading\n"
                    + "\n".join(rec_lines) + "\n"
                )
        overall = report.get("overall_confidence", CONFIDENCE_INSUFFICIENT)
        stopped_reasons = (
            ["all budget criteria met"]
            if status is not None and not status.has_gaps
            else ([g.reason for g in status.gaps] if status else [])
        )
        if recommendations:
            stopped_reasons = stopped_reasons + [
                f"document cap ({self._max_documents}) reached; "
                f"{len(recommendations)} further source(s) recommended"
            ]
        return {
            "outcome": RESEARCH_OK,
            "objective": objective,
            "iterations": pipeline["rounds"],
            "claim": {"confidence": overall, "confidence_score": None, "convergence":
                      status.convergence if status else None},
            "stopped": {
                "decision": "stop",
                "reasons": stopped_reasons or [notes],
                "convergence": status.convergence if status else None,
                "met": status.met if status else {},
            },
            "graph": graph.as_dict(),
            "verification": report_bundle.get("verification"),
            "report": report,
            "pipeline": pipeline,
            "blocked": blocked,
            "gaps": status.as_dict() if status else {},
            "recommendations": recommendations,
            "log": rounds_log,
        }

    def _absorb_candidates(
        self,
        plan: list[tuple[str, str]],
        candidates: dict[str, _Gathered],
        n: int,
        scholar,
        search,
        activity: Any,
    ) -> None:
        for mode, query in plan:
            provider = scholar if mode == "scholar" else search
            if provider is None:
                continue
            self._record(activity, "search", f"Searching {mode}: {query!r}")
            for g in self._gather(mode, provider, query, n):
                candidates.setdefault(g.source.id, g)
        self._record(
            activity, "search", f"Candidate pool now {len(candidates)} source(s)."
        )

    def _acquire_unread(
        self,
        unread: list[Source],
        remaining: int,
        workspace: Any,
        activity: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        """Acquire up to ``remaining`` unread sources. Returns (docs, blocked, n_full)."""
        documents: dict[str, Any] = {}
        blocked: list[dict[str, Any]] = []
        acquired_full = 0
        if self._librarian is None or remaining <= 0:
            return documents, blocked, acquired_full
        try:
            acq = self._librarian.acquire(
                unread,
                workspace=workspace,
                activity=activity,
                top_k=remaining,
            )
            for doc in acq.documents:
                documents[doc.source_id] = doc
            blocked = list(getattr(acq, "blocked", []) or [])
            acquired_full = len(documents)
        except Exception:  # noqa: BLE001
            self._logger.exception("acquisition failed; falling back to abstracts")
        return documents, blocked, acquired_full

    def _collect_candidates(
        self, objective: str, eb: EvidenceBudget, n: int, scholar, search, activity: Any,
    ) -> dict[str, _Gathered]:
        """Legacy one-shot gather (kept for the Tier-0 snippet loop helpers)."""
        full_plan = query_plan(objective, max_iterations=len(_VARIANTS) * 2)
        plan = [
            (mode, query) for mode, query in full_plan
            if (mode == "scholar" and scholar is not None)
            or (mode == "web" and search is not None)
        ][: eb.max_search_iterations]
        target = max(self._max_documents * 2, self._max_documents + 5)
        candidates: dict[str, _Gathered] = {}
        for mode, query in plan:
            provider = scholar if mode == "scholar" else search
            self._record(activity, "search", f"Searching {mode}: {query!r}")
            for g in self._gather(mode, provider, query, n):
                candidates.setdefault(g.source.id, g)
            if len(candidates) >= target:
                break
        self._record(activity, "search",
                     f"Gathered {len(candidates)} candidate source(s).")
        return candidates

    @staticmethod
    def _record(activity: Any, phase: str, message: str) -> None:
        if activity is None:
            return
        try:
            activity.record(phase, message)
        except Exception:  # noqa: BLE001 - the feed is best-effort, never fatal
            pass

    @staticmethod
    def _persist_artifacts(
        workspace: Any, graph: EvidenceGraph, pipeline: dict[str, Any], notes: str,
    ) -> None:
        """Write claims/evidence/manifest into the job workspace (best-effort)."""
        if workspace is None:
            return
        try:
            workspace.write_json("claims.json", [c.as_dict() for c in graph.claims.values()])
            workspace.write_json("evidence.json", graph.as_dict())
            workspace.append_note(notes)
            if hasattr(workspace, "load_manifest") and hasattr(workspace, "write_json"):
                manifest = workspace.load_manifest()
                counts = manifest.setdefault("counts", {})
                for key, field in (
                    ("found", "found"),
                    ("acquired", "downloaded"),
                    ("read", "read"),
                    ("extracted", "extracted"),
                    ("verified", "verified"),
                ):
                    counts[field] = max(int(counts.get(field, 0)), int(pipeline.get(key, 0)))
                from datetime import datetime, timezone
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                workspace.write_json("manifest.json", manifest)
        except Exception:  # noqa: BLE001 - workspace I/O must never fail research
            pass

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
                    out.append(_Gathered(src, extract_value(text), text[:300], full_text=text))
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
                out.append(_Gathered(src, extract_value(snippet), snippet[:300], full_text=snippet))
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

    def _render(
        self, objective: str, graph: EvidenceGraph, eb: EvidenceBudget, *, notes: str = "",
    ) -> dict[str, Any]:
        try:
            return self._reports.report(
                objective, graph.as_dict(), budget=eb.as_dict(), notes=notes
            )
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
