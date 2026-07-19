"""RepoWatcher — the Repository-Learning persistent worker (Phase B · §B.6, BB7).

Each tick re-learns a repository through the B.1–B.5 pipeline, structured as the operator-added
interface **Detect → Compare → Policy → Ingest**:

- **Detect** — has the working tree changed since the last tick? (cheap content checksum for a
  local path). An unchanged repo short-circuits to a **cheap no-op** — no clone, no parse, no LLM,
  no new ledger event.
- **Compare** — what changed (the architecture-graph diff from B.3: added/removed modules & edges).
- **Policy** — what to do about it. Phase B always does a **full-repo** ingest; the ``decide_policy``
  hook + the change set are surfaced now so a later **partial / per-file** re-ingest drops in
  without reshaping the worker (partial ingest is out of scope for Phase B, §5).
- **Ingest** — ``IntelligenceService.learn_repository`` (governed, reversible): refreshes the
  architecture graph, supersedes findings, runs the structural-change-gated design review (B.5).

Durability (checkpoint/resume, crash backoff, versioned-config pickup, live operator input) is
the WorkerManager's job (see ``workers/base.py``); this worker only implements one bounded tick.
Per P11 it owns no knowledge — it drives the stateless translators and journals what it did (P9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from atlas.engineering.ingest import compute_tree_checksum
from atlas.workers.base import PersistentWorker, TickContext, TickResult

if TYPE_CHECKING:
    from atlas.intelligence.service import IntelligenceService

POLICY_SKIP = "skip"
POLICY_FULL_INGEST = "full_ingest"
POLICY_PARTIAL_INGEST = "partial_ingest"  # reserved for a future phase (§5)


def decide_policy(change_set: dict[str, Any]) -> str:
    """The **Policy** hook (operator-added interface): decide what to do about a change set.

    Phase B is intentionally simple — any change ⇒ a **full-repo** re-ingest, no change ⇒ skip.
    The change set already carries the per-module delta (B.3), so a later phase can return
    ``POLICY_PARTIAL_INGEST`` for small diffs here **without touching the worker**.
    """
    if not change_set.get("changed", True):
        return POLICY_SKIP
    return POLICY_FULL_INGEST


class RepoWatcher(PersistentWorker):
    type = "repo_watcher"
    VERSION = 1
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
            # Only journal when a config pickup makes this tick noteworthy; else stay quiet.
            note = f"{config_note}no change (tree unchanged)".strip() if config_note else ""
            return TickResult(state=state, note=note)

        # --- Ingest (full-repo for Phase B) ------------------------------
        out = self._intel.learn_repository(
            path=repo_path or None,
            url=repo_url or None,
            branch=cfg.get("branch"),
            mission_id=ctx.mission_id,
            policy=cfg.get("policy") or "project",
            embed=bool(cfg.get("embed_code", False)),
        )
        if out.get("outcome") != "ok":
            # A real ingest failure (missing path, clone error): surface it so the manager applies
            # crash backoff and — if persistent — pauses for the operator (B4). Never silent.
            raise RuntimeError(f"repo ingest failed: {out.get('reason', 'unknown error')}")

        # --- Compare + Policy (surfaced for a future partial ingest) -----
        change_set = self._change_set(out)
        policy = decide_policy(change_set)

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
        graph = out.get("architecture_graph") or {}
        if graph.get("version") is not None:
            state["last_graph_version"] = graph["version"]

        note = (
            f"{config_note}ingested {change_set['name']}: "
            f"{out.get('findings', 0)} finding(s), {out.get('design_findings', 0)} design; "
            f"graph v{graph.get('version', '?')}"
            + (" (structural change)" if change_set["changed"] else " (unchanged graph)")
        ).strip()
        return TickResult(state=state, note=note)

    # --- Detect ---------------------------------------------------------
    def _detect(self, repo_path: str, state: dict[str, Any], *, force: bool) -> dict[str, Any]:
        """Cheap change detection: for a local path, checksum the tree and compare to last tick.

        Returns ``{skip, checksum}``. A remote URL can't be detected without fetching, so it
        always falls through to Ingest (where the Asset Store reuses an unchanged version, B.1).
        """
        if force or not repo_path:
            return {"skip": False, "checksum": None}
        try:
            checksum = compute_tree_checksum(repo_path)
        except Exception:  # noqa: BLE001 - detection must never crash a tick; ingest will report
            return {"skip": False, "checksum": None}
        if checksum and checksum == state.get("last_tree_checksum"):
            return {"skip": True, "checksum": checksum}
        return {"skip": False, "checksum": checksum}

    # --- Compare --------------------------------------------------------
    @staticmethod
    def _change_set(out: dict[str, Any]) -> dict[str, Any]:
        """Normalize a learn result into a change set (the Compare output, surfaced for Policy)."""
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
