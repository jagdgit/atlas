"""Owner-experience extraction + consolidation (Phase C · §C.6, CC6/P11/P13).

Dual extraction: the *same* read of a repository Artifact that feeds engineering findings
(:mod:`atlas.engineering.findings`) ALSO feeds this stateless translator, which distills the owner's
**experience** — "works with Python", "uses Celery", "applies the Repository pattern" — as candidate
experience records. Each is one *observation from one project*; the shared Knowledge Consolidator
(C.3) then makes them cumulative (P13): the same skill/technology + context seen across many projects
strengthens ONE experience (evidence-merge, rising confidence + maturity), never N rows.

OI-C13 adds a parallel path for **conversation** Artifacts: chat-stated skills
("I spent years on PostgreSQL") become experience observations (not only prose findings).

Like the engineering extractor this owns no state and makes no decisions (P11): it reads the distilled
artifact and returns experience dicts; the :class:`ExperienceWriter` routes them through the
consolidator bound to an :class:`~atlas.repositories.experience_store.ExperienceStore`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from atlas.knowledge.domains import DOMAIN_EXPERIENCE

# Bump when the experience *shape* changes, independent of the reader (BB8).
EXPERIENCE_EXTRACTOR_VERSION = "1.2.0"

CTX_LANGUAGE = "language"
CTX_PATTERN = "pattern"
CTX_STATED = "stated"  # owner-stated in conversation (OI-C13)
CTX_DEPENDENCY = "dependency"  # declared production deps (OI-C10)

_MAX_LANGUAGES = 6
_MAX_FRAMEWORKS = 16
_MAX_PATTERNS = 16
_MAX_DEPENDENCIES = 24
_MAX_CONVERSATION_SKILLS = 24

# Curated tech/skill lexicon for deterministic chat distillation (no LLM).
_SKILL_TERMS = (
    "postgresql", "postgres", "python", "typescript", "javascript", "golang", "rust",
    "java", "kotlin", "swift", "celery", "redis", "rabbitmq", "kafka", "fastapi",
    "django", "flask", "react", "vue", "angular", "nextjs", "nodejs", "docker",
    "kubernetes", "terraform", "ansible", "aws", "gcp", "azure", "pytorch",
    "tensorflow", "spark", "hadoop", "elasticsearch", "mongodb", "mysql", "sqlite",
    "graphql", "grpc", "protobuf", "linux", "bash", "sql", "pandas", "numpy",
    "scikit-learn", "sklearn", "huggingface", "langchain", "ollama", "whisper",
)

_SKILL_ALT = {
    "postgres": "postgresql",
    "nodejs": "node.js",
    "nextjs": "next.js",
    "sklearn": "scikit-learn",
}

# First-person claim verbs near a skill term → treat as stated experience.
_CLAIM_VERBS = re.compile(
    r"\b(?:i(?:'?m| am|'?ve| have)?|we(?:'ve| have)?)\s+"
    r"(?:spent|worked|used|use|using|built|wrote|write|know|knew|learned|learn|"
    r"shipped|ran|run|maintain|maintained|expert|skilled|proficient|familiar)\b",
    re.IGNORECASE,
)

_SKILL_ALT_PATTERN = "|".join(
    re.escape(s) for s in sorted(_SKILL_TERMS, key=len, reverse=True)
)
_YEARS_RE = re.compile(
    rf"\b(\d+)\s*(?:\+\s*)?(?:years?|yrs?)\b.{{0,24}}?\b({_SKILL_ALT_PATTERN})\b"
    rf"|\b({_SKILL_ALT_PATTERN})\b.{{0,24}}?\b(\d+)\s*(?:\+\s*)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_SKILL_FIND_RE = re.compile(rf"\b({_SKILL_ALT_PATTERN})\b", re.IGNORECASE)


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

    # OI-C10 — declared package deps (requirements / pyproject / package.json) as soft signal.
    deps = distilled.get("dependencies", {}) or {}
    dep_names: list[str] = []
    if isinstance(deps, dict):
        for group in deps.values():
            if isinstance(group, (list, tuple, set)):
                dep_names.extend(str(d) for d in group)
            elif group:
                dep_names.append(str(group))
    elif isinstance(deps, (list, tuple)):
        dep_names.extend(str(d) for d in deps)
    for dep in _filter_deps(dep_names)[:_MAX_DEPENDENCIES]:
        experiences.append(
            make(f"Uses {dep} in production dependencies", dep, CTX_DEPENDENCY, score=0.35)
        )

    return experiences


def build_conversation_experiences(
    artifact: dict[str, Any],
    *,
    asset_id: str | None = None,
    asset_version: int | None = None,
    mission_id: str | None = None,
    job_id: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Distill owner-stated skill experiences from a Conversation Reader artifact (OI-C13).

    Only **user**/human turns are scanned (assistant mentions are not owner evidence).
    Deterministic lexicon + claim-verb / years patterns — no LLM.
    """
    sections = artifact.get("sections") or []
    user_bits: list[str] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        role = str(sec.get("role") or "").strip().lower()
        if role not in {"user", "human", "owner", "me", "operator"}:
            continue
        text = str(sec.get("text") or "").strip()
        if text:
            user_bits.append(text)
    if not user_bits and artifact.get("text"):
        for line in str(artifact.get("text") or "").splitlines():
            low = line.lower()
            if low.startswith(("user:", "human:", "owner:", "me:", "operator:")):
                user_bits.append(line.split(":", 1)[-1].strip())

    blob = "\n".join(user_bits)
    if not blob.strip():
        return []

    src = str(asset_id or artifact.get("asset_id") or "conversation")
    found: dict[str, dict[str, Any]] = {}

    for m in _YEARS_RE.finditer(blob):
        skill_raw = (m.group(2) or m.group(3) or "").strip()
        years_raw = m.group(1) or m.group(4)
        skill = _normalize_skill(skill_raw)
        if not skill:
            continue
        years = int(years_raw) if years_raw else None
        snippet = m.group(0)[:160]
        found[skill] = {
            "statement": (
                f"Stated {years}+ years with {skill}"
                if years
                else f"Stated experience with {skill}"
            ),
            "score": 0.55 if years and years >= 2 else 0.5,
            "snippet": snippet,
            "years": years,
        }

    for m in _SKILL_FIND_RE.finditer(blob):
        skill = _normalize_skill(m.group(1))
        if not skill or skill in found:
            continue
        start, end = m.span()
        window = blob[max(0, start - 80) : min(len(blob), end + 80)]
        if not _CLAIM_VERBS.search(window):
            continue
        found[skill] = {
            "statement": f"Stated experience with {skill}",
            "score": 0.45,
            "snippet": window.strip()[:160],
            "years": None,
        }

    experiences: list[dict[str, Any]] = []
    for skill, meta in list(found.items())[:_MAX_CONVERSATION_SKILLS]:
        value: dict[str, Any] = {
            "kind": "experience",
            "skill": skill,
            "context": CTX_STATED,
        }
        if meta.get("years") is not None:
            value["years"] = meta["years"]
        prov: dict[str, Any] = {
            "source": source or "conversation",
            "asset_id": asset_id or "",
            "asset_version": asset_version,
            "skill": skill,
            "context": CTX_STATED,
            "extractor_version": EXPERIENCE_EXTRACTOR_VERSION,
            "knowledge_type": "experience",
        }
        if mission_id:
            prov["mission_id"] = mission_id
        if job_id:
            prov["job_id"] = job_id
        experiences.append({
            "statement": meta["statement"],
            "claim_type": "experience",
            "domain": DOMAIN_EXPERIENCE,
            "status": "active",
            "confidence": "LOW",
            "confidence_score": float(meta["score"]),
            "value": value,
            "supporting": [{
                "source_id": src,
                "evidence_level": 2,
                "snippet": meta["snippet"],
            }],
            "provenance": prov,
        })
    return experiences


_SKIP_DEPS = {
    "python", "pip", "setuptools", "wheel", "pytest", "pytest-cov", "coverage",
    "mypy", "ruff", "black", "flake8", "isort", "tox", "hatchling", "poetry",
    "typing-extensions", "types-requests", "pre-commit", "uv",
}


def _filter_deps(names: list[str]) -> list[str]:
    """Normalize package names and drop tooling/meta noise."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in names:
        # strip version pins: "celery[redis]>=5" → celery
        base = str(raw or "").strip().split(";")[0].strip()
        for sep in ("[", "==", ">=", "<=", "~=", "!=", ">", "<", "@"):
            if sep in base:
                base = base.split(sep, 1)[0]
        base = base.strip().strip("\"'").lower()
        if not base or base in _SKIP_DEPS or base in seen:
            continue
        seen.add(base)
        out.append(base)
    return out


def _normalize_skill(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    return _SKILL_ALT.get(s, s)


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
    an :class:`~atlas.repositories.experience_store.ExperienceStore`. Experiences are cross-project
    cumulative knowledge (P13): reverting a learn **peels** that project's supporting source
    (OI-C10) rather than deleting the shared skill row other projects still evidence.
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

    def retract_source(self, source_id: str) -> dict[str, Any]:
        """Peel one project's ``source_id`` from all experiences (OI-C10).

        Recomputes confidence/maturity from remaining supporters. Archives the row when
        no independent sources remain. Does not invent subtractive merge math beyond
        :func:`~atlas.knowledge.lifecycle.belief_from_support`.
        """
        sid = str(source_id or "").strip()
        if not sid:
            return {"retracted": 0, "updated": 0, "archived": 0, "ids": []}

        rows = self._list_active()
        retracted = updated = archived = 0
        ids: list[str] = []
        from atlas.knowledge.lifecycle import belief_from_support

        for row in rows:
            supporting = list(row.get("supporting") or row.get("supporting_sources") or [])
            kept = [
                e for e in supporting
                if self._entry_source_id(e) != sid
            ]
            if len(kept) == len(supporting):
                continue
            fid = str(row.get("id") or "")
            if not fid:
                continue
            retracted += 1
            ids.append(fid)
            if not kept:
                if hasattr(self._store, "set_status"):
                    self._store.set_status(fid, "archived")
                archived += 1
                continue
            belief = belief_from_support(kept)
            if hasattr(self._store, "update_evidence"):
                self._store.update_evidence(
                    fid,
                    supporting=kept,
                    confidence=belief["confidence"],
                    confidence_score=belief["confidence_score"],
                    maturity=belief["maturity"],
                )
            updated += 1
        self._logger.info(
            "experience retract source=%s: peeled=%d updated=%d archived=%d",
            sid, retracted, updated, archived,
        )
        return {
            "retracted": retracted,
            "updated": updated,
            "archived": archived,
            "ids": ids,
        }

    def _list_active(self) -> list[dict[str, Any]]:
        if hasattr(self._store, "list_active"):
            try:
                return list(self._store.list_active(limit=5000) or [])
            except TypeError:
                return list(self._store.list_active() or [])
        rows = getattr(self._store, "rows", None)
        if isinstance(rows, dict):
            return [
                dict(r) for r in rows.values()
                if str(r.get("status") or "") in {"active", "contested"}
            ]
        return []

    @staticmethod
    def _entry_source_id(entry: Any) -> str:
        if isinstance(entry, dict):
            return str(entry.get("source_id") or entry.get("source") or "")
        return str(entry or "")
