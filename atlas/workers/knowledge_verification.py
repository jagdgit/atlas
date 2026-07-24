"""KnowledgeVerificationWatcher — continuous verification mission (KV.7).

Each tick drains a batch of UNVERIFIED knowledge findings through the shared
``KnowledgeVerificationService`` (same VerificationEngine as operator verify —
KV1). Optional budget-capped Research gather is config-gated (default off).

Never invents a parallel truth store (KV6). Never completes — permanent watcher.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult

_PROMOTED = frozenset({"HIGH", "MEDIUM"})


class KnowledgeVerificationWatcher(PersistentWorker):
    type = "knowledge_verification"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        verification: Any,
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._verification = verification
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.knowledge_verification")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        force = any(bool(item.get("force")) for item in ctx.inputs)

        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        if self._verification is None:
            note = f"{config_note}knowledge verification unavailable".strip()
            return TickResult(state=state, note=note)

        batch_limit = max(1, int(cfg.get("batch_limit") or 10))
        gather = bool(cfg.get("gather", False))
        max_gather = cfg.get("max_gather_iterations")
        try:
            max_gather_i = int(max_gather) if max_gather is not None else 2
        except (TypeError, ValueError):
            max_gather_i = 2

        claim_types = cfg.get("claim_types")
        if isinstance(claim_types, str):
            claim_types = [claim_types]
        if not claim_types:
            claim_types = ["claim"]

        detect_contra = bool(cfg.get("detect_contradictions", True))

        filters = {
            "asset_id": (str(cfg["asset_id"]).strip() or None) if cfg.get("asset_id") else None,
            "job_id": (str(cfg["job_id"]).strip() or None) if cfg.get("job_id") else None,
            "source_url": (
                str(cfg["source_url"]).strip() or None
            )
            if cfg.get("source_url")
            else None,
            "claim_types": list(claim_types),
            "limit": batch_limit,
        }

        pending = self._verification.list_pending(**filters)
        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["last_pending"] = len(pending)

        if not pending and not force:
            note = f"{config_note}no UNVERIFIED findings queued".strip() if config_note else ""
            # Quiet idle — same pattern as empty research topic.
            return TickResult(state=state, note=note)

        out = self._verification.verify_batch(
            asset_id=filters["asset_id"],
            job_id=filters["job_id"],
            source_url=filters["source_url"],
            claim_types=filters["claim_types"],
            limit=batch_limit,
            gather=gather,
            max_gather_iterations=max_gather_i,
            detect_contradictions=detect_contra,
        )

        selected = int(out.get("selected") or 0)
        scored = int(out.get("promoted_or_scored") or 0)
        still = int(out.get("still_unverified") or 0)
        state["last_verify"] = {
            "selected": selected,
            "promoted_or_scored": scored,
            "still_unverified": still,
            "gather": bool(out.get("gather_requested")),
            "version": out.get("version"),
        }
        state["total_verified"] = int(state.get("total_verified", 0)) + selected

        promoted_rows = [
            r
            for r in (out.get("before_after") or [])
            if str(r.get("after_confidence") or "").upper() in _PROMOTED
        ]
        if promoted_rows and bool(cfg.get("alert_on_promoted", True)):
            for row in promoted_rows[:10]:
                self._emit(
                    "KnowledgeVerified",
                    {
                        "mission_id": str(ctx.mission_id),
                        "finding_id": row.get("finding_id"),
                        "statement": row.get("statement"),
                        "before": row.get("confidence"),
                        "after": row.get("after_confidence"),
                        "gather_added": row.get("gather_added"),
                    },
                )

        self._emit(
            "VerificationProgress",
            {
                "mission_id": str(ctx.mission_id),
                "selected": selected,
                "promoted_or_scored": scored,
                "still_unverified": still,
                "gather": gather,
                "pending_before": len(pending),
            },
        )

        note = (
            f"{config_note}verify batch: {selected} selected, "
            f"{scored} scored, {still} still UNVERIFIED/INSUFFICIENT"
            + (" (gather on)" if gather else "")
            + (f"; {len(promoted_rows)} promoted notify" if promoted_rows else "")
        ).strip()
        return TickResult(state=state, note=note)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source="knowledge_verification")
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("emit %s failed: %s", event_type, exc)
