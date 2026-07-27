"""InvestorReportsWorker — morning + evening investor email digests.

Morning (IST): Daily Investment Plan + policy brief + portfolio snapshot.
Evening (IST, after NSE close): plan recap + recent fills + EOD portfolio.
Trade fills are also emailed from PaperTradingWorker via InvestorReportMailer.

Outage resilience: if the IST window was missed (offline / no SMTP / Atlas down),
the next tick after the window still catch-up-sends **once per IST day**. SMTP
failures do not mark the day as sent.
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
    VERSION = 3
    journal_ticks = True

    def __init__(
        self,
        *,
        mailer: Any,
        portfolio: Any | None = None,
        data_dir: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._mailer = mailer
        self._portfolio = portfolio
        self._data_dir = data_dir
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
        ist_date = now_ist.strftime("%Y-%m-%d")

        morning_start = int(cfg.get("morning_hour_start") or 7)
        morning_end = int(cfg.get("morning_hour_end") or 10)
        # Evening after NSE cash close (~15:30 IST); default 15:45–18:00.
        evening_start_h = int(cfg.get("evening_hour_start") or 15)
        evening_start_m = int(cfg.get("evening_minute_start") or 45)
        evening_end = int(cfg.get("evening_hour_end") or 18)
        # Catch-up may run until this hour (IST) so late internet restores still deliver.
        catch_up_until = int(cfg.get("catch_up_until_hour") or 23)

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

        morning_sent = False
        evening_sent = False
        if self._mailer is not None:
            if hasattr(self._mailer, "already_sent_morning"):
                morning_sent = bool(self._mailer.already_sent_morning(ist_date))
            if hasattr(self._mailer, "already_sent_evening"):
                evening_sent = bool(self._mailer.already_sent_evening(ist_date))

        # Catch-up: after the scheduled window, still send once per IST day if not sent.
        morning_catch_up = (
            not morning_sent
            and not in_morning
            and hour >= morning_end
            and hour <= catch_up_until
            and now_ist.weekday() < 5  # Mon–Fri (same spirit as market week)
        )
        evening_catch_up = (
            not evening_sent
            and not in_evening
            and evening_ok
            and hour >= evening_end
            and hour <= catch_up_until
            and now_ist.weekday() < 5
        )

        send_morning = False
        send_evening = False
        catch_up_morning = False
        catch_up_evening = False
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
            send_morning = in_morning or morning_catch_up
            send_evening = in_evening or evening_catch_up
            catch_up_morning = bool(morning_catch_up and not in_morning)
            catch_up_evening = bool(evening_catch_up and not in_evening)

        if not send_morning and not send_evening:
            state["skipped"] = "outside_report_windows_ist"
            return TickResult(
                state=state,
                note=(
                    f"idle: outside IST windows morning {morning_start:02d}–{morning_end:02d} "
                    f"/ evening {evening_start_h:02d}:{evening_start_m:02d}–{evening_end:02d} "
                    f"(catch-up until {catch_up_until:02d}; now {hour:02d}:{minute:02d})"
                ),
            )

        if self._mailer is None:
            return TickResult(state=state, note="idle: investor mailer not configured")

        portfolio_doc = self._portfolio_doc(portfolio_key, ist_date=ist_date)

        notes: list[str] = []
        if send_morning:
            result = self._mailer.send_morning(
                program_id=program_id,
                portfolio=portfolio_doc if isinstance(portfolio_doc, dict) else None,
                force=force,
                catch_up=catch_up_morning,
            )
            state["last_morning_send"] = result
            state["last_attempt_utc"] = datetime.now(timezone.utc).isoformat()
            if result.get("sent"):
                tag = " (catch-up)" if result.get("catch_up") else ""
                notes.append(f"morning sent{tag}: {result.get('subject')}")
            else:
                notes.append(f"morning not sent: {result.get('reason') or result}")

        if send_evening:
            result = self._mailer.send_evening(
                program_id=program_id,
                portfolio=portfolio_doc if isinstance(portfolio_doc, dict) else None,
                force=force,
                catch_up=catch_up_evening,
            )
            state["last_evening_send"] = result
            state["last_attempt_utc"] = datetime.now(timezone.utc).isoformat()
            if result.get("sent"):
                tag = " (catch-up)" if result.get("catch_up") else ""
                notes.append(f"evening sent{tag}: {result.get('subject')}")
            else:
                notes.append(f"evening not sent: {result.get('reason') or result}")

        if not notes:
            return TickResult(state=state, note="idle: no matching report window")
        return TickResult(state=state, note="; ".join(notes))

    def _portfolio_doc(
        self, portfolio_key: str | None, *, ist_date: str
    ) -> dict[str, Any] | None:
        if not portfolio_key:
            return None
        try:
            from atlas.investment import portfolios as pf
            from atlas.investment.session_notes import format_no_fill_reasons, load_day_notes

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
                        portfolio_doc["equity_value"] = snap.get("equity")
                        portfolio_doc["positions_value"] = snap.get("holdings_value")
                except Exception:  # noqa: BLE001
                    self._logger.debug("sim portfolio snapshot failed", exc_info=True)
                if hasattr(self._portfolio, "trades"):
                    try:
                        trades = self._portfolio.trades(pid, limit=50)
                        portfolio_doc["recent_trades"] = self._tag_trades_ist_day(
                            list(trades or []), ist_date=ist_date
                        )
                        portfolio_doc["trade_count"] = len(trades or [])
                    except Exception:  # noqa: BLE001
                        self._logger.debug("sim portfolio trades failed", exc_info=True)

            data_dir = self._data_dir
            if not data_dir and self._mailer is not None:
                data_dir = getattr(self._mailer, "_data_dir", None)
            notes = load_day_notes(
                data_dir, portfolio_key=portfolio_key, ist_date=ist_date
            )
            portfolio_doc["no_fill_reasons"] = format_no_fill_reasons(notes)
            if notes.get("feed_gap_days") is not None:
                portfolio_doc["feed_gap_days"] = notes.get("feed_gap_days")
            return portfolio_doc
        except Exception:  # noqa: BLE001
            self._logger.debug("portfolio meta lookup failed", exc_info=True)
            return None

    @staticmethod
    def _tag_trades_ist_day(
        trades: list[dict[str, Any]], *, ist_date: str
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in trades:
            if not isinstance(t, dict):
                continue
            row = dict(t)
            ts = row.get("created_at") or row.get("ts") or row.get("filled_at") or row.get("t")
            match = False
            if ts is not None:
                try:
                    if isinstance(ts, datetime):
                        dt = ts
                    else:
                        raw = str(ts).replace("Z", "+00:00")
                        dt = datetime.fromisoformat(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    match = dt.astimezone(_IST).strftime("%Y-%m-%d") == ist_date
                except Exception:  # noqa: BLE001
                    match = False
            row["ist_day_match"] = match
            out.append(row)
        return out
