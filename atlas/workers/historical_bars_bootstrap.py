"""OI-HIST-BARS — budgeted multi-year daily bar bootstrap worker."""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class HistoricalBarsBootstrapWorker(PersistentWorker):
    """J1 — fill durable bar_store with 5–10y history (Yahoo history job)."""

    type = "historical_bars_bootstrap"
    VERSION = 1

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        market_reader: Any | None = None,
        yahoo_adapter: Any | None = None,
        host_guard: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._market_reader = market_reader
        self._yahoo = yahoo_adapter
        self._host_guard = host_guard
        self._logger = logger or logging.getLogger(
            "atlas.workers.historical_bars_bootstrap"
        )

    def _fetch(self, symbol: str, **kwargs: Any) -> list:
        # Prefer raw Yahoo adapter so durable-prefer does not short-circuit history.
        if self._yahoo is not None and hasattr(self._yahoo, "fetch_bars"):
            return list(self._yahoo.fetch_bars(symbol, **kwargs) or [])
        if self._market_reader is not None and hasattr(self._market_reader, "_adapters"):
            ad = (self._market_reader._adapters or {}).get("yahoo")  # noqa: SLF001
            if ad is not None:
                return list(ad.fetch_bars(symbol, **kwargs) or [])
        raise RuntimeError("no yahoo adapter for historical bootstrap")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = dict(ctx.config or {})
        state = dict(ctx.state or {})
        if self._host_guard is not None:
            try:
                if hasattr(self._host_guard, "should_pause") and self._host_guard.should_pause():
                    return TickResult(state=state, note="idle: host_guard pause")
            except Exception:  # noqa: BLE001
                pass
        if not self._data_dir:
            return TickResult(state=state, note="idle: no data_dir")

        try:
            from atlas.investment.yahoo_fundamentals import (
                yahoo_background_should_yield_to_live,
            )

            if yahoo_background_should_yield_to_live():
                return TickResult(
                    state=state,
                    note="idle: yield yahoo to live session (RTH)",
                )
        except Exception:  # noqa: BLE001
            pass

        from atlas.investment.historical_bars import (
            bootstrap_batch,
            default_priority_symbols,
            load_progress,
        )

        max_n = max(1, min(20, int(cfg.get("max_symbols_per_tick") or 6)))
        range_ = str(cfg.get("range") or "10y")
        symbols = list(cfg.get("symbols") or []) or default_priority_symbols(
            self._data_dir, limit=int(cfg.get("universe_limit") or 80)
        )
        # Rotate cursor so we walk the list across ticks
        cursor = int(state.get("cursor") or 0)
        if cursor >= len(symbols):
            cursor = 0
        ordered = symbols[cursor:] + symbols[:cursor]

        try:
            out = bootstrap_batch(
                self._data_dir,
                ordered,
                fetch_bars=self._fetch,
                max_n=max_n,
                range_=range_,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("hist bootstrap batch failed: %s", exc)
            return TickResult(state=state, note=f"hist bootstrap error: {exc}")

        state["cursor"] = (cursor + int(out.get("attempted") or 0)) % max(1, len(symbols))
        state["last"] = {
            "attempted": out.get("attempted"),
            "ok": out.get("ok"),
            "gaps": out.get("gaps"),
            "done_n": out.get("done_n"),
        }
        prog = load_progress(self._data_dir)
        note = (
            f"hist bootstrap: attempted={out.get('attempted')} ok={out.get('ok')} "
            f"gaps={out.get('gaps')} done={out.get('done_n')}/"
            f"{len(prog.get('done') or {})} range={range_}"
        )
        return TickResult(state=state, note=note)
