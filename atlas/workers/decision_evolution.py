"""DecisionEvolutionWorker — DI.2 Day1/Week1/Month1/Quarter revisits.

Runs due evolution checkpoints: appends ``revisit`` timeline events with
``what_changed`` diffs vs frozen Decision Packets. Never rewrites packets.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class DecisionEvolutionWorker(PersistentWorker):
    type = "decision_evolution"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        timeline: Any | None = None,
        decision_packets: Any | None = None,
        investment_research: Any | None = None,
        market_reader: Any | None = None,
        attributions: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._timeline = timeline
        self._packets = decision_packets
        self._research = investment_research
        self._market = market_reader
        self._attributions = attributions
        self._logger = logger or logging.getLogger("atlas.workers.decision_evolution")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        portfolio_key = str(cfg.get("portfolio_key") or "india_equity_learner").strip()
        program_id = str(cfg.get("program_id") or "market_intelligence")
        limit = max(1, min(int(cfg.get("max_revisits") or 20), 50))

        if self._timeline is None:
            return TickResult(state=state, note="idle: decision timeline not wired")

        def mark_fn(symbol: str) -> float | None:
            if self._market is None:
                return None
            try:
                out = self._market.bars_for(symbol, provider="yahoo", limit=1)
                bars = list((out or {}).get("bars") or [])
                if bars and bars[-1].get("close") is not None:
                    return float(bars[-1]["close"])
            except Exception:  # noqa: BLE001
                return None
            return None

        def awareness_fn(symbol: str) -> dict[str, Any] | None:
            if self._research is None:
                return None
            try:
                return self._research.awareness(symbol, program_id=program_id)
            except Exception:  # noqa: BLE001
                return None

        try:
            result = self._timeline.run_due_revisits(
                portfolio_key=portfolio_key,
                limit=limit,
                mark_fn=mark_fn,
                awareness_fn=awareness_fn,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("decision evolution tick failed: %s", exc)
            return TickResult(state=state, note=f"error: {exc}")

        # DI.Attr — provisional attribution on each completed revisit
        attr_n = 0
        if self._attributions is not None:
            for item in result.get("items") or []:
                try:
                    self._attributions.record(
                        decision_id=item.get("decision_id"),
                        symbol=str(item.get("symbol") or ""),
                        portfolio_key=portfolio_key,
                        trigger="revisit",
                        checkpoint=str(item.get("checkpoint") or ""),
                        what_changed=item.get("what_changed"),
                        what_changed_event_ids=[str(item.get("timeline_event_id"))]
                        if item.get("timeline_event_id")
                        else None,
                        price_change_pct=(item.get("what_changed") or {}).get(
                            "price_change_pct"
                        ),
                    )
                    attr_n += 1
                except Exception:  # noqa: BLE001
                    self._logger.debug("DI.Attr revisit attribution skipped", exc_info=True)

        counts = {}
        try:
            counts = self._timeline.learning_counts(portfolio_key=portfolio_key)
        except Exception:  # noqa: BLE001
            counts = {}
        state["last_evolution"] = {
            "completed": result.get("completed"),
            "due": result.get("due"),
            "as_of_ist": result.get("as_of_ist"),
            "counts": counts,
            "attributions": attr_n,
        }
        return TickResult(
            state=state,
            note=(
                f"evolution: completed={result.get('completed')} due={result.get('due')} "
                f"pending={counts.get('pending_revisits', '?')} "
                f"done={counts.get('done_revisits', '?')} attr={attr_n}"
            ),
        )
