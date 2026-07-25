"""PaperTradingWorker — the Paper-Trading Mission's persistent worker (Phase D · §D.6, flagship e2e).

The applied mission that ties D-Core together. Each tick drives the ONE decision path:

    bars → indicators → DecisionEngine.decide → apply → journal → notify

Feed sources (config ``feed_mode``):
- **asset_replay** (default) — Asset Store ``market_data`` via :class:`~atlas.readers.market_data.MarketDataReader`
- **live** — :class:`~atlas.trading.market_reader.MarketReaderService` (Yahoo / keyed providers)

Buys/sells respect ``market_session`` when ``respect_market_hours`` is true (NSE/US regular hours).
Simulation fills only — no real broker (P10).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.decision.rules import CapabilityGap
from atlas.trading.broker_profiles import compute_fees, get_broker_profile
from atlas.trading.indicators import compute_indicators
from atlas.trading.sessions import session_status
from atlas.workers.base import PersistentWorker, TickContext, TickResult

MISSION_TYPE_PAPER_TRADING = "paper_trading"
ASSET_KIND_MARKET_DATA = "market_data"


class PaperTradingWorker(PersistentWorker):
    type = "paper_trading"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        assets: Any,
        market_data: Any,
        decision_engine: Any,
        portfolio: Any,
        learning: Any = None,
        experience_os: Any = None,
        mission_context: Any = None,
        policy_engine: Any = None,
        events: Any = None,
        live_market: Any = None,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._reader = market_data
        self._engine = decision_engine
        self._portfolio = portfolio
        self._learning = learning
        self._experience_os = experience_os
        self._mission_context = mission_context
        self._policy_engine = policy_engine
        self._events = events
        self._live_market = live_market
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._logger = logger or logging.getLogger("atlas.workers.paper_trading")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        instruments = cfg.get("instruments") or []
        if not instruments:
            # Operator-visible idle reason (empty note looked like "doing nothing silently").
            return TickResult(
                state=state,
                note=(
                    "idle: no instruments in config — register sample market_data "
                    "(Missions UI) and set instruments=[{symbol, asset}], or use "
                    "Chat/Job: start paper trading with 10000 on DEMO; "
                    "for live tape set feed_mode=live and instruments=[{symbol}]"
                ),
            )

        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        # Live operator inputs: block/unblock a symbol ("don't trade SYM"), or force a tick.
        blocked = {str(s).lower() for s in (state.get("blocked_symbols") or [])}
        for item in ctx.inputs:
            if item.get("block_symbol"):
                blocked.add(str(item["block_symbol"]).lower())
            if item.get("unblock_symbol"):
                blocked.discard(str(item["unblock_symbol"]).lower())
        state["blocked_symbols"] = sorted(blocked)

        portfolio = self._portfolio.ensure_portfolio(
            mission_id=ctx.mission_id,
            starting_cash=float(cfg.get("starting_cash", 100_000.0)),
        )
        portfolio_id = portfolio["id"]
        state["portfolio_id"] = str(portfolio_id)

        feed_mode = str(cfg.get("feed_mode") or "asset_replay").strip().lower()
        if feed_mode not in ("asset_replay", "live"):
            feed_mode = "asset_replay"

        respect_hours = bool(cfg.get("respect_market_hours", True))
        session_id = str(cfg.get("market_session") or "always_open").strip() or "always_open"
        sess = session_status(session_id, clock=self._clock)
        session_open = True if not respect_hours else sess.open
        state["session"] = {
            "id": sess.session_id,
            "open": session_open,
            "reason": sess.reason if respect_hours else "hours_ignored",
            "local_now": sess.local_now,
        }

        cursors: dict[str, int] = dict(state.get("cursors") or {})
        last_bar_keys: dict[str, str] = dict(state.get("last_bar_keys") or {})
        bars_per_tick = max(1, int(cfg.get("bars_per_tick", 1)))
        strategy = cfg.get("strategy") or {}
        allowed = [str(i.get("symbol")) for i in instruments if i.get("symbol")]

        totals = {
            "decisions": 0,
            "buys": 0,
            "sells": 0,
            "holds": 0,
            "gaps": 0,
            "errors": 0,
            "session_skips": 0,
        }
        marks: dict[str, float] = {}
        exhausted = 0
        last_actions: list[str] = []

        for inst in instruments:
            symbol = str(inst.get("symbol") or "").strip()
            asset_name = str(inst.get("asset") or symbol).strip()
            if not symbol:
                continue
            try:
                if feed_mode == "live":
                    bars = self._load_live_bars(symbol, cfg)
                else:
                    bars = self._load_bars(asset_name)
            except CapabilityGap as exc:
                totals["gaps"] += 1
                last_actions.append(f"{symbol}: gap ({exc.capability})")
                continue
            except Exception as exc:  # noqa: BLE001 - a bad feed must not stop the others
                totals["errors"] += 1
                self._logger.warning("feed load failed for %s (%s): %s", symbol, asset_name, exc)
                last_actions.append(f"{symbol}: feed_error")
                continue
            if not bars:
                if feed_mode == "live":
                    last_actions.append(f"{symbol}: empty_live_feed")
                else:
                    exhausted += 1
                    last_actions.append(f"{symbol}: empty_feed")
                continue

            if feed_mode == "live":
                cursor = len(bars) - 1
                price = float(bars[cursor]["close"])
                marks[symbol] = price
                bar_key = str(bars[cursor].get("t") if bars[cursor].get("t") is not None else cursor)
                if not session_open:
                    totals["session_skips"] += 1
                    last_actions.append(
                        f"{symbol}: session_closed ({sess.reason}) mark @ {price:.2f}"
                    )
                    continue
                if last_bar_keys.get(symbol) == bar_key:
                    last_actions.append(f"{symbol}: mark_only @ {price:.2f} (same bar)")
                    continue
                action = self._decide_bar(
                    symbol=symbol,
                    bars=bars,
                    cursor=cursor,
                    cfg=cfg,
                    strategy=strategy,
                    allowed=allowed,
                    blocked=sorted(blocked),
                    portfolio_id=portfolio_id,
                    mission_id=ctx.mission_id,
                    config_version=ctx.config_version,
                    totals=totals,
                    marks=marks,
                    state=state,
                )
                last_bar_keys[symbol] = bar_key
                if action:
                    last_actions.append(action)
                bar_snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
                self._check_drawdown(state, bar_snapshot, cfg, ctx.mission_id)
                continue

            # --- asset_replay path ---
            cursor = int(cursors.get(symbol, 0))
            if cursor >= len(bars):
                exhausted += 1
                last_actions.append(f"{symbol}: feed_exhausted ({len(bars)} bars)")
                continue

            if not session_open:
                # Still advance marks from the next bar so equity reflects the feed, but no trades.
                price = float(bars[min(cursor, len(bars) - 1)]["close"])
                marks[symbol] = price
                totals["session_skips"] += 1
                last_actions.append(
                    f"{symbol}: session_closed ({sess.reason}) mark @ {price:.2f}"
                )
                continue

            processed = 0
            while cursor < len(bars) and processed < bars_per_tick:
                action = self._decide_bar(
                    symbol=symbol,
                    bars=bars,
                    cursor=cursor,
                    cfg=cfg,
                    strategy=strategy,
                    allowed=allowed,
                    blocked=sorted(blocked),
                    portfolio_id=portfolio_id,
                    mission_id=ctx.mission_id,
                    config_version=ctx.config_version,
                    totals=totals,
                    marks=marks,
                    state=state,
                )
                if action:
                    last_actions.append(action)
                # Track equity peak + drawdown per bar so an intra-replay drawdown is caught (not
                # just the end-of-tick value) — reboot-safe via the persisted peak in state.
                bar_snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
                self._check_drawdown(state, bar_snapshot, cfg, ctx.mission_id)
                cursor += 1
                processed += 1
            cursors[symbol] = cursor
            if cursor >= len(bars):
                exhausted += 1

        state["cursors"] = cursors
        state["last_bar_keys"] = last_bar_keys
        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["feed_mode"] = feed_mode

        snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
        state["equity"] = snapshot["equity"]

        # Live tape never "exhausts"; replay completes when every feed is spent.
        done = (
            False
            if feed_mode == "live"
            else (exhausted >= len(instruments) and exhausted > 0)
        )
        action_bit = ""
        if last_actions:
            # Keep journal readable: last few actions only.
            action_bit = " | " + "; ".join(last_actions[-4:])
        session_bit = ""
        if respect_hours and not session_open:
            session_bit = f" | market {sess.session_id} closed ({sess.reason})"
        elif respect_hours and sess.session_id != "always_open":
            session_bit = f" | market {sess.session_id} open"
        note = (
            f"{config_note}tick [{feed_mode}]: {totals['decisions']} decision(s) "
            f"(+{totals['buys']} buy, +{totals['sells']} sell, {totals['holds']} hold"
            + (f", {totals['gaps']} gap" if totals["gaps"] else "")
            + (f", {totals['errors']} error" if totals["errors"] else "")
            + (
                f", {totals['session_skips']} session_skip"
                if totals["session_skips"]
                else ""
            )
            + f"); equity {snapshot['equity']:.2f} "
            f"(P&L {snapshot['realized_pnl'] + snapshot['unrealized_pnl']:+.2f})"
            f"{session_bit}{action_bit}"
            + (" | DONE: all feeds exhausted (fixture replay complete)" if done else "")
        ).strip()
        return TickResult(state=state, done=done, note=note)

    # --- per-bar decision ------------------------------------------------
    def _decide_bar(
        self,
        *,
        symbol: str,
        bars: list[dict[str, Any]],
        cursor: int,
        cfg: dict[str, Any],
        strategy: dict[str, Any],
        allowed: list[str],
        blocked: list[str],
        portfolio_id: Any,
        mission_id: str,
        config_version: int | None,
        totals: dict[str, int],
        marks: dict[str, float],
        state: dict[str, Any],
    ) -> str | None:
        closes = [float(b["close"]) for b in bars[: cursor + 1]]
        indicators = compute_indicators(closes, strategy)
        price = closes[-1]
        marks[symbol] = price
        position = self._portfolio.position(portfolio_id, symbol) or {}
        held = float(position.get("quantity", 0.0))
        snapshot = self._portfolio.snapshot(portfolio_id, prices={symbol: price})

        mentor_advice = ""
        mission_ctx_summary = ""
        mission_ctx_citations: list[str] = []
        fact_findings: list[dict[str, Any]] = []
        predicted_findings: list[dict[str, Any]] = []
        if self._mission_context is not None:
            try:
                gathered = self._mission_context.gather(
                    f"markets trading {symbol}",
                    program_id="market",
                    limit=8,
                )
                mission_ctx_summary = str(gathered.get("summary") or "")[:400]
                mission_ctx_citations = list(gathered.get("citations") or [])[:8]
                # Prefer Experience block from shared API when present.
                for it in gathered.get("items") or []:
                    kind = str(it.get("item_kind") or it.get("kind") or "")
                    if kind == "experience_advice":
                        mentor_advice = str(it.get("advice") or "")[:500]
                    elif kind == "finding":
                        row = {
                            "id": it.get("id"),
                            "statement": it.get("statement"),
                            "truth_kind": it.get("truth_kind"),
                            "claim_type": it.get("claim_type"),
                            "status": it.get("status"),
                            "freshness": it.get("freshness"),
                            "valid_from": it.get("valid_from"),
                            "valid_until": it.get("valid_until"),
                        }
                        if str(it.get("truth_kind") or "") == "predicted":
                            predicted_findings.append(row)
                        else:
                            fact_findings.append(row)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("mission_context gather skipped: %s", exc)
        if not mentor_advice and self._learning is not None:
            try:
                adv = self._learning.advice_for(f"markets trading {symbol}", limit=3)
                mentor_advice = str(adv.get("advice") or "")[:500]
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("mentor advice_for skipped: %s", exc)

        request = DecisionRequest(
            mission_id=mission_id,
            mission_type=MISSION_TYPE_PAPER_TRADING,
            config_version=config_version,
            context={
                "symbol": symbol,
                "domain": "markets",
                "domains": ["markets"],
                "mission_type": MISSION_TYPE_PAPER_TRADING,
                "price": price,
                "indicators": indicators,
                "position_qty": held,
                "equity": snapshot["equity"],
                "cash": snapshot["cash"],
                "allowed_symbols": allowed,
                "blocked_symbols": blocked,
                "max_position_qty": cfg.get("max_position_qty", 0),
                "max_exposure_pct": cfg.get("max_exposure_pct", 0),
                "trade_fraction": strategy.get("trade_fraction", 0.1),
                "rsi_overbought": strategy.get("rsi_overbought", 70.0),
                "rsi_oversold": strategy.get("rsi_oversold", 30.0),
                "mentor_advice": mentor_advice,
                "mission_context_summary": mission_ctx_summary,
                "mission_context_citations": mission_ctx_citations,
                # OI-F2 — keep forecasts out of the operative-fact bucket.
                "fact_findings": fact_findings[:8],
                "predicted_findings": predicted_findings[:8],
            },
        )
        decision = self._engine.decide(request)
        totals["decisions"] += 1
        why = (decision.why or "").strip()
        why_short = (why[:80] + "…") if len(why) > 80 else why
        if decision.action_kind != ACTION_RECOMMEND:
            if decision.action_kind == "capability_gap":
                totals["gaps"] += 1
                return f"{symbol}: gap ({why_short or 'missing capability'})"
            totals["holds"] += 1
            return f"{symbol}: hold @ {price:.2f}"

        # The engine wraps the chosen option under action["payload"] (action["kind"] == "recommend").
        payload = (decision.action or {}).get("payload") or {}
        kind = payload.get("kind")
        if kind not in ("buy", "sell"):
            totals["holds"] += 1
            return f"{symbol}: hold @ {price:.2f}"

        qty = float(payload.get("quantity") or 0.0)
        if qty <= 0:
            totals["holds"] += 1
            return f"{symbol}: hold @ {price:.2f}"

        if self._policy_engine is not None:
            try:
                exposure = 0.0
                if float(snapshot.get("equity") or 0) > 0 and price > 0:
                    exposure = 100.0 * (held * price) / float(snapshot["equity"])
                verdict = self._policy_engine.evaluate(
                    action={"kind": kind, "symbol": symbol, "quantity": qty, "price": price},
                    context={
                        "equity": snapshot.get("equity"),
                        "position_qty": held,
                        "exposure_pct": exposure,
                        "drawdown_pct": state.get("last_drawdown_pct"),
                        "price": price,
                    },
                    scope="domain:markets",
                )
                if not verdict.get("allowed", True):
                    totals["holds"] += 1
                    detail = ""
                    viols = verdict.get("hard_violations") or []
                    if viols:
                        detail = str(viols[0].get("detail") or "")
                    return f"{symbol}: policy_block ({detail or 'hard constraint'})"
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("policy_engine evaluate skipped: %s", exc)

        fee = 0.0
        profile_id = str(cfg.get("broker_profile") or "").strip()
        if profile_id:
            breakdown = compute_fees(
                get_broker_profile(profile_id),
                side=kind,
                quantity=qty,
                price=price,
            )
            fee = float(breakdown.total)
        try:
            trade = self._portfolio.apply_trade(
                portfolio_id,
                symbol=symbol,
                side=kind,
                quantity=qty,
                price=price,
                fee=fee,
                mission_id=mission_id,
                decision_id=decision.id,
            )
        except Exception as exc:  # noqa: BLE001 - a rejected sim fill is reported, never fatal
            totals["errors"] += 1
            self._logger.warning("sim fill rejected (%s %s %s): %s", kind, qty, symbol, exc)
            return f"{symbol}: fill_rejected ({exc})"

        totals["buys" if kind == "buy" else "sells"] += 1
        self._emit("PaperTradingFill", {
            "mission_id": str(mission_id), "decision_id": str(decision.id) if decision.id else None,
            "symbol": symbol, "side": kind, "quantity": qty, "price": price,
            "realized_pnl": float(trade.get("realized_pnl", 0.0)),
        })
        if kind == "sell":
            self._remember_outcome(
                symbol, trade, decision, indicators=indicators, cfg=cfg
            )
        return f"{symbol}: {kind} {qty:g} @ {price:.2f} ({why_short or 'signal'})"

    # --- learning loop ---------------------------------------------------
    def _remember_outcome(
        self,
        symbol: str,
        trade: dict[str, Any],
        decision: Any,
        *,
        indicators: dict[str, Any] | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        """Record Decision→Outcome via the OI-F4 feedback convention (OI-MP1 / OI-F1)."""
        if self._experience_os is None and self._learning is None:
            return
        from atlas.decision.feedback import (
            DIFF_MATCHED,
            DIFF_MISSED,
            DIFF_UNKNOWN,
            build_feedback_journal,
            record_feedback_loop,
        )
        from atlas.decision.knowledge import (
            bias_recommendations,
            decision_knowledge_tags,
            link_metadata,
            outcome_label,
            should_enable_decision_bias,
        )

        pnl = float(trade.get("realized_pnl", 0.0))
        outcome = outcome_label(pnl)
        difference = {
            "profit": DIFF_MATCHED,
            "loss": DIFF_MISSED,
            "flat": DIFF_UNKNOWN,
        }.get(outcome, DIFF_UNKNOWN)
        decision_id = str(getattr(decision, "id", None) or "") or None
        why = (decision.why or "").strip() or "strategy exit signal"
        ind = indicators if isinstance(indicators, dict) else {}
        observation_bits = []
        if ind.get("rsi") is not None:
            observation_bits.append(f"RSI={ind.get('rsi')}")
        if ind.get("sma_fast") is not None and ind.get("sma_slow") is not None:
            observation_bits.append(
                f"SMA fast/slow={ind.get('sma_fast')}/{ind.get('sma_slow')}"
            )
        observation = (
            "; ".join(str(b) for b in observation_bits)
            if observation_bits
            else f"Exit signal on {symbol} at realized P&L {pnl:+.2f}"
        )
        reflection = (
            "Outcome matched thesis."
            if pnl > 0
            else (
                "Outcome contradicted thesis — review entry timing and open risk events."
                if pnl < 0
                else "Flat outcome — little signal for strategy update."
            )
        )
        lesson = (
            "Reinforce setups that produced positive expectancy under current constraints."
            if pnl > 0
            else (
                "Before similar entries, re-check catalysts and risk limits; "
                "do not treat a single indicator as sufficient."
                if pnl < 0
                else "Treat flat outcomes as inconclusive; avoid overfitting to noise."
            )
        )
        title = f"Paper trade closed on {symbol}: {outcome} {pnl:+.2f}"
        recommendation = f"sell {symbol} (simulation)"
        outcome_text = f"{outcome} {pnl:+.2f}"
        cfg = cfg if isinstance(cfg, dict) else {}
        enable_bias = bool(cfg.get("enable_decision_soft_bias", True)) and should_enable_decision_bias(
            outcome
        )
        tags = decision_knowledge_tags(symbol, outcome, decision_id=decision_id)
        meta = link_metadata(
            decision_id=decision_id, symbol=symbol, outcome=outcome, pnl=pnl
        )
        meta["feedback_loop"] = True
        meta["difference"] = difference
        journal_kwargs = build_feedback_journal(
            title=title,
            recommendation=recommendation,
            outcome=outcome_text,
            difference=difference,
            observation=observation,
            reasoning=why,
            reflection=reflection,
            lesson=lesson,
            domain="markets",
            mission_type=MISSION_TYPE_PAPER_TRADING,
            decision_id=decision_id,
            subject=symbol,
            recommendations=bias_recommendations(symbol, outcome, pnl),
            metadata_extra=meta,
            tags_extra=tags,
        )
        # Prefer OI-F1 decision_knowledge tags ordering / content.
        journal_kwargs["tags"] = tags + [
            t for t in journal_kwargs["tags"] if t not in tags
        ]
        journal_kwargs["metadata"] = {**journal_kwargs["metadata"], **meta}
        record_feedback_loop(
            experience_os=self._experience_os,
            learning=self._learning,
            journal_kwargs=journal_kwargs,
            enable_bias=enable_bias,
            difference=difference,
            logger=self._logger,
        )

    # --- notifications ---------------------------------------------------
    def _check_drawdown(
        self, state: dict[str, Any], snapshot: dict[str, Any], cfg: dict[str, Any], mission_id: str
    ) -> None:
        equity = float(snapshot["equity"])
        peak = float(state.get("peak_equity", equity))
        peak = max(peak, equity)
        state["peak_equity"] = peak
        threshold = float(cfg.get("drawdown_alert_pct", 0) or 0)
        if threshold <= 0 or peak <= 0:
            return
        drawdown = (peak - equity) / peak * 100.0
        state["last_drawdown_pct"] = round(drawdown, 2)
        if drawdown >= threshold and not state.get("drawdown_alerted"):
            state["drawdown_alerted"] = True
            self._emit("PaperTradingDrawdown", {
                "mission_id": str(mission_id), "equity": equity, "peak_equity": peak,
                "drawdown_pct": round(drawdown, 2), "threshold_pct": threshold,
            })
        elif drawdown < threshold:
            state["drawdown_alerted"] = False

    # --- helpers ---------------------------------------------------------
    def _load_bars(self, asset_name: str) -> list[dict[str, Any]]:
        asset = self._assets.get_by_name(ASSET_KIND_MARKET_DATA, asset_name)
        if asset is None:
            raise FileNotFoundError(f"no market_data asset named {asset_name!r}")
        artifact = self._reader.read(str(asset["id"]))
        if artifact.get("outcome") != "ok":
            raise RuntimeError(f"feed unreadable: {artifact.get('reason', 'unknown')}")
        return list(artifact.get("bars") or [])

    def _load_live_bars(self, symbol: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        if self._live_market is None:
            raise CapabilityGap(
                "market_reader",
                "live feed_mode requires MarketReaderService (wire live_market= on worker)",
            )
        provider = str(cfg.get("live_provider") or "yahoo").strip() or "yahoo"
        limit = max(5, int(cfg.get("live_bars_limit", 100)))
        out = self._live_market.bars_for(symbol, provider=provider, limit=limit)
        return list(out.get("bars") or [])

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001 - telemetry must never break a tick
            self._logger.exception("failed to emit %s", event_type)
