"""InvestorReportsWorker — morning pre-invest email digest.

Sends the Daily Investment Plan (+ government policy brief + portfolio snapshot)
to configured Gmail recipients before the trading session. Trade fills are emailed
from PaperTradingWorker via InvestorReportMailer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from atlas.workers.base import PersistentWorker, TickContext, TickResult

_IST = ZoneInfo("Asia/Kolkata")


class InvestorReportsWorker(PersistentWorker):
    type = "investor_reports"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        mailer: Any,
        portfolio: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._mailer = mailer
        self._portfolio = portfolio
        self._logger = logger or logging.getLogger("atlas.workers.investor_reports")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        program_id = str(cfg.get("program_id") or "market_intelligence")
        portfolio_key = str(cfg.get("portfolio_key") or "").strip() or None
        force = bool(cfg.get("force") or False)
        # Only send in the morning window (IST) unless force / operator input.
        now_ist = datetime.now(_IST)
        hour = now_ist.hour
        window_start = int(cfg.get("morning_hour_start") or 7)
        window_end = int(cfg.get("morning_hour_end") or 10)
        in_window = window_start <= hour < window_end
        for inp in ctx.inputs or []:
            if isinstance(inp, dict) and inp.get("force"):
                force = True

        if not force and not in_window:
            state["skipped"] = "outside_morning_window_ist"
            return TickResult(
                state=state,
                note=f"idle: outside morning window IST {window_start:02d}–{window_end:02d} (now {hour:02d})",
            )

        portfolio_doc = None
        if portfolio_key:
            try:
                from atlas.investment import portfolios as pf

                meta = pf.get(portfolio_key)
                if isinstance(meta, dict):
                    portfolio_doc = {
                        "portfolio_key": portfolio_key,
                        "label": meta.get("label"),
                        "starting_cash": meta.get("starting_cash"),
                        "cash": meta.get("starting_cash"),
                        "sim_portfolio_id": meta.get("sim_portfolio_id") or meta.get("portfolio_id"),
                    }
                    pid = portfolio_doc.get("sim_portfolio_id")
                    if pid and self._portfolio is not None and hasattr(self._portfolio, "snapshot"):
                        try:
                            snap = self._portfolio.snapshot(pid)
                            if isinstance(snap, dict):
                                portfolio_doc.update(snap)
                                portfolio_doc["positions"] = snap.get("positions") or snap.get(
                                    "holdings"
                                )
                        except Exception:  # noqa: BLE001
                            self._logger.debug("sim portfolio snapshot failed", exc_info=True)
            except Exception:  # noqa: BLE001
                self._logger.debug("portfolio meta lookup failed", exc_info=True)

        if self._mailer is None:
            return TickResult(state=state, note="idle: investor mailer not configured")

        result = self._mailer.send_morning(
            program_id=program_id,
            portfolio=portfolio_doc if isinstance(portfolio_doc, dict) else None,
            force=force,
        )
        state["last_send"] = result
        state["last_attempt_utc"] = datetime.now(timezone.utc).isoformat()
        if result.get("sent"):
            return TickResult(state=state, note=f"morning report sent: {result.get('subject')}")
        return TickResult(
            state=state,
            note=f"morning report not sent: {result.get('reason') or result}",
        )
