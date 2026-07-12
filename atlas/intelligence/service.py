"""IntelligenceService — the ``intelligence`` capability (S19, D11/§5d).

Engineering Intelligence is the top of the Learning-Level ladder (§5d.6). It consumes
what ``CodeCapability`` (S14) produces and turns it into knowledge *about the user*:

- **L2 Understand** — ``learn_repository`` parses a repo (repo map + mined patterns +
  symbols) and stores its structure in the **Code store**. This is promoted through
  the S18b learning ledger via ``CodeStoreSink`` — so it is *governed, explainable and
  reversible* like every other learning action (never silent).
- **L3 Connect** — ``search`` / ``connections`` do cross-project retrieval and link
  repositories that share frameworks/dependencies.
- **L4 Generalize** — ``generalize`` mines *across* learned repos to find the patterns,
  frameworks and languages you use consistently ("you *always* use the Repository
  pattern"), persisted as a recomputable materialised view.
- **L5 Recommend** — ``recommend`` turns those generalizations into proactive advice —
  the Personal Coding Assistant. ``profile`` summarises "who you are as an engineer".

Everything is best-effort and returns structured outcomes; parsing errors become an
``error`` outcome, never an exception (R2/R3).
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.models.learning import (
    LEVEL_UNDERSTAND,
    SOURCE_REPO,
    STORE_CODE,
)
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.code.service import CodeService
    from atlas.config import IntelligenceConfig
    from atlas.repositories.intelligence_repo import IntelligenceRepository
    from atlas.services.learning_service import LearningService


class CodeStoreSink:
    """Materialises/deactivates a learned repository. Registered on the LearningService
    under the ``code`` store so repository promotion flows through the one ledger."""

    def __init__(self, repo: "IntelligenceRepository") -> None:
        self._repo = repo

    def apply(self, payload: dict[str, Any], *, policy: str | None = None) -> str:
        rec = self._repo.add_repository(
            name=payload.get("name", ""),
            root=payload.get("root", ""),
            languages=payload.get("languages", {}),
            frameworks=payload.get("frameworks", []),
            entry_points=payload.get("entry_points", []),
            dependencies=payload.get("dependencies", {}),
            file_count=payload.get("file_count", 0),
            symbol_count=payload.get("symbol_count", 0),
            loc=payload.get("loc", 0),
            summary=payload.get("summary", ""),
            top_symbols=payload.get("top_symbols", []),
            patterns=payload.get("patterns", []),
            policy=policy or payload.get("policy", "project"),
        )
        return rec.id

    def revert(self, ref_id: str) -> None:
        self._repo.set_repository_status(ref_id, "reverted")


class IntelligenceService:
    name = "intelligence"

    def __init__(
        self,
        code: "CodeService",
        repo: "IntelligenceRepository",
        learning: "LearningService",
        config: "IntelligenceConfig | None" = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._code = code
        self._repo = repo
        self._learning = learning
        self._config = config
        self._enabled = getattr(config, "enabled", True)
        self._default_policy = getattr(config, "default_policy", "project")
        self._min_repos = getattr(config, "generalize_min_repos", 2)
        self._min_prevalence = getattr(config, "generalize_min_prevalence", 0.6)
        self._top_k = getattr(config, "recommend_top_k", 5)
        self._logger = logger or logging.getLogger("atlas.intelligence")

    # --- L2 Understand --------------------------------------------------
    def learn_repository(
        self, root: str, *, policy: str | None = None, apply: bool = True
    ) -> dict[str, Any]:
        """Parse a repository and promote its structure into the Code store (governed).

        Explicit user act ⇒ applied by default; still recorded in the ledger so it is
        explainable and reversible. Returns a structured outcome (never raises)."""
        try:
            payload = self._distill(root)
        except NotADirectoryError:
            return {"outcome": "error", "reason": f"not a directory: {root}"}
        except Exception as exc:  # noqa: BLE001 - parsing must never crash the call
            self._logger.exception("learn_repository failed for %s", root)
            return {"outcome": "error", "reason": str(exc)}

        result = self._learning.propose(
            SOURCE_REPO,
            STORE_CODE,
            source_id=payload["root"],
            summary=f"Learned repository: {payload['name']} "
            f"({payload['file_count']} files, {payload['symbol_count']} symbols)",
            reason="A repository's structure becomes durable Code-store knowledge (§5d).",
            origin=payload["root"],
            payload=payload,
            policy=policy or self._default_policy,
            level=LEVEL_UNDERSTAND,
            project=payload["name"],
            apply=apply,
        )
        out = {"outcome": "ok", "event": result.get("event"), "applied": result.get("applied", False)}
        ref = (result.get("event") or {}).get("ref_id")
        if ref:
            rec = self._repo.get_repository(ref)
            out["repository"] = rec.as_dict() if rec else None
        return out

    def _distill(self, root: str) -> dict[str, Any]:
        repo_map = self._code.repo_map(root)
        patterns = self._code.patterns(root)
        symbols = self._code.search_symbols("", root=root, limit=25)
        symbol_count = sum(int(f.get("symbols", 0)) for f in repo_map.get("files", []))
        name = Path(repo_map.get("root", root)).name or "repo"
        frameworks = repo_map.get("frameworks", [])
        languages = repo_map.get("languages", {})
        summary = self._summarize(name, languages, frameworks, patterns)
        top_symbols = [
            {"qualname": s.get("qualname"), "kind": s.get("kind"), "file": s.get("file")}
            for s in symbols
        ]
        return {
            "name": name,
            "root": repo_map.get("root", str(Path(root).resolve())),
            "languages": languages,
            "frameworks": frameworks,
            "entry_points": repo_map.get("entry_points", []),
            "dependencies": repo_map.get("dependencies", {}),
            "file_count": repo_map.get("file_count", 0),
            "symbol_count": symbol_count,
            "loc": repo_map.get("total_loc", 0),
            "summary": summary,
            "top_symbols": top_symbols,
            "patterns": patterns,
        }

    @staticmethod
    def _summarize(
        name: str, languages: dict[str, int], frameworks: list[str], patterns: list[dict]
    ) -> str:
        langs = ", ".join(sorted(languages, key=lambda k: -languages[k])[:3]) or "unknown"
        fw = ", ".join(frameworks[:4]) or "no framework detected"
        pat = ", ".join(p.get("name", "") for p in patterns[:4])
        base = f"{name}: {langs}; {fw}."
        return f"{base} Patterns: {pat}." if pat else base

    # --- L3 Connect -----------------------------------------------------
    def list_repositories(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self._repo.list_repositories(limit=limit)]

    def get_repository(self, repo_id: str) -> dict[str, Any] | None:
        rec = self._repo.get_repository(repo_id)
        return rec.as_dict() if rec else None

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        repos = self._repo.search_repositories(query, limit=limit) if query.strip() \
            else self._repo.list_repositories(limit=limit)
        rows = [r.as_dict() for r in repos]
        return {
            "query": query,
            "repositories": rows,
            "connections": self._connect(rows),
            "level": 3,
        }

    def connections(self) -> dict[str, Any]:
        rows = [r.as_dict() for r in self._repo.list_repositories(limit=200)]
        return {"connections": self._connect(rows), "level": 3}

    @staticmethod
    def _connect(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Link repositories that share frameworks or top-level languages (§5d L3)."""
        edges: list[dict[str, Any]] = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                shared_fw = sorted(set(a["frameworks"]) & set(b["frameworks"]))
                shared_lang = sorted(set(a["languages"]) & set(b["languages"]))
                if shared_fw or (len(shared_lang) >= 2):
                    edges.append({
                        "a": a["name"], "b": b["name"],
                        "shared_frameworks": shared_fw,
                        "shared_languages": shared_lang,
                    })
        return edges

    # --- L4 Generalize --------------------------------------------------
    def generalize(self) -> dict[str, Any]:
        """Mine across learned repos for consistently-used patterns/frameworks/langs.

        A materialised, recomputable view over the (governed) L2 repositories — it is
        an *inference*, so it is recomputed rather than separately governed."""
        repos = [r.as_dict() for r in self._repo.list_repositories(limit=500)]
        total = len(repos)
        if total < self._min_repos:
            return {
                "outcome": "insufficient_data",
                "total_repos": total,
                "min_repos": self._min_repos,
                "patterns": [],
            }
        buckets: dict[tuple[str, str], list[str]] = {}

        def bump(name: str, category: str, repo_name: str) -> None:
            if not name:
                return
            buckets.setdefault((name, category), []).append(repo_name)

        for r in repos:
            for p in r.get("patterns", []):
                bump(p.get("name", ""), "pattern", r["name"])
            for fw in r.get("frameworks", []):
                bump(fw, "framework", r["name"])
            for lang in r.get("languages", {}):
                bump(lang, "language", r["name"])

        computed: list[dict[str, Any]] = []
        for (name, category), repo_names in buckets.items():
            evidence = sorted(set(repo_names))
            prevalence = len(evidence) / total
            if prevalence < self._min_prevalence:
                continue
            computed.append({
                "name": name,
                "category": category,
                "description": f"Used in {len(evidence)}/{total} learned repositories.",
                "prevalence": prevalence,
                "repo_count": len(evidence),
                "total_repos": total,
                "confidence": round(prevalence, 3),
                "level": 4,
                "evidence": evidence,
            })
        computed.sort(key=lambda p: (-p["prevalence"], p["name"]))
        self._repo.replace_patterns(computed)
        return {"outcome": "ok", "total_repos": total, "patterns": computed, "level": 4}

    def patterns(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [p.as_dict() for p in self._repo.list_patterns(limit=limit)]

    # --- L5 Recommend ---------------------------------------------------
    def recommend(self, context: str = "", *, limit: int | None = None) -> dict[str, Any]:
        k = limit or self._top_k
        pats = self._repo.list_patterns(limit=200)
        if not pats and self._repo.count_repositories() >= self._min_repos:
            self.generalize()
            pats = self._repo.list_patterns(limit=200)
        ctx = (context or "").lower()
        ranked = sorted(pats, key=lambda p: -p.prevalence)
        recs: list[dict[str, Any]] = []
        for p in ranked[:k]:
            relevant = (not ctx) or p.name.lower() in ctx or p.category in ctx
            recs.append({
                "pattern": p.name,
                "category": p.category,
                "prevalence": round(p.prevalence, 3),
                "level_name": "L5 Recommend",
                "relevant_to_context": relevant,
                "recommendation": (
                    f"You use {p.name} in {p.repo_count}/{p.total_repos} repositories "
                    f"({p.prevalence:.0%}) — consider it here for consistency."
                ),
            })
        return {"context": context, "recommendations": recs, "level": 5}

    def profile(self) -> dict[str, Any]:
        """A summary of the user's engineering profile — 'Atlas learns *you*'."""
        repos = [r.as_dict() for r in self._repo.list_repositories(limit=500)]
        langs: Counter[str] = Counter()
        fws: Counter[str] = Counter()
        for r in repos:
            langs.update(r.get("languages", {}))
            for fw in r.get("frameworks", []):
                fws[fw] += 1
        top_patterns = [p.as_dict() for p in self._repo.list_patterns(limit=10)]
        return {
            "repositories": len(repos),
            "languages": dict(langs.most_common(10)),
            "frameworks": dict(fws.most_common(10)),
            "top_patterns": top_patterns,
            "summary": self._profile_summary(len(repos), langs, fws, top_patterns),
        }

    @staticmethod
    def _profile_summary(n: int, langs: Counter, fws: Counter, patterns: list[dict]) -> str:
        if n == 0:
            return "No repositories learned yet."
        top_lang = ", ".join(l for l, _ in langs.most_common(3)) or "various languages"
        top_fw = ", ".join(f for f, _ in fws.most_common(3)) or "no dominant framework"
        top_pat = ", ".join(p["name"] for p in patterns[:3])
        base = f"Across {n} repositories you work mainly in {top_lang}, favouring {top_fw}."
        return f"{base} You consistently apply: {top_pat}." if top_pat else base

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            repos = self._repo.count_repositories()
            pats = self._repo.count_patterns()
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return HealthStatus.fail(f"code store unreachable: {exc}")
        return HealthStatus.ok(
            f"{repos} learned repo(s), {pats} generalized pattern(s)",
            enabled=self._enabled,
        )
