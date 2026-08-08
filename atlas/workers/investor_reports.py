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
        market_reader: Any | None = None,
        data_dir: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._mailer = mailer
        self._portfolio = portfolio
        self._market_reader = market_reader
        self._data_dir = data_dir
        self._logger = logger or logging.getLogger("atlas.workers.investor_reports")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        program_id = str(cfg.get("program_id") or "market_intelligence")
        # Market investor reports belong to the learner book by default. Leaving
        # this null produced Cash/Equity=None and hid real fills after restart.
        portfolio_key = (
            str(cfg.get("portfolio_key") or "").strip()
            or (
                "india_equity_learner"
                if program_id == "market_intelligence"
                else None
            )
        )
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
                morning_sent = bool(
                    self._mailer.already_sent_morning(
                        ist_date, laboratory_id=portfolio_key
                    )
                )
            if hasattr(self._mailer, "already_sent_evening"):
                evening_sent = bool(
                    self._mailer.already_sent_evening(
                        ist_date, laboratory_id=portfolio_key
                    )
                )

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
            persona = meta.get("persona") if isinstance(meta.get("persona"), dict) else {}
            mission_id = meta.get("mission_id") or meta.get("ledger_mission_id")
            portfolio_doc: dict[str, Any] = {
                "portfolio_key": portfolio_key,
                "laboratory_id": portfolio_key,
                "label": meta.get("label"),
                "starting_cash": persona.get("capital"),
                "cash": persona.get("capital"),
                "mission_id": mission_id,
                "sim_portfolio_id": meta.get("sim_portfolio_id") or meta.get("portfolio_id"),
                "persona": persona,
            }
            # Registry identity is durable, but the sim id/cash live in Postgres.
            # Resolve by (mission, portfolio_key) after every restart.
            if (
                not portfolio_doc.get("sim_portfolio_id")
                and mission_id
                and self._portfolio is not None
                and hasattr(self._portfolio, "ensure_portfolio")
            ):
                ensured = self._portfolio.ensure_portfolio(
                    mission_id=mission_id,
                    name=portfolio_key,
                    starting_cash=float(persona.get("capital") or 0),
                    base_currency=str(persona.get("currency") or "INR"),
                )
                portfolio_doc["sim_portfolio_id"] = ensured.get("id")
                portfolio_doc["starting_cash"] = ensured.get("starting_cash")
                portfolio_doc["cash"] = ensured.get("cash")
            pid = portfolio_doc.get("sim_portfolio_id")
            if pid and self._portfolio is not None and hasattr(self._portfolio, "snapshot"):
                try:
                    positions = []
                    repo = getattr(self._portfolio, "_repo", None)
                    if repo is not None and hasattr(repo, "list_positions"):
                        positions = list(repo.list_positions(pid) or [])
                    marks, previous = self._market_marks(
                        [str(p.get("symbol") or "") for p in positions]
                    )
                    snap = self._portfolio.snapshot(pid, prices=marks)
                    if isinstance(snap, dict):
                        portfolio_doc.update(snap)
                        portfolio_doc["positions"] = snap.get("positions") or snap.get(
                            "holdings"
                        )
                        portfolio_doc["equity_value"] = snap.get("equity")
                        portfolio_doc["positions_value"] = snap.get("holdings_value")
                        portfolio_doc["marks"] = marks
                        portfolio_doc["previous_closes"] = previous
                        portfolio_doc["valuation_basis"] = (
                            "latest daily market bars"
                            if marks
                            else "average cost (market marks unavailable)"
                        )
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
                self._add_cash_and_pnl_metrics(
                    portfolio_doc, pid=pid, ist_date=ist_date
                )

            data_dir = self._data_dir
            if not data_dir and self._mailer is not None:
                data_dir = getattr(self._mailer, "_data_dir", None)
            notes = load_day_notes(
                data_dir, portfolio_key=portfolio_key, ist_date=ist_date
            )
            portfolio_doc["no_fill_reasons"] = format_no_fill_reasons(notes)
            if notes.get("feed_gap_days") is not None:
                portfolio_doc["feed_gap_days"] = notes.get("feed_gap_days")
            try:
                from atlas.investment.decision_packets import DecisionPacketStore

                store = DecisionPacketStore(data_dir=data_dir)
                portfolio_doc["decisions"] = store.list_day(
                    portfolio_key=portfolio_key, ts_ist=ist_date, limit=100
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.1 decisions list failed", exc_info=True)
            try:
                from atlas.investment.decision_timeline import DecisionTimelineStore
                from atlas.investment.fundamentals import fundamentals_view

                tstore = DecisionTimelineStore(data_dir=data_dir)
                evo = tstore.learning_counts(portfolio_key=portfolio_key)
                open_syms = [
                    str(p.get("symbol") or "").strip().upper()
                    for p in (portfolio_doc.get("positions") or [])
                    if isinstance(p, dict) and p.get("symbol")
                    and float(p.get("qty") or p.get("quantity") or p.get("shares") or 0) > 0
                ]
                if open_syms:
                    try:
                        kind = str(
                            (persona.get("personality_kind") if isinstance(persona, dict) else None)
                            or meta.get("personality_kind")
                            or "swing"
                        )
                        cov_tl = tstore.open_book_timeline_coverage(
                            portfolio_key=portfolio_key,
                            open_symbols=open_syms,
                            personality_kind=kind,
                            review_schedule=(
                                persona.get("review_schedule")
                                if isinstance(persona, dict)
                                else None
                            ),
                        )
                        evo.update(
                            {
                                "open_books": cov_tl.get("open_books"),
                                "open_books_with_full_schedule": cov_tl.get(
                                    "open_books_with_full_schedule"
                                ),
                                "overdue_revisits": cov_tl.get("overdue_revisits"),
                                "timeline_books": cov_tl.get("books"),
                            }
                        )
                    except Exception:  # noqa: BLE001
                        self._logger.debug("LQ.2 coverage enrich failed", exc_info=True)
                portfolio_doc["evolution"] = evo
                fv = fundamentals_view(data_dir, program_id="market_intelligence", limit=5)
                cov = dict(fv.get("coverage") or {})
                # Attach watchlist gap summary when positions known
                syms = [
                    str(p.get("symbol"))
                    for p in (portfolio_doc.get("positions") or [])
                    if isinstance(p, dict) and p.get("symbol")
                ]
                if syms:
                    from atlas.investment.fundamentals import learner_fundamentals_gaps

                    cov["learner_gaps"] = learner_fundamentals_gaps(
                        data_dir, syms, program_id="market_intelligence"
                    )
                portfolio_doc["fundamentals_coverage"] = cov
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.2/DI.4 evening enrich failed", exc_info=True)
            try:
                from atlas.investment.observations import DecisionObservationStore

                ostore = DecisionObservationStore(data_dir=data_dir)
                portfolio_doc["observations"] = ostore.list_since(
                    since_hours=24.0, limit=20
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.Obs evening enrich failed", exc_info=True)
            try:
                from atlas.investment.decision_attribution import (
                    DecisionAttributionStore,
                    mirror_root,
                )
                import json
                from pathlib import Path

                items: list = []
                root = mirror_root(data_dir) / "by_id" if data_dir else None
                if root and root.is_dir():
                    for path in sorted(
                        root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
                    )[:15]:
                        try:
                            doc = json.loads(path.read_text(encoding="utf-8"))
                        except Exception:  # noqa: BLE001
                            continue
                        if (
                            isinstance(doc, dict)
                            and doc.get("portfolio_key") == portfolio_key
                        ):
                            items.append(doc)
                portfolio_doc["attributions"] = items
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.Attr evening enrich failed", exc_info=True)
            try:
                from atlas.investment import watchlists as wl
                from atlas.investment.trading_kpis import (
                    build_trading_kpis,
                    save_day_kpis,
                )

                plan = None
                snap = wl.latest("market_intelligence")
                if isinstance(snap, dict):
                    plan = (snap.get("extra") or {}).get("daily_plan") or snap.get(
                        "daily_plan"
                    )
                digest = None
                if self._mailer is not None and hasattr(self._mailer, "_research_digest"):
                    try:
                        digest = self._mailer._research_digest("market_intelligence")
                    except Exception:  # noqa: BLE001
                        digest = None
                kpis = build_trading_kpis(
                    portfolio=portfolio_doc,
                    plan=plan if isinstance(plan, dict) else None,
                    session_note=notes,
                    research_digest=digest if isinstance(digest, dict) else None,
                    ist_date=ist_date,
                )
                portfolio_doc["kpis"] = kpis
                save_day_kpis(
                    data_dir,
                    portfolio_key=portfolio_key,
                    ist_date=ist_date,
                    kpis=kpis,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("trading kpi snapshot failed", exc_info=True)
            try:
                from atlas.investment.process_proxies import collect_process_scorecard

                portfolio_doc["process_proxies"] = collect_process_scorecard(
                    data_dir=data_dir,
                    portfolio_key=portfolio_key,
                    portfolio=portfolio_doc,
                    ist_date=ist_date,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.5 process proxies enrich failed", exc_info=True)
            try:
                from atlas.investment.meta_learning import collect_meta_learning_inputs

                portfolio_doc["meta_learning"] = collect_meta_learning_inputs(
                    data_dir=data_dir,
                    portfolio_key=portfolio_key,
                    portfolio=portfolio_doc,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.6 meta-learning enrich failed", exc_info=True)
            try:
                from atlas.investment.ml_export import ml_export_status

                portfolio_doc["ml_export"] = ml_export_status(
                    data_dir=data_dir,
                    portfolio_key=portfolio_key,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.7 ml-export status enrich failed", exc_info=True)
            try:
                from atlas.investment.atlasnet_prep import atlasnet_prep_status

                portfolio_doc["atlasnet_prep"] = atlasnet_prep_status(
                    data_dir=data_dir,
                    laboratory_id=portfolio_key,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("LQ.9 atlasnet hard-gate enrich failed", exc_info=True)
            # DI.3 after KPIs + process + meta so dashboards can read all
            try:
                from atlas.investment.di_dashboards import collect_dashboard_inputs

                portfolio_doc["di_dashboards"] = collect_dashboard_inputs(
                    data_dir=data_dir,
                    portfolio_key=portfolio_key,
                    portfolio=portfolio_doc,
                    ist_date=ist_date,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.3 dashboards enrich failed", exc_info=True)
            return portfolio_doc
        except Exception:  # noqa: BLE001
            self._logger.debug("portfolio meta lookup failed", exc_info=True)
            return None

    def _market_marks(
        self, symbols: list[str]
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Latest and previous daily closes for honest EOD valuation."""
        latest: dict[str, float] = {}
        previous: dict[str, float] = {}
        if self._market_reader is None:
            return latest, previous
        for symbol in dict.fromkeys(s for s in symbols if s):
            try:
                out = self._market_reader.bars_for(
                    symbol, provider="yahoo", limit=2
                )
                bars = list((out or {}).get("bars") or [])
                if bars and bars[-1].get("close") is not None:
                    latest[symbol] = float(bars[-1]["close"])
                if len(bars) > 1 and bars[-2].get("close") is not None:
                    previous[symbol] = float(bars[-2]["close"])
            except Exception:  # noqa: BLE001
                self._logger.debug("EOD mark unavailable for %s", symbol, exc_info=True)
        return latest, previous

    def _add_cash_and_pnl_metrics(
        self, portfolio_doc: dict[str, Any], *, pid: Any, ist_date: str
    ) -> None:
        """Add contribution-adjusted total P&L and approximate trading-day P&L."""
        repo = getattr(self._portfolio, "_repo", None)
        movements: list[dict[str, Any]] = []
        if repo is not None and hasattr(repo, "list_cash_movements"):
            try:
                movements = list(repo.list_cash_movements(pid, limit=200) or [])
            except Exception:  # noqa: BLE001
                movements = []
        deposits = sum(
            float(m.get("amount") or 0)
            for m in movements
            if str(m.get("kind") or "") == "deposit"
        )
        withdrawals = sum(
            abs(float(m.get("amount") or 0))
            + float(m.get("tds") or 0)
            + float(m.get("fee") or 0)
            for m in movements
            if str(m.get("kind") or "") == "withdraw"
        )
        starting = float(portfolio_doc.get("starting_cash") or 0)
        net_contributed = starting + deposits - withdrawals
        equity = float(
            portfolio_doc.get("equity")
            or portfolio_doc.get("equity_value")
            or 0
        )
        portfolio_doc["deposits"] = deposits
        portfolio_doc["withdrawals"] = withdrawals
        portfolio_doc["net_contributed_capital"] = net_contributed
        portfolio_doc["total_pnl"] = equity - net_contributed
        portfolio_doc["total_return_pct"] = (
            100.0 * (equity - net_contributed) / net_contributed
            if net_contributed > 0
            else None
        )

        trades = list(portfolio_doc.get("recent_trades") or [])
        day_trades = [
            t for t in trades
            if isinstance(t, dict) and t.get("ist_day_match")
        ]
        previous = portfolio_doc.get("previous_closes") or {}
        marks = portfolio_doc.get("marks") or {}
        positions = portfolio_doc.get("positions") or []
        if not marks or not previous:
            portfolio_doc["day_pnl"] = None
            return
        # Start-of-day holdings plus today's fills, marked to latest close.
        day_pnl = 0.0
        current_qty: dict[str, float] = {
            str(p.get("symbol")): float(p.get("quantity") or p.get("qty") or 0)
            for p in positions
            if isinstance(p, dict) and p.get("symbol")
        }
        start_qty = dict(current_qty)
        for trade in day_trades:
            symbol = str(trade.get("symbol") or "")
            qty = float(trade.get("quantity") or trade.get("qty") or 0)
            side = str(trade.get("side") or "").lower()
            if side == "buy":
                start_qty[symbol] = start_qty.get(symbol, 0.0) - qty
            elif side == "sell":
                start_qty[symbol] = start_qty.get(symbol, 0.0) + qty
        for symbol, qty in start_qty.items():
            if symbol in marks and symbol in previous:
                day_pnl += qty * (float(marks[symbol]) - float(previous[symbol]))
        for trade in day_trades:
            symbol = str(trade.get("symbol") or "")
            if symbol not in marks:
                continue
            qty = float(trade.get("quantity") or trade.get("qty") or 0)
            price = float(trade.get("price") or trade.get("fill_price") or 0)
            fee = float(trade.get("fee") or 0)
            side = str(trade.get("side") or "").lower()
            if side == "buy":
                day_pnl += qty * (float(marks[symbol]) - price) - fee
            elif side == "sell" and symbol in previous:
                day_pnl += qty * (price - float(previous[symbol])) - fee
        portfolio_doc["day_pnl"] = day_pnl
        base = equity - day_pnl
        portfolio_doc["day_return_pct"] = (
            100.0 * day_pnl / base if base > 0 else None
        )

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
