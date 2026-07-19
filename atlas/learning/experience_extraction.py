"""Owner-experience extraction + consolidation (Phase C · §C.6, CC6/P11/P13).

Dual extraction: the *same* read of a repository Artifact that feeds engineering findings
(:mod:`atlas.engineering.findings`) ALSO feeds this stateless translator, which distills the owner's
**experience** — "works with Python", "uses Celery", "applies the Repository pattern" — as candidate
experience records. Each is one *observation from one project*; the shared Knowledge Consolidator
(C.3) then makes them cumulative (P13): the same skill/technology + context seen across many projects
strengthens ONE experience (evidence-merge, rising confidence + maturity), never N rows.

Like the engineering extractor this owns no state and makes no decisions (P11): it reads the distilled
artifact and returns experience dicts; the :class:`ExperienceWriter` routes them through the
consolidator bound to an :class:`~atlas.repositories.experience_store.ExperienceStore`.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.knowledge.domains import DOMAIN_EXPERIENCE

# Bump when the experience *shape* changes, independent of the reader (BB8).
EXPERIENCE_EXTRACTOR_VERSION = "1.0.0"

CTX_LANGUAGE = "language"
CTX_PATTERN = "pattern"

_MAX_LANGUAGES = 6
_MAX_FRAMEWORKS = 16
_MAX_PATTERNS = 16


def build_repo_experiences(
    distilled: dict[str, Any],
    *,
    repo_uid: str | None,
    asset_id: str | None = None,
    asset_version: int | None = None,
    mission_id: str | None = None,
    job_id: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Distill owner-experience observations from one repository ingest.

    Emits language / framework / pattern experiences, each seeded with a single supporting source
    keyed on the **repository** (``repo_uid``) — so re-learning the *same* repo is a no-op while a
    *different* project corroborates the skill (the consolidator handles the merge). ``mission_id`` /
    ``job_id`` / ``source`` are stamped as provenance (P12): who observed it, never ownership.
    """
    name = str(distilled.get("name", "repo") or "repo")
    languages = distilled.get("languages", {}) or {}
    frameworks = distilled.get("frameworks", []) or []
    patterns = distilled.get("patterns", []) or []
    # Repo is the unit of corroboration; fall back to asset/name when no stable uid is available.
    src = str(repo_uid or asset_id or name)
    primary = _primary_language(languages)

    def prov(skill: str, context: str) -> dict[str, Any]:
        p: dict[str, Any] = {
            "source": source or "repo",
            "repo_uid": repo_uid or "",
            "asset_id": asset_id or "",
            "asset_version": asset_version,
            "repo": name,
            "skill": skill,
            "context": context,
            "extractor_version": EXPERIENCE_EXTRACTOR_VERSION,
            "knowledge_type": "experience",
        }
        if mission_id:
            p["mission_id"] = mission_id
        if job_id:
            p["job_id"] = job_id
        return p

    def support(context: str) -> list[dict[str, Any]]:
        return [{"source_id": src, "evidence_level": 2, "snippet": f"{name} ({context})"}]

    def make(statement: str, skill: str, context: str, *, score: float) -> dict[str, Any]:
        return {
            "statement": statement,
            "claim_type": "experience",
            "domain": DOMAIN_EXPERIENCE,
            "status": "active",
            "confidence": "LOW",
            "confidence_score": score,
            "value": {"kind": "experience", "skill": skill, "context": context},
            "supporting": support(context),
            "provenance": prov(skill, context),
        }

    experiences: list[dict[str, Any]] = []

    for lang in _top_keys(languages, _MAX_LANGUAGES):
        experiences.append(make(f"Works with {lang}", lang, CTX_LANGUAGE, score=0.45))

    for fw in _dedup(frameworks)[:_MAX_FRAMEWORKS]:
        context = primary or "software"
        experiences.append(make(f"Uses {fw}", str(fw), context, score=0.4))

    for pat in patterns[:_MAX_PATTERNS]:
        pname = str(pat.get("name", "")).strip() if isinstance(pat, dict) else str(pat).strip()
        if not pname:
            continue
        experiences.append(
            make(f"Applies the {pname} pattern", pname, CTX_PATTERN, score=0.4)
        )

    return experiences


def _primary_language(languages: dict[str, Any]) -> str:
    if not languages:
        return ""
    try:
        return str(max(languages, key=lambda k: languages[k])).lower()
    except (TypeError, ValueError):
        return str(next(iter(languages))).lower()


def _top_keys(mapping: dict[str, Any], limit: int) -> list[str]:
    if not mapping:
        return []
    try:
        ordered = sorted(mapping, key=lambda k: -mapping[k])
    except (TypeError, ValueError):
        ordered = list(mapping)
    return [str(k) for k in ordered[:limit]]


def _dedup(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        s = str(it).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


class ExperienceWriter:
    """Consolidate extracted experiences into ``learning.experiences`` (single write path, CC3/CC6).

    Mirrors :class:`~atlas.engineering.findings.EngineeringFindingWriter` but binds the consolidator to
    an :class:`~atlas.repositories.experience_store.ExperienceStore`. There is **no** batch archival:
    experiences are cross-project cumulative knowledge (P13), so a later repo does not retire an earlier
    project's contribution — reverting a single learn must not un-corroborate a skill.
    """

    def __init__(
        self,
        store: Any,
        *,
        lifecycle: Any | None = None,
        lineage: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._logger = logger or logging.getLogger("atlas.learning.experience")
        if lifecycle is None:
            from atlas.knowledge.consolidation import KnowledgeLifecycleService

            lifecycle = KnowledgeLifecycleService(store, lineage=lineage, logger=self._logger)
        self._life = lifecycle

    def write(self, experiences: list[dict[str, Any]]) -> dict[str, Any]:
        if not experiences:
            return {"created": 0, "revised": 0, "merged": 0, "noop": 0, "ids": []}
        created = revised = merged = noop = 0
        ids: list[str] = []
        for data in experiences:
            incoming = {**data, "domain": DOMAIN_EXPERIENCE}
            row = self._life.consolidate(incoming)
            transition = row.get("_transition")
            if transition == "create":
                created += 1
            elif transition == "noop":
                noop += 1
            elif transition == "merge_evidence":
                merged += 1
            else:  # revise / supersede / split_contested / contested
                revised += 1
            ids.append(str(row["id"]))
        self._logger.info(
            "experiences: +%d ~%d ^%d =%d", created, revised, merged, noop
        )
        return {
            "created": created, "revised": revised, "merged": merged,
            "noop": noop, "ids": ids,
        }
