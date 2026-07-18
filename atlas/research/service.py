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
    level_name,
)
from atlas.research.classifier import classify
from atlas.research.grouping import group_claims
from atlas.research.reader import Reader
from atlas.research.relevance import filter_relevant, score_relevance
from atlas.verification.engine import EvidenceBudget

# A candidate's abstract/snippet must have at least this much text before we treat it as
# a Tier-1 "document" worth extracting from — a 10-word web snippet is not a paper.
# Abstracts/snippets need real substance before we treat them as extractable
# "documents". Publisher landing pages (~200–400 chars) used to inflate the
# doc count, burn extract calls, and starve gap follow-ups.
_MIN_TIER1_CHARS = 500

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
        resources=None,
        execution=None,
        per_query: int = 5,
        max_documents: int = 12,
        max_extract_workers: int = 1,
        max_worker_threads: int = 4,
        knowledge=None,
        prior_k: int = 5,
        synthesizer=None,
        learning=None,
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
        self._resources = resources
        self._execution = execution
        self._knowledge = knowledge
        self._prior_k = max(1, int(prior_k or 5))
        self._synthesizer = synthesizer
        self._learning = learning
        self._per_query = per_query
        self._max_documents = max_documents
        self._max_extract_workers = max(1, int(max_extract_workers or 1))
        self._max_worker_threads = max(1, int(max_worker_threads or 1))
        self._logger = logger or logging.getLogger("atlas.research")
        self._last_throttle_reason: str | None = None

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
        resource_profile: str | None = None,
    ) -> dict[str, Any]:
        objective = (objective or "").strip()
        if not objective:
            return {"outcome": RESEARCH_ERROR, "reason": "empty objective"}

        prior = self._recall_prior(objective, activity=activity, workspace=workspace)
        advice = self._recall_advice(objective, activity=activity, workspace=workspace)

        scholar = self._resolve("scholar", self._scholar)
        search = self._resolve("search", self._search)
        if scholar is None and search is None:
            return {
                "outcome": RESEARCH_UNAVAILABLE,
                "objective": objective,
                "reason": "no research providers available (need scholar and/or search)",
                "prior_knowledge": prior,
                "experience_advice": advice,
            }

        eb = self._budget(budget, max_iterations)
        n = per_query or self._per_query

        # Deep pipeline (C4): read documents and extract structured claims instead of
        # scoring URLs. Requires a ClaimExtractor; the Librarian is optional (abstracts
        # alone still yield Tier-1 claims), which keeps it working when fetch is offline.
        if self._extractor is not None:
            result = self._research_deep(
                objective, eb, n, scholar, search,
                activity=activity, workspace=workspace,
                resource_profile=resource_profile,
            )
            if prior is not None:
                result = {**result, "prior_knowledge": prior}
            if advice is not None:
                result = {**result, "experience_advice": advice}
            return result

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
                "prior_knowledge": prior,
                "experience_advice": advice,
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
            "prior_knowledge": prior,
            "experience_advice": advice,
        }

    # --- deep pipeline (Stage 3, Steps 5–6 / §5d–5i, C4/C5) -------------
    def _research_deep(
        self, objective: str, eb: EvidenceBudget, n: int, scholar, search,
        *, activity: Any, workspace: Any, resource_profile: str | None = None,
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

        # Stage 3.2c: ask Resource Manager for pool sizes; surface protection posture.
        self._apply_resource_advice(activity, resource_profile)

        # Seed the first round with the base objective (scholar then web).
        pending_plan: list[tuple[str, str]] = []
        if scholar is not None:
            pending_plan.append(("scholar", base))
        if search is not None:
            pending_plan.append(("web", base))

        for round_i in range(1, eb.max_search_iterations + 1):
            # Re-check pressure each round (detect → slow).
            self._apply_resource_advice(activity, resource_profile, quiet=True)
            # 0) Incorporate any human input queued while this job is running.
            self._absorb_user_inputs(
                workspace, activity, pending_plan, scholar, search
            )

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

            # 2) Relevance gate, then acquire remaining capacity (open-access first).
            remaining = max(0, self._max_documents - len(documents))
            unread_gathered = [
                g for sid, g in candidates.items() if sid not in documents
            ]
            kept, dropped = filter_relevant(objective, unread_gathered)
            if dropped:
                self._record(
                    activity, "search",
                    f"Relevance filter dropped {len(dropped)} off-topic candidate(s).",
                )
                # Remove dropped from the candidate pool so they don't fill the cap later.
                for item, _rel in dropped:
                    sid = item.source.id if hasattr(item, "source") else getattr(item, "id", "")
                    candidates.pop(sid, None)
                    graph.sources.pop(sid, None)
            # Prefer higher-evidence, on-topic sources when filling the doc budget.
            kept.sort(
                key=lambda g: (
                    score_relevance(
                        objective, title=g.source.title,
                        snippet=g.snippet, url=g.source.url,
                    ).score,
                    g.source.evidence_level,
                ),
                reverse=True,
            )
            unread = [g.source for g in kept]
            if remaining > 0 and unread:
                new_docs, new_blocked, n_full = self._acquire_unread(
                    unread, remaining, workspace, activity
                )
                documents.update(new_docs)
                blocked.extend(new_blocked)
                acquired_full += n_full
                blocked_ids = {
                    str(b.get("source_id") or b.get("url") or "")
                    for b in new_blocked
                    if isinstance(b, dict)
                }
                # Tier-1 fallback: usable abstracts only — never for paywalled
                # sources we already skipped (those stubs yield 0 claims).
                for g in kept:
                    sid = g.source.id
                    if sid in documents or len(documents) >= self._max_documents:
                        continue
                    if sid in blocked_ids or g.source.url in blocked_ids:
                        continue
                    text = (g.full_text or "").strip()
                    if len(text) >= _MIN_TIER1_CHARS:
                        documents[sid] = self._reader.read_text(
                            text, source_id=sid, title=g.source.title, url=g.source.url,
                        )

            # 3) Extract claims from newly-read docs not yet extracted (parallel under caps).
            new_claims = self._extract_parallel(
                documents, raw, graph, activity
            )
            raw.extend(new_claims)

            # 4) Group + verify (fresh each round — merging is cheap and deterministic).
            # Sort evidence by source_id before grouping for stable ordering (D32.4).
            grouped = group_claims(raw)
            graph.claims.clear()
            for claim in sorted(grouped, key=lambda c: c.id if hasattr(c, "id") else str(c)):
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
        # Authoritative acquisition/extraction funnel (report must match runtime).
        read_ok = sum(1 for d in documents.values() if getattr(d, "has_text", False))
        reader_failures = len(documents) - read_ok
        paywalled = sum(
            1 for b in blocked if (b.get("failure_code") or "") == "paywall"
        ) or len(blocked)
        sources_with_claims = len(
            {c.evidence[0].source_id for c in raw if c.evidence}
        )
        extract_failed = max(read_ok - sources_with_claims, 0)
        numeric_claims = sum(
            1 for c in raw
            if c.evidence and not c.evidence[0].inferred and c.value is not None
        )
        prose_claims = sum(
            1 for c in raw
            if c.evidence and not c.evidence[0].inferred
            and (c.evidence[0].locator or "").startswith("prose:")
        )
        inferred_claims = sum(1 for c in raw if c.evidence and c.evidence[0].inferred)
        pipeline = {
            "found": len(candidates),
            "acquired": acquired_full,
            "read": read_ok,
            "reader_failures": reader_failures,
            "paywalled": paywalled,
            "extract_ok": sources_with_claims,
            "extract_failed": extract_failed,
            "extracted": len(raw),
            "claims": len(grouped),
            "numeric_claims": numeric_claims,
            "prose_claims": prose_claims,
            "inferred_claims": inferred_claims,
            "verified": verified,
            "rejected": len(grouped) - verified,
            "blocked": len(blocked),
            "rounds": len(rounds_log),
            "chars_read": sum(len(getattr(d, "text", "") or "") for d in documents.values()),
            "documents_read": len(documents),
        }
        gap_note = ""
        if status is not None and status.has_gaps:
            gap_note = " Unmet gaps: " + "; ".join(g.reason for g in status.gaps) + "."
        # Honest funnel narrative — every stage reconciles with the counters below.
        notes = (
            f"Pipeline: found {pipeline['found']} source(s) → acquired "
            f"{pipeline['acquired']} → read {pipeline['read']} "
            f"({pipeline['reader_failures']} reader failure(s), "
            f"{pipeline['paywalled']} paywalled) → {pipeline['extract_ok']} produced "
            f"claims / {pipeline['extract_failed']} yielded none → extracted "
            f"{pipeline['extracted']} claim(s) "
            f"({pipeline['numeric_claims']} numeric, {pipeline['prose_claims']} prose, "
            f"{pipeline['inferred_claims']} inferred) → verified "
            f"{pipeline['verified']} (rejected {pipeline['rejected']}) over "
            f"{pipeline['rounds']} round(s)."
            + gap_note
        )
        findings = self._synthesize_findings(
            graph,
            objective=objective,
            workspace=workspace,
            documents=documents,
        )
        pipeline["findings"] = len(findings)
        reasoning = self._reason_across(
            findings or list(graph.claims.values()),
            gaps=status,
            objective=objective,
            activity=activity,
        )
        edges = reasoning.get("edges") or []
        pipeline["edges"] = len(edges)
        pipeline["contradictions"] = sum(
            1 for e in edges if (e.get("relation") if isinstance(e, dict) else "") == "contradict"
        )
        pipeline["patterns"] = len(reasoning.get("patterns") or [])
        pipeline["opportunities"] = len(reasoning.get("opportunities") or [])
        pipeline["hypotheses"] = len(reasoning.get("hypotheses") or [])
        # Per-source pipeline trace (§3B hardening): a structured state object for
        # every source — search → acquire → read → extract → verify → findings —
        # so a regression in any stage is diagnosable in minutes, per source.
        trace = self._build_source_traces(
            candidates, documents, raw, graph, findings, blocked
        )
        pipeline["trace"] = trace
        self._record_trace(activity, workspace, trace)
        self._persist_artifacts(
            workspace, graph, pipeline, notes, findings=findings, reasoning=reasoning
        )
        report_bundle = self._render(
            objective, graph, eb, notes=notes, findings=findings,
            reasoning=reasoning, pipeline=pipeline,
        )
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
            "findings": [f.as_dict() for f in findings],
            "reasoning": reasoning,
            "log": rounds_log,
        }

    def _apply_resource_advice(
        self,
        activity: Any,
        profile: str | None = None,
        *,
        quiet: bool = False,
    ) -> None:
        """Ask the Resource Manager for pool sizes; throttle when pressure detected."""
        if self._resources is None:
            return
        try:
            rec = self._resources.recommend_pool_sizes(profile=profile)
        except Exception:  # noqa: BLE001 - RM must never break research
            self._logger.debug("resource manager advice failed", exc_info=True)
            return
        self._max_extract_workers = max(1, int(rec.extract_workers))
        self._max_worker_threads = max(1, int(rec.global_max))
        if self._librarian is not None:
            try:
                self._librarian._max_workers = max(1, int(rec.acquire_workers))
                self._librarian._global_max_workers = max(1, int(rec.global_max))
            except Exception:  # noqa: BLE001
                pass
        if quiet and rec.throttle_reason == self._last_throttle_reason:
            return
        if rec.throttled:
            self._last_throttle_reason = rec.throttle_reason
            self._record(
                activity,
                "lifecycle",
                f"Slowing for system protection: {rec.throttle_reason} "
                f"(workers→1; {rec.protection.get('message', '')})",
                throttled=True,
                profile=rec.profile,
            )
        elif not quiet:
            self._last_throttle_reason = None
            self._record(
                activity,
                "lifecycle",
                f"Resources: profile={rec.profile}, acquire≤{rec.acquire_workers}, "
                f"extract≤{rec.extract_workers}; {rec.protection.get('message', '')}",
                profile=rec.profile,
                acquire_workers=rec.acquire_workers,
                extract_workers=rec.extract_workers,
            )
        elif self._last_throttle_reason and not rec.throttled:
            self._last_throttle_reason = None
            self._record(
                activity,
                "lifecycle",
                f"Resource pressure eased — resuming profile={rec.profile} "
                f"(acquire≤{rec.acquire_workers}, extract≤{rec.extract_workers})",
                profile=rec.profile,
            )

    def _absorb_user_inputs(
        self,
        workspace: Any,
        activity: Any,
        pending_plan: list[tuple[str, str]],
        scholar,
        search,
    ) -> None:
        """Pull queued human guidance into the next search plan (between rounds)."""
        if workspace is None or not hasattr(workspace, "pending_user_inputs"):
            return
        try:
            texts = workspace.pending_user_inputs()
        except Exception:  # noqa: BLE001
            return
        for text in texts:
            preview = text if len(text) <= 120 else text[:117] + "…"
            self._record(activity, "lifecycle", f"Incorporating your input: {preview}")
            if scholar is not None:
                pending_plan.append(("scholar", text))
            if search is not None:
                pending_plan.append(("web", text))
            # If neither provider is up, still keep the note for the report trail.
            if scholar is None and search is None:
                try:
                    workspace.append_note(f"user input (no search provider): {text}")
                except Exception:  # noqa: BLE001
                    pass

    def _absorb_candidates(
        self,
        plan: list[tuple[str, str]],
        candidates: dict[str, _Gathered],
        n: int,
        scholar,
        search,
        activity: Any,
    ) -> None:
        # Canonical identity map so arxiv/ar5iv/PDF/DOI representations of the same
        # paper collapse into one logical source (never counted as two studies).
        from atlas.research.acquire import canonical_source_id

        canon: dict[str, str] = {}
        for sid, g in candidates.items():
            canon.setdefault(canonical_source_id(g.source), sid)
        collapsed = 0
        for mode, query in plan:
            provider = scholar if mode == "scholar" else search
            if provider is None:
                continue
            self._record(activity, "search", f"Searching {mode}: {query!r}")
            for g in self._gather(mode, provider, query, n):
                sid = g.source.id
                if sid in candidates:
                    continue
                key = canonical_source_id(g.source)
                existing_sid = canon.get(key)
                if existing_sid is not None:
                    # Same paper, different representation → keep the better one.
                    if self._prefer_representation(g, candidates.get(existing_sid)):
                        candidates.pop(existing_sid, None)
                        candidates[sid] = g
                        canon[key] = sid
                    collapsed += 1
                    continue
                candidates[sid] = g
                canon[key] = sid
        if collapsed:
            self._record(
                activity, "search",
                f"Collapsed {collapsed} duplicate representation(s) of the same "
                f"paper (canonical identity).",
            )
        self._record(
            activity, "search", f"Candidate pool now {len(candidates)} source(s)."
        )

    @staticmethod
    def _prefer_representation(new: _Gathered, existing: _Gathered | None) -> bool:
        """True if ``new`` is a better representation of a paper than ``existing``.

        Prefer full-text HTML (e.g. ar5iv) and higher evidence level; a richer
        representation extracts more reliably than a landing page/abstract.
        """
        if existing is None:
            return True
        new_full = len((new.full_text or "").strip())
        old_full = len((existing.full_text or "").strip())
        if (new_full >= _MIN_TIER1_CHARS) != (old_full >= _MIN_TIER1_CHARS):
            return new_full >= _MIN_TIER1_CHARS
        if new.source.evidence_level != existing.source.evidence_level:
            return new.source.evidence_level > existing.source.evidence_level
        return new_full > old_full

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
        ordered_unread = self._order_execution_items(
            unread,
            kind="download",
            item_id=lambda source: source.id,
            activity=activity,
        )
        # Adaptive acquire pool: never allocate more workers than source work.
        if self._resources is not None:
            try:
                rec = self._resources.recommend_pool_sizes(
                    download_work=min(remaining, len(ordered_unread)),
                    reader_work=min(remaining, len(ordered_unread)),
                )
                self._librarian._max_workers = rec.acquire_workers
            except Exception:  # noqa: BLE001
                self._logger.debug("adaptive acquire sizing failed", exc_info=True)
        try:
            acq = self._librarian.acquire(
                ordered_unread,
                workspace=workspace,
                activity=activity,
                top_k=remaining,
            )
            # Deterministic doc map by source_id (D32.4).
            for doc in sorted(acq.documents, key=lambda d: d.source_id):
                documents[doc.source_id] = doc
            blocked = list(getattr(acq, "blocked", []) or [])
            acquired_full = len(documents)
        except Exception:  # noqa: BLE001
            self._logger.exception("acquisition failed; falling back to abstracts")
        return documents, blocked, acquired_full

    def _extract_parallel(
        self,
        documents: dict[str, Any],
        raw: list[Claim],
        graph: EvidenceGraph,
        activity: Any,
    ) -> list[Claim]:
        """Extract claims from unread docs under ``max_extract_workers`` (3.2b)."""
        from atlas.research.concurrency import clamp_workers, map_parallel

        extracted_ids = {c.evidence[0].source_id for c in raw if c.evidence}
        # Stable input order by source_id so parallel results merge deterministically.
        pending = [
            (sid, documents[sid])
            for sid in sorted(documents.keys())
            if sid not in extracted_ids
        ]
        if not pending or self._extractor is None:
            return []

        workers = clamp_workers(
            self._max_extract_workers,
            global_max=self._max_worker_threads,
            fallback=1,
            queue_depth=len(pending),
            work_count=len(pending),
        )
        pending = self._order_execution_items(
            pending,
            kind="llm_extract",
            item_id=lambda item: item[0],
            activity=activity,
        )
        if activity is not None and workers > 1 and len(pending) > 1:
            self._record(
                activity, "extract",
                f"Extracting from {len(pending)} document(s) with up to {workers} worker(s).",
                workers=workers,
            )

        def _one(item: tuple[str, Any]) -> tuple[str, list[Claim], str | None, str | None]:
            sid, doc = item
            if not getattr(doc, "has_text", True):
                code = getattr(doc, "failure_code", "") or "empty_text"
                reason = getattr(doc, "failure_reason", "") or "no extractable text"
                return sid, [], code, reason
            level = graph.sources[sid].evidence_level if sid in graph.sources else None
            try:
                # Activity is not thread-safe across workers; record on main thread.
                res = self._extractor.extract(doc, evidence_level=level, activity=None)
                claims = list(res.claims)
                if not claims:
                    # Never a silent "0 claims": carry the extractor's diagnosis.
                    return sid, [], "no_claims", res.reason or "no claim patterns matched"
                return sid, claims, None, None
            except Exception as exc:  # noqa: BLE001
                self._logger.exception("claim extraction failed for %s", sid)
                return sid, [], "parse_error", f"{type(exc).__name__}: {exc}"

        outcomes = map_parallel(
            _one, pending, max_workers=workers, ordered=True, logger=self._logger
        )
        new_claims: list[Claim] = []
        for sid, claims, code, reason in outcomes:
            if code in ("empty_text", "paywall", "unsupported") and not claims:
                # Reader-side failure: the document never yielded usable text.
                self._record(
                    activity, "read",
                    f"Reader failure for {sid}: {code} — {reason}",
                    source_id=sid, failure_code=code,
                )
                continue
            if code and not claims:
                if code == "parse_error":
                    self._record(
                        activity, "extract",
                        f"Extract failed for {sid}: {reason}",
                        source_id=sid, failure_code=code,
                    )
                else:
                    # code == "no_claims": reader OK but nothing extractable.
                    self._record(
                        activity, "extract",
                        f"Extracted 0 claims from {sid} "
                        f"(reader={getattr(documents[sid], 'reader_id', '')}, "
                        f"chars={getattr(documents[sid], 'chars', 0)}) — {reason}",
                        source_id=sid, failure_code=code,
                    )
                continue
            self._record(
                activity, "extract",
                f"Extracted {len(claims)} claim(s) from {sid}",
                source_id=sid, claims=len(claims),
            )
            new_claims.extend(claims)
        return new_claims

    def _order_execution_items(
        self,
        items: list[Any],
        *,
        kind: str,
        item_id,
        activity: Any,
    ) -> list[Any]:
        """Order work through the kernel Execution Planner when available."""
        if not items or self._execution is None:
            return list(items)
        try:
            from atlas.core.execution import ExecutionTask

            by_id = {str(item_id(item)): item for item in items}
            planned = self._execution.plan(
                [
                    ExecutionTask(id=task_id, kind=kind)
                    for task_id in sorted(by_id)
                ]
            )
            deferred = [task for task in planned if not task.admitted]
            if deferred:
                self._record(
                    activity,
                    "lifecycle",
                    f"Execution admission deferred {len(deferred)} {kind} task(s); "
                    "they remain queued under resource limits.",
                    task_kind=kind,
                    deferred=len(deferred),
                )
            # Tasks remain queued rather than being dropped. The underlying RM
            # lane/caps enforce admission while this order lets admitted/cheap
            # work proceed first.
            return [by_id[row.task.id] for row in planned]
        except Exception:  # noqa: BLE001
            self._logger.debug("execution planning failed; using stable input", exc_info=True)
            return list(items)

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
    def _record(activity: Any, phase: str, message: str, **data: Any) -> None:
        if activity is None:
            return
        try:
            activity.record(phase, message, **data)
        except TypeError:
            # Recorders that only accept (phase, message) still work.
            try:
                activity.record(phase, message)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 - the feed is best-effort, never fatal
            pass

    @staticmethod
    def _persist_artifacts(
        workspace: Any,
        graph: EvidenceGraph,
        pipeline: dict[str, Any],
        notes: str,
        *,
        findings: list | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        """Write claims/evidence/findings/reasoning/manifest into the job workspace."""
        if workspace is None:
            return
        try:
            workspace.write_json("claims.json", [c.as_dict() for c in graph.claims.values()])
            workspace.write_json("evidence.json", graph.as_dict())
            if findings is not None:
                workspace.write_json(
                    "findings.json",
                    [f.as_dict() if hasattr(f, "as_dict") else f for f in findings],
                )
            if reasoning is not None:
                workspace.write_json("reasoning.json", reasoning)
            if pipeline is not None:
                workspace.write_json("pipeline.json", pipeline)
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
                    ("findings", "findings"),
                    ("patterns", "patterns"),
                    ("hypotheses", "hypotheses"),
                ):
                    counts[field] = max(int(counts.get(field, 0)), int(pipeline.get(key, 0)))
                from datetime import datetime, timezone
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                workspace.write_json("manifest.json", manifest)
        except Exception:  # noqa: BLE001 - workspace I/O must never fail research
            pass

    def _build_source_traces(
        self,
        candidates: dict[str, _Gathered],
        documents: dict[str, Any],
        raw: list[Claim],
        graph: EvidenceGraph,
        findings: list | None,
        blocked: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """One structured state object per source, across every pipeline stage.

        Fields answer "what happened to this source?": searched → acquired → read
        (reader/chars/sections) → extracted (numeric/qualitative/inferred) → distinct
        → verified → findings, plus an explicit ``status`` and ``failure_reason`` when
        a stage stopped. This is the trace the operator asked for — debugging by
        reading one row instead of correlating log lines.
        """
        from collections import defaultdict

        numeric: dict[str, int] = defaultdict(int)
        prose: dict[str, int] = defaultdict(int)
        inferred: dict[str, int] = defaultdict(int)
        for c in raw:
            if not c.evidence:
                continue
            ev = c.evidence[0]
            sid = ev.source_id
            if getattr(ev, "inferred", False):
                inferred[sid] += 1
            elif c.value is not None:
                numeric[sid] += 1
            else:
                prose[sid] += 1

        distinct: dict[str, int] = defaultdict(int)
        verified: dict[str, int] = defaultdict(int)
        for c in graph.claims.values():
            is_verified = c.confidence != CONFIDENCE_INSUFFICIENT
            for sid in {e.source_id for e in c.evidence}:
                distinct[sid] += 1
                if is_verified:
                    verified[sid] += 1

        finding_by_sid: dict[str, int] = defaultdict(int)
        for f in findings or []:
            fd = f.as_dict() if hasattr(f, "as_dict") else dict(f)
            sids = {
                str(s.get("source_id", ""))
                for s in (fd.get("supporting_sources") or [])
                if isinstance(s, dict) and s.get("source_id")
            }
            for sid in sids:
                finding_by_sid[sid] += 1

        blocked_by_sid: dict[str, dict[str, Any]] = {}
        for b in blocked or []:
            if not isinstance(b, dict):
                continue
            key = str(b.get("source_id") or b.get("url") or "")
            if key:
                blocked_by_sid.setdefault(key, b)

        # Stable order: candidates first (discovery order), then any doc/blocked-only ids.
        order: list[str] = list(candidates.keys())
        for sid in list(documents.keys()) + list(blocked_by_sid.keys()):
            if sid not in order:
                order.append(sid)

        traces: list[dict[str, Any]] = []
        for sid in order:
            g = candidates.get(sid)
            doc = documents.get(sid)
            src = (g.source if g else None) or graph.sources.get(sid)
            title = ((src.title if src else "") or sid) or ""
            url = (src.url if src else "") or ""
            lvl = getattr(src, "evidence_level", None) if src else None
            blk = blocked_by_sid.get(sid) or blocked_by_sid.get(url)
            acquired = doc is not None
            read = bool(doc and getattr(doc, "has_text", False))
            n_num = numeric.get(sid, 0)
            n_prose = prose.get(sid, 0)
            n_inf = inferred.get(sid, 0)
            row = {
                "source_id": sid,
                "title": title[:120],
                "url": url,
                "evidence_level": lvl,
                "level_name": level_name(lvl) if lvl else "",
                "searched": True,
                "acquired": acquired,
                "read": read,
                "reader": (getattr(doc, "reader_id", "") if doc else ""),
                "chars": (getattr(doc, "chars", 0) if doc else 0),
                "sections": (len(getattr(doc, "sections", []) or []) if doc else 0),
                "numeric_claims": n_num,
                "qualitative_claims": n_prose,
                "inferred_claims": n_inf,
                "distinct_claims": distinct.get(sid, 0),
                "verified_claims": verified.get(sid, 0),
                "findings": finding_by_sid.get(sid, 0),
            }
            if blk:
                row["status"] = "blocked"
                row["failure_reason"] = str(
                    blk.get("reason") or blk.get("failure_code") or "blocked"
                )
            elif not acquired:
                row["status"] = "not_acquired"
                row["failure_reason"] = "not selected within document cap, or fetch failed"
            elif not read:
                row["status"] = "read_failed"
                row["failure_reason"] = (
                    getattr(doc, "failure_reason", "")
                    or getattr(doc, "failure_code", "")
                    or "no extractable text"
                )
            elif (n_num + n_prose + n_inf) == 0:
                row["status"] = "no_claims"
                row["failure_reason"] = "read OK but no claim patterns matched"
            else:
                row["status"] = "ok"
                row["failure_reason"] = ""
            traces.append(row)
        return traces

    def _record_trace(
        self, activity: Any, workspace: Any, trace: list[dict[str, Any]]
    ) -> None:
        """Persist the per-source trace and note a one-line summary on the feed."""
        if workspace is not None and hasattr(workspace, "write_json"):
            try:
                workspace.write_json("pipeline_trace.json", trace)
            except Exception:  # noqa: BLE001 - trace is diagnostic, never fatal
                pass
        if activity is None or not trace:
            return
        by_status: dict[str, int] = {}
        for row in trace:
            st = str(row.get("status", ""))
            by_status[st] = by_status.get(st, 0) + 1
        summary = ", ".join(f"{k}: {v}" for k, v in sorted(by_status.items()))
        self._record(
            activity, "lifecycle",
            f"Pipeline trace for {len(trace)} source(s) — {summary}.",
        )

    def _reason_across(
        self,
        items: list,
        *,
        gaps: Any = None,
        objective: str = "",
        activity: Any = None,
    ) -> dict[str, Any]:
        """Best-effort cross-document reasoning (3B.4)."""
        try:
            from atlas.research.reasoning import CrossDocumentReasoner

            result = CrossDocumentReasoner(logger=self._logger).reason(
                items, gaps=gaps, objective=objective
            )
            payload = result.as_dict()
            self._record(
                activity,
                "reasoning",
                (
                    f"Cross-doc reasoning: {len(result.edges)} edge(s), "
                    f"{len(result.patterns)} pattern(s), "
                    f"{len(result.opportunities)} opportunity(ies), "
                    f"{len(result.hypotheses)} hypothesis(es)."
                ),
            )
            return payload
        except Exception:  # noqa: BLE001
            self._logger.exception("cross-document reasoning failed")
            return {
                "edges": [],
                "patterns": [],
                "opportunities": [],
                "hypotheses": [],
            }

    def _synthesize_findings(
        self,
        graph: EvidenceGraph,
        *,
        objective: str = "",
        workspace: Any = None,
        documents: dict[str, Any] | None = None,
    ) -> list:
        """Best-effort Claims → Findings via EvidenceSynthesizer."""
        synthesizer = self._synthesizer
        if synthesizer is None:
            try:
                from atlas.research.synthesis import EvidenceSynthesizer

                synthesizer = EvidenceSynthesizer(logger=self._logger)
            except Exception:  # noqa: BLE001
                return []
        try:
            claims = list(graph.claims.values())
            job_id = None
            if workspace is not None and hasattr(workspace, "job_id"):
                job_id = str(workspace.job_id)
            return synthesizer.synthesize(
                claims,
                already_grouped=True,
                job_id=job_id,
                objective=objective,
                domain="research",
                documents=documents,
            )
        except Exception:  # noqa: BLE001
            self._logger.exception("finding synthesis failed")
            return []

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
        self,
        objective: str,
        graph: EvidenceGraph,
        eb: EvidenceBudget,
        *,
        notes: str = "",
        findings: list | None = None,
        reasoning: dict[str, Any] | None = None,
        pipeline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            finding_dicts = None
            if findings:
                finding_dicts = [
                    f.as_dict() if hasattr(f, "as_dict") else f for f in findings
                ]
            return self._reports.report(
                objective,
                graph.as_dict(),
                budget=eb.as_dict(),
                notes=notes,
                findings=finding_dicts,
                reasoning=reasoning,
                pipeline=pipeline,
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

    def _recall_advice(
        self,
        objective: str,
        *,
        activity: Any = None,
        workspace: Any = None,
    ) -> dict[str, Any] | None:
        """Advice-only experience recall for research (3B.5). Non-mutating."""
        if self._learning is None or not hasattr(self._learning, "advice_for"):
            return None
        try:
            advice = self._learning.advice_for(objective)
            if workspace is not None and hasattr(workspace, "write_json"):
                try:
                    workspace.write_json("experience_advice.json", advice)
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("experience_advice workspace write failed: %s", exc)
            if activity is not None and advice.get("count"):
                try:
                    activity(
                        "experience_advice",
                        f"Recalled {advice['count']} experience advice item(s) "
                        "(non-mutating).",
                        count=advice["count"],
                    )
                except TypeError:
                    try:
                        activity(
                            f"Recalled {advice.get('count', 0)} experience advice item(s)."
                        )
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass
            return advice
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("experience advice recall failed: %s", exc)
            return {"error": str(exc), "mutating": False}

    def _recall_prior(
        self,
        objective: str,
        *,
        activity: Any = None,
        workspace: Any = None,
    ) -> dict[str, Any] | None:
        """Mandatory Access Layer recall for research (3B.1). Best-effort."""
        if self._knowledge is None or not hasattr(self._knowledge, "retrieve"):
            return None
        try:
            from atlas.research.prior_knowledge import recall_prior_knowledge

            ranked = recall_prior_knowledge(
                self._knowledge, objective, k=self._prior_k
            )
            payload = ranked.as_dict()
            if workspace is not None and hasattr(workspace, "write_json"):
                try:
                    workspace.write_json("prior_knowledge.json", payload)
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("prior_knowledge workspace write failed: %s", exc)
            if activity is not None:
                try:
                    activity(
                        "prior_knowledge",
                        f"Recalled {len(ranked.hits)} prior knowledge hit(s).",
                        hits=len(ranked.hits),
                        mode=ranked.mode,
                    )
                except TypeError:
                    try:
                        activity(
                            f"Recalled {len(ranked.hits)} prior knowledge hit(s)."
                        )
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass
            return {
                "hits": len(ranked.hits),
                "mode": ranked.mode,
                "diagnostics_id": ranked.diagnostics_id,
                "chunk_ids": [h.chunk_id for h in ranked.hits],
            }
        except Exception as exc:  # noqa: BLE001 — never fail research on recall
            self._logger.warning("prior knowledge recall failed: %s", exc)
            return {"error": str(exc)}

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
