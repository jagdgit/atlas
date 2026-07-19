"""OwnerKnowledgeWorker — the Owner Knowledge Mission's persistent worker (Phase C · §C.8).

The permanent mission that learns *you*. Each tick walks the operator's **User Archive** (a set of
configured roots — code, docs/papers/notes, chat/Cursor exports) and, per root, drives the ONE
unified pipeline built in C.2–C.6:

- **code** roots → :meth:`IntelligenceService.learn_repository` (engineering findings **and** owner
  experiences, both consolidated globally, P12/P13);
- **document** roots → the Document Reader via :class:`IngestionService` (assets → chunks + prose
  candidates → findings, with coverage);
- **conversation** roots → the Conversation Reader via :class:`IngestionService` (chats as a
  first-class knowledge source).

After ingesting, it rebuilds the **personal profile** (skills/identity/timeline) from the now-current
experience + engineering knowledge (:meth:`PersonalService.infer` — inferred facts only, CC7/A9). It
**never completes**: each tick is a bounded pass; a per-root content checksum in the checkpoint state
makes an unchanged root a cheap no-op and makes the whole loop resume after a reboot (the manager
reloads the checkpoint). Per P11 the worker owns no knowledge — it drives stateless translators and
journals what it did (P9).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from atlas.engineering.ingest import compute_tree_checksum
from atlas.workers.base import PersistentWorker, TickContext, TickResult

KIND_CODE = "code"
KIND_DOCUMENT = "document"
KIND_CONVERSATION = "conversation"

_DEFAULT_EXTENSIONS = {
    KIND_DOCUMENT: (".txt", ".md", ".pdf", ".html", ".htm", ".rst"),
    KIND_CONVERSATION: (".json", ".jsonl"),
}


class OwnerKnowledgeWorker(PersistentWorker):
    type = "owner_knowledge"
    VERSION = 1
    journal_ticks = True  # journal meaningful ticks (ingests); pure no-ops return empty notes

    def __init__(
        self,
        *,
        ingestion: Any,
        intelligence: Any,
        personal: Any = None,
        conversation_reader: Any = None,
        candidates: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ingestion = ingestion
        self._intel = intelligence
        self._personal = personal
        self._conversation_reader = conversation_reader
        # CandidateConsumer: doc/chat ingests emit prose candidates; drain them into findings so the
        # archive's understanding is materialized each tick (single write path stays the Consolidator).
        self._candidates = candidates
        self._logger = logger or logging.getLogger("atlas.workers.owner_knowledge")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        force = any(bool(item.get("force")) for item in ctx.inputs)

        roots = cfg.get("archive_roots") or []
        if not roots:
            return TickResult(state=state, note="")  # nothing configured yet — idle quietly

        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        root_state: dict[str, Any] = dict(state.get("roots") or {})
        totals = {
            "findings": 0, "experiences": 0, "documents": 0,
            "conversations": 0, "candidates": 0, "code_repos": 0,
            "skipped": 0, "errors": 0,
        }
        changed_any = False

        for root in roots:
            path = str(root.get("path") or "").strip()
            if not path:
                continue
            kind = str(root.get("kind") or KIND_DOCUMENT)
            domain = str(root.get("domain") or "personal")
            sig = self._signature(path)
            prev = root_state.get(path) or {}
            if not force and sig and sig == prev.get("checksum"):
                totals["skipped"] += 1
                continue
            try:
                self._process_root(
                    path, kind, domain, cfg, ctx.mission_id, totals,
                    override_ext=root.get("extensions"),
                )
                changed_any = True
                root_state[path] = {"checksum": sig, "kind": kind}
            except Exception as exc:  # noqa: BLE001 - a bad root must not stop the whole archive
                totals["errors"] += 1
                self._logger.warning("owner archive root failed (%s): %s", path, exc)

        state["roots"] = root_state

        # Drain the prose candidates the doc/chat ingests emitted into findings (P11/P13: the
        # Consolidator is still the single write path; the worker just triggers the drain).
        if self._candidates is not None and (changed_any or force):
            try:
                drained = self._candidates.consume_pending(limit=500)
                totals["candidate_findings"] = len(drained)
            except Exception as exc:  # noqa: BLE001 - draining is best-effort
                self._logger.warning("owner candidate drain failed: %s", exc)

        profile_note = ""
        if bool(cfg.get("build_profile", True)) and self._personal is not None and (changed_any or force):
            try:
                inferred = self._personal.infer()
                profile_note = (
                    f"; profile skills={inferred.get('skills', 0)} "
                    f"identity={inferred.get('identity', 0)} timeline={inferred.get('timeline', 0)}"
                )
            except Exception as exc:  # noqa: BLE001 - profile build is best-effort
                self._logger.warning("owner profile inference failed: %s", exc)

        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["last_totals"] = totals

        if not changed_any and not force:
            note = f"{config_note}no change (archive unchanged)".strip() if config_note else ""
            return TickResult(state=state, note=note)

        note = (
            f"{config_note}archive: {totals['code_repos']} repo(s) "
            f"(+{totals['findings']} finding, +{totals['experiences']} experience), "
            f"{totals['documents']} doc(s), {totals['conversations']} chat(s), "
            f"+{totals['candidates']} candidate(s){profile_note}"
        ).strip()
        return TickResult(state=state, note=note)

    # --- per-root processing --------------------------------------------
    def _process_root(
        self,
        path: str,
        kind: str,
        domain: str,
        cfg: dict[str, Any],
        mission_id: str,
        totals: dict[str, int],
        *,
        override_ext: Any = None,
    ) -> None:
        if kind == KIND_CODE:
            out = self._intel.learn_repository(
                path=path,
                mission_id=mission_id,
                policy=cfg.get("policy") or "project",
                embed=bool(cfg.get("embed", False)),
            )
            if out.get("outcome") != "ok":
                raise RuntimeError(f"code ingest failed: {out.get('reason', 'unknown error')}")
            totals["code_repos"] += 1
            totals["findings"] += int(out.get("findings", 0) or 0)
            totals["experiences"] += int(out.get("experiences", 0) or 0)
            return

        # document / conversation: read each matching file through the unified bridge.
        reader = self._conversation_reader if kind == KIND_CONVERSATION else None
        source = "conversation" if kind == KIND_CONVERSATION else "document"
        asset_kind = "conversation" if kind == KIND_CONVERSATION else "document"
        extensions = self._extensions_for(kind, override=override_ext)
        for file in self._discover(path, extensions):
            res = self._ingestion.ingest_file(
                file,
                kind=asset_kind,
                domain=domain,
                embed=bool(cfg.get("embed", False)),
                extract_findings=True,
                reader=reader,
                source=source,
            )
            if kind == KIND_CONVERSATION:
                totals["conversations"] += 1
            else:
                totals["documents"] += 1
            totals["candidates"] += int(res.candidates or 0)

    # --- helpers --------------------------------------------------------
    @staticmethod
    def _extensions_for(kind: str, *, override: Any = None) -> tuple[str, ...]:
        if override:
            return tuple(str(e).lower() for e in override)
        return _DEFAULT_EXTENSIONS.get(kind, ())

    @staticmethod
    def _discover(path: str, extensions: tuple[str, ...]) -> list[Path]:
        root = Path(path).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"archive root not found: {root}")
        if root.is_file():
            return [root] if root.suffix.lower() in extensions else []
        return sorted(
            p for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in extensions
        )

    @staticmethod
    def _signature(path: str) -> str | None:
        """Cheap content signature of a root to skip an unchanged root (reboot-safe)."""
        try:
            return compute_tree_checksum(path)
        except Exception:  # noqa: BLE001 - detection must never crash a tick
            return None
