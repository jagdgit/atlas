"""ResearchFreshnessWorker — IRA.7 TTL incremental refresh (Market Program).

Periodically marks stale dossier sections and refreshes them from hermetic
seeds / filing refs — no full rebuild when thesis already exists.

IRA.21: cooperative IR-RO11 memory gates between symbols (bounded batches).
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult
from atlas.workers.memory_coop import (
    MemoryBudgetSignal,
    apply_memory_pause_state,
    gate_memory,
)


class ResearchFreshnessWorker(PersistentWorker):
    type = "research_freshness"
    VERSION = 2
    journal_ticks = True

    def __init__(
        self,
        *,
        research: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._research = research
        self._logger = logger or logging.getLogger("atlas.workers.research_freshness")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        program_id = str(cfg.get("program_id") or "market_intelligence")
        # IRA.21 — keep batches small; resume next tick via cursor
        max_symbols = max(1, min(int(cfg.get("max_symbols") or 4), 12))
        cursor = int(state.get("symbol_cursor") or 0)

        if self._research is None:
            return TickResult(
                state=state,
                note="idle: investment_research not wired",
            )

        try:
            # IRA.26 — prefer symbols with open work / critical missing inputs
            if hasattr(self._research, "symbols_needing_work"):
                symbols = list(
                    self._research.symbols_needing_work(
                        program_id=program_id, limit=max(max_symbols * 3, 12)
                    )
                    or []
                )
            if not symbols:
                symbols = list(self._research.list_symbols(program_id=program_id) or [])
        except Exception:  # noqa: BLE001
            symbols = []
        if not symbols and hasattr(self._research, "refresh_stale"):
            # Fall back to bulk API when list_symbols unavailable
            try:
                gate_memory(ctx)
                result = self._research.refresh_stale(
                    program_id=program_id,
                    max_symbols=max_symbols,
                )
            except MemoryBudgetSignal as signal:
                apply_memory_pause_state(state, signal)
                return TickResult(
                    state=state,
                    note=f"IR-RO11 {state.get('memory_action')}: {state.get('memory_reason')}",
                )
            count = int(result.get("count") or 0)
            state["last_refresh_count"] = count
            state["last_refresh"] = result.get("items") or []
            state.pop("memory_action", None)
            state.pop("memory_reason", None)
            syms = [i.get("symbol") for i in (result.get("items") or []) if i.get("symbol")]
            note = (
                f"refreshed {count} dossier(s): {', '.join(syms[:5])}"
                if count
                else "no stale research sections"
            )
            return TickResult(state=state, note=note)

        if not symbols:
            state.pop("memory_action", None)
            state.pop("memory_reason", None)
            return TickResult(state=state, note="no research dossiers yet")

        n = len(symbols)
        start = cursor % n
        refreshed: list[dict[str, Any]] = []
        processed = 0
        try:
            for i in range(n):
                if processed >= max_symbols:
                    break
                gate_memory(ctx)
                sym = symbols[(start + i) % n]
                try:
                    result = self._research.refresh_stale(
                        sym,
                        program_id=program_id,
                        max_symbols=1,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("research freshness %s failed: %s", sym, exc)
                    processed += 1
                    continue
                processed += 1
                for item in result.get("items") or []:
                    refreshed.append(item)
            state["symbol_cursor"] = (start + processed) % n
            state.pop("memory_action", None)
            state.pop("memory_reason", None)
        except MemoryBudgetSignal as signal:
            apply_memory_pause_state(
                state,
                signal,
                extras={
                    "symbol_cursor": (start + processed) % n if n else 0,
                    "last_refresh_count": len(refreshed),
                    "last_refresh": refreshed,
                },
            )
            return TickResult(
                state=state,
                note=(
                    f"IR-RO11 {state.get('memory_action')}: {state.get('memory_reason')} "
                    f"(refreshed={len(refreshed)}, cursor={state.get('symbol_cursor')})"
                ).strip(),
            )

        state["last_refresh_count"] = len(refreshed)
        state["last_refresh"] = refreshed
        syms = [i.get("symbol") for i in refreshed if i.get("symbol")]
        if refreshed:
            note = f"refreshed {len(refreshed)} dossier(s): {', '.join(syms[:5])}"
        else:
            note = f"no stale research sections (scanned {processed})"
        return TickResult(state=state, note=note)
