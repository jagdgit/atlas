"""FundamentalEvidenceWorker — UQ-driven NSE/XBRL fundamental acquisition.

Drains due pe/fcf/roe tasks (priority + backoff) → shared NSE pool → store →
UQ DONE. Yahoo is secondary/cross-check only. Never scrapes Screener HTML.
Never loosens gates.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class FundamentalEvidenceWorker(PersistentWorker):
    type = "fundamental_evidence"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        yahoo_enabled: bool = False,
        investment_research: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._yahoo_enabled = bool(yahoo_enabled)
        self._research = investment_research
        self._logger = logger or logging.getLogger(
            "atlas.workers.fundamental_evidence"
        )

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        data_dir = str(cfg.get("data_dir") or self._data_dir or "")
        if not data_dir:
            return TickResult(state=state, note="idle: data_dir not wired")

        from atlas.investment.fundamental_evidence import drain_uncertainty_queue
        from atlas.investment.yahoo_fundamentals import (
            get_yahoo_rate_gate,
            yahoo_background_should_yield_to_live,
        )

        enabled = bool(cfg.get("yahoo_enabled", self._yahoo_enabled))
        lab = str(cfg.get("portfolio_key") or "india_equity_learner")
        program_id = str(cfg.get("program_id") or "market_intelligence")
        limit = max(1, min(int(cfg.get("max_symbols") or 6), 8))
        nse_concurrency = max(1, min(int(cfg.get("nse_concurrency") or 3), 4))
        yahoo_secondary = bool(cfg.get("yahoo_secondary", False))

        yahoo_yield = False
        try:
            if enabled and yahoo_secondary and yahoo_background_should_yield_to_live():
                yahoo_yield = True
        except Exception:  # noqa: BLE001
            yahoo_yield = False

        gate = get_yahoo_rate_gate(data_dir)
        gst = gate.status()
        cooling = float(gst.get("cooldown_remaining_s") or 0) > 0
        # Yahoo cooldown / RTH yield must not skip NSE/identity drain.

        try:
            out = drain_uncertainty_queue(
                data_dir,
                laboratory_id=lab,
                program_id=program_id,
                limit=limit,
                enabled=enabled,
                yahoo_secondary=yahoo_secondary and enabled and not cooling and not yahoo_yield,
                nse_concurrency=nse_concurrency,
                push_to_ira=bool(cfg.get("push_to_ira", True)),
                research=self._research,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("fundamental evidence drain failed")
            state["last_error"] = str(exc)[:200]
            return TickResult(
                state=state, note=f"FEA error: {type(exc).__name__}"
            )

        plan = out.get("plan") if isinstance(out.get("plan"), dict) else {}
        state["last_acquire"] = {
            "queued": out.get("queued"),
            "acquired_n": out.get("acquired_n"),
            "queue_depth": plan.get("queue_depth"),
            "backing_off_n": plan.get("backing_off_n"),
            "priority_due": plan.get("priority_due"),
            "results": [
                {
                    "symbol": r.get("symbol"),
                    "reason": r.get("reason"),
                    "acquired": [a.get("field") for a in (r.get("acquired") or [])],
                    "still_missing": r.get("still_missing"),
                    "chain_stops_at": ((r.get("evidence_view") or {}).get("chain_stops_at")),
                }
                for r in (out.get("results") or [])[:5]
            ],
        }
        state.pop("last_error", None)

        n = int(out.get("acquired_n") or 0)
        q = int(out.get("queued") or 0)
        back = int(plan.get("backing_off_n") or 0)
        if q == 0 and back:
            note = f"FEA idle: {back} symbol(s) backing off NSE"
        elif q == 0:
            note = "FEA idle: no PENDING UQ pe/fcf/roe/debt tasks"
        elif n:
            syms = ", ".join(
                str(r.get("symbol")) for r in (out.get("results") or [])[:3]
            )
            note = f"FEA acquired {n} field(s) across {q} symbol(s): {syms}"
        else:
            reasons = [
                str(r.get("reason") or "?") for r in (out.get("results") or [])[:3]
            ]
            note = f"FEA queued={q} acquired=0 backoff={back} reasons={reasons}"
        return TickResult(state=state, note=note)
