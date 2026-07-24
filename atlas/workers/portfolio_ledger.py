"""PortfolioLedgerWorker — Market Intelligence M6 (MI.6).

Maintains a fee/tax-aware sim ledger using Broker Profiles. Processes
``pending_fills`` / operator inputs; journals statement each tick.
Simulation only — never broker login (P10).
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.trading.broker_profiles import get_broker_profile
from atlas.trading.ledger import PortfolioLedgerService
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class PortfolioLedgerWorker(PersistentWorker):
    type = "portfolio_ledger"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        ledger: Any,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ledger = ledger
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.portfolio_ledger")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        profile_id = str(cfg.get("broker_profile") or "paper_demo").strip()
        custom = cfg.get("custom_broker_profile")
        custom = custom if isinstance(custom, dict) else None
        profile = get_broker_profile(profile_id, custom=custom)

        starting_cash = float(cfg.get("starting_cash") or 100_000.0)
        currency = str(cfg.get("base_currency") or profile.currency or "INR")
        portfolio_name = str(cfg.get("portfolio_name") or "ledger")

        portfolio = self._ledger.ensure_portfolio(
            mission_id=ctx.mission_id,
            name=portfolio_name,
            starting_cash=starting_cash,
            base_currency=currency,
        )
        portfolio_id = portfolio["id"]
        state["portfolio_id"] = str(portfolio_id)

        fills = list(cfg.get("pending_fills") or [])
        for inp in ctx.inputs or []:
            if inp.get("fill") and isinstance(inp["fill"], dict):
                fills.append(inp["fill"])
            elif inp.get("side") and inp.get("symbol"):
                fills.append(inp)

        applied = 0
        errors = 0
        notes: list[str] = []
        # Apply each fill once — keys in state survive reboots (P9).
        handled = set(state.get("handled_fill_keys") or [])

        for fill in fills:
            if not isinstance(fill, dict):
                continue
            symbol = str(fill.get("symbol") or "").strip()
            side = str(fill.get("side") or "").strip().lower()
            try:
                qty = float(fill.get("quantity") or 0.0)
                price = float(fill.get("price") or 0.0)
            except (TypeError, ValueError):
                errors += 1
                notes.append(f"bad fill numbers: {fill}")
                continue
            if not symbol or side not in ("buy", "sell") or qty <= 0 or price <= 0:
                errors += 1
                notes.append(f"invalid fill {symbol}/{side}")
                continue
            key = f"{symbol}:{side}:{qty:g}@{price:g}"
            if key in handled and not fill.get("force"):
                continue
            try:
                result = self._ledger.apply_fill(
                    portfolio_id,
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    price=price,
                    broker_profile=profile_id,
                    custom_profile=custom,
                    mission_id=ctx.mission_id,
                )
            except Exception as exc:  # noqa: BLE001
                errors += 1
                notes.append(f"{symbol} {side}: {exc}")
                self._logger.warning("ledger fill failed: %s", exc)
                continue
            applied += 1
            handled.add(key)
            fees = float((result.get("fees") or {}).get("total") or 0.0)
            notes.append(f"{side} {qty:g} {symbol} @ {price:g} fee={fees:g}")
            if self._events is not None:
                try:
                    self._events.emit(
                        "PortfolioLedgerFill",
                        {
                            "mission_id": ctx.mission_id,
                            "symbol": symbol,
                            "side": side,
                            "quantity": qty,
                            "price": price,
                            "fees": result.get("fees"),
                            "broker_profile": profile_id,
                        },
                        source=self.type,
                    )
                except Exception:  # noqa: BLE001
                    pass

        state["handled_fill_keys"] = list(handled)[-100:]

        prices = {
            str(k): float(v)
            for k, v in (cfg.get("marks") or {}).items()
            if v is not None
        }
        statement = self._ledger.statement(
            portfolio_id, prices=prices or None, broker_profile=profile_id
        )
        state["last_equity"] = statement.get("equity")
        state["last_fees_paid"] = statement.get("fees_paid")

        head = (
            f"ledger[{profile.id}]: equity={float(statement.get('equity') or 0):.2f} "
            f"cash={float(statement.get('cash') or 0):.2f} "
            f"fees_paid={float(statement.get('fees_paid') or 0):.2f} "
            f"fills+={applied} err={errors}"
        )
        detail = "; ".join(notes[:5])
        return TickResult(state=state, note=f"{head} | {detail}" if detail else head)
