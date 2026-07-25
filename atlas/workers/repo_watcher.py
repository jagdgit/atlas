"""RepoWatcher — the Repository-Learning persistent worker (Phase B · §B.6, BB7).

Each tick re-learns a repository through the B.1–B.5 pipeline, structured as the operator-added
interface **Detect → Compare → Policy → Ingest**:

- **Detect** — has the working tree changed since the last tick? (cheap content checksum +
  per-file blob manifest for a local path). An unchanged repo short-circuits to a **cheap no-op**.
- **Compare** — file-level delta (added/removed/modified) from the Detect manifests (OI-B2);
  architecture-graph module deltas are still attached after Ingest for the journal.
- **Policy** — ``decide_policy`` chooses ``skip`` / ``partial_ingest`` / ``full_ingest``.
- **Ingest** — ``IntelligenceService.learn_repository`` (governed, reversible), optionally with
  ``paths=`` / ``drop_paths=`` so only the changed files are re-parsed and merged into the prior
  artifact (same Derived Artifact / graph / findings stores — no parallel).

Durability (checkpoint/resume, crash backoff, versioned-config pickup, live operator input) is
the WorkerManager's job (see ``workers/base.py``); this worker only implements one bounded tick.
Per P11 it owns no knowledge — it drives the stateless translators and journals what it did (P9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from atlas.engineering.ingest import (
    compute_tree_checksum,
    diff_file_manifests,
    file_blob_manifest,
)
from atlas.workers.base import PersistentWorker, TickContext, TickResult

if TYPE_CHECKING:
    from atlas.intelligence.service import IntelligenceService

POLICY_SKIP = "skip"
POLICY_FULL_INGEST = "full_ingest"
POLICY_PARTIAL_INGEST = "partial_ingest"

# Small file deltas use partial re-parse; larger / first / forced ticks stay full.
PARTIAL_MAX_CHANGED = 20
PARTIAL_MAX_REMOVED = 5


def decide_policy(change_set: dict[str, Any]) -> str:
    """The **Policy** hook: decide what to do about a change set (OI-B2).

    - no change → skip
    - first tick / force / unknown file delta → full_ingest
    - small file delta (≤ partial_max_changed, ≤ partial_max_removed) → partial_ingest
    - otherwise → full_ingest
    """
    if not change_set.get("changed", True):
        return POLICY_SKIP
    if change_set.get("force_full") or not change_set.get("has_baseline", False):
        return POLICY_FULL_INGEST
    changed_files = change_set.get("changed_files")
    if changed_files is None:
        # Compat: post-ingest architecture-only change sets without file lists.
        return POLICY_FULL_INGEST
    removed = list(change_set.get("removed_files") or [])
    if not changed_files and not removed:
        return POLICY_SKIP
    max_c = int(change_set.get("partial_max_changed") or PARTIAL_MAX_CHANGED)
    max_r = int(change_set.get("partial_max_removed") or PARTIAL_MAX_REMOVED)
    if len(changed_files) <= max_c and len(removed) <= max_r:
        return POLICY_PARTIAL_INGEST
    return POLICY_FULL_INGEST


class RepoWatcher(PersistentWorker):
    type = "repo_watcher"
    VERSION = 2
    journal_ticks = True  # journal meaningful ticks (ingests/changes); no-ops return empty notes

    def __init__(self, intelligence: "IntelligenceService") -> None:
        self._intel = intelligence

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})

        # Live operator input (Q4): a transient nudge to force a re-ingest this tick.
        force = any(bool(item.get("force")) for item in ctx.inputs)

        repo_path = str(cfg.get("repo_path") or "").strip()
        repo_url = str(cfg.get("repo_url") or "").strip()
        if not repo_path and not repo_url:
            return TickResult(state=state, note="")  # nothing configured yet — idle quietly

        # A versioned config edit (add a language / toggle embed) is picked up automatically by
        # the manager; surface it in the journal so "config change picked up next tick" is visible.
        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        # --- Detect ------------------------------------------------------
        detected = self._detect(repo_path, state, force=force)
        if detected["skip"]:
            state["ticks"] = int(state.get("ticks", 0)) + 1
            state["last_result"] = "no_change"
            note = f"{config_note}no change (tree unchanged)".strip() if config_note else ""
            return TickResult(state=state, note=note)

        # --- Compare (file delta) + Policy *before* Ingest (OI-B2) ------
        file_delta = detected.get("file_delta") or {}
        pre_cs = {
            "changed": True,
            "has_baseline": bool(detected.get("has_baseline")),
            "changed_files": file_delta.get("changed_files"),
            "removed_files": file_delta.get("removed") or [],
            "force_full": bool(force or not repo_path),
            "partial_max_changed": int(cfg.get("partial_max_changed") or PARTIAL_MAX_CHANGED),
            "partial_max_removed": int(cfg.get("partial_max_removed") or PARTIAL_MAX_REMOVED),
        }
        policy = decide_policy(pre_cs)

        learn_kw: dict[str, Any] = {
            "path": repo_path or None,
            "url": repo_url or None,
            "branch": cfg.get("branch"),
            "mission_id": ctx.mission_id,
            "policy": cfg.get("policy") or "project",
            "embed": bool(cfg.get("embed_code", False)),
        }
        if policy == POLICY_PARTIAL_INGEST:
            learn_kw["paths"] = list(file_delta.get("changed_files") or [])
            learn_kw["drop_paths"] = list(file_delta.get("removed") or [])

        # --- Ingest ------------------------------------------------------
        out = self._intel.learn_repository(**learn_kw)
        if out.get("outcome") != "ok":
            # A real ingest failure (missing path, clone error): surface it so the manager applies
            # crash backoff and — if persistent — pauses for the operator (B4). Never silent.
            raise RuntimeError(f"repo ingest failed: {out.get('reason', 'unknown error')}")

        change_set = self._change_set(out)
        change_set["ingest_policy"] = policy
        change_set["changed_files"] = list(file_delta.get("changed_files") or [])
        change_set["removed_files"] = list(file_delta.get("removed") or [])

        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["ingests"] = int(state.get("ingests", 0)) + 1
        state["last_result"] = "ingested"
        state["last_policy"] = policy
        state["last_change_set"] = change_set
        state["repo_uid"] = (out.get("repository") or {}).get("repo_uid") or state.get("repo_uid")
        asset = out.get("asset") or {}
        # Prefer the checksum we detected from the working tree (a local path) so the next tick's
        # Detect compares like-for-like; fall back to the asset's checksum (remote URL path).
        if detected.get("checksum"):
            state["last_tree_checksum"] = detected["checksum"]
        elif asset.get("tree_checksum"):
            state["last_tree_checksum"] = asset["tree_checksum"]
        if detected.get("manifest") is not None:
            state["last_file_manifest"] = detected["manifest"]
        graph = out.get("architecture_graph") or {}
        if graph.get("version") is not None:
            state["last_graph_version"] = graph["version"]

        mode = "partial" if policy == POLICY_PARTIAL_INGEST else "full"
        note = (
            f"{config_note}ingested {change_set['name']} [{mode}]: "
            f"{out.get('findings', 0)} finding(s), {out.get('design_findings', 0)} design; "
            f"graph v{graph.get('version', '?')}"
            + (" (structural change)" if change_set["changed"] else " (unchanged graph)")
        ).strip()
        return TickResult(state=state, note=note)

    # --- Detect ---------------------------------------------------------
    def _detect(self, repo_path: str, state: dict[str, Any], *, force: bool) -> dict[str, Any]:
        """Cheap change detection: tree checksum + per-file blob manifest (OI-B2).

        Returns ``{skip, checksum, manifest, file_delta, has_baseline}``. A remote URL can't
        be detected without fetching, so it always falls through to full Ingest.
        """
        if force or not repo_path:
            return {
                "skip": False,
                "checksum": None,
                "manifest": None,
                "file_delta": None,
                "has_baseline": False,
            }
        try:
            checksum = compute_tree_checksum(repo_path)
            manifest = file_blob_manifest(repo_path)
        except Exception:  # noqa: BLE001 - detection must never crash a tick; ingest will report
            return {
                "skip": False,
                "checksum": None,
                "manifest": None,
                "file_delta": None,
                "has_baseline": False,
            }
        if checksum and checksum == state.get("last_tree_checksum"):
            return {
                "skip": True,
                "checksum": checksum,
                "manifest": manifest,
                "file_delta": None,
                "has_baseline": True,
            }
        prev = state.get("last_file_manifest")
        has_baseline = isinstance(prev, dict) and bool(prev)
        if has_baseline:
            file_delta = diff_file_manifests(prev, manifest)
        else:
            # First ingest baseline — Policy will choose full_ingest.
            file_delta = {
                "added": sorted(manifest.keys()),
                "removed": [],
                "modified": [],
                "changed_files": sorted(manifest.keys()),
            }
        return {
            "skip": False,
            "checksum": checksum,
            "manifest": manifest,
            "file_delta": file_delta,
            "has_baseline": has_baseline,
        }

    # --- Compare (post-ingest journal enrichment) -----------------------
    @staticmethod
    def _change_set(out: dict[str, Any]) -> dict[str, Any]:
        """Normalize a learn result into a change set (journal / operator surface)."""
        graph = out.get("architecture_graph") or {}
        diff = graph.get("diff") or {}
        asset = out.get("asset") or {}
        graph_changed = (graph.get("version") is not None) and not graph.get("reused", False)
        return {
            "name": (out.get("repository") or {}).get("name", "repo"),
            "changed": bool(graph_changed or diff.get("changed")),
            "asset_reused": bool(asset.get("reused", False)),
            "asset_version": asset.get("asset_version"),
            "graph_version": graph.get("version"),
            "graph_reused": bool(graph.get("reused", False)),
            "added_modules": diff.get("added_modules", []),
            "removed_modules": diff.get("removed_modules", []),
            "findings": out.get("findings", 0),
            "design_findings": out.get("design_findings", 0),
        }
