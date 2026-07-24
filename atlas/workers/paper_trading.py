"""PaperTradingWorker — the Paper-Trading Mission's persistent worker (Phase D · §D.6, flagship e2e).

The applied mission that ties D-Core together. Each tick replays the next bar of every configured
instrument's OHLCV feed and, per symbol, drives the ONE decision path:

    Asset → MarketDataReader → bars → indicators → DecisionEngine.decide → apply → journal → notify

- **read** the feed (an Asset) through the stateless :class:`~atlas.readers.market_data.MarketDataReader`
  (P8/P11);
- **compute** deterministic indicator signals (ephemeral decision context, not knowledge);
- **decide** via the shared :class:`~atlas.decision.engine.DecisionEngine` + the registered
  :class:`~atlas.trading.strategy.StrategyDecisionRule` (policy-influenced, constraint-bounded, P9);
- **apply** a recommended buy/sell to the *virtual* portfolio (simulation → flows freely, DD3, P10);
- **learn** — a realized sell's outcome is remembered as an Experience so strategy confidence grows
  over time (C.6/P13);
- **notify** on notable events (a fill, a drawdown breach) via the event bus.

It owns no knowledge (P11): it drives stateless translators + the engine and journals what it did (P9).
Bounded + checkpointed: state carries a per-symbol bar cursor so the loop resumes exactly where it
left off after a reboot, and completes when every feed is exhausted.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.trading.broker_profiles import compute_fees, get_broker_profile
from atlas.trading.indicators import compute_indicators
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
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._reader = market_data
        self._engine = decision_engine
        self._portfolio = portfolio
        self._learning = learning
        self._events = events
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
                    "Chat/Job: start paper trading with 10000 on DEMO"
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

        cursors: dict[str, int] = dict(state.get("cursors") or {})
        bars_per_tick = max(1, int(cfg.get("bars_per_tick", 1)))
        strategy = cfg.get("strategy") or {}
        allowed = [str(i.get("symbol")) for i in instruments if i.get("symbol")]

        totals = {"decisions": 0, "buys": 0, "sells": 0, "holds": 0, "gaps": 0, "errors": 0}
        marks: dict[str, float] = {}
        exhausted = 0
        last_actions: list[str] = []

        for inst in instruments:
            symbol = str(inst.get("symbol") or "").strip()
            asset_name = str(inst.get("asset") or symbol).strip()
            if not symbol:
                continue
            try:
                bars = self._load_bars(asset_name)
            except Exception as exc:  # noqa: BLE001 - a bad feed must not stop the others
                totals["errors"] += 1
                self._logger.warning("feed load failed for %s (%s): %s", symbol, asset_name, exc)
                last_actions.append(f"{symbol}: feed_error")
                continue
            if not bars:
                exhausted += 1
                last_actions.append(f"{symbol}: empty_feed")
                continue

            cursor = int(cursors.get(symbol, 0))
            if cursor >= len(bars):
                exhausted += 1
                last_actions.append(f"{symbol}: feed_exhausted ({len(bars)} bars)")
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
        state["ticks"] = int(state.get("ticks", 0)) + 1

        snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
        state["equity"] = snapshot["equity"]

        done = exhausted >= len(instruments) and exhausted > 0
        action_bit = ""
        if last_actions:
            # Keep journal readable: last few actions only.
            action_bit = " | " + "; ".join(last_actions[-4:])
        note = (
            f"{config_note}tick: {totals['decisions']} decision(s) "
            f"(+{totals['buys']} buy, +{totals['sells']} sell, {totals['holds']} hold"
            + (f", {totals['gaps']} gap" if totals["gaps"] else "")
            + (f", {totals['errors']} error" if totals["errors"] else "")
            + f"); equity {snapshot['equity']:.2f} "
            f"(P&L {snapshot['realized_pnl'] + snapshot['unrealized_pnl']:+.2f})"
            f"{action_bit}"
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
    ) -> str | None:
        closes = [float(b["close"]) for b in bars[: cursor + 1]]
        indicators = compute_indicators(closes, strategy)
        price = closes[-1]
        marks[symbol] = price
        position = self._portfolio.position(portfolio_id, symbol) or {}
        held = float(position.get("quantity", 0.0))
        snapshot = self._portfolio.snapshot(portfolio_id, prices={symbol: price})

        request = DecisionRequest(
            mission_id=mission_id,
            mission_type=MISSION_TYPE_PAPER_TRADING,
            config_version=config_version,
            context={
                "symbol": symbol,
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
            self._remember_outcome(symbol, trade, decision, indicators=indicators)
        return f"{symbol}: {kind} {qty:g} @ {price:.2f} ({why_short or 'signal'})"

    # --- learning loop ---------------------------------------------------
    def _remember_outcome(
        self,
        symbol: str,
        trade: dict[str, Any],
        decision: Any,
        *,
        indicators: dict[str, Any] | None = None,
    ) -> None:
        """Record an Experience Journal entry (MP3): Observation→…→Lesson."""
        if self._learning is None:
            return
        pnl = float(trade.get("realized_pnl", 0.0))
        outcome = "profit" if pnl > 0 else ("loss" if pnl < 0 else "flat")
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
        problem = (
            f"Observation: {observation}\n"
            f"Reasoning: {why}\n"
            f"Decision: sell {symbol} (simulation)\n"
            f"Outcome: {outcome} {pnl:+.2f}"
        )
        solution = f"Reflection: {reflection}"
        lessons = f"Lesson: {lesson}"
        try:
            self._learning.remember_experience(
                title=f"Paper trade closed on {symbol}: {outcome} {pnl:+.2f}",
                problem=problem,
                solution=solution,
                lessons=lessons,
                domain="markets",
                tags=[symbol.lower(), "paper_trading", outcome, "experience_journal"],
            )
        except Exception as exc:  # noqa: BLE001 - learning is best-effort, never breaks a tick
            self._logger.warning("remember_experience failed for %s: %s", symbol, exc)

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

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001 - telemetry must never break a tick
            self._logger.exception("failed to emit %s", event_type)
