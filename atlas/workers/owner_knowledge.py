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
reloads the checkpoint). Per tick it also consults the coverage map for **reader-version**
staleness (A10 / OI-C8) and force-re-reads those assets without requiring content change.
Per P11 the worker owns no knowledge — it drives stateless translators and
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
        coverage: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ingestion = ingestion
        self._intel = intelligence
        self._personal = personal
        self._conversation_reader = conversation_reader
        # CandidateConsumer: doc/chat ingests emit prose candidates; drain them into findings so the
        # archive's understanding is materialized each tick (single write path stays the Consolidator).
        self._candidates = candidates
        # C.4 / OI-C8: coverage map drives reader-version re-extraction (A10).
        self._coverage = coverage
        self._logger = logger or logging.getLogger("atlas.workers.owner_knowledge")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        force = any(bool(item.get("force")) for item in ctx.inputs)

        roots = cfg.get("archive_roots") or []
        # Idle only when there is nothing to do at all (no roots, no coverage re-extract,
        # and orphan-asset backfill disabled).
        can_backfill = bool(cfg.get("backfill_orphan_assets", True)) and hasattr(
            self._ingestion, "backfill_orphan_documents"
        )
        if not roots and self._coverage is None and not can_backfill:
            return TickResult(state=state, note="")  # nothing configured yet — idle quietly

        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        root_state: dict[str, Any] = dict(state.get("roots") or {})
        totals = {
            "findings": 0, "experiences": 0, "documents": 0,
            "conversations": 0, "candidates": 0, "code_repos": 0,
            "skipped": 0, "errors": 0, "reextracted": 0, "backfilled": 0,
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

        # OI-C8 / A10: re-read assets whose coverage was recorded under an older reader version.
        reextracted = self._reextract_stale(cfg, totals)
        if reextracted:
            changed_any = True

        # OI-C4: opportunistic Asset links for pre-Phase-C documents (bounded).
        backfilled = self._backfill_orphan_assets(cfg, totals)
        if backfilled:
            changed_any = True

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

        reex_note = (
            f", reextracted={totals['reextracted']}" if totals.get("reextracted") else ""
        )
        bf_note = (
            f", backfilled={totals['backfilled']}" if totals.get("backfilled") else ""
        )
        note = (
            f"{config_note}archive: {totals['code_repos']} repo(s) "
            f"(+{totals['findings']} finding, +{totals['experiences']} experience), "
            f"{totals['documents']} doc(s), {totals['conversations']} chat(s), "
            f"+{totals['candidates']} candidate(s){reex_note}{bf_note}{profile_note}"
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

    def _reextract_stale(self, cfg: dict[str, Any], totals: dict[str, int]) -> int:
        """Force-re-read assets stale after a reader version bump (OI-C8 / A10)."""
        if self._coverage is None or not hasattr(self._ingestion, "reingest_asset"):
            return 0
        if cfg.get("reextract_stale", True) is False:
            return 0
        limit = max(1, int(cfg.get("reextract_limit") or 50))
        done = 0
        for reader_id, reader_obj, source in self._reader_targets():
            version = str(getattr(reader_obj, "VERSION", "") or "")
            if not version:
                continue
            try:
                flagged = self._coverage.mark_stale_for_reextraction(
                    reader_id, reader_version=version, limit=limit
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "stale coverage mark failed (%s@%s): %s", reader_id, version, exc
                )
                continue
            for row in flagged or []:
                asset_id = str(row.get("asset_id") or "")
                if not asset_id:
                    continue
                try:
                    av = row.get("asset_version")
                    res = self._ingestion.reingest_asset(
                        asset_id,
                        int(av) if av is not None else None,
                        domain=str(row.get("domain") or "personal"),
                        embed=bool(cfg.get("embed", False)),
                        extract_findings=True,
                        reader=reader_obj if source == "conversation" else None,
                        source=source,
                        force=True,
                    )
                    totals["reextracted"] += 1
                    totals["candidates"] += int(getattr(res, "candidates", 0) or 0)
                    if source == "conversation":
                        totals["conversations"] += 1
                    else:
                        totals["documents"] += 1
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    totals["errors"] += 1
                    self._logger.warning(
                        "reextract failed for asset %s: %s", asset_id, exc
                    )
        return done

    def _backfill_orphan_assets(self, cfg: dict[str, Any], totals: dict[str, int]) -> int:
        """Link orphan knowledge.documents rows to Assets (OI-C4)."""
        if not bool(cfg.get("backfill_orphan_assets", True)):
            return 0
        if not hasattr(self._ingestion, "backfill_orphan_documents"):
            return 0
        limit = max(0, int(cfg.get("backfill_limit") or 25))
        if limit <= 0:
            return 0
        try:
            report = self._ingestion.backfill_orphan_documents(limit=limit)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("orphan document backfill failed: %s", exc)
            return 0
        n = int((report or {}).get("linked") or 0)
        totals["backfilled"] += n
        return n

    def _reader_targets(self) -> list[tuple[str, Any, str]]:
        """(reader_id, reader_obj, source) pairs for coverage-driven re-extraction."""
        out: list[tuple[str, Any, str]] = []
        # Default document reader lives on the ingestion bridge.
        doc = getattr(self._ingestion, "_reader", None)
        if doc is not None and getattr(doc, "id", None) and getattr(doc, "VERSION", None):
            out.append((str(doc.id), doc, "document"))
        conv = self._conversation_reader
        if conv is not None and getattr(conv, "id", None) and getattr(conv, "VERSION", None):
            out.append((str(conv.id), conv, "conversation"))
        return out

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
