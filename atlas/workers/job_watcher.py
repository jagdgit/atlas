"""JobWatcher — Career Advisor worker (Phase D · §D.8 / CI.1.3).

Each tick drives the D-Core decision path over configured posting sources:

    Asset → JobPostingsReader → postings → DecisionEngine.decide
    (JobDecisionRule: match Personal + Policy + constraints) → journal (P9) → notify

**Advisor-only (L-SPLIT / CI.1.3):** Discovery belongs to ``career_observer``. This worker
ranks and notifies; it never scrapes and never applies (P14). Optional Career Memory
watchlist companies merge into the company filter when ``use_career_watchlist`` is true.
Bounded + checkpointed: state carries a sources fingerprint and seen posting ids.
Never completes.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.career.decision_rule import MISSION_TYPE_JOB_HUNTING
from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.workers.base import PersistentWorker, TickContext, TickResult

ASSET_KIND_JOB_POSTINGS = "job_postings"


class JobWatcher(PersistentWorker):
    type = "job_watcher"
    VERSION = 2
    journal_ticks = True

    def __init__(
        self,
        *,
        assets: Any,
        postings_reader: Any,
        decision_engine: Any,
        personal: Any = None,
        experience_os: Any = None,
        learning: Any = None,
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._reader = postings_reader
        self._engine = decision_engine
        self._personal = personal
        self._experience_os = experience_os
        self._learning = learning
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.job_watcher")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        feedback_n = self._process_outcome_feedback(
            ctx, cfg, state, mission_type=MISSION_TYPE_JOB_HUNTING, domain="career"
        )
        sources = [str(s).strip() for s in (cfg.get("sources") or []) if str(s).strip()]
        if not sources:
            note = f"feedback={feedback_n}" if feedback_n else ""
            return TickResult(state=state, note=note)

        force = any(bool(item.get("force")) for item in ctx.inputs)
        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        postings, load_errors = self._load_all(sources)
        fingerprint = self._fingerprint(sources, postings, cfg)
        if not force and fingerprint == state.get("sources_fingerprint") and not load_errors:
            state["ticks"] = int(state.get("ticks", 0)) + 1
            note = f"{config_note}no change (postings unchanged)".strip() if config_note else ""
            if feedback_n:
                note = f"{note}; feedback={feedback_n}".strip("; ")
            return TickResult(state=state, note=note)

        personal_skills = self._personal_skill_names(
            include_inferred=bool(cfg.get("include_inferred_skills", True))
        )
        max_recs = max(1, int(cfg.get("max_recommendations") or 5))
        companies = self._merge_companies(cfg)

        decision_ctx = {
            "postings": postings,
            "locations": list(cfg.get("locations") or []),
            "companies": companies,
            "skills": list(cfg.get("skills") or []),
            "min_salary": cfg.get("min_salary", 0),
            "min_skill_overlap": int(cfg.get("min_skill_overlap") or 0),
            "personal_skills": sorted(personal_skills),
            "include_inferred_skills": bool(cfg.get("include_inferred_skills", True)),
            "use_opportunity_score": bool(cfg.get("use_opportunity_score", True)),
            "watchlist_companies": companies,
            "research_by_company": dict(cfg.get("research_by_company") or {}),
        }
        decision = self._engine.decide(
            DecisionRequest(
                mission_id=ctx.mission_id,
                mission_type=MISSION_TYPE_JOB_HUNTING,
                config_version=ctx.config_version,
                context=decision_ctx,
            )
        )
        state["last_decision_id"] = str(decision.id) if decision.id else None
        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["sources_fingerprint"] = fingerprint
        state["last_posting_count"] = len(postings)
        state["last_company_filter"] = companies

        # CI.0.3 — notify up to max_recommendations *new* matches (seen-id checkpoint).
        # Only fan out when the journaled decision is a real recommend_match (respect policy hold).
        ranked_postings: list[dict[str, Any]] = []
        if decision.action_kind == ACTION_RECOMMEND:
            payload = (decision.action or {}).get("payload") or {}
            if payload.get("kind") == "recommend_match":
                ranked_postings = self._ranked_match_postings(
                    decision, decision_ctx, limit=max_recs
                )
        seen = list(state.get("seen_posting_ids") or [])
        seen_set = set(seen)
        new_recs: list[dict[str, Any]] = []
        for posting in ranked_postings:
            pid = str(posting.get("id") or "")
            if not pid or pid in seen_set:
                continue
            new_recs.append(posting)
            seen.append(pid)
            seen_set.add(pid)
            self._emit("JobMatchRecommended", {
                "mission_id": str(ctx.mission_id),
                "decision_id": str(decision.id) if decision.id else None,
                "posting": posting,
                "why": decision.why,
            })
            if len(new_recs) >= max_recs:
                break

        state["seen_posting_ids"] = seen[-500:]
        state["last_recommended"] = new_recs[0] if new_recs else state.get("last_recommended")
        state["last_recommended_count"] = len(new_recs)

        titles = ", ".join((r.get("title") or "")[:40] for r in new_recs[:3])
        note = (
            f"{config_note}job watch: {len(postings)} posting(s)"
            + (f", {load_errors} source error(s)" if load_errors else "")
            + (
                f"; recommended {len(new_recs)}/{max_recs}"
                + (f" ({titles})" if titles else "")
                if new_recs
                else "; hold"
            )
            + (f"; feedback={feedback_n}" if feedback_n else "")
        ).strip()
        return TickResult(state=state, note=note)

    def _merge_companies(self, cfg: dict[str, Any]) -> list[str]:
        """CI.1.3 — config companies ∪ Career Memory watchlist (when enabled)."""
        companies = [str(c).strip() for c in (cfg.get("companies") or []) if str(c).strip()]
        if not bool(cfg.get("use_career_watchlist", True)):
            return companies
        try:
            from atlas.career import watchlist as wl

            for name in wl.companies_for_filter():
                if name not in companies:
                    companies.append(name)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("career watchlist merge skipped: %s", exc)
        return companies

    def _process_outcome_feedback(
        self,
        ctx: TickContext,
        cfg: dict[str, Any],
        state: dict[str, Any],
        *,
        mission_type: str,
        domain: str,
    ) -> int:
        """OI-F4 — drain Recommendation→Outcome→Difference→Learning feedback."""
        if self._experience_os is None and self._learning is None:
            return 0
        from atlas.decision.feedback import (
            build_feedback_journal,
            collect_outcome_feedback,
            difference_label,
            record_feedback_loop,
        )

        items = collect_outcome_feedback(list(ctx.inputs or []), cfg)
        if not items:
            return 0
        enable_bias = bool(cfg.get("enable_soft_bias", True))
        count = 0
        for item in items:
            decision_id = str(
                item.get("decision_id") or state.get("last_decision_id") or ""
            ) or None
            recommendation = str(
                item.get("recommendation")
                or item.get("title")
                or "prior job recommendation"
            )
            outcome = str(item.get("outcome") or item.get("actual") or "unknown")
            expected = str(item.get("expected") or "recommend")
            difference = str(item.get("difference") or difference_label(expected, outcome))
            subject = str(item.get("subject") or item.get("posting_id") or "") or None
            journal_kwargs = build_feedback_journal(
                title=str(item.get("title") or f"Job recommendation feedback: {difference}"),
                recommendation=recommendation,
                outcome=outcome,
                difference=difference,
                observation=str(item.get("observation") or recommendation),
                reasoning=str(item.get("reasoning") or "Operator outcome on a job recommend"),
                domain=domain,
                mission_type=mission_type,
                decision_id=decision_id,
                subject=subject,
            )
            result = record_feedback_loop(
                experience_os=self._experience_os,
                learning=self._learning,
                journal_kwargs=journal_kwargs,
                enable_bias=enable_bias,
                difference=difference,
                logger=self._logger,
            )
            if result.get("ok"):
                count += 1
        state["last_feedback_count"] = count
        return count

    # --- helpers --------------------------------------------------------
    def _load_all(self, sources: list[str]) -> tuple[list[dict[str, Any]], int]:
        postings: list[dict[str, Any]] = []
        errors = 0
        seen_ids: set[str] = set()
        for name in sources:
            try:
                for p in self._load_source(name):
                    pid = str(p.get("id") or "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        postings.append(p)
            except Exception as exc:  # noqa: BLE001 - a bad source must not stop the others
                errors += 1
                self._logger.warning("job postings source failed (%s): %s", name, exc)
        return postings, errors

    def _load_source(self, asset_name: str) -> list[dict[str, Any]]:
        asset = self._assets.get_by_name(ASSET_KIND_JOB_POSTINGS, asset_name)
        if asset is None:
            raise FileNotFoundError(f"no job_postings asset named {asset_name!r}")
        artifact = self._reader.read(str(asset["id"]))
        if artifact.get("outcome") != "ok":
            raise RuntimeError(f"postings unreadable: {artifact.get('reason', 'unknown')}")
        return list(artifact.get("postings") or [])

    def _ranked_match_postings(
        self,
        decision: Any,
        decision_ctx: dict[str, Any],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Ordered recommend_match postings for notification fan-out (CI.0.3)."""
        from atlas.career.decision_rule import JobDecisionRule
        from atlas.decision.contracts import DecisionRequest

        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(posting: dict[str, Any] | None) -> None:
            if not isinstance(posting, dict):
                return
            pid = str(posting.get("id") or "")
            if not pid or pid in seen:
                return
            seen.add(pid)
            out.append(posting)

        # Prefer primary decision payload first when it is a match.
        if getattr(decision, "action_kind", None) == ACTION_RECOMMEND:
            payload = (getattr(decision, "action", None) or {}).get("payload") or {}
            if payload.get("kind") == "recommend_match":
                _add(payload.get("posting") or {})

        try:
            rule = JobDecisionRule()
            options = rule.score(
                DecisionRequest(
                    mission_id=getattr(decision, "mission_id", None) or "job_watcher",
                    mission_type=MISSION_TYPE_JOB_HUNTING,
                    context=decision_ctx,
                ),
                context=_EmptyIntel(),
            )
            ranked = [
                o
                for o in options
                if (o.payload or {}).get("kind") == "recommend_match"
            ]
            ranked.sort(key=lambda o: float(getattr(o, "final_score", None) or o.score or 0), reverse=True)
            for o in ranked:
                if len(out) >= limit:
                    break
                _add((o.payload or {}).get("posting") or {})
        except Exception as exc:  # noqa: BLE001 - fan-out is best-effort
            self._logger.warning("job match fan-out ranking failed: %s", exc)
        return out[:limit]

    def _personal_skill_names(self, *, include_inferred: bool) -> set[str]:
        from atlas.personal.skill_hygiene import skill_names_from_facts

        if self._personal is None:
            return set()
        try:
            facts = self._personal.skills(include_inferred=include_inferred) or []
        except Exception as exc:  # noqa: BLE001 - personal is advisory for matching
            self._logger.warning("personal skills lookup failed: %s", exc)
            return set()
        return {n.lower() for n in skill_names_from_facts(facts, include_inferred=include_inferred)}

    @staticmethod
    def _fingerprint(sources: list[str], postings: list[dict[str, Any]], cfg: dict[str, Any]) -> str:
        ids = sorted(str(p.get("id") or "") for p in postings)
        key = "|".join([
            ",".join(sources),
            ",".join(ids),
            str(cfg.get("min_salary", 0)),
            ",".join(sorted(str(s) for s in (cfg.get("skills") or []))),
            ",".join(sorted(str(s) for s in (cfg.get("locations") or []))),
            ",".join(sorted(str(s) for s in (cfg.get("companies") or []))),
        ])
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001
            self._logger.exception("failed to emit %s", event_type)


class _EmptyIntel:
    """Minimal IntelligenceContext stand-in for JobDecisionRule fan-out."""

    def has(self, name: str) -> bool:  # noqa: ARG002
        return False
