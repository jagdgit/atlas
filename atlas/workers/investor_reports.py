"""InvestorReportsWorker — morning + evening investor email digests.

Morning (IST): Daily Investment Plan + policy brief + portfolio snapshot.
Evening (IST, after NSE close): plan recap + recent fills + EOD portfolio.
Trade fills are also emailed from PaperTradingWorker via InvestorReportMailer.
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
    VERSION = 2
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
        now_ist = datetime.now(_IST)
        hour = now_ist.hour
        minute = now_ist.minute

        morning_start = int(cfg.get("morning_hour_start") or 7)
        morning_end = int(cfg.get("morning_hour_end") or 10)
        # Evening after NSE cash close (~15:30 IST); default 15:45–18:00.
        evening_start_h = int(cfg.get("evening_hour_start") or 15)
        evening_start_m = int(cfg.get("evening_minute_start") or 45)
        evening_end = int(cfg.get("evening_hour_end") or 18)

        in_morning = morning_start <= hour < morning_end
        evening_ok = (hour > evening_start_h) or (
            hour == evening_start_h and minute >= evening_start_m
        )
        in_evening = evening_ok and hour < evening_end

        for inp in ctx.inputs or []:
            if isinstance(inp, dict) and inp.get("force"):
                force = True
            if isinstance(inp, dict) and inp.get("kind") in {"evening", "morning"}:
                force = True
                state["force_kind"] = inp.get("kind")

        force_kind = str(state.pop("force_kind", "") or cfg.get("force_kind") or "").strip().lower()
        send_morning = False
        send_evening = False
        if force and force_kind == "evening":
            send_evening = True
        elif force and force_kind == "morning":
            send_morning = True
        elif force:
            # Legacy Market "Send test" → morning; also allow current window.
            if in_evening and not in_morning:
                send_evening = True
            else:
                send_morning = True
        else:
            send_morning = in_morning
            send_evening = in_evening

        if not send_morning and not send_evening:
            state["skipped"] = "outside_report_windows_ist"
            return TickResult(
                state=state,
                note=(
                    f"idle: outside IST windows morning {morning_start:02d}–{morning_end:02d} "
                    f"/ evening {evening_start_h:02d}:{evening_start_m:02d}–{evening_end:02d} "
                    f"(now {hour:02d}:{minute:02d})"
                ),
            )

        if self._mailer is None:
            return TickResult(state=state, note="idle: investor mailer not configured")

        portfolio_doc = self._portfolio_doc(portfolio_key)

        notes: list[str] = []
        if send_morning:
            result = self._mailer.send_morning(
                program_id=program_id,
                portfolio=portfolio_doc if isinstance(portfolio_doc, dict) else None,
                force=force,
            )
            state["last_morning_send"] = result
            state["last_attempt_utc"] = datetime.now(timezone.utc).isoformat()
            if result.get("sent"):
                notes.append(f"morning sent: {result.get('subject')}")
            else:
                notes.append(f"morning not sent: {result.get('reason') or result}")

        if send_evening:
            result = self._mailer.send_evening(
                program_id=program_id,
                portfolio=portfolio_doc if isinstance(portfolio_doc, dict) else None,
                force=force,
            )
            state["last_evening_send"] = result
            state["last_attempt_utc"] = datetime.now(timezone.utc).isoformat()
            if result.get("sent"):
                notes.append(f"evening sent: {result.get('subject')}")
            else:
                notes.append(f"evening not sent: {result.get('reason') or result}")

        if not notes:
            return TickResult(state=state, note="idle: no matching report window")
        return TickResult(state=state, note="; ".join(notes))

    def _portfolio_doc(self, portfolio_key: str | None) -> dict[str, Any] | None:
        if not portfolio_key:
            return None
        try:
            from atlas.investment import portfolios as pf

            meta = pf.get(portfolio_key)
            if not isinstance(meta, dict):
                return None
            portfolio_doc: dict[str, Any] = {
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
            return portfolio_doc
        except Exception:  # noqa: BLE001
            self._logger.debug("portfolio meta lookup failed", exc_info=True)
            return None
