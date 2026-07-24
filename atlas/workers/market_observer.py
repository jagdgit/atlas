"""MarketObserverWorker — Market Intelligence M1 (MI.3).

Observes configured symbols/instruments via MarketReader, journals moves, and
flags interesting percent changes. Simulation Program only — never broker login.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.decision.rules import CapabilityGap
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class MarketObserverWorker(PersistentWorker):
    type = "market_observer"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        market_reader: Any,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._reader = market_reader
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.market_observer")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        instruments = list(cfg.get("instruments") or [])
        symbols = [str(s).strip() for s in (cfg.get("symbols") or []) if str(s).strip()]
        provider = str(cfg.get("provider") or "").strip() or None
        limit = max(2, int(cfg.get("bars_limit", 60)))
        alert_pct = float(cfg.get("move_alert_pct", 5.0) or 5.0)

        targets: list[dict[str, str]] = []
        for inst in instruments:
            if not isinstance(inst, dict):
                continue
            sym = str(inst.get("symbol") or "").strip()
            asset = str(inst.get("asset") or "").strip()
            if sym or asset:
                targets.append({"symbol": sym or asset, "asset": asset})
        for sym in symbols:
            if not any(t["symbol"] == sym for t in targets):
                targets.append({"symbol": sym, "asset": ""})

        if not targets:
            return TickResult(
                state=state,
                note=(
                    "idle: no symbols/instruments — set symbols=['RELIANCE.NS'] "
                    "or instruments=[{symbol, asset}] (sample market_data feed)"
                ),
            )

        notes: list[str] = []
        interesting: list[dict[str, Any]] = []
        gaps = 0
        ok = 0
        for target in targets:
            try:
                result = self._reader.bars_for(
                    target["symbol"],
                    provider=provider,
                    asset=target["asset"] or None,
                    limit=limit,
                )
            except CapabilityGap as gap:
                gaps += 1
                notes.append(f"{target['symbol']}: gap {gap.capability}")
                continue
            except Exception as exc:  # noqa: BLE001
                gaps += 1
                notes.append(f"{target['symbol']}: error {exc}")
                self._logger.warning("observe failed for %s: %s", target["symbol"], exc)
                continue
            ok += 1
            move = result.get("pct_move")
            count = int(result.get("count") or 0)
            prov = result.get("provider")
            move_s = f"{move:+.2f}%" if isinstance(move, (int, float)) else "n/a"
            notes.append(f"{target['symbol']}@{prov}: {count} bars, move {move_s}")
            if isinstance(move, (int, float)) and abs(move) >= alert_pct:
                interesting.append(
                    {
                        "symbol": target["symbol"],
                        "pct_move": round(float(move), 3),
                        "provider": prov,
                        "score": min(1.0, abs(float(move)) / max(alert_pct, 1e-6) / 4.0),
                    }
                )

        state["last_interesting"] = interesting
        state["last_ok"] = ok
        state["last_gaps"] = gaps
        if interesting and self._events is not None:
            try:
                self._events.emit(
                    "MarketInterestingMove",
                    {
                        "mission_id": ctx.mission_id,
                        "events": interesting,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

        head = f"observe: {ok} ok, {gaps} gap(s)"
        if interesting:
            head += f", {len(interesting)} interesting"
        detail = "; ".join(notes[:6])
        return TickResult(state=state, note=f"{head} | {detail}" if detail else head)
