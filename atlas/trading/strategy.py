"""StrategyDecisionRule — the Paper-Trading mission's Decision-Engine plugin (Phase D · §D.6, BB-D2).

One symbol per :class:`~atlas.decision.contracts.DecisionRequest`: the worker computes indicator
signals for a symbol and asks the engine "buy, sell, or hold?". This rule scores those candidate
options **deterministically** (Q7) from a moving-average crossover + RSI filter — no LLM, no
persistence. The engine then folds in **policy influence** (e.g. ``avoid TSLA`` nudges its buy score
down; ``prefer AAPL`` nudges it up — DD5) and picks the top option.

The rule is **constraint-bounded** from the versioned mission config + live operator inputs (both
arrive in ``request.context``, assembled by the worker):
  * an operator ``blocked_symbols`` entry (a live "don't trade SYM" input) → only *hold* is offered;
  * an ``allowed_symbols`` allow-list → a symbol outside it → only *hold*;
  * ``max_position_qty`` / ``max_exposure_pct`` → a buy that would breach the cap is withheld.

Simulation only (P10): every option is ``side_effecting = False`` so applies flow freely (DD3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from atlas.decision.contracts import DecisionRequest, ScoredOption

if TYPE_CHECKING:
    from atlas.decision.context import IntelligenceContext

MISSION_TYPE_PAPER_TRADING = "paper_trading"

_HOLD_SCORE = 0.5
_SIGNAL_BASE = 1.0
_MARGIN_WEIGHT = 5.0  # how strongly the MA margin sharpens a signal's score (bounded below)


class StrategyDecisionRule:
    """Deterministic MA-crossover + RSI strategy → buy/sell/hold options for one symbol."""

    mission_type = MISSION_TYPE_PAPER_TRADING
    VERSION = "1.0.0"

    def score(
        self, request: DecisionRequest, context: "IntelligenceContext"
    ) -> list[ScoredOption]:
        ctx = request.context or {}
        symbol = str(ctx.get("symbol") or "").strip()
        if not symbol:
            return []  # nothing to decide → the engine holds

        sym_tag = symbol.lower()
        indicators = ctx.get("indicators") or {}
        price = _as_float(ctx.get("price") if ctx.get("price") is not None else indicators.get("price"))
        held = _as_float(ctx.get("position_qty"), default=0.0)
        equity = _as_float(ctx.get("equity"), default=0.0)
        cash = _as_float(ctx.get("cash"), default=equity)

        # Hold is the policy-neutral default: it deliberately does NOT carry the symbol tag, so an
        # ``avoid SYM`` policy penalizes the actionable buy/sell options and lets hold win (DD5).
        hold = ScoredOption(
            key="hold",
            score=_HOLD_SCORE,
            text="hold",
            tags=("hold",),
            rationale="no actionable signal",
            payload={"kind": "hold", "symbol": symbol},
        )

        # --- hard constraints: only hold is offered -------------------------
        blocked = {str(s).lower() for s in (ctx.get("blocked_symbols") or [])}
        if sym_tag in blocked:
            hold.rationale = f"operator blocked trading {symbol} (live input)"
            return [hold]
        allowed = ctx.get("allowed_symbols")
        if allowed and sym_tag not in {str(s).lower() for s in allowed}:
            hold.rationale = f"{symbol} not in configured instrument allow-list"
            return [hold]

        sma_fast = _as_float(indicators.get("sma_fast"))
        sma_slow = _as_float(indicators.get("sma_slow"))
        rsi = _as_float(indicators.get("rsi"))
        if sma_fast is None or sma_slow is None or price is None:
            hold.rationale = f"warming up ({indicators.get('bars', 0)} bars; indicators not ready)"
            return [hold]

        options: list[ScoredOption] = [hold]
        margin = (sma_fast - sma_slow) / sma_slow if sma_slow else 0.0
        rsi_ok_buy = rsi is None or rsi < _as_float(ctx.get("rsi_overbought"), default=70.0)
        rsi_ok_sell = rsi is None or rsi > _as_float(ctx.get("rsi_oversold"), default=30.0)

        # --- BUY: fast MA above slow MA, not overbought, and within risk caps ---
        if margin > 0 and rsi_ok_buy:
            qty = self._buy_quantity(ctx, price=price, held=held, equity=equity, cash=cash)
            if qty > 0:
                options.append(
                    ScoredOption(
                        key=f"buy:{symbol}",
                        score=_SIGNAL_BASE + _MARGIN_WEIGHT * margin,
                        text=f"buy {qty} {symbol} @ {price:.4f}",
                        tags=("buy", sym_tag),
                        rationale=(
                            f"SMA{indicators.get('params', {}).get('sma_fast', '')} "
                            f"({sma_fast:.4f}) crossed above SMA"
                            f"{indicators.get('params', {}).get('sma_slow', '')} ({sma_slow:.4f}); "
                            f"margin {margin:+.2%}"
                            + (f", RSI {rsi:.1f}" if rsi is not None else "")
                        ),
                        payload={"kind": "buy", "symbol": symbol, "quantity": qty, "price": price},
                    )
                )

        # --- SELL: fast MA below slow MA (exit) while holding -----------------
        if margin < 0 and rsi_ok_sell and held > 0:
            qty = min(held, self._sell_quantity(ctx, held=held))
            if qty > 0:
                options.append(
                    ScoredOption(
                        key=f"sell:{symbol}",
                        score=_SIGNAL_BASE + _MARGIN_WEIGHT * abs(margin),
                        text=f"sell {qty} {symbol} @ {price:.4f}",
                        tags=("sell", sym_tag),
                        rationale=(
                            f"SMA fast ({sma_fast:.4f}) fell below SMA slow ({sma_slow:.4f}); "
                            f"margin {margin:+.2%}"
                            + (f", RSI {rsi:.1f}" if rsi is not None else "")
                        ),
                        payload={"kind": "sell", "symbol": symbol, "quantity": qty, "price": price},
                    )
                )

        return options

    # --- sizing ---------------------------------------------------------
    def _buy_quantity(
        self, ctx: dict[str, Any], *, price: float, held: float, equity: float, cash: float
    ) -> float:
        if price <= 0:
            return 0.0
        max_qty = _as_float(ctx.get("max_position_qty"), default=0.0)
        # Target notional per trade from the risk budget (fraction of equity), default a fixed size.
        trade_pct = _as_float(ctx.get("trade_fraction"), default=0.1)
        budget = min(cash, equity * trade_pct) if equity > 0 else cash
        qty = float(int(budget / price)) if price > 0 else 0.0
        if max_qty and max_qty > 0:
            room = max_qty - held
            if room <= 0:
                return 0.0
            qty = min(qty, room)
        # Enforce max exposure (position notional / equity) if configured.
        max_exposure = _as_float(ctx.get("max_exposure_pct"), default=0.0)
        if max_exposure and equity > 0:
            max_notional = equity * (max_exposure / 100.0)
            current_notional = held * price
            room_notional = max_notional - current_notional
            if room_notional <= 0:
                return 0.0
            qty = min(qty, float(int(room_notional / price)))
        return max(qty, 0.0)

    def _sell_quantity(self, ctx: dict[str, Any], *, held: float) -> float:
        # Default strategy exits the full position; a fraction can be configured.
        frac = _as_float(ctx.get("sell_fraction"), default=1.0)
        frac = min(max(frac, 0.0), 1.0)
        return held * frac if frac < 1.0 else held


def _as_float(value: Any, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
