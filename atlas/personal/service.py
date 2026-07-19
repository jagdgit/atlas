"""PersonalService — the ``personal`` capability (Phase C · §C.7, CC7/A9/P10).

Personal Intelligence is "a model of you, not a memory dump": a curated profile assembled INDIRECTLY
from Experience (skills), Engineering Intelligence (identity/timeline) and operator interaction. Facts
are **auto-inferred with confidence + provenance** and held as ``inferred``; an operator promotes them
to ``verified`` (or ``corrects``/``rejects`` them) — no silent scraping (A9). Everything is governed +
reversible via a ``personal.events`` journal, mirroring the Policy store.

Retrieval, not action (P10): other missions READ this profile (e.g. job-search constraints) and
resume/LinkedIn/portfolio managers DRAFT from it — this service never scans code and never posts.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.services.base import HealthStatus

# The maturity of the underlying experience shapes the inferred fact's confidence label.
_MATURITY_CONFIDENCE = {
    "established": ("HIGH", 0.85),
    "verified": ("MEDIUM", 0.6),
    "candidate": ("LOW", 0.4),
}


class PersonalService:
    name = "personal"
    VERSION = "1.0.0"

    def __init__(
        self,
        repo: Any,
        *,
        experiences: Any = None,
        intelligence: Any = None,
        llm: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        # ExperienceStore (skills) + IntelligenceService (identity/timeline) are read-only sources; the
        # profile is assembled from them, never the other way round.
        self._experiences = experiences
        self._intelligence = intelligence
        # Optional LLM for best-effort resume/LinkedIn summary polish (deterministic-first).
        self._llm = llm
        self._logger = logger or logging.getLogger("atlas.personal")

    # --- inference (Atlas → inferred facts) ----------------------------
    def infer(self, *, actor: str = "atlas") -> dict[str, Any]:
        """Refresh inferred facts from the current Experience + Engineering knowledge.

        Idempotent (CC7): re-running upserts on the natural key and NEVER downgrades an operator's
        ``verified``/``rejected`` decision. Returns per-category counts.
        """
        skills = self._infer_skills(actor=actor)
        identity = self._infer_identity(actor=actor)
        timeline = self._infer_timeline(actor=actor)
        result = {"skills": skills, "identity": identity, "timeline": timeline}
        self._logger.info("personal inference: %s", result)
        return result

    def _infer_skills(self, *, actor: str) -> int:
        if self._experiences is None:
            return 0
        try:
            experiences = self._experiences.list_active(limit=1000)
        except Exception as exc:  # noqa: BLE001 - inference must never crash a caller
            self._logger.warning("skill inference could not read experiences: %s", exc)
            return 0
        count = 0
        for exp in experiences:
            value = exp.get("value") if isinstance(exp.get("value"), dict) else {}
            if value.get("kind") != "experience":
                continue
            skill = str(value.get("skill") or "").strip()
            if not skill:
                continue
            context = str(value.get("context") or "").strip()
            corroboration = int(exp.get("corroboration_count") or 0)
            maturity = str(exp.get("maturity") or "candidate")
            conf, score = _MATURITY_CONFIDENCE.get(maturity, ("LOW", 0.4))
            sources = [
                s.get("source_id") for s in (exp.get("supporting") or [])
                if isinstance(s, dict) and s.get("source_id")
            ]
            ctx = f" ({context})" if context else ""
            projects = f", corroborated by {corroboration} project(s)" if corroboration else ""
            self._upsert_fact(
                "skill", skill.lower(),
                subject=context.lower(),
                statement=f"Skilled in {skill}{ctx}{projects}.",
                value={
                    "skill": skill, "context": context,
                    "corroboration_count": corroboration, "maturity": maturity,
                },
                confidence=conf, confidence_score=score, source="experience",
                provenance={
                    "experience_id": exp.get("id"),
                    "canonical_id": exp.get("canonical_id"),
                    "maturity": maturity,
                    "sources": sources,
                },
                actor=actor,
            )
            count += 1
        return count

    def _infer_identity(self, *, actor: str) -> int:
        if self._intelligence is None:
            return 0
        try:
            profile = self._intelligence.profile()
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("identity inference could not read intelligence: %s", exc)
            return 0
        if not profile or not profile.get("repositories"):
            return 0
        self._upsert_fact(
            "identity", "engineering_profile",
            statement=profile.get("summary", ""),
            value={
                "repositories": profile.get("repositories", 0),
                "languages": profile.get("languages", {}),
                "frameworks": profile.get("frameworks", {}),
            },
            confidence="MEDIUM", confidence_score=0.6, source="intelligence",
            provenance={"repositories": profile.get("repositories", 0)},
            actor=actor,
        )
        return 1

    def _infer_timeline(self, *, actor: str) -> int:
        if self._intelligence is None:
            return 0
        try:
            repos = self._intelligence.list_repositories(limit=500)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("timeline inference could not read repositories: %s", exc)
            return 0
        count = 0
        for r in repos:
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            langs = r.get("languages", {}) or {}
            top = ", ".join(sorted(langs, key=lambda k: -langs[k])[:3]) if langs else "code"
            self._upsert_fact(
                "timeline", name.lower(),
                statement=f"Worked on {name} ({top}).",
                value={
                    "project": name, "languages": langs,
                    "frameworks": r.get("frameworks", []),
                    "first_learned": str(r.get("created_at") or ""),
                },
                confidence="LOW", confidence_score=0.4, source="intelligence",
                provenance={"repo_id": r.get("id"), "repo_uid": r.get("repo_uid")},
                actor=actor,
            )
            count += 1
        return count

    def _upsert_fact(self, category: str, key: str, **kwargs: Any) -> dict[str, Any]:
        actor = kwargs.pop("actor", "atlas")
        prior = self._repo.get_by_natural(category, key, kwargs.get("subject", ""))
        fact = self._repo.upsert(category, key, **kwargs)
        # Journal only the first appearance of a fact (an inference event); idempotent refreshes of an
        # existing fact are telemetry, not profile changes, and would flood the journal.
        if prior is None:
            self._repo.record_event(fact["id"], "inferred", after=fact, actor=actor)
        return fact

    # --- operator governance (inferred → verified/rejected) ------------
    def confirm(self, fact_id: str, *, actor: str = "operator") -> dict[str, Any]:
        """Operator confirms an inferred fact → ``verified`` (CC7/A9)."""
        before = self._require(fact_id)
        after = self._repo.set_state(fact_id, "verified")
        self._repo.record_event(fact_id, "confirmed", before=before, after=after, actor=actor)
        return after

    def correct(
        self,
        fact_id: str,
        *,
        statement: str | None = None,
        value: dict[str, Any] | None = None,
        actor: str = "operator",
    ) -> dict[str, Any]:
        """Operator edits a fact and thereby verifies it (an operator-authored fact is authoritative)."""
        before = self._require(fact_id)
        after = self._repo.update(
            fact_id, statement=statement, value=value, state="verified"
        )
        self._repo.record_event(fact_id, "corrected", before=before, after=after, actor=actor)
        return after

    def reject(self, fact_id: str, *, actor: str = "operator") -> dict[str, Any]:
        """Operator rejects a fact → ``rejected`` (Atlas must not re-infer over it)."""
        before = self._require(fact_id)
        after = self._repo.set_state(fact_id, "rejected")
        self._repo.record_event(fact_id, "rejected", before=before, after=after, actor=actor)
        return after

    def add_fact(
        self,
        category: str,
        key: str,
        *,
        subject: str = "",
        statement: str = "",
        value: dict[str, Any] | None = None,
        actor: str = "operator",
    ) -> dict[str, Any]:
        """Operator adds an authoritative fact directly (starts life ``verified``)."""
        prior = self._repo.get_by_natural(category, key, subject)
        fact = self._repo.upsert(
            category, key, subject=subject, statement=statement, value=value,
            state="verified", confidence="HIGH", confidence_score=1.0,
            source="operator", created_by=actor,
        )
        # upsert leaves a verified/rejected fact's body untouched; force operator edits through update.
        if prior is not None:
            fact = self._repo.update(
                fact["id"], statement=statement, value=value, state="verified"
            )
        self._repo.record_event(
            fact["id"], "corrected" if prior else "confirmed",
            before=prior, after=fact, actor=actor,
        )
        return fact

    def revert(self, event_id: str, *, actor: str = "operator") -> dict[str, Any]:
        """Undo a journaled personal-fact change using its before/after snapshots (P9/reversible)."""
        event = self._repo.get_event(event_id)
        if event is None:
            raise KeyError(f"personal event not found: {event_id}")
        action = event["action"]
        before = event.get("before")
        fact_id = event.get("fact_id")
        if action in ("confirmed", "corrected", "rejected", "updated") and before:
            restored = self._repo.restore(before)
            self._repo.record_event(fact_id, "reverted", after=restored, actor=actor)
            return restored
        if action == "inferred" and fact_id:
            self._repo.delete(fact_id)
            self._repo.record_event(fact_id, "reverted", before=event.get("after"), actor=actor)
            return {"id": fact_id, "deleted": True}
        if action == "deleted" and before:
            restored = self._repo.restore(before)
            self._repo.record_event(fact_id, "reverted", after=restored, actor=actor)
            return restored
        raise ValueError(f"personal event action cannot be reverted: {action}")

    # --- reads (for other missions & the console) ----------------------
    def get_fact(self, fact_id: str) -> dict[str, Any] | None:
        return self._repo.get(fact_id)

    def list_facts(
        self, *, category: str | None = None, state: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        return self._repo.list(category=category, state=state, limit=limit)

    def skills(self, *, include_inferred: bool = True) -> list[dict[str, Any]]:
        facts = self._repo.list(category="skill", limit=1000)
        return [f for f in facts if self._presentable(f, include_inferred)]

    def profile(self, *, include_inferred: bool = True) -> dict[str, Any]:
        """The assembled profile other missions read: identity, skills, timeline, professional."""
        out: dict[str, list[dict[str, Any]]] = {
            "identity": [], "skill": [], "timeline": [], "professional": [],
        }
        for f in self._repo.list(limit=2000):
            if f["category"] in out and self._presentable(f, include_inferred):
                out[f["category"]].append(f)
        return {
            "identity": out["identity"],
            "skills": out["skill"],
            "timeline": out["timeline"],
            "professional": out["professional"],
        }

    def list_events(
        self, *, fact_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._repo.list_events(fact_id=fact_id, limit=limit)

    # --- drafting (retrieval, not action; P10) -------------------------
    def draft(
        self, kind: str = "resume", *, name: str | None = None, include_inferred: bool = False
    ) -> dict[str, Any]:
        """Draft a resume/LinkedIn summary purely from the profile (defaults to verified facts only).

        A resume should present confirmed facts, so ``include_inferred`` is False by default — pass
        True to preview a draft from the not-yet-verified profile too.
        """
        from atlas.personal import draft as _draft

        profile = self.profile(include_inferred=include_inferred)
        if kind == "linkedin":
            out = _draft.build_linkedin(profile, llm=self._llm)
        elif kind == "resume":
            out = _draft.build_resume(profile, name=name, llm=self._llm)
        else:
            raise ValueError(f"unknown draft kind: {kind}")
        out["kind"] = kind
        return out

    @staticmethod
    def _presentable(fact: dict[str, Any], include_inferred: bool) -> bool:
        if fact["state"] == "rejected":
            return False
        if fact["state"] == "inferred" and not include_inferred:
            return False
        return True

    def _require(self, fact_id: str) -> dict[str, Any]:
        fact = self._repo.get(fact_id)
        if fact is None:
            raise KeyError(f"personal fact not found: {fact_id}")
        return fact

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            self._repo.list(limit=1)
        except Exception as exc:  # noqa: BLE001
            return HealthStatus.fail(f"personal store unreachable: {exc}")
        return HealthStatus.ok("personal store reachable")
