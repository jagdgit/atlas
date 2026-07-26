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
import re
from typing import Any

from atlas.services.base import HealthStatus

# The maturity of the underlying experience shapes the inferred fact's confidence label.
_MATURITY_CONFIDENCE = {
    "established": ("HIGH", 0.85),
    "verified": ("MEDIUM", 0.6),
    "candidate": ("LOW", 0.4),
}

# OI-C11 — graded proficiency (not just maturity→confidence).
_PROFICIENCY_ORDER = ("beginner", "intermediate", "advanced", "expert")

_ROLE_RE = re.compile(
    r"\b(?:i(?:'?m| am|'?ve| have)?|we)\s+"
    r"(?:was|were|worked\s+as|served\s+as)\s+"
    r"(?:an?\s+)?"
    r"(?P<title>[A-Za-z][A-Za-z0-9 /&-]{2,48}?)"
    r"\s+at\s+(?P<org>[A-Za-z0-9][\w .,&-]{1,60}?)(?=\s+(?:building|working|doing|where|,|\.|$))",
    re.IGNORECASE,
)
_ROLE_LOOSE_RE = re.compile(
    r"\b(?:i(?:'?m| am|'?ve| have)?)\s+(?:was|were)\s+(?:an?\s+)?"
    r"(?P<title>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,5})"
    r"(?:\s+at\s+(?P<org>[A-Z][\w.&-]{1,40}(?:\s+[A-Z][\w.&-]{0,40}){0,4}))?",
    re.IGNORECASE,
)
_PUB_RE = re.compile(
    r"\b(?:published|publication|paper|patent|thesis|dissertation)\b.{0,80}",
    re.IGNORECASE,
)


def _proficiency(
    *,
    maturity: str,
    years: int | None,
    corroboration: int,
) -> str:
    """Map maturity / stated years / corroboration → graded proficiency (OI-C11)."""
    y = int(years) if years is not None else None
    if (y is not None and y >= 5) or (maturity == "established" and corroboration >= 3):
        return "expert"
    if (y is not None and y >= 3) or maturity == "established":
        return "advanced"
    if (y is not None and y >= 1) or maturity == "verified" or corroboration >= 2:
        return "intermediate"
    return "beginner"


class PersonalService:
    name = "personal"
    VERSION = "1.1.0"

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
        professional = self._infer_professional(actor=actor)
        result = {
            "skills": skills,
            "identity": identity,
            "timeline": timeline,
            "professional": professional,
        }
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
            years = value.get("years")
            try:
                years_i = int(years) if years is not None else None
            except (TypeError, ValueError):
                years_i = None
            conf, score = _MATURITY_CONFIDENCE.get(maturity, ("LOW", 0.4))
            level = _proficiency(
                maturity=maturity, years=years_i, corroboration=corroboration
            )
            sources = [
                s.get("source_id") for s in (exp.get("supporting") or [])
                if isinstance(s, dict) and s.get("source_id")
            ]
            ctx = f" ({context})" if context else ""
            projects = f", corroborated by {corroboration} project(s)" if corroboration else ""
            yrs = f", ~{years_i}y" if years_i is not None else ""
            self._upsert_fact(
                "skill", skill.lower(),
                subject=context.lower(),
                statement=f"Skilled in {skill}{ctx}{projects}{yrs} [{level}].",
                value={
                    "skill": skill,
                    "context": context,
                    "corroboration_count": corroboration,
                    "maturity": maturity,
                    "proficiency": level,
                    "years": years_i,
                },
                confidence=conf, confidence_score=score, source="experience",
                provenance={
                    "experience_id": exp.get("id"),
                    "canonical_id": exp.get("canonical_id"),
                    "maturity": maturity,
                    "proficiency": level,
                    "sources": sources,
                },
                actor=actor,
            )
            # OI-C11 — timeline dates from stated years on skills.
            if years_i is not None and years_i > 0:
                self._upsert_fact(
                    "timeline", f"skill:{skill.lower()}",
                    subject=context.lower(),
                    statement=f"~{years_i} years with {skill}{ctx}.",
                    value={
                        "skill": skill,
                        "years": years_i,
                        "context": context,
                        "kind": "skill_tenure",
                    },
                    confidence=conf, confidence_score=score, source="experience",
                    provenance={
                        "experience_id": exp.get("id"),
                        "years": years_i,
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

    def _infer_professional(self, *, actor: str) -> int:
        """Heuristic professional facts from Experience statements/snippets (OI-C11).

        Roles / publications distilled from owner-stated experience text. Full CV / Research
        finding auto-inference remains deferred when those structured sources appear.
        """
        if self._experiences is None:
            return 0
        try:
            experiences = self._experiences.list_active(limit=1000)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("professional inference could not read experiences: %s", exc)
            return 0
        count = 0
        seen: set[str] = set()
        for exp in experiences:
            texts: list[str] = []
            stmt = str(exp.get("statement") or "").strip()
            if stmt:
                texts.append(stmt)
            for s in exp.get("supporting") or []:
                if isinstance(s, dict) and s.get("snippet"):
                    texts.append(str(s["snippet"]))
            blob = "\n".join(texts)
            if not blob:
                continue
            for matcher in (_ROLE_RE, _ROLE_LOOSE_RE):
                for m in matcher.finditer(blob):
                    title = (m.group("title") or "").strip(" .,")
                    org = (m.groupdict().get("org") or "").strip(" .,")
                    if len(title) < 3:
                        continue
                    key = f"role:{(title + '@' + org).lower()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    where = f" at {org}" if org else ""
                    self._upsert_fact(
                        "professional", key,
                        statement=f"Role: {title}{where}.",
                        value={"kind": "role", "title": title, "org": org or None},
                        confidence="LOW", confidence_score=0.45, source="experience",
                        provenance={
                            "experience_id": exp.get("id"),
                            "snippet": m.group(0)[:160],
                        },
                        actor=actor,
                    )
                    count += 1
            for m in _PUB_RE.finditer(blob):
                snippet = m.group(0).strip()[:160]
                key = f"pub:{snippet.lower()[:48]}"
                if key in seen:
                    continue
                seen.add(key)
                self._upsert_fact(
                    "professional", key,
                    statement=f"Publication/patent signal: {snippet}",
                    value={"kind": "publication", "snippet": snippet},
                    confidence="LOW", confidence_score=0.4, source="experience",
                    provenance={"experience_id": exp.get("id")},
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

    def learn_from_cv_text(
        self,
        text: str,
        *,
        source_path: str | None = None,
        actor: str = "atlas",
    ) -> dict[str, Any]:
        """Parse resume/CV text into inferred personal facts (Confirm/Reject on dashboard)."""
        from atlas.personal.cv_extract import extract_cv_facts

        proposals = extract_cv_facts(text, source_path=source_path)
        written = 0
        by_cat: dict[str, int] = {}
        for prop in proposals:
            cat = str(prop["category"])
            self._upsert_fact(
                cat,
                prop["key"],
                subject=prop.get("subject") or "",
                statement=prop.get("statement") or "",
                value=prop.get("value"),
                confidence=prop.get("confidence") or "MEDIUM",
                confidence_score=float(prop.get("confidence_score") or 0.6),
                source=prop.get("source") or "cv",
                provenance=prop.get("provenance"),
                actor=actor,
            )
            written += 1
            by_cat[cat] = by_cat.get(cat, 0) + 1
        return {
            "ok": True,
            "facts": written,
            "by_category": by_cat,
            "source_path": source_path,
            "note": (
                "CV facts are *inferred* — open Personal and Confirm/Reject. "
                "Atlas does not post to LinkedIn."
            ),
        }

    def learn_from_cv_path(self, path: str, *, actor: str = "atlas") -> dict[str, Any]:
        """Extract text from a CV file on disk and learn facts."""
        from pathlib import Path

        from atlas.ingestion.extractors import extract

        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"path not found: {p}")
        text = extract(p)
        if not text:
            return {
                "ok": False,
                "facts": 0,
                "reason": (
                    "no extractable text (scanned PDF needs OCR, or empty file)"
                ),
                "source_path": str(p.resolve()),
            }
        return self.learn_from_cv_text(text, source_path=str(p.resolve()), actor=actor)

    def linkedin_suggestions(
        self,
        *,
        linkedin_text: str | None = None,
        linkedin_path: str | None = None,
        linkedin_url: str | None = None,
        include_inferred: bool = True,
    ) -> dict[str, Any]:
        """Profile improvement tips for LinkedIn — suggestions only, never writes."""
        from atlas.personal.linkedin_coach import linkedin_suggestions as _coach

        text = linkedin_text
        if not text and linkedin_path:
            from pathlib import Path

            from atlas.ingestion.extractors import extract

            p = Path(linkedin_path).expanduser()
            if not p.is_file():
                raise FileNotFoundError(f"path not found: {p}")
            text = extract(p) or p.read_text(encoding="utf-8", errors="replace")
        profile = self.profile(include_inferred=include_inferred)
        return _coach(
            profile,
            linkedin_text=text,
            linkedin_url=linkedin_url,
        )

    def best_jobs(
        self,
        *,
        assets: Any | None = None,
        postings_reader: Any | None = None,
        decision_engine: Any | None = None,
        feed_path: str | None = None,
        limit: int = 10,
        include_inferred_skills: bool = True,
    ) -> dict[str, Any]:
        """Best open jobs for this profile (recommend-only; never apply)."""
        from atlas.career.jobs_panel import best_jobs_for_profile

        return best_jobs_for_profile(
            personal=self,
            assets=assets,
            postings_reader=postings_reader,
            decision_engine=decision_engine,
            feed_path=feed_path,
            limit=limit,
            include_inferred_skills=include_inferred_skills,
        )

    def note_project_period(
        self,
        *,
        project: str,
        note: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        repo_uid: str | None = None,
        root: str | None = None,
        actor: str = "operator",
    ) -> dict[str, Any]:
        """Record owner context for a project/repo as an inferred timeline fact.

        Example: note=\"my work from 2022 to March 2025\". Confirm/Reject on Personal.
        """
        name = (project or root or repo_uid or "project").strip()
        start = (period_start or "").strip() or None
        end = (period_end or "").strip() or None
        note_text = (note or "").strip() or None
        if not (note_text or start or end):
            raise ValueError("provide note and/or period_start/period_end")

        period = ""
        if start or end:
            period = f" ({start or '?'} → {end or 'present'})"
        if note_text:
            statement = note_text if note_text.endswith(".") else note_text + "."
            if period and period.strip(" ()") not in statement:
                statement = statement.rstrip(".") + period + "."
        else:
            statement = f"Worked on {name}{period}."

        key = f"owner_project:{(repo_uid or name).lower()[:100]}"
        fact = self._upsert_fact(
            "timeline",
            key,
            subject=(root or "")[:120],
            statement=statement[:500],
            value={
                "kind": "owner_project_period",
                "project": name,
                "repo_uid": repo_uid,
                "root": root,
                "period_start": start,
                "period_end": end,
                "note": note_text,
            },
            confidence="HIGH",
            confidence_score=0.85,
            source="operator",
            provenance={"actor": actor, "via": "engineering_ingest"},
            actor=actor,
        )
        return {"fact": fact, "statement": statement}

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
