"""EventResearchWorker — Market Intelligence M4 (MI.4).

Polls durable ``MarketInterestingMove`` events and enqueues research Jobs when
score ≥ threshold (opt-in until tuned — default spawn_research false on observer;
this worker defaults spawn_research true so M4 owns the Job side-effect).
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.trading.interesting_events import InterestingEvent
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class EventResearchWorker(PersistentWorker):
    type = "event_research"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        jobs: Any,
        event_repo: Any | None = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._jobs = jobs
        self._event_repo = event_repo
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.event_research")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        if not cfg.get("spawn_research", True):
            return TickResult(
                state=state,
                note="idle: spawn_research=false — enable to enqueue why-did-it-move Jobs",
            )

        threshold = float(cfg.get("score_threshold") or 0.7)
        handled = set(state.get("handled_event_ids") or [])
        spawned = 0
        scanned = 0

        # 1) Operator / mission inputs
        for inp in ctx.inputs or []:
            ev = self._from_input(inp)
            if ev is None:
                continue
            scanned += 1
            key = self._dedupe_key(ev)
            if key in handled or ev.score < threshold:
                continue
            if self._spawn(ev, mission_id=ctx.mission_id):
                handled.add(key)
                spawned += 1

        # 2) Durable MarketInterestingMove events
        for row in self._recent_moves(limit=int(cfg.get("event_scan_limit") or 20)):
            scanned += 1
            eid = str(row.get("id") or "")
            payload = row.get("payload") or {}
            for raw in payload.get("events") or []:
                ev = self._from_payload(raw)
                if ev is None:
                    continue
                key = eid + ":" + self._dedupe_key(ev) if eid else self._dedupe_key(ev)
                if key in handled or ev.score < threshold:
                    continue
                if self._spawn(ev, mission_id=ctx.mission_id):
                    handled.add(key)
                    spawned += 1

        # 3) Config-queued pending events (hermetic tests / operator seed)
        for raw in cfg.get("pending_events") or []:
            ev = self._from_payload(raw)
            if ev is None:
                continue
            scanned += 1
            key = self._dedupe_key(ev)
            if key in handled or ev.score < threshold:
                continue
            if self._spawn(ev, mission_id=ctx.mission_id):
                handled.add(key)
                spawned += 1

        state["handled_event_ids"] = list(handled)[-100:]
        state["last_spawned"] = spawned
        if scanned == 0 and spawned == 0:
            return TickResult(
                state=state,
                note=(
                    "idle: no interesting events yet — Market Observer emits "
                    "MarketInterestingMove when moves clear the alert"
                ),
            )
        return TickResult(
            state=state,
            note=f"event_research: scanned {scanned}, spawned {spawned} job(s) "
            f"(threshold={threshold:g})",
        )

    def _spawn(self, ev: InterestingEvent, *, mission_id: str) -> bool:
        try:
            detail = self._jobs.create_job(ev.research_objective())
            job = detail.get("job") if isinstance(detail, dict) else None
            job_id = getattr(job, "id", None) or (job.get("id") if isinstance(job, dict) else None)
            self._logger.info(
                "spawned research job %s for %s (score=%.2f)",
                job_id,
                ev.symbol,
                ev.score,
            )
            if self._events is not None:
                try:
                    self._events.emit(
                        "EventResearchJobSpawned",
                        {
                            "mission_id": mission_id,
                            "job_id": str(job_id) if job_id else None,
                            "symbol": ev.symbol,
                            "score": ev.score,
                            "kind": ev.kind,
                        },
                        source=self.type,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return True
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("failed to spawn research job: %s", exc)
            return False

    def _recent_moves(self, *, limit: int) -> list[dict[str, Any]]:
        if self._event_repo is None:
            return []
        try:
            return list(
                self._event_repo.recent(limit=limit, event_type="MarketInterestingMove")
                or []
            )
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _dedupe_key(ev: InterestingEvent) -> str:
        move = f"{ev.pct_move:.2f}" if ev.pct_move is not None else ""
        return f"{ev.symbol}:{ev.kind}:{move}:{ev.detail[:40]}"

    @staticmethod
    def _from_input(inp: dict[str, Any]) -> InterestingEvent | None:
        if inp.get("interesting_event"):
            return EventResearchWorker._from_payload(inp["interesting_event"])
        if inp.get("symbol") and (inp.get("pct_move") is not None or inp.get("detail")):
            return EventResearchWorker._from_payload(inp)
        return None

    @staticmethod
    def _from_payload(raw: Any) -> InterestingEvent | None:
        if not isinstance(raw, dict):
            return None
        symbol = str(raw.get("symbol") or "").strip()
        if not symbol:
            return None
        try:
            score = float(raw.get("score") if raw.get("score") is not None else 0.75)
        except (TypeError, ValueError):
            score = 0.75
        pct = raw.get("pct_move")
        try:
            pct_f = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct_f = None
        return InterestingEvent(
            symbol=symbol,
            kind=str(raw.get("kind") or "price_move"),
            score=max(0.0, min(1.0, score)),
            detail=str(raw.get("detail") or raw.get("reason") or f"{symbol} interesting"),
            pct_move=pct_f,
            provider=raw.get("provider"),
        )
