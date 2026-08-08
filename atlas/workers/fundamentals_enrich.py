"""FundamentalsEnrichWorker — LQ.7 Tier C Yahoo enrich on watchlist gaps.

Scheduled medium-confidence fill for missing PE/FCF/ROE/D/E. Never invents;
Screener/filing still outrank Yahoo. Gated on ``market.yahoo_enabled`` (or
explicit config ``yahoo_enabled``).
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class FundamentalsEnrichWorker(PersistentWorker):
    type = "fundamentals_enrich"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        yahoo_enabled: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._yahoo_enabled = bool(yahoo_enabled)
        self._logger = logger or logging.getLogger("atlas.workers.fundamentals_enrich")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        program_id = str(cfg.get("program_id") or "market_intelligence")
        limit = max(1, min(int(cfg.get("max_symbols") or 3), 10))
        batch_size = max(1, min(int(cfg.get("batch_size") or limit), 5))
        enabled = bool(cfg.get("yahoo_enabled", self._yahoo_enabled))
        data_dir = str(cfg.get("data_dir") or self._data_dir or "")

        if not data_dir:
            return TickResult(state=state, note="idle: data_dir not wired")

        from atlas.investment.fundamentals import enrich_watchlist_gaps
        from atlas.investment.yahoo_fundamentals import get_yahoo_rate_gate

        if enabled:
            gate = get_yahoo_rate_gate(data_dir)
            if gate.remaining_cooldown_s() > 0:
                rem = gate.remaining_cooldown_s()
                state["last_enrich"] = {
                    "reason": "yahoo_cooldown",
                    "cooldown_remaining_s": round(rem, 1),
                    "rate_gate": gate.status(),
                }
                return TickResult(
                    state=state,
                    note=f"LQ.7 cooling down {rem:.0f}s (respect Yahoo rate limits)",
                )

        try:
            result = enrich_watchlist_gaps(
                data_dir,
                program_id=program_id,
                enabled=enabled,
                limit=limit,
                batch_size=batch_size,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("LQ.7 fundamentals enrich failed")
            state["last_error"] = str(exc)[:200]
            return TickResult(state=state, note=f"enrich error: {type(exc).__name__}")

        state["last_enrich"] = {
            "fetched": result.get("fetched"),
            "skipped": result.get("skipped_already_covered"),
            "reason": result.get("reason"),
            "gap_symbols": (result.get("gap_symbols") or [])[:12],
            "remaining": result.get("remaining"),
            "errors": len(result.get("errors") or []),
            "mode": result.get("mode") or result.get("reason"),
            "rate_gate": result.get("rate_gate"),
        }
        state.pop("last_error", None)

        fetched = int(result.get("fetched") or 0)
        reason = str(result.get("reason") or "")
        remaining = int(result.get("remaining") or 0)
        if reason == "yahoo_disabled":
            note = f"LQ.7 gated (yahoo_disabled); {len(result.get('gap_symbols') or [])} gaps remain"
        elif reason == "no_gaps":
            note = "LQ.7 no watchlist gaps"
        elif reason == "no_watchlist_symbols":
            note = "LQ.7 idle: empty watchlist"
        elif reason == "yahoo_cooldown":
            cool = (result.get("rate_gate") or {}).get("cooldown_remaining_s")
            note = f"LQ.7 cooldown {cool}s; {remaining} gaps queued"
        elif fetched:
            syms = ", ".join(str(s) for s in (result.get("symbols") or [])[:5])
            tail = f"; {remaining} remain" if remaining else ""
            note = f"LQ.7 enriched {fetched}: {syms}{tail}"
        else:
            err_n = len(result.get("errors") or [])
            tail = f"; {remaining} remain" if remaining else ""
            note = f"LQ.7 fetched 0 (errors={err_n}){tail}"

        return TickResult(state=state, note=note)
