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
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.engineering.architecture import build_architecture_graph
from atlas.engineering.design_review import (
    CLAIM_DESIGN,
    CLAIM_RISK,
    should_review,
)
from atlas.engineering.findings import (
    CLAIM_DEPENDENCY,
    CLAIM_PATTERN,
    CLAIM_STRUCTURE,
    EXTRACTOR_VERSION,
    build_engineering_findings,
)
from atlas.knowledge.domains import DOMAIN_CODE
from atlas.learning.experience_extraction import build_repo_experiences
from atlas.models.learning import (
    LEVEL_UNDERSTAND,
    SOURCE_REPO,
    STORE_CODE,
)
from atlas.services.base import HealthStatus

# Stable namespace for a fallback repo_uid when no acquirer/asset provenance is available
# (legacy local-path learns) — keeps engineering-finding identity distinct per repository.
_FALLBACK_REPO_NS = uuid.UUID("a7c0de00-0000-4b00-8000-a71a50000002")

if TYPE_CHECKING:
    from atlas.code.service import CodeService
    from atlas.config import IntelligenceConfig
    from atlas.engineering.architecture import ArchitectureGraphStore
    from atlas.engineering.artifacts import DerivedArtifactStore
    from atlas.engineering.design_review import DesignReviewer
    from atlas.engineering.findings import EngineeringFindingWriter
    from atlas.engineering.ingest import RepoAcquirer
    from atlas.repositories.finding_repo import FindingRepository
    from atlas.repositories.intelligence_repo import IntelligenceRepository
    from atlas.services.learning_service import LearningService


class CodeStoreSink:
    """Materialises/deactivates a learned repository. Registered on the LearningService
    under the ``code`` store so repository promotion flows through the one ledger.

    Applying also promotes the run's **engineering findings** into ``knowledge.findings``
    (domain=code) via the :class:`EngineeringFindingWriter`, so findings share the repo's
    single governed, reversible ledger event — reverting archives both (B.2/BB9).

    Dual extraction (C.6): the same run also consolidates the owner's **experiences** into
    ``learning.experiences`` via the :class:`ExperienceWriter`. Unlike findings these are NOT archived
    on revert — experiences are cross-project cumulative knowledge (P13), so retiring one learn must
    not un-corroborate a skill that other projects also evidence."""

    def __init__(
        self,
        repo: "IntelligenceRepository",
        *,
        findings: "EngineeringFindingWriter | None" = None,
        experiences: Any = None,
    ) -> None:
        self._repo = repo
        self._findings = findings
        self._experiences = experiences

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
            # Phase B provenance (§B.1): stable identity + Asset Store link (may be absent).
            repo_uid=payload.get("repo_uid"),
            root_commit=payload.get("root_commit"),
            normalized_remote=payload.get("normalized_remote"),
            asset_id=payload.get("asset_id"),
            asset_version=payload.get("asset_version"),
        )
        if self._findings is not None and payload.get("engineering_findings"):
            claim_types = payload.get("engineering_finding_claim_types")
            self._findings.write(
                payload["engineering_findings"],
                archive_claim_types=set(claim_types) if claim_types else None,
            )
        if self._experiences is not None and payload.get("experiences"):
            self._experiences.write(payload["experiences"])
        return rec.id

    def revert(self, ref_id: str) -> None:
        self._repo.set_repository_status(ref_id, "reverted")
        if self._findings is not None:
            rec = self._repo.get_repository(ref_id)
            repo_uid = getattr(rec, "repo_uid", None)
            if repo_uid:
                self._findings.archive_for_repo(str(repo_uid))


class IntelligenceService:
    name = "intelligence"

    def __init__(
        self,
        code: "CodeService",
        repo: "IntelligenceRepository",
        learning: "LearningService",
        config: "IntelligenceConfig | None" = None,
        *,
        acquirer: "RepoAcquirer | None" = None,
        artifacts: "DerivedArtifactStore | None" = None,
        graph_store: "ArchitectureGraphStore | None" = None,
        design_reviewer: "DesignReviewer | None" = None,
        findings: "EngineeringFindingWriter | None" = None,
        finding_repo: "FindingRepository | None" = None,
        coverage: Any = None,
        policy: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._code = code
        self._repo = repo
        self._learning = learning
        self._config = config
        self._acquirer = acquirer
        self._artifacts = artifacts
        self._graph_store = graph_store
        self._design_reviewer = design_reviewer
        self._findings = findings
        self._finding_repo = finding_repo
        # C.4: when wired, record repo extraction into the coverage map (telemetry, never gates learn).
        self._coverage = coverage
        # C.5: when wired, operator policies influence advice ranking (influence, not arbitration).
        self._policy = policy
        self._enabled = getattr(config, "enabled", True)
        self._default_policy = getattr(config, "default_policy", "project")
        self._min_repos = getattr(config, "generalize_min_repos", 2)
        self._min_prevalence = getattr(config, "generalize_min_prevalence", 0.6)
        self._top_k = getattr(config, "recommend_top_k", 5)
        self._embed = getattr(config, "embed_code", False)
        self._embed_cap = getattr(config, "embed_cap", 500)
        self._logger = logger or logging.getLogger("atlas.intelligence")

    # --- L2 Understand --------------------------------------------------
    def learn_repository(
        self,
        root: str | None = None,
        *,
        path: str | None = None,
        url: str | None = None,
        branch: str | None = None,
        mission_id: str | None = None,
        job_id: str | None = None,
        policy: str | None = None,
        apply: bool = True,
        embed: bool | None = None,
    ) -> dict[str, Any]:
        """Acquire a repository (local path or remote URL) and promote its structure (governed).

        When a :class:`RepoAcquirer` is wired (B.1), the repo is first registered as a
        versioned ``git_repo`` **asset** (raw bytes) and distilled **from the asset copy**, so
        the learned row carries a stable ``repo_uid`` + ``asset_id/version`` provenance and a
        re-clone of the same repo re-uses its asset version. Without an acquirer it falls back
        to distilling a local ``root`` in place (pre-Phase-B behaviour).

        Explicit user act ⇒ applied by default; still recorded in the ledger so it is
        explainable and reversible. Returns a structured outcome (never raises)."""
        source_path = path or root
        if not source_path and not url:
            return {"outcome": "error", "reason": "learn_repository requires a path or url"}

        acquired = None
        if self._acquirer is not None and (url or source_path):
            try:
                acquired = self._acquirer.acquire(
                    path=source_path, url=url, branch=branch, mission_id=mission_id
                )
                distill_root = acquired.working_dir
            except Exception as exc:  # noqa: BLE001 - acquisition must never crash the call
                self._logger.exception("repo acquisition failed for %s", url or source_path)
                return {"outcome": "error", "reason": str(exc)}
        elif url:
            return {"outcome": "error", "reason": "remote URLs require the repo acquirer"}
        else:
            distill_root = source_path  # type: ignore[assignment]

        reader = "code"
        reader_version = getattr(self._code, "VERSION", "1.0.0")
        embed_result: dict[str, Any] | None = None
        try:
            # Reader → Artifact (BB11): reuse the cached artifact for an unchanged asset
            # version so a re-extraction never re-parses the repo.
            artifact = self._load_artifact(
                distill_root, acquired, reader=reader, reader_version=reader_version
            )
            payload = self._distill_from_artifact(artifact, distill_root)

            if acquired is not None:
                # Stamp durable identity + Asset Store provenance; keep logical source as root.
                payload["root"] = acquired.source
                payload["repo_uid"] = acquired.repo_uid
                payload["root_commit"] = acquired.root_commit
                payload["normalized_remote"] = acquired.normalized_remote
                payload["asset_id"] = acquired.asset_id
                payload["asset_version"] = acquired.asset_version
            payload.setdefault("repo_uid", self._fallback_repo_uid(payload["root"]))

            # Artifact → Extraction → Knowledge (BB2): engineering findings ride the same event.
            payload["engineering_findings"] = build_engineering_findings(
                payload, artifact,
                repo_uid=payload.get("repo_uid"),
                asset_id=payload.get("asset_id"),
                asset_version=payload.get("asset_version"),
                reader=reader, reader_version=reader_version,
                # P12 provenance: who discovered these findings (never ownership).
                mission_id=mission_id, job_id=job_id,
                source=SOURCE_REPO,
            )
            # Dual extraction (C.6): the SAME read also distills owner experiences (languages,
            # frameworks, patterns). They ride the same governed event and are consolidated into
            # learning.experiences by the sink, becoming cumulative across projects (P13/CC6).
            payload["experiences"] = build_repo_experiences(
                payload,
                repo_uid=payload.get("repo_uid"),
                asset_id=payload.get("asset_id"),
                asset_version=payload.get("asset_version"),
                mission_id=mission_id, job_id=job_id,
                source=SOURCE_REPO,
            )
            # The import/call/module graph is a diffable derived product (B.3/BB3).
            graph_doc = build_architecture_graph(artifact, repo_uid=payload["repo_uid"])

            if self._embed if embed is None else embed:
                embed_result = self._maybe_embed(distill_root)
        except NotADirectoryError:
            return {"outcome": "error", "reason": f"not a directory: {distill_root}"}
        except Exception as exc:  # noqa: BLE001 - parsing must never crash the call
            self._logger.exception("learn_repository failed for %s", distill_root)
            return {"outcome": "error", "reason": str(exc)}
        finally:
            if acquired is not None:
                acquired.cleanup()

        # B.3 persist the graph *first* so the design review (B.5) can gate on its structural
        # diff before the findings are written into the one governed ledger event.
        graph_info = self._persist_graph(
            payload["repo_uid"], graph_doc,
            asset_id=payload.get("asset_id"),
            asset_version=payload.get("asset_version"),
            mission_id=mission_id,
        )

        # B.5 design reasoning — advice-only, structural-change-triggered (BB6/Q-B3/P10).
        covered = {CLAIM_STRUCTURE, CLAIM_DEPENDENCY, CLAIM_PATTERN}
        design_info = self._run_design_review(
            payload, graph_doc, graph_info, mission_id=mission_id, job_id=job_id
        )
        if design_info["ran"]:
            payload["engineering_findings"].extend(design_info["findings"])
            covered |= {CLAIM_DESIGN, CLAIM_RISK}
        payload["engineering_finding_claim_types"] = sorted(covered)

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
        out = {
            "outcome": "ok",
            "event": result.get("event"),
            "applied": result.get("applied", False),
            "findings": len(payload.get("engineering_findings", [])),
            "experiences": len(payload.get("experiences", [])),
            "design_findings": len(design_info["findings"]),
            "design_review": {"ran": design_info["ran"], "reason": design_info["reason"]},
        }
        if embed_result is not None:
            out["embedded_chunks"] = embed_result.get("ingested_chunks", 0)
        self._record_coverage(
            payload, reader=reader, reader_version=reader_version,
            findings_count=out["findings"],
            chunks_count=int((embed_result or {}).get("ingested_chunks", 0)),
        )
        if graph_info is not None:
            out["architecture_graph"] = graph_info
        if acquired is not None:
            out["asset"] = {
                "repo_uid": acquired.repo_uid,
                "asset_id": acquired.asset_id,
                "asset_version": acquired.asset_version,
                "reused": acquired.reused,
                "tree_checksum": acquired.tree_checksum,
            }
        ref = (result.get("event") or {}).get("ref_id")
        if ref:
            rec = self._repo.get_repository(ref)
            out["repository"] = rec.as_dict() if rec else None
        return out

    def _record_coverage(
        self,
        payload: dict[str, Any],
        *,
        reader: str,
        reader_version: str,
        findings_count: int,
        chunks_count: int,
    ) -> None:
        """Record what the code reader extracted from this repo asset (C.4).

        Requires an Asset Store-backed learn (asset_id present); legacy local-path learns have no
        asset to key coverage on and are skipped. Best-effort telemetry — never fails the learn."""
        if self._coverage is None:
            return
        asset_id = payload.get("asset_id")
        asset_version = payload.get("asset_version")
        if not asset_id or asset_version is None:
            return
        try:
            self._coverage.record(
                asset_id,
                int(asset_version),
                reader,
                reader_version,
                status="done",
                extractor_version=EXTRACTOR_VERSION,
                domain=DOMAIN_CODE,
                source=SOURCE_REPO,
                repo_uid=payload.get("repo_uid"),
                findings_count=findings_count,
                chunks_count=chunks_count,
            )
        except Exception:  # noqa: BLE001 - coverage is best-effort telemetry
            self._logger.warning(
                "failed to record coverage for %s", asset_id, exc_info=True
            )

    def _load_artifact(
        self,
        distill_root: str,
        acquired: Any,
        *,
        reader: str,
        reader_version: str,
    ) -> dict[str, Any]:
        """Return the reader artifact, reusing the Derived Artifact Store when possible (BB11)."""
        asset_id = getattr(acquired, "asset_id", None)
        asset_version = getattr(acquired, "asset_version", None)
        can_cache = (
            self._artifacts is not None and asset_id and asset_version is not None
        )
        if can_cache:
            cached = self._artifacts.get(asset_id, asset_version, reader, reader_version)
            if cached is not None:
                self._logger.info(
                    "reusing derived artifact for asset %s v%s (%s %s) — no re-parse",
                    asset_id, asset_version, reader, reader_version,
                )
                return cached
        # Reached only on a Derived-Artifact-Store miss (new/unknown asset version), so we always
        # want a fresh parse — a re-ingest of the same local path must not be served a stale
        # in-memory parse (otherwise a changed repo would look unchanged, breaking re-ingest).
        artifact = self._code.artifact(distill_root, refresh=True)
        if can_cache:
            try:
                self._artifacts.put(
                    asset_id, asset_version, reader, reader_version, artifact
                )
            except Exception:  # noqa: BLE001 - caching is best-effort, never fatal
                self._logger.debug("derived artifact cache write failed", exc_info=True)
        return artifact

    def _maybe_embed(self, distill_root: str) -> dict[str, Any] | None:
        """Embed code chunks into the knowledge base (BB4); best-effort, never fatal."""
        try:
            return self._code.index(
                distill_root, ingest=True, embed_cap=self._embed_cap
            )
        except Exception:  # noqa: BLE001 - embedding must never crash a learn
            self._logger.exception("code embedding failed for %s", distill_root)
            return None

    def _persist_graph(
        self,
        repo_uid: str,
        graph_doc: dict[str, Any],
        *,
        asset_id: str | None,
        asset_version: int | None,
        mission_id: str | None,
    ) -> dict[str, Any] | None:
        """Persist the architecture graph as a versioned asset (B.3); best-effort."""
        if self._graph_store is None:
            return None
        try:
            return self._graph_store.persist(
                repo_uid, graph_doc,
                repo_asset_id=asset_id,
                repo_asset_version=asset_version,
                mission_id=mission_id,
            )
        except Exception:  # noqa: BLE001 - graph persistence must never crash a learn
            self._logger.exception("architecture graph persist failed for %s", repo_uid)
            return None

    def _run_design_review(
        self,
        payload: dict[str, Any],
        graph_doc: dict[str, Any],
        graph_info: dict[str, Any] | None,
        *,
        mission_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Structural-change-gated design review during a learn (B.5). Never raises."""
        if self._design_reviewer is None or not self._design_reviewer.available():
            return {"ran": False, "reason": "design review disabled or LLM unavailable",
                    "findings": []}
        if not should_review(graph_info):
            return {"ran": False, "reason": "no structural change (design review skipped)",
                    "findings": []}
        try:
            findings = self._design_reviewer.review(
                distilled=payload,
                graph_doc=graph_doc,
                diff=(graph_info or {}).get("diff"),
                repo_uid=payload.get("repo_uid"),
                asset_id=payload.get("asset_id"),
                asset_version=payload.get("asset_version"),
                reader="code",
                reader_version=getattr(self._code, "VERSION", "1.0.0"),
                mission_id=mission_id, job_id=job_id, source=SOURCE_REPO,
            )
        except Exception:  # noqa: BLE001 - design review must never crash a learn
            self._logger.exception("design review failed for %s", payload.get("name"))
            return {"ran": False, "reason": "design review error", "findings": []}
        return {"ran": True, "reason": "structural change", "findings": findings}

    def review_design(self, repo_uid: str) -> dict[str, Any]:
        """On-demand design review for a learned repo (B.5) — always available via the API.

        Reuses the repo's persisted architecture graph (B.3) + learned metadata; writes
        design/risk findings through the governed finding writer (scoped so structure/
        dependency/pattern findings are untouched). Returns a structured outcome (never raises).
        """
        if self._design_reviewer is None or not self._design_reviewer.available():
            return {"outcome": "unavailable", "reason": "design review disabled or no LLM"}
        if self._graph_store is None:
            return {"outcome": "error", "reason": "no architecture graph store"}
        graph_doc = self._graph_store.get(repo_uid)
        if graph_doc is None:
            return {"outcome": "error", "reason": f"no architecture graph for {repo_uid}"}
        rec = self._repo.get_by_repo_uid(repo_uid)
        if rec is None:
            return {"outcome": "error", "reason": f"no learned repository for {repo_uid}"}
        record = rec.as_dict()
        distilled = {
            "name": record.get("name", "repo"),
            "root": record.get("root", ""),
            "languages": record.get("languages", {}),
            "frameworks": record.get("frameworks", []),
            "patterns": record.get("patterns", []),
            "repo_uid": repo_uid,
            "asset_id": record.get("asset_id"),
            "asset_version": record.get("asset_version"),
        }
        try:
            findings = self._design_reviewer.review(
                distilled=distilled,
                graph_doc=graph_doc,
                diff=None,
                repo_uid=repo_uid,
                asset_id=record.get("asset_id"),
                asset_version=record.get("asset_version"),
                reader="code",
                reader_version=getattr(self._code, "VERSION", "1.0.0"),
            )
        except Exception as exc:  # noqa: BLE001 - on-demand review must never raise
            self._logger.exception("on-demand design review failed for %s", repo_uid)
            return {"outcome": "error", "reason": str(exc)}
        written = {}
        if self._findings is not None:
            written = self._findings.write(
                findings, archive_claim_types={CLAIM_DESIGN, CLAIM_RISK}
            )
        return {
            "outcome": "ok",
            "repo_uid": repo_uid,
            "design_findings": len(findings),
            "findings": findings,
            "written": written,
        }

    def architecture_graph(
        self, repo_uid: str, *, version: int | None = None
    ) -> dict[str, Any] | None:
        """Return a repo's persisted architecture graph (latest unless a version given, B.3)."""
        if self._graph_store is None:
            return None
        return self._graph_store.get(repo_uid, version)

    def architecture_graph_versions(self, repo_uid: str) -> list[dict[str, Any]]:
        """Version rows (newest first) for a repo's architecture graph (B.3)."""
        if self._graph_store is None:
            return []
        return self._graph_store.versions(repo_uid)

    def architecture_graph_diff(
        self, repo_uid: str, from_version: int, to_version: int
    ) -> dict[str, Any] | None:
        """Structural diff between two persisted graph versions (B.3)."""
        if self._graph_store is None:
            return None
        return self._graph_store.diff(repo_uid, from_version, to_version)

    # --- engineering findings (read side, B.7) --------------------------
    def list_findings(
        self,
        *,
        repo_uid: str | None = None,
        claim_type: str | None = None,
        mission_id: str | None = None,
        job_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Active engineering findings (``domain="code"``), optionally scoped to a repo/claim type.

        ``mission_id``/``job_id`` scope to *who discovered* the findings (P12 provenance — a
        read-only lens, never an ownership/visibility filter). Each row is shaped for the
        API/console with the **"why"** (P9): statement, confidence, value (evidence/rationale/
        rejected alternatives for design findings), and provenance (repo/path/symbol/reader/model)."""
        if self._finding_repo is None:
            return []
        if mission_id:
            rows = self._finding_repo.list_by_mission(mission_id, limit=limit)
        elif job_id:
            rows = self._finding_repo.list_by_job(job_id, limit=limit)
        elif repo_uid:
            rows = self._finding_repo.list_active_by_repo_uid(repo_uid, domain=DOMAIN_CODE)
        else:
            rows = self._finding_repo.list_active(domain=DOMAIN_CODE, limit=limit)
        if claim_type:
            rows = [r for r in rows if str(r.get("claim_type", "")) == claim_type]
        return [self._finding_view(r) for r in rows[:limit]]

    @staticmethod
    def _finding_view(row: dict[str, Any]) -> dict[str, Any]:
        def _iso(value: Any) -> Any:
            return value.isoformat() if hasattr(value, "isoformat") else value

        prov = row.get("provenance") or {}
        return {
            "id": str(row.get("id", "")),
            "canonical_id": row.get("canonical_id"),
            "statement": row.get("statement", ""),
            "claim_type": row.get("claim_type", ""),
            "confidence": row.get("confidence", ""),
            "confidence_score": row.get("confidence_score", 0.0),
            "status": row.get("status", ""),
            "value": row.get("value") or {},
            "provenance": prov,
            # P12: who *discovered* this (columns preferred, provenance JSON as fallback).
            "mission_id": (str(row["mission_id"]) if row.get("mission_id") else None)
            or prov.get("mission_id"),
            "job_id": (str(row["job_id"]) if row.get("job_id") else None) or prov.get("job_id"),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
        }

    @staticmethod
    def _fallback_repo_uid(root: str) -> str:
        return str(uuid.uuid5(_FALLBACK_REPO_NS, f"path:{root}"))

    def _distill_from_artifact(
        self, artifact: dict[str, Any], distill_root: str
    ) -> dict[str, Any]:
        repo_map = artifact.get("repo_map", {}) or {}
        patterns = artifact.get("patterns", []) or []
        symbols = artifact.get("symbols", []) or []
        symbol_count = artifact.get("symbol_count")
        if symbol_count is None:
            symbol_count = sum(int(f.get("symbols", 0)) for f in repo_map.get("files", []))
        root = repo_map.get("root", str(Path(distill_root).resolve()))
        name = Path(root).name or "repo"
        frameworks = repo_map.get("frameworks", [])
        languages = repo_map.get("languages", {})
        summary = self._summarize(name, languages, frameworks, patterns)
        top_symbols = [
            {"qualname": s.get("qualname"), "kind": s.get("kind"), "file": s.get("file")}
            for s in symbols[:25]
        ]
        return {
            "name": name,
            "root": root,
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
        for p in ranked:
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
        # C.5: operator policies re-order advice (prefer/avoid) — influence, never removal (CC8).
        self._apply_policy_to_recs(recs)
        recs = recs[:k]
        return {"context": context, "recommendations": recs, "level": 5}

    def _apply_policy_to_recs(self, recs: list[dict[str, Any]]) -> None:
        policy = getattr(self, "_policy", None)
        if policy is None or not hasattr(policy, "advice_influence"):
            return
        try:
            influence = list(policy.advice_influence() or [])
        except Exception:  # noqa: BLE001 - policy must never break advice
            self._logger.debug("policy advice influence failed", exc_info=True)
            return
        if not influence:
            return
        for rec in recs:
            text = f"{rec['pattern']} {rec['category']} {rec['recommendation']}".lower()
            tokens = set(re.findall(r"[a-z0-9]+", text))
            delta = 0.0
            applied: list[str] = []
            for pr in influence:
                terms = set(pr.get("terms") or ())
                weight = float(pr.get("weight") or 0.0)
                if not terms or weight == 0.0:
                    continue
                overlap = len(terms & tokens) / len(terms)
                if overlap > 0:
                    delta += weight * overlap
                    applied.append(str(pr.get("id")))
            rec["policy_boost"] = round(delta, 4)
            rec["policy_ids"] = applied
        recs.sort(key=lambda r: -(r["prevalence"] + r.get("policy_boost", 0.0)))

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
