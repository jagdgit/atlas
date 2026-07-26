"""InvestmentUniverseWorker — Market Intelligence M0 (OI-IL0 / IL.2–IL.3).

Refreshes an index membership (default NIFTY50), ranks with WHY ± explanations
(IL.3), publishes the watchlist for Decision Simulation auto-mode, and journals.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.investment import watchlists as wl
from atlas.investment.quality_seed import resolve_quality_seed
from atlas.investment.ranking import rank_universe, summarize_phase
from atlas.investment.universe import INDEX_NIFTY50, as_instruments, membership
from atlas.workers.base import PersistentWorker, TickContext, TickResult

EVENT_UNIVERSE_UPDATED = "InvestmentUniverseUpdated"


class InvestmentUniverseWorker(PersistentWorker):
    type = "investment_universe"
    VERSION = 2
    journal_ticks = True

    def __init__(
        self,
        *,
        events: Any | None = None,
        market_reader: Any | None = None,
        policy_engine: Any | None = None,
        experience_os: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._events = events
        self._reader = market_reader
        self._policy = policy_engine
        self._experience = experience_os
        self._logger = logger or logging.getLogger("atlas.workers.investment_universe")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        index = str(cfg.get("index") or INDEX_NIFTY50).strip() or INDEX_NIFTY50
        max_watch = max(1, int(cfg.get("max_watchlist") or 15))
        mode = str(cfg.get("mode") or "auto").strip().lower() or "auto"
        program_id = str(cfg.get("program_id") or wl.DEFAULT_PROGRAM)
        pinned = [str(s).strip() for s in (cfg.get("pinned_symbols") or []) if str(s).strip()]
        lookback = max(5, int(cfg.get("lookback_bars") or 40))
        provider = str(cfg.get("provider") or "").strip() or None
        weights = cfg.get("rank_weights") if isinstance(cfg.get("rank_weights"), dict) else None
        use_default_seed = cfg.get("use_quality_seed")
        if use_default_seed is None:
            use_default_seed = True
        quality_seed = resolve_quality_seed(
            cfg.get("quality_seed"),
            index=index,
            use_default=bool(use_default_seed),
        )

        try:
            members = membership(index)
        except KeyError as exc:
            return TickResult(state=state, note=f"idle: {exc}")

        if mode == "pin" and pinned:
            want = {p if p.endswith(".NS") else f"{p}.NS" for p in pinned}
            watch_members = [m for m in members if m["symbol"] in want]
            if not watch_members:
                watch_members = [
                    {
                        "symbol": (p if p.endswith(".NS") else f"{p}.NS"),
                        "name": p,
                        "sector": "",
                        "nse_symbol": p.replace(".NS", ""),
                        "exchange": "NSE",
                        "asset_class": "cash_equity",
                    }
                    for p in pinned
                ]
            # Pin mode: still score for WHY, but only among pinned set.
            pool = watch_members
            top_n = len(watch_members)
        else:
            pool = members
            top_n = max_watch

        bars_by_symbol = self._collect_bars(
            [str(m["symbol"]) for m in pool],
            lookback=lookback,
            provider=provider,
        )
        # IL.8 — merge operator screener snapshot (+ optional computed) into quality
        use_screener = cfg.get("use_screener_signals")
        if use_screener is None:
            use_screener = True
        screener_meta: dict[str, Any] = {}
        if use_screener:
            from atlas.investment.screener_signals import merge_into_quality

            quality_seed, screener_meta = merge_into_quality(
                quality_seed,
                program_id=program_id,
                bars_by_symbol=bars_by_symbol,
                use_computed=bool(cfg.get("screener_computed", True)),
                config_snapshot=cfg.get("screener_snapshot")
                if isinstance(cfg.get("screener_snapshot"), dict)
                else None,
            )
        policy_deltas = self._policy_deltas(pool)
        experience_bias = self._experience_bias(pool)

        ranked = rank_universe(
            pool,
            bars_by_symbol=bars_by_symbol,
            quality_by_symbol=quality_seed or None,
            policy_delta_by_symbol=policy_deltas or None,
            experience_bias_by_symbol=experience_bias or None,
            max_watchlist=top_n,
            weights=weights,
            lookback_short=int(cfg.get("lookback_short") or 5),
            lookback_long=int(cfg.get("lookback_long") or 20),
            min_bars=int(cfg.get("min_bars") or 5),
            cold_start_coverage=float(cfg.get("cold_start_coverage") or 0.25),
        )

        watch = [
            {
                "symbol": r["symbol"],
                "name": r.get("name", ""),
                "sector": r.get("sector", ""),
                "nse_symbol": r.get("nse_symbol", ""),
                "exchange": r.get("exchange", "NSE"),
                "asset_class": r.get("asset_class", "cash_equity"),
            }
            for r in ranked
        ]
        phase_info = summarize_phase(ranked)

        from atlas.investment.daily_plan import build_daily_plan

        persona_capital = cfg.get("starting_cash") or cfg.get("capital")
        try:
            plan_capital = float(persona_capital) if persona_capital is not None else 10_000.0
        except (TypeError, ValueError):
            plan_capital = 10_000.0
        daily_plan = build_daily_plan(
            ranked,
            capital=plan_capital,
            program_id=program_id,
            portfolio_key=str(cfg.get("portfolio_key") or "").strip() or None,
            index=index,
            max_candidates=min(5, max_watch),
            extra={
                "phase": phase_info["phase"],
                "confidence": phase_info["confidence"],
                "index": index,
            },
        )

        snap = wl.publish(
            program_id=program_id,
            index=index,
            watchlist=watch,
            ranked=ranked,
            mission_id=str(ctx.mission_id) if ctx.mission_id else None,
            mode=mode,
            extra={
                "universe_size": len(members),
                "max_watchlist": max_watch,
                "phase": phase_info["phase"],
                "confidence": phase_info["confidence"],
                "bars_symbols": len(bars_by_symbol),
                "quality_seed_count": len(quality_seed),
                "provider": provider or "",
                "daily_plan": daily_plan,
                "screener": screener_meta,
                "ranking": "il.3+il.8" if screener_meta.get("merged_count") else "il.3",
            },
        )

        state["index"] = index
        state["program_id"] = program_id
        state["watchlist_symbols"] = [r["symbol"] for r in ranked]
        state["universe_size"] = len(members)
        state["updated_at"] = snap["updated_at"]
        state["phase"] = phase_info["phase"]
        state["confidence"] = phase_info["confidence"]
        state["quality_seed_count"] = len(quality_seed)
        state["provider"] = provider or ""
        state["screener_merged"] = int(screener_meta.get("merged_count") or 0)
        state["daily_plan_summary"] = daily_plan.get("summary")
        state["top_reasons"] = [
            {"symbol": r["symbol"], "reason": r.get("reason", ""), "score": r.get("score")}
            for r in ranked[:5]
        ]

        if self._events is not None:
            try:
                self._events.emit(
                    EVENT_UNIVERSE_UPDATED,
                    {
                        "mission_id": str(ctx.mission_id) if ctx.mission_id else None,
                        "program_id": program_id,
                        "index": index,
                        "symbols": state["watchlist_symbols"],
                        "count": len(ranked),
                        "phase": phase_info["phase"],
                        "confidence": phase_info["confidence"],
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("universe event emit failed", exc_info=True)

        top = ", ".join(state["watchlist_symbols"][:5]) or "(none)"
        phase = phase_info["phase"]
        conf = phase_info["confidence"]
        qbit = f", quality_seed={len(quality_seed)}" if quality_seed else ""
        pbit = f", provider={provider}" if provider else ""
        sbit = (
            f", screener={screener_meta.get('merged_count')}"
            if screener_meta.get("merged_count")
            else ""
        )
        plan_bit = f"; plan={daily_plan.get('summary')}" if daily_plan.get("summary") else ""
        return TickResult(
            state=state,
            note=(
                f"{index}: {len(members)} constituents → watchlist {len(ranked)} "
                f"(mode={mode}, phase={phase}, confidence={conf}{qbit}{pbit}{sbit}); top={top}"
                f"{plan_bit}"
            ),
        )

    def _collect_bars(
        self,
        symbols: list[str],
        *,
        lookback: int,
        provider: str | None,
    ) -> dict[str, list[dict[str, Any]]]:
        if self._reader is None:
            return {}
        out: dict[str, list[dict[str, Any]]] = {}
        for sym in symbols:
            try:
                result = self._reader.bars_for(sym, provider=provider, limit=lookback)
            except Exception:  # noqa: BLE001 — CapabilityGap / network: honest empty
                self._logger.debug("bars_for failed for %s", sym, exc_info=True)
                continue
            bars = list((result or {}).get("bars") or [])
            if bars:
                out[sym] = bars
        return out

    def _policy_deltas(self, members: list[dict[str, Any]]) -> dict[str, float]:
        if self._policy is None:
            return {}
        out: dict[str, float] = {}
        for m in members:
            sym = str(m.get("symbol") or "").strip()
            if not sym:
                continue
            try:
                verdict = self._policy.evaluate(
                    action={"kind": "buy", "symbol": sym},
                    context={"domain": "finance", "text": sym},
                )
            except Exception:  # noqa: BLE001
                continue
            if isinstance(verdict, dict):
                try:
                    out[sym] = float(verdict.get("soft_delta") or 0.0)
                except (TypeError, ValueError):
                    continue
        return out

    def _experience_bias(self, members: list[dict[str, Any]]) -> dict[str, float]:
        if self._experience is None:
            return {}
        out: dict[str, float] = {}
        caution = ("loss", "caution", "avoid", "drawdown", "failed", "mistake")
        support = ("win", "lesson applied", "improved", "success")
        for m in members:
            sym = str(m.get("symbol") or "").strip()
            if not sym:
                continue
            try:
                advice = self._experience.advice_for(sym, limit=5)
            except Exception:  # noqa: BLE001
                continue
            text = ""
            if isinstance(advice, dict):
                text = str(advice.get("advice") or "").lower()
            bias = 0.0
            if any(w in text for w in caution):
                bias -= 0.2
            if any(w in text for w in support):
                bias += 0.1
            if bias:
                out[sym] = bias
        return out


def auto_instruments(
    *,
    program_id: str = wl.DEFAULT_PROGRAM,
    max_n: int = 10,
    fallback_index: str = INDEX_NIFTY50,
) -> list[dict[str, str]]:
    """Resolve instruments for M5 when config.instruments is empty."""
    got = wl.instruments_for(program_id, max_n=max_n)
    if got:
        return got
    # Cold start before first M0 tick: seed from static universe.
    return as_instruments(fallback_index, limit=max_n)
