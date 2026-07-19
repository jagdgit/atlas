"""Engineering findings extraction (Phase B · §B.2, BB2/BB8/Q-B5).

Turns a reader **Artifact** (repo map, mined patterns, dependency graph) into durable
**engineering findings** in ``knowledge.findings`` with ``domain="code"`` — *no new findings
table* (P5/P7). Findings carry structural provenance (``repo_uid/asset/path/symbol/reader``)
and artifact versions (BB8); identity is ``repo_uid+path+symbol+claim_type+reader`` (Q-B5) so a
re-ingest **supersedes** the matching revision and **archives** ones that disappeared — never a
blind overwrite. Per constitution P11 this is a stateless translator: it reads artifacts and
writes findings; it owns no state and makes no decisions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.knowledge.domains import DOMAIN_CODE
from atlas.knowledge.lifecycle import finding_identity_key

if TYPE_CHECKING:
    from atlas.repositories.finding_repo import FindingRepository

# Extractor version (P2/BB8): bump when the finding *shape* changes, independent of the reader.
EXTRACTOR_VERSION = "1.0.0"

CLAIM_STRUCTURE = "structure"
CLAIM_DEPENDENCY = "dependency"
CLAIM_PATTERN = "pattern"


def _provenance(
    *,
    repo_uid: str | None,
    asset_id: str | None,
    asset_version: int | None,
    repo: str,
    path: str,
    symbol: str,
    reader: str,
    reader_version: str,
    mission_id: str | None = None,
    job_id: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    prov: dict[str, Any] = {
        "repo_uid": repo_uid or "",
        "asset_id": asset_id or "",
        "asset_version": asset_version,
        "repo": repo,
        "path": path,
        "symbol": symbol,
        "reader": reader,
        "reader_version": reader_version,
        "extractor_version": EXTRACTOR_VERSION,
        "knowledge_type": "software",
    }
    # P12: who *discovered* this finding (provenance, not ownership). Omitted when unknown so
    # pre-Phase-C / non-mission ingests stay byte-identical.
    if mission_id:
        prov["mission_id"] = mission_id
    if job_id:
        prov["job_id"] = job_id
    if source:
        prov["source"] = source
    return prov


def build_engineering_findings(
    distilled: dict[str, Any],
    artifact: dict[str, Any],
    *,
    repo_uid: str | None,
    asset_id: str | None,
    asset_version: int | None,
    reader: str,
    reader_version: str,
    mission_id: str | None = None,
    job_id: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Structure + dependency + pattern findings for one repository ingest (B.2).

    ``mission_id``/``job_id``/``source`` are stamped as **provenance** (P12): who *discovered* the
    finding, never who owns it.
    """
    name = distilled.get("name", "repo")
    repo = distilled.get("root", "")
    languages = distilled.get("languages", {}) or {}
    frameworks = distilled.get("frameworks", []) or []
    dependencies = distilled.get("dependencies", {}) or {}
    patterns = distilled.get("patterns", []) or artifact.get("patterns", []) or []

    def prov(path: str, symbol: str) -> dict[str, Any]:
        return _provenance(
            repo_uid=repo_uid, asset_id=asset_id, asset_version=asset_version,
            repo=repo, path=path, symbol=symbol, reader=reader, reader_version=reader_version,
            mission_id=mission_id, job_id=job_id, source=source,
        )

    findings: list[dict[str, Any]] = []

    # 1. One repo-level structure finding.
    lang_str = ", ".join(sorted(languages, key=lambda k: -languages[k])[:4]) or "unknown"
    fw_str = ", ".join(frameworks[:5]) or "no detected framework"
    findings.append({
        "statement": (
            f"{name} is a {lang_str} project ({distilled.get('file_count', 0)} files, "
            f"{distilled.get('symbol_count', 0)} symbols) using {fw_str}."
        ),
        "claim_type": CLAIM_STRUCTURE,
        "domain": DOMAIN_CODE,
        "confidence": "HIGH",
        "confidence_score": 0.95,
        "value": {
            "kind": "repo_structure",
            "file_count": distilled.get("file_count", 0),
            "symbol_count": distilled.get("symbol_count", 0),
            "loc": distilled.get("loc", 0),
            "languages": languages,
            "frameworks": frameworks,
            "entry_points": distilled.get("entry_points", []),
        },
        "provenance": prov("", ""),
    })

    # 2. One dependency finding per package manager (symbol = manager → distinct identity).
    for manager in sorted(dependencies):
        deps = dependencies.get(manager) or []
        if not deps:
            continue
        shown = ", ".join(sorted(str(d) for d in deps)[:12])
        findings.append({
            "statement": f"{name} declares {len(deps)} {manager} dependency(ies): {shown}.",
            "claim_type": CLAIM_DEPENDENCY,
            "domain": DOMAIN_CODE,
            "confidence": "HIGH",
            "confidence_score": 0.9,
            "value": {"kind": "dependencies", "manager": manager, "dependencies": list(deps)},
            "provenance": prov("", manager),
        })

    # 3. One pattern finding per mined engineering pattern (symbol = pattern name).
    for pat in patterns:
        pname = str(pat.get("name", "")).strip()
        if not pname:
            continue
        findings.append({
            "statement": f"{name} applies the {pname} pattern. {pat.get('description', '')}".strip(),
            "claim_type": CLAIM_PATTERN,
            "domain": DOMAIN_CODE,
            "confidence": "MEDIUM",
            "confidence_score": float(pat.get("confidence", 0.7) or 0.7),
            "value": {"kind": "pattern", "name": pname},
            "provenance": prov("", pname),
        })

    return findings


class EngineeringFindingWriter:
    """Governed, supersession-aware writer for engineering findings (B.2/BB9).

    C.3e — the per-finding write goes through the **Knowledge Consolidator**
    (``KnowledgeLifecycleService.consolidate``) so there is a single create/noop/revise path for all
    knowledge. This writer keeps only what the one-finding-at-a-time consolidator has *no* concept
    of: the **repo-scoped batch archival** of findings that vanished from the current ingest
    (``_archive_stale``), which stays as a distinct post-step wrapper.
    """

    def __init__(
        self,
        finding_repo: "FindingRepository",
        *,
        lifecycle: Any | None = None,
        lineage: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = finding_repo
        self._logger = logger or logging.getLogger("atlas.engineering.findings")
        if lifecycle is None:
            from atlas.knowledge.consolidation import KnowledgeLifecycleService

            lifecycle = KnowledgeLifecycleService(finding_repo, lineage=lineage, logger=self._logger)
        self._life = lifecycle

    def write(
        self,
        findings: list[dict[str, Any]],
        *,
        archive_claim_types: set[str] | None = None,
    ) -> dict[str, Any]:
        """Consolidate the given findings and archive stale ones for the repo.

        Each finding is routed through the Consolidator (single write path, CC3): new → create,
        unchanged → noop, changed body → revise (stable canonical). ``archive_claim_types`` scopes
        the batch archival to the given claim types — so an ingest that deliberately omits a family
        of findings (e.g. a doc-only re-ingest that **skips** the LLM design review, B.5) does **not**
        archive the prior findings of the omitted family. ``None`` (default) archives every stale
        finding for the repo (back-compatible).
        """
        if not findings:
            return {"created": 0, "revised": 0, "archived": 0, "noop": 0, "ids": []}
        repo_uid = str((findings[0].get("provenance") or {}).get("repo_uid") or "")
        created = revised = noop = 0
        ids: list[str] = []
        seen: set[tuple[Any, ...]] = set()

        for data in findings:
            seen.add(finding_identity_key(data))
            # Engineering findings are durable, active claims; stamp the axes the consolidator's
            # fingerprint/identity expect so a byte-identical re-ingest is a true no-op.
            incoming = {**data, "status": "active", "domain": DOMAIN_CODE}
            row = self._life.consolidate(incoming)
            transition = row.get("_transition")
            if transition == "create":
                created += 1
            elif transition == "noop":
                noop += 1
            else:  # revise / supersede / split_contested / contested / merge_evidence
                revised += 1
            ids.append(str(row["id"]))

        archived = self._archive_stale(
            repo_uid, keep=seen, claim_types=archive_claim_types
        )
        self._logger.info(
            "engineering findings for %s: +%d ~%d =%d -%d",
            repo_uid, created, revised, noop, archived,
        )
        return {
            "created": created, "revised": revised, "archived": archived,
            "noop": noop, "ids": ids,
        }

    def archive_for_repo(self, repo_uid: str) -> int:
        """Archive every active engineering finding for a repo (revert path, BB9)."""
        return self._archive_stale(repo_uid, keep=set())

    def _archive_stale(
        self,
        repo_uid: str,
        *,
        keep: set[tuple[Any, ...]],
        claim_types: set[str] | None = None,
    ) -> int:
        if not repo_uid:
            return 0
        archived = 0
        for row in self._repo.list_active_by_repo_uid(repo_uid, domain=DOMAIN_CODE):
            if finding_identity_key(row) in keep:
                continue
            if claim_types is not None and str(row.get("claim_type", "")) not in claim_types:
                continue
            self._repo.set_status(str(row["id"]), "archived")
            archived += 1
        return archived
