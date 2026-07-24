"""NewsIntelligenceWorker — Market Intelligence M3 (MI.4).

Ingest configured headlines/items → typed knowledge candidates → CandidateConsumer.
Optional verify queue hand-off. Hermetic by default (config headlines); live RSS later.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.knowledge.media_extraction import MediaKnowledgeExtractor
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class NewsIntelligenceWorker(PersistentWorker):
    type = "news_intelligence"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        candidates: Any,
        extractor: Any | None = None,
        knowledge_verification: Any | None = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._candidates = candidates
        self._extractor = extractor or MediaKnowledgeExtractor(max_claims=8)
        self._verify = knowledge_verification
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.news_intelligence")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        items = self._collect_items(cfg, ctx.inputs)
        if not items:
            return TickResult(
                state=state,
                note=(
                    "idle: no headlines — set headlines=['…'] or items="
                    "[{symbol,text}] (live RSS lands later)"
                ),
            )

        seen = set(state.get("seen_hashes") or [])
        emitted = 0
        skipped = 0
        new_hashes: list[str] = []
        for item in items:
            text = str(item.get("text") or "").strip()
            if len(text) < 12:
                skipped += 1
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            if digest in seen:
                skipped += 1
                continue
            symbol = str(item.get("symbol") or "").strip()
            source = str(item.get("source") or "news_config").strip()
            evidence = {
                "source": source,
                "symbol": symbol or None,
                "mission_id": ctx.mission_id,
            }
            payloads = self._extractor.extract(
                text,
                evidence_ref=evidence,
                domain="markets",
            )
            for payload in payloads:
                try:
                    self._candidates.emit(payload)
                    emitted += 1
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("candidate emit failed: %s", exc)
            seen.add(digest)
            new_hashes.append(digest)

        if emitted and hasattr(self._candidates, "consume_pending"):
            try:
                self._candidates.consume_pending(limit=max(emitted, 20))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("candidate consolidate failed: %s", exc)

        # Bound seen set
        state["seen_hashes"] = list(seen)[-200:]

        verify_note = ""
        if emitted and cfg.get("verify") and self._verify is not None:
            try:
                result = self._verify.verify_batch(
                    limit=int(cfg.get("verify_batch_limit") or 5),
                    gather=bool(cfg.get("gather") or False),
                )
                verify_note = f"; verify status={result.get('status')} n={result.get('selected', len(result.get('results') or []))}"
            except Exception as exc:  # noqa: BLE001
                verify_note = f"; verify skipped ({exc})"

        if self._events is not None and emitted:
            try:
                self._events.emit(
                    "NewsIntelligenceExtracted",
                    {
                        "mission_id": ctx.mission_id,
                        "emitted": emitted,
                        "items": len(new_hashes),
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        return TickResult(
            state=state,
            note=(
                f"news: emitted {emitted} candidate(s), skipped {skipped}"
                f"{verify_note}"
            ),
        )

    @staticmethod
    def _collect_items(cfg: dict[str, Any], inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw in cfg.get("items") or []:
            if isinstance(raw, dict) and raw.get("text"):
                items.append(dict(raw))
        for headline in cfg.get("headlines") or []:
            text = str(headline).strip()
            if text:
                items.append({"text": text, "source": "headline"})
        for inp in inputs or []:
            if inp.get("headline"):
                items.append(
                    {
                        "text": str(inp["headline"]),
                        "symbol": str(inp.get("symbol") or ""),
                        "source": "operator_input",
                    }
                )
            if inp.get("text"):
                items.append(
                    {
                        "text": str(inp["text"]),
                        "symbol": str(inp.get("symbol") or ""),
                        "source": "operator_input",
                    }
                )
        return items
